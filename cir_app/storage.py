from __future__ import annotations

import os
import json
import shutil
import sqlite3
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .constants import (
    PRESCRIPTION_DONE,
    PRESCRIPTION_NO_REMARKS,
    PRESCRIPTION_NOT_STARTED,
    REMARK_COMPLETED,
    REMARK_IN_PROGRESS,
    REMARK_NOT_STARTED,
    REMARK_STATUS_LABELS,
    SOURCE_LABELS,
    SOURCE_OWNER,
)
from .models import Actor
from .paths import ProfilePaths


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_iso() -> str:
    return date.today().isoformat()


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def safe_folder_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value.strip())
    return cleaned.strip("_") or "prescription"


class Repository:
    def __init__(self, paths: ProfilePaths, actor: Actor, owner_name: str, read_only: bool = False):
        self.paths = paths
        self.actor = actor
        self.owner_name = owner_name
        self.read_only = read_only
        if not self.read_only:
            self.paths.ensure()
        self.connection = self._connect()
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if not self.read_only:
            self.connection.execute("PRAGMA journal_mode = WAL")
            self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if not self.read_only:
            return sqlite3.connect(self.paths.db_path)
        uri = self.paths.db_path.resolve().as_uri() + "?mode=ro"
        return sqlite3.connect(uri, uri=True)

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS objects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                customer TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                owner_slug TEXT NOT NULL,
                owner_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                created_by_slug TEXT NOT NULL,
                created_by_name TEXT NOT NULL,
                created_by_kind TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by_slug TEXT NOT NULL,
                updated_by_name TEXT NOT NULL,
                updated_by_kind TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prescriptions (
                id TEXT PRIMARY KEY,
                object_id TEXT NOT NULL DEFAULT '',
                number TEXT NOT NULL,
                project TEXT NOT NULL DEFAULT '',
                contractor TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                issued_date TEXT NOT NULL DEFAULT '',
                owner_slug TEXT NOT NULL,
                owner_name TEXT NOT NULL DEFAULT '',
                attachment_folder TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                created_by_slug TEXT NOT NULL,
                created_by_name TEXT NOT NULL,
                created_by_kind TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by_slug TEXT NOT NULL,
                updated_by_name TEXT NOT NULL,
                updated_by_kind TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS remarks (
                id TEXT PRIMARY KEY,
                prescription_id TEXT NOT NULL,
                internal_code TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                due_date TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'not_started',
                note TEXT NOT NULL DEFAULT '',
                attachment_folder TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                created_by_slug TEXT NOT NULL,
                created_by_name TEXT NOT NULL,
                created_by_kind TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by_slug TEXT NOT NULL,
                updated_by_name TEXT NOT NULL,
                updated_by_kind TEXT NOT NULL,
                FOREIGN KEY (prescription_id) REFERENCES prescriptions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                actor_slug TEXT NOT NULL,
                actor_name TEXT NOT NULL,
                actor_kind TEXT NOT NULL,
                owner_slug TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                changes_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS imported_packages (
                id TEXT PRIMARY KEY,
                package_type TEXT NOT NULL,
                package_name TEXT NOT NULL DEFAULT '',
                package_hash TEXT NOT NULL DEFAULT '',
                imported_at TEXT NOT NULL,
                sender_slug TEXT NOT NULL DEFAULT '',
                sender_name TEXT NOT NULL DEFAULT '',
                summary_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_objects_name ON objects(name);
            CREATE INDEX IF NOT EXISTS idx_remarks_prescription ON remarks(prescription_id);
            CREATE INDEX IF NOT EXISTS idx_remarks_due_date ON remarks(due_date);
            CREATE INDEX IF NOT EXISTS idx_audit_log_changed_at ON audit_log(changed_at);
            CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);
            CREATE INDEX IF NOT EXISTS idx_imported_packages_hash ON imported_packages(package_hash);
            """
        )
        self._ensure_column("prescriptions", "object_id", "TEXT NOT NULL DEFAULT ''")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_prescriptions_object ON prescriptions(object_id)")
        self._ensure_column("remarks", "internal_code", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("remarks", "attachment_folder", "TEXT NOT NULL DEFAULT ''")
        self._migrate_project_objects()
        self.connection.commit()

    def _ensure_column(self, table: str, column: str, declaration: str) -> None:
        columns = {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def _has_table(self, table: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def _table_columns(self, table: str) -> set[str]:
        if not self._has_table(table):
            return set()
        return {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}

    def _require_write(self) -> None:
        if self.read_only:
            raise RuntimeError("Репозиторий открыт только для чтения.")

    def list_objects(self, filter_name: str = "all") -> list[dict[str, Any]]:
        if not self._has_table("objects"):
            return [
                item
                for item in _objects_from_prescriptions(self.list_prescriptions())
                if _matches_object_filter(item, filter_name)
            ]
        objects = [dict(row) for row in self.connection.execute("SELECT * FROM objects ORDER BY name")]
        prescriptions_by_object: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for prescription in self.list_prescriptions():
            prescriptions_by_object[prescription.get("object_id", "")].append(prescription)
        result = []
        for item in objects:
            computed = self._compute_object(item, prescriptions_by_object.get(item["id"], []))
            if _matches_object_filter(computed, filter_name):
                result.append(computed)
        return result

    def list_prescriptions(self, filter_name: str = "all") -> list[dict[str, Any]]:
        if not self._has_table("prescriptions"):
            return []
        prescription_columns = self._table_columns("prescriptions")
        has_objects = self._has_table("objects") and "object_id" in prescription_columns
        if has_objects:
            query = """
                SELECT p.*, o.name AS object_name, o.address AS object_address, o.customer AS object_customer
                FROM prescriptions p
                LEFT JOIN objects o ON o.id = p.object_id
                ORDER BY COALESCE(o.name, p.project, ''), p.issued_date DESC, p.number DESC
                """
        else:
            query = """
                SELECT p.*, '' AS object_id, p.project AS object_name, '' AS object_address, '' AS object_customer
                FROM prescriptions p
                ORDER BY p.project, p.issued_date DESC, p.number DESC
                """
        prescriptions = [
            dict(row)
            for row in self.connection.execute(query)
        ]
        remarks_by_prescription = self._remarks_grouped()
        result = []
        for prescription in prescriptions:
            computed = self._compute_prescription(prescription, remarks_by_prescription.get(prescription["id"], []))
            if _matches_filter(computed, filter_name):
                result.append(computed)
        return result

    def list_remarks(self, prescription_id: str | list[str] | tuple[str, ...] | set[str] | None = None, filter_name: str = "all") -> list[dict[str, Any]]:
        if not self._has_table("remarks") or not self._has_table("prescriptions"):
            return []
        prescription_ids = _normalize_ids(prescription_id)
        where = ""
        params: list[str] = []
        if prescription_ids:
            placeholders = ",".join("?" for _ in prescription_ids)
            where = f"WHERE r.prescription_id IN ({placeholders})"
            params = prescription_ids
        prescription_columns = self._table_columns("prescriptions")
        has_objects = self._has_table("objects") and "object_id" in prescription_columns
        if has_objects:
            query = f"""
                SELECT r.*, p.number AS prescription_number, p.object_id, p.project, p.contractor, p.owner_slug, p.owner_name,
                       o.name AS object_name, o.address AS object_address, o.customer AS object_customer
                FROM remarks r
                JOIN prescriptions p ON p.id = r.prescription_id
                LEFT JOIN objects o ON o.id = p.object_id
                {where}
                ORDER BY r.due_date, r.created_at
                """
        else:
            query = f"""
                SELECT r.*, p.number AS prescription_number, '' AS object_id, p.project, p.contractor, p.owner_slug, p.owner_name,
                       p.project AS object_name, '' AS object_address, '' AS object_customer
                FROM remarks r
                JOIN prescriptions p ON p.id = r.prescription_id
                {where}
                ORDER BY r.due_date, r.created_at
                """
        rows = self.connection.execute(query, params)
        result = []
        today = date.today()
        for row in rows:
            item = dict(row)
            item["internal_code"] = item.get("internal_code") or f"RM-{item.get('id', '')[:8]}"
            due = _parse_date(item.get("due_date", ""))
            item["status_label"] = REMARK_STATUS_LABELS.get(item.get("status", ""), item.get("status", ""))
            item["is_overdue"] = bool(due and due < today and item.get("status") not in REMARK_COMPLETED)
            item["source_label"] = SOURCE_LABELS.get(item.get("updated_by_kind", ""), item.get("updated_by_kind", ""))
            item["needs_owner_review"] = item.get("created_by_kind") != SOURCE_OWNER or item.get("updated_by_kind") != SOURCE_OWNER
            if _matches_remark_filter(item, filter_name):
                result.append(item)
        return result

    def object_options(self) -> list[tuple[str, str]]:
        if not self._has_table("objects"):
            return [(item.get("id", ""), item.get("name", "")) for item in self.list_objects()]
        rows = self.connection.execute("SELECT id, name FROM objects ORDER BY name")
        return [(row["id"], row["name"]) for row in rows]

    def get_object(self, object_id: str) -> dict[str, Any] | None:
        if not self._has_table("objects"):
            return None
        row = self.connection.execute("SELECT * FROM objects WHERE id = ?", (object_id,)).fetchone()
        return dict(row) if row else None

    def find_object_by_name(self, name: str) -> dict[str, Any] | None:
        if not self._has_table("objects"):
            return None
        row = self.connection.execute("SELECT * FROM objects WHERE name = ?", (name.strip(),)).fetchone()
        return dict(row) if row else None

    def get_prescription(self, prescription_id: str) -> dict[str, Any] | None:
        if not self._has_table("prescriptions"):
            return None
        row = self.connection.execute("SELECT * FROM prescriptions WHERE id = ?", (prescription_id,)).fetchone()
        return dict(row) if row else None

    def get_remark(self, remark_id: str) -> dict[str, Any] | None:
        if not self._has_table("remarks"):
            return None
        row = self.connection.execute("SELECT * FROM remarks WHERE id = ?", (remark_id,)).fetchone()
        return dict(row) if row else None

    def prescription_options(self) -> list[tuple[str, str]]:
        if not self._has_table("prescriptions"):
            return []
        prescription_columns = self._table_columns("prescriptions")
        if self._has_table("objects") and "object_id" in prescription_columns:
            query = """
                SELECT p.id, p.number, p.project, o.name AS object_name
                FROM prescriptions p
                LEFT JOIN objects o ON o.id = p.object_id
                ORDER BY COALESCE(o.name, p.project, ''), p.issued_date DESC, p.number DESC
                """
        else:
            query = """
                SELECT p.id, p.number, p.project, p.project AS object_name
                FROM prescriptions p
                ORDER BY p.project, p.issued_date DESC, p.number DESC
                """
        rows = self.connection.execute(query)
        return [
            (row["id"], " · ".join(part for part in (row["number"], row["object_name"] or row["project"]) if part).strip())
            for row in rows
        ]

    def save_object(self, payload: dict[str, str]) -> str:
        self._require_write()
        record_id = payload.get("id") or str(uuid.uuid4())
        timestamp = now_iso()
        existing = self.connection.execute("SELECT * FROM objects WHERE id = ?", (record_id,)).fetchone()
        values = (
            payload.get("name", "").strip(),
            payload.get("address", "").strip(),
            payload.get("customer", "").strip(),
            payload.get("note", "").strip(),
        )
        if existing:
            self.connection.execute(
                """
                UPDATE objects
                SET name = ?, address = ?, customer = ?, note = ?,
                    updated_at = ?, updated_by_slug = ?, updated_by_name = ?, updated_by_kind = ?
                WHERE id = ?
                """,
                (
                    *values,
                    timestamp,
                    self.actor.slug,
                    self.actor.name,
                    self.actor.source_kind,
                    record_id,
                ),
            )
            changes = _field_changes(dict(existing), dict(zip(("name", "address", "customer", "note"), values)), ("name", "address", "customer", "note"))
            if changes:
                self._add_audit("object", record_id, "update", f"Объект изменен: {values[0]}", changes, timestamp)
        else:
            self.connection.execute(
                """
                INSERT INTO objects (
                    id, name, address, customer, note, owner_slug, owner_name,
                    created_at, created_by_slug, created_by_name, created_by_kind,
                    updated_at, updated_by_slug, updated_by_name, updated_by_kind
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    *values,
                    self.paths.slug,
                    self.owner_name,
                    timestamp,
                    self.actor.slug,
                    self.actor.name,
                    self.actor.source_kind,
                    timestamp,
                    self.actor.slug,
                    self.actor.name,
                    self.actor.source_kind,
                ),
            )
            self._add_audit(
                "object",
                record_id,
                "create",
                f"Объект создан: {values[0]}",
                _create_changes(dict(zip(("name", "address", "customer", "note"), values))),
                timestamp,
            )
        self.connection.commit()
        return record_id

    def save_prescription(self, payload: dict[str, str]) -> str:
        self._require_write()
        record_id = payload.get("id") or str(uuid.uuid4())
        timestamp = now_iso()
        object_id = self._normalize_object_id(payload.get("object_id", ""))
        existing = self.connection.execute("SELECT * FROM prescriptions WHERE id = ?", (record_id,)).fetchone()
        user_values = {
            "object_id": object_id,
            "number": payload.get("number", "").strip(),
            "project": payload.get("project", "").strip(),
            "contractor": payload.get("contractor", "").strip(),
            "subject": payload.get("subject", "").strip(),
            "issued_date": payload.get("issued_date", "").strip() or (today_iso() if not existing else ""),
        }
        if existing:
            self.connection.execute(
                """
                UPDATE prescriptions
                SET object_id = ?, number = ?, project = ?, contractor = ?, subject = ?, issued_date = ?,
                    updated_at = ?, updated_by_slug = ?, updated_by_name = ?, updated_by_kind = ?
                WHERE id = ?
                """,
                (
                    object_id,
                    user_values["number"],
                    user_values["project"],
                    user_values["contractor"],
                    user_values["subject"],
                    user_values["issued_date"],
                    timestamp,
                    self.actor.slug,
                    self.actor.name,
                    self.actor.source_kind,
                    record_id,
                ),
            )
            changes = _field_changes(
                dict(existing),
                user_values,
                ("object_id", "number", "project", "contractor", "subject", "issued_date"),
            )
            if changes:
                self._add_audit("prescription", record_id, "update", f"Предписание изменено: {user_values['number']}", changes, timestamp)
        else:
            folder = self._new_attachment_folder(record_id, user_values["number"])
            self.connection.execute(
                """
                INSERT INTO prescriptions (
                    id, object_id, number, project, contractor, subject, issued_date, owner_slug, owner_name,
                    attachment_folder, created_at, created_by_slug, created_by_name, created_by_kind,
                    updated_at, updated_by_slug, updated_by_name, updated_by_kind
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    user_values["object_id"],
                    user_values["number"],
                    user_values["project"],
                    user_values["contractor"],
                    user_values["subject"],
                    user_values["issued_date"],
                    self.paths.slug,
                    self.owner_name,
                    str(folder.relative_to(self.paths.profile_dir)),
                    timestamp,
                    self.actor.slug,
                    self.actor.name,
                    self.actor.source_kind,
                    timestamp,
                    self.actor.slug,
                    self.actor.name,
                    self.actor.source_kind,
                ),
            )
            self._add_audit(
                "prescription",
                record_id,
                "create",
                f"Предписание создано: {user_values['number']}",
                _create_changes(user_values),
                timestamp,
            )
        self.connection.commit()
        return record_id

    def save_remark(
        self,
        payload: dict[str, str],
        actor_slug: str | None = None,
        actor_name: str | None = None,
        actor_kind: str | None = None,
        audit_prefix: str = "",
    ) -> str:
        self._require_write()
        record_id = payload.get("id") or str(uuid.uuid4())
        timestamp = now_iso()
        audit_actor_slug = actor_slug or self.actor.slug
        audit_actor_name = actor_name or self.actor.name
        audit_actor_kind = actor_kind or self.actor.source_kind
        prescription_id = payload.get("prescription_id", "")
        internal_code = payload.get("internal_code", "").strip() or self._next_remark_code(prescription_id)
        existing = self.connection.execute("SELECT * FROM remarks WHERE id = ?", (record_id,)).fetchone()
        user_values = {
            "prescription_id": prescription_id,
            "internal_code": internal_code,
            "description": payload.get("description", "").strip(),
            "location": payload.get("location", "").strip(),
            "due_date": payload.get("due_date", "").strip(),
            "status": payload.get("status", REMARK_NOT_STARTED),
            "note": payload.get("note", "").strip(),
        }
        if existing:
            attachment_folder = self._remark_attachment_relative_path(
                prescription_id,
                record_id,
                internal_code,
                existing["internal_code"],
                existing["attachment_folder"],
            )
            self.connection.execute(
                """
                UPDATE remarks
                SET prescription_id = ?, internal_code = ?, description = ?, location = ?, due_date = ?, status = ?, note = ?,
                    attachment_folder = ?,
                    updated_at = ?, updated_by_slug = ?, updated_by_name = ?, updated_by_kind = ?
                WHERE id = ?
                """,
                (
                    prescription_id,
                    internal_code,
                    user_values["description"],
                    user_values["location"],
                    user_values["due_date"],
                    user_values["status"],
                    user_values["note"],
                    attachment_folder,
                    timestamp,
                    audit_actor_slug,
                    audit_actor_name,
                    audit_actor_kind,
                    record_id,
                ),
            )
            changes = _field_changes(
                dict(existing),
                user_values,
                ("prescription_id", "internal_code", "description", "location", "due_date", "status", "note"),
            )
            if changes:
                self._add_audit(
                    "remark",
                    record_id,
                    "update",
                    f"{audit_prefix}Замечание изменено: {internal_code}",
                    changes,
                    timestamp,
                    actor_slug=audit_actor_slug,
                    actor_name=audit_actor_name,
                    actor_kind=audit_actor_kind,
                )
        else:
            self.connection.execute(
                """
                INSERT INTO remarks (
                    id, prescription_id, internal_code, description, location, due_date, status, note, attachment_folder,
                    created_at, created_by_slug, created_by_name, created_by_kind,
                    updated_at, updated_by_slug, updated_by_name, updated_by_kind
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    prescription_id,
                    internal_code,
                    user_values["description"],
                    user_values["location"],
                    user_values["due_date"],
                    user_values["status"],
                    user_values["note"],
                    str(self._new_remark_attachment_folder(prescription_id, record_id, internal_code).relative_to(self.paths.profile_dir)),
                    timestamp,
                    audit_actor_slug,
                    audit_actor_name,
                    audit_actor_kind,
                    timestamp,
                    audit_actor_slug,
                    audit_actor_name,
                    audit_actor_kind,
                ),
            )
            self._add_audit(
                "remark",
                record_id,
                "create",
                f"{audit_prefix}Замечание создано: {internal_code}",
                _create_changes(user_values),
                timestamp,
                actor_slug=audit_actor_slug,
                actor_name=audit_actor_name,
                actor_kind=audit_actor_kind,
            )
        self.connection.commit()
        return record_id

    def delete_objects(self, object_ids: list[str]) -> int:
        self._require_write()
        ids = _normalize_ids(object_ids)
        if not ids:
            return 0
        linked = self.connection.execute(
            f"SELECT COUNT(*) AS count FROM prescriptions WHERE object_id IN ({','.join('?' for _ in ids)})",
            ids,
        ).fetchone()
        if linked and int(linked["count"]):
            raise RuntimeError("Нельзя удалить объект, пока к нему привязаны предписания.")
        rows = self.connection.execute(
            f"SELECT * FROM objects WHERE id IN ({','.join('?' for _ in ids)})",
            ids,
        ).fetchall()
        timestamp = now_iso()
        for row in rows:
            item = dict(row)
            self._add_audit("object", item["id"], "delete", f"Объект удален: {item.get('name', '')}", _delete_changes(item), timestamp)
        self.connection.execute(
            f"DELETE FROM objects WHERE id IN ({','.join('?' for _ in ids)})",
            ids,
        )
        self.connection.commit()
        return len(ids)

    def delete_prescriptions(self, prescription_ids: list[str]) -> int:
        self._require_write()
        ids = _normalize_ids(prescription_ids)
        if not ids:
            return 0
        rows = self.connection.execute(
            f"SELECT * FROM prescriptions WHERE id IN ({','.join('?' for _ in ids)})",
            ids,
        ).fetchall()
        remark_rows = self.connection.execute(
            f"SELECT * FROM remarks WHERE prescription_id IN ({','.join('?' for _ in ids)})",
            ids,
        ).fetchall()
        timestamp = now_iso()
        for row in rows:
            item = dict(row)
            self._add_audit(
                "prescription",
                item["id"],
                "delete",
                f"Предписание удалено: {item.get('number', '')}",
                _delete_changes(item),
                timestamp,
            )
        for row in remark_rows:
            item = dict(row)
            self._add_audit(
                "remark",
                item["id"],
                "delete",
                f"Замечание удалено вместе с предписанием: {item.get('internal_code', '')}",
                _delete_changes(item),
                timestamp,
            )
        self.connection.execute(
            f"DELETE FROM prescriptions WHERE id IN ({','.join('?' for _ in ids)})",
            ids,
        )
        self.connection.commit()
        for row in rows:
            self._delete_relative_folder(row["attachment_folder"])
        return len(ids)

    def delete_remarks(self, remark_ids: list[str]) -> int:
        self._require_write()
        ids = _normalize_ids(remark_ids)
        if not ids:
            return 0
        rows = self.connection.execute(
            f"SELECT * FROM remarks WHERE id IN ({','.join('?' for _ in ids)})",
            ids,
        ).fetchall()
        timestamp = now_iso()
        for row in rows:
            item = dict(row)
            self._add_audit("remark", item["id"], "delete", f"Замечание удалено: {item.get('internal_code', '')}", _delete_changes(item), timestamp)
        self.connection.execute(
            f"DELETE FROM remarks WHERE id IN ({','.join('?' for _ in ids)})",
            ids,
        )
        self.connection.commit()
        for row in rows:
            self._delete_relative_folder(row["attachment_folder"])
        return len(ids)

    def attachments_path(self, prescription_id: str) -> Path:
        row = self.connection.execute("SELECT attachment_folder FROM prescriptions WHERE id = ?", (prescription_id,)).fetchone()
        if not row:
            return self.paths.attachments_dir
        folder = self.paths.profile_dir / row["attachment_folder"]
        if not self.read_only:
            folder.mkdir(parents=True, exist_ok=True)
        return folder

    def remark_attachments_path(self, remark_id: str) -> Path:
        row = self.connection.execute(
            "SELECT prescription_id, internal_code, attachment_folder FROM remarks WHERE id = ?",
            (remark_id,),
        ).fetchone()
        if not row:
            return self.paths.attachments_dir
        if row["attachment_folder"]:
            folder = self.paths.profile_dir / row["attachment_folder"]
        else:
            self._require_write()
            folder = self._new_remark_attachment_folder(row["prescription_id"], remark_id, row["internal_code"] or f"RM-{remark_id[:8]}")
            self.connection.execute(
                "UPDATE remarks SET attachment_folder = ? WHERE id = ?",
                (str(folder.relative_to(self.paths.profile_dir)), remark_id),
            )
            self.connection.commit()
        if not self.read_only:
            folder.mkdir(parents=True, exist_ok=True)
        return folder

    def copy_attachments(self, prescription_id: str, source_paths: list[str]) -> int:
        self._require_write()
        target = self.attachments_path(prescription_id)
        copied = _copy_files(target, source_paths)
        if copied:
            self._add_audit(
                "prescription",
                prescription_id,
                "add_attachments",
                f"Добавлены вложения к предписанию: {len(copied)}",
                {"files": {"before": [], "after": copied}},
            )
            self.connection.commit()
        return len(copied)

    def copy_remark_attachments(
        self,
        remark_id: str,
        source_paths: list[str],
        actor_slug: str | None = None,
        actor_name: str | None = None,
        actor_kind: str | None = None,
        audit_prefix: str = "",
    ) -> int:
        self._require_write()
        target = self.remark_attachments_path(remark_id)
        copied = _copy_files(target, source_paths)
        if copied:
            self._add_audit(
                "remark",
                remark_id,
                "add_attachments",
                f"{audit_prefix}Добавлены вложения к замечанию: {len(copied)}",
                {"files": {"before": [], "after": copied}},
                actor_slug=actor_slug,
                actor_name=actor_name,
                actor_kind=actor_kind,
            )
            self.connection.commit()
        return len(copied)

    def list_audit_log(self) -> list[dict[str, Any]]:
        if not self._has_table("audit_log"):
            return []
        return [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT *
                FROM audit_log
                ORDER BY changed_at, id
                """
            )
        ]

    def list_imported_packages(self) -> list[dict[str, Any]]:
        if not self._has_table("imported_packages"):
            return []
        return [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT *
                FROM imported_packages
                ORDER BY imported_at, id
                """
            )
        ]

    def _add_audit(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        summary: str,
        changes: dict[str, Any],
        changed_at: str | None = None,
        actor_slug: str | None = None,
        actor_name: str | None = None,
        actor_kind: str | None = None,
    ) -> None:
        self._require_write()
        self.connection.execute(
            """
            INSERT INTO audit_log (
                id, entity_type, entity_id, action, changed_at,
                actor_slug, actor_name, actor_kind, owner_slug, owner_name,
                summary, changes_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                entity_type,
                entity_id,
                action,
                changed_at or now_iso(),
                actor_slug or self.actor.slug,
                actor_name or self.actor.name,
                actor_kind or self.actor.source_kind,
                self.paths.slug,
                self.owner_name,
                summary,
                json.dumps(changes, ensure_ascii=False, sort_keys=True),
            ),
        )

    def has_imported_package(self, package_id: str, package_hash: str = "") -> bool:
        if not self._has_table("imported_packages"):
            return False
        row = self.connection.execute(
            """
            SELECT 1
            FROM imported_packages
            WHERE id = ? OR (? <> '' AND package_hash = ?)
            """,
            (package_id, package_hash, package_hash),
        ).fetchone()
        return row is not None

    def record_imported_package(
        self,
        package_id: str,
        package_type: str,
        package_name: str,
        package_hash: str,
        sender_slug: str,
        sender_name: str,
        summary: dict[str, Any],
    ) -> None:
        self._require_write()
        timestamp = now_iso()
        payload = json.dumps(summary, ensure_ascii=False, sort_keys=True)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO imported_packages (
                id, package_type, package_name, package_hash, imported_at,
                sender_slug, sender_name, summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (package_id, package_type, package_name, package_hash, timestamp, sender_slug, sender_name, payload),
        )
        self._add_audit(
            "package",
            package_id,
            "import_package",
            f"Импортирован пакет обмена: {package_name}",
            {"summary": {"before": "", "after": payload}},
            timestamp,
        )
        self.connection.commit()

    def _delete_relative_folder(self, relative_path: str) -> None:
        if not relative_path:
            return
        target = (self.paths.profile_dir / relative_path).resolve()
        base = self.paths.profile_dir.resolve()
        if target.exists() and target.is_dir() and target.is_relative_to(base):
            shutil.rmtree(target, ignore_errors=True)

    def _next_remark_code(self, prescription_id: str) -> str:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM remarks WHERE prescription_id = ?",
            (prescription_id,),
        ).fetchone()
        return f"RM-{int(row['count']) + 1:03d}"

    def _new_remark_attachment_folder(self, prescription_id: str, remark_id: str, internal_code: str) -> Path:
        folder = self._remark_attachment_folder_path(prescription_id, remark_id, internal_code)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _remark_attachment_folder_path(self, prescription_id: str, remark_id: str, internal_code: str) -> Path:
        parent = self.attachments_path(prescription_id) / "remarks"
        return parent / f"{safe_folder_name(internal_code)}_{remark_id[:8]}"

    def _remark_attachment_relative_path(
        self,
        prescription_id: str,
        remark_id: str,
        internal_code: str,
        previous_code: str,
        previous_relative: str,
    ) -> str:
        target = self._remark_attachment_folder_path(prescription_id, remark_id, internal_code)
        if not previous_relative:
            target.mkdir(parents=True, exist_ok=True)
            return str(target.relative_to(self.paths.profile_dir))
        previous = self.paths.profile_dir / previous_relative
        if previous.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            if previous.exists() and target.exists():
                for child in previous.iterdir():
                    shutil.move(str(child), str(target / child.name))
                previous.rmdir()
            elif previous.exists():
                previous.rename(target)
            else:
                target.mkdir(parents=True, exist_ok=True)
            return str(target.relative_to(self.paths.profile_dir))
        previous.mkdir(parents=True, exist_ok=True)
        return previous_relative

    def dashboard(self) -> dict[str, Any]:
        prescriptions = self.list_prescriptions()
        remarks = self.list_remarks()
        projects: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "active": 0, "overdue": 0})
        objects: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "active": 0, "overdue": 0})
        for item in prescriptions:
            project = item.get("project") or "Без проекта"
            projects[project]["total"] += 1
            if not item["is_done"]:
                projects[project]["active"] += 1
            if item["overdue_count"]:
                projects[project]["overdue"] += 1
            object_name = item.get("object_name") or item.get("project") or "Без объекта"
            objects[object_name]["total"] += 1
            if not item["is_done"]:
                objects[object_name]["active"] += 1
            if item["overdue_count"]:
                objects[object_name]["overdue"] += 1
        return {
            "prescriptions_total": len(prescriptions),
            "prescriptions_active": sum(1 for item in prescriptions if not item["is_done"]),
            "prescriptions_overdue": sum(1 for item in prescriptions if item["overdue_count"]),
            "near_due": sum(1 for item in prescriptions if item["near_due"]),
            "remarks_open": sum(1 for item in remarks if item["status"] not in REMARK_COMPLETED),
            "needs_owner_review": sum(1 for item in prescriptions if item["needs_owner_review"])
            + sum(1 for item in remarks if item["needs_owner_review"]),
            "objects": dict(sorted(objects.items())),
            "projects": dict(sorted(projects.items())),
        }

    def export_payload(self) -> dict[str, list[list[Any]]]:
        objects = self.list_objects()
        prescriptions = self.list_prescriptions()
        remarks = self.list_remarks()
        audit_log = self.list_audit_log()
        imported_packages = self.list_imported_packages()
        return {
            "Objects": [_object_headers()] + [_object_row(item) for item in objects],
            "Prescriptions": [_prescription_headers()] + [_prescription_row(item) for item in prescriptions],
            "Remarks": [_remark_headers()] + [_remark_row(item) for item in remarks],
            "AuditLog": [_audit_headers()] + [_audit_row(item) for item in audit_log],
            "ImportedPackages": [_imported_package_headers()] + [_imported_package_row(item) for item in imported_packages],
        }

    def _remarks_grouped(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if not self._has_table("remarks"):
            return grouped
        for row in self.connection.execute("SELECT * FROM remarks"):
            grouped[row["prescription_id"]].append(dict(row))
        return grouped

    def _compute_object(self, item: dict[str, Any], prescriptions: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(prescriptions)
        active = sum(1 for prescription in prescriptions if not prescription.get("is_done"))
        overdue = sum(1 for prescription in prescriptions if prescription.get("overdue_count"))
        remarks_total = sum(int(prescription.get("remarks_total") or 0) for prescription in prescriptions)
        remarks_done = sum(int(prescription.get("remarks_done") or 0) for prescription in prescriptions)
        result = dict(item)
        result.update(
            {
                "prescriptions_total": total,
                "prescriptions_active": active,
                "prescriptions_overdue": overdue,
                "remarks_total": remarks_total,
                "remarks_done": remarks_done,
                "percent": int(round(remarks_done / remarks_total * 100)) if remarks_total else 0,
                "near_due": any(prescription.get("near_due") for prescription in prescriptions),
                "source_label": SOURCE_LABELS.get(item.get("updated_by_kind", ""), item.get("updated_by_kind", "")),
                "needs_owner_review": item.get("created_by_kind") != SOURCE_OWNER or item.get("updated_by_kind") != SOURCE_OWNER,
            }
        )
        return result

    def _compute_prescription(self, prescription: dict[str, Any], remarks: list[dict[str, Any]]) -> dict[str, Any]:
        today = date.today()
        total = len(remarks)
        done = sum(1 for item in remarks if item.get("status") in REMARK_COMPLETED)
        in_progress = sum(1 for item in remarks if item.get("status") == REMARK_IN_PROGRESS)
        percent = int(round(done / total * 100)) if total else 0
        due_dates = [_parse_date(item.get("due_date", "")) for item in remarks if item.get("due_date")]
        due_dates = [value for value in due_dates if value is not None]
        incomplete_due_dates = [
            _parse_date(item.get("due_date", ""))
            for item in remarks
            if item.get("status") not in REMARK_COMPLETED and item.get("due_date")
        ]
        incomplete_due_dates = [value for value in incomplete_due_dates if value is not None]
        overdue_count = sum(1 for value in incomplete_due_dates if value < today)
        if not remarks:
            status = PRESCRIPTION_NO_REMARKS
        elif done == total:
            status = PRESCRIPTION_DONE
        elif in_progress or done:
            status = f"Исполняется ({percent}%)"
        else:
            status = PRESCRIPTION_NOT_STARTED
        result = dict(prescription)
        result.update(
            {
                "object_display_name": prescription.get("object_name") or prescription.get("project") or "Без объекта",
                "status": status,
                "percent": percent,
                "remarks_total": total,
                "remarks_done": done,
                "due_date": max(due_dates).isoformat() if due_dates else "",
                "nearest_due_date": min(incomplete_due_dates).isoformat() if incomplete_due_dates else "",
                "overdue_count": overdue_count,
                "near_due": bool(
                    incomplete_due_dates
                    and min(incomplete_due_dates) >= today
                    and min(incomplete_due_dates) <= today + timedelta(days=7)
                ),
                "is_done": bool(total and done == total),
                "source_label": SOURCE_LABELS.get(prescription.get("updated_by_kind", ""), prescription.get("updated_by_kind", "")),
                "needs_owner_review": prescription.get("created_by_kind") != SOURCE_OWNER
                or prescription.get("updated_by_kind") != SOURCE_OWNER,
            }
        )
        return result

    def _new_attachment_folder(self, record_id: str, number: str) -> Path:
        folder_name = safe_folder_name(number) if number else record_id[:8]
        folder = self.paths.attachments_dir / f"{folder_name}_{record_id[:8]}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _normalize_object_id(self, object_id: str) -> str:
        object_id = (object_id or "").strip()
        if not object_id:
            return ""
        row = self.connection.execute("SELECT id FROM objects WHERE id = ?", (object_id,)).fetchone()
        return object_id if row else ""

    def _migrate_project_objects(self) -> None:
        rows = self.connection.execute(
            """
            SELECT id, project
            FROM prescriptions
            WHERE COALESCE(object_id, '') = '' AND TRIM(COALESCE(project, '')) <> ''
            """
        ).fetchall()
        if not rows:
            return
        object_ids_by_name = {
            row["name"]: row["id"]
            for row in self.connection.execute("SELECT id, name FROM objects WHERE owner_slug = ?", (self.paths.slug,))
        }
        timestamp = now_iso()
        for row in rows:
            name = row["project"].strip()
            object_id = object_ids_by_name.get(name)
            if not object_id:
                object_id = str(uuid.uuid4())
                self.connection.execute(
                    """
                    INSERT INTO objects (
                        id, name, address, customer, note, owner_slug, owner_name,
                        created_at, created_by_slug, created_by_name, created_by_kind,
                        updated_at, updated_by_slug, updated_by_name, updated_by_kind
                    )
                    VALUES (?, ?, '', '', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        object_id,
                        name,
                        self.paths.slug,
                        self.owner_name,
                        timestamp,
                        self.actor.slug,
                        self.actor.name,
                        self.actor.source_kind,
                        timestamp,
                        self.actor.slug,
                        self.actor.name,
                        self.actor.source_kind,
                    ),
                )
                object_ids_by_name[name] = object_id
            self.connection.execute("UPDATE prescriptions SET object_id = ? WHERE id = ?", (object_id, row["id"]))


def _copy_files(target: Path, source_paths: list[str]) -> list[str]:
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in source_paths:
        source_path = Path(source)
        if source_path.exists() and source_path.is_file():
            destination = _unique_destination(target / source_path.name)
            shutil.copy2(source_path, destination)
            copied.append(destination.name)
    return copied


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{uuid.uuid4().hex[:8]}{suffix}")


def _field_changes(before: dict[str, Any], after: dict[str, Any], fields: tuple[str, ...]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for field in fields:
        previous = "" if before.get(field) is None else str(before.get(field, ""))
        current = "" if after.get(field) is None else str(after.get(field, ""))
        if previous != current:
            result[field] = {"before": previous, "after": current}
    return result


def _create_changes(values: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        field: {"before": "", "after": "" if value is None else str(value)}
        for field, value in values.items()
        if value is not None and str(value) != ""
    }


def _delete_changes(values: dict[str, Any]) -> dict[str, dict[str, str]]:
    ignored = {"created_at", "updated_at"}
    return {
        field: {"before": "" if value is None else str(value), "after": ""}
        for field, value in values.items()
        if field not in ignored and value is not None and str(value) != ""
    }


def _objects_from_prescriptions(prescriptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in prescriptions:
        object_id = item.get("object_id", "")
        name = item.get("object_name") or item.get("project") or "Без объекта"
        key = object_id or name
        grouped.setdefault(
            key,
            {
                "id": object_id or name,
                "name": name,
                "address": item.get("object_address", ""),
                "customer": item.get("object_customer", ""),
                "note": "",
                "owner_slug": item.get("owner_slug", ""),
                "owner_name": item.get("owner_name", ""),
                "created_at": item.get("created_at", ""),
                "created_by_kind": item.get("created_by_kind", ""),
                "created_by_name": item.get("created_by_name", ""),
                "updated_at": item.get("updated_at", ""),
                "updated_by_kind": item.get("updated_by_kind", ""),
                "updated_by_name": item.get("updated_by_name", ""),
                "prescriptions_total": 0,
                "prescriptions_active": 0,
                "prescriptions_overdue": 0,
                "remarks_total": 0,
                "remarks_done": 0,
                "near_due": False,
                "needs_owner_review": False,
            },
        )
        grouped[key]["prescriptions_total"] += 1
        if not item.get("is_done"):
            grouped[key]["prescriptions_active"] += 1
        if item.get("overdue_count"):
            grouped[key]["prescriptions_overdue"] += 1
        grouped[key]["remarks_total"] += int(item.get("remarks_total") or 0)
        grouped[key]["remarks_done"] += int(item.get("remarks_done") or 0)
        grouped[key]["near_due"] = bool(grouped[key]["near_due"] or item.get("near_due"))
        grouped[key]["needs_owner_review"] = bool(grouped[key]["needs_owner_review"] or item.get("needs_owner_review"))
    for item in grouped.values():
        total = int(item.get("remarks_total") or 0)
        done = int(item.get("remarks_done") or 0)
        item["percent"] = int(round(done / total * 100)) if total else 0
        item["source_label"] = SOURCE_LABELS.get(item.get("updated_by_kind", ""), item.get("updated_by_kind", ""))
    return [dict(value) for value in sorted(grouped.values(), key=lambda row: row.get("name", ""))]


def _normalize_ids(value: str | list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [item for item in value if item]


def _matches_filter(item: dict[str, Any], filter_name: str) -> bool:
    if filter_name == "active":
        return not item.get("is_done")
    if filter_name == "overdue":
        return bool(item.get("overdue_count"))
    if filter_name == "near_due":
        return bool(item.get("near_due"))
    if filter_name == "not_owner":
        return bool(item.get("needs_owner_review"))
    return True


def _matches_object_filter(item: dict[str, Any], filter_name: str) -> bool:
    if filter_name == "active":
        return bool(item.get("prescriptions_active"))
    if filter_name == "overdue":
        return bool(item.get("prescriptions_overdue"))
    if filter_name == "near_due":
        return bool(item.get("near_due"))
    if filter_name == "not_owner":
        return bool(item.get("needs_owner_review"))
    return True


def _matches_remark_filter(item: dict[str, Any], filter_name: str) -> bool:
    if filter_name == "active":
        return item.get("status") not in REMARK_COMPLETED
    if filter_name == "overdue":
        return bool(item.get("is_overdue"))
    if filter_name == "not_owner":
        return bool(item.get("needs_owner_review"))
    return True


def _object_headers() -> list[str]:
    return [
        "id",
        "owner_slug",
        "owner_name",
        "name",
        "address",
        "customer",
        "note",
        "prescriptions_total",
        "prescriptions_active",
        "prescriptions_overdue",
        "remarks_total",
        "remarks_done",
        "percent",
        "near_due",
        "source_label",
        "needs_owner_review",
        "created_at",
        "created_by_kind",
        "created_by_name",
        "updated_at",
        "updated_by_kind",
        "updated_by_name",
    ]


def _object_row(item: dict[str, Any]) -> list[Any]:
    return [item.get(header, "") for header in _object_headers()]


def _prescription_headers() -> list[str]:
    return [
        "id",
        "owner_slug",
        "owner_name",
        "object_id",
        "object_name",
        "object_address",
        "object_customer",
        "number",
        "project",
        "contractor",
        "subject",
        "issued_date",
        "status",
        "percent",
        "remarks_total",
        "remarks_done",
        "due_date",
        "nearest_due_date",
        "overdue_count",
        "created_at",
        "created_by_kind",
        "created_by_name",
        "updated_at",
        "updated_by_kind",
        "updated_by_name",
        "attachment_folder",
    ]


def _prescription_row(item: dict[str, Any]) -> list[Any]:
    return [item.get(header, "") for header in _prescription_headers()]


def _remark_headers() -> list[str]:
    return [
        "id",
        "prescription_id",
        "prescription_number",
        "object_id",
        "object_name",
        "object_address",
        "object_customer",
        "owner_slug",
        "owner_name",
        "project",
        "contractor",
        "internal_code",
        "description",
        "location",
        "due_date",
        "status",
        "status_label",
        "note",
        "is_overdue",
        "created_at",
        "created_by_kind",
        "created_by_name",
        "updated_at",
        "updated_by_kind",
        "updated_by_name",
        "attachment_folder",
    ]


def _remark_row(item: dict[str, Any]) -> list[Any]:
    return [item.get(header, "") for header in _remark_headers()]


def _audit_headers() -> list[str]:
    return [
        "id",
        "entity_type",
        "entity_id",
        "action",
        "changed_at",
        "actor_slug",
        "actor_name",
        "actor_kind",
        "owner_slug",
        "owner_name",
        "summary",
        "changes_json",
    ]


def _audit_row(item: dict[str, Any]) -> list[Any]:
    return [item.get(header, "") for header in _audit_headers()]


def _imported_package_headers() -> list[str]:
    return [
        "id",
        "package_type",
        "package_name",
        "package_hash",
        "imported_at",
        "sender_slug",
        "sender_name",
        "summary_json",
    ]


def _imported_package_row(item: dict[str, Any]) -> list[Any]:
    return [item.get(header, "") for header in _imported_package_headers()]
