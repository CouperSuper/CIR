from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import AppConfig
from .constants import (
    PRESCRIPTION_DONE,
    REMARK_COMPLETED,
    ROLE_SPECIALIST,
    ROLE_SUPERVISOR,
    ROLE_LABELS,
    SOURCE_OWNER,
)
from .locks import ProfileLock
from .models import Actor, source_kind_for
from .paths import ProfilePaths, profile_paths, server_root
from .profile_meta import ensure_profile_metadata, list_profiles, read_profile_name
from .storage import Repository
from .xlsx_export import write_xlsx


IMAGE_EXTENSIONS = {".png", ".gif", ".ppm", ".pgm", ".jpg", ".jpeg", ".bmp", ".webp"}


class Runtime:
    def __init__(self, config: AppConfig):
        self.session_id = str(uuid.uuid4())
        self.config = config.normalized()
        self.root = server_root(self.config.server_root)
        self.paths: ProfilePaths | None = None
        self.actor: Actor | None = None
        self.repo: Repository | None = None
        self.lock: ProfileLock | None = None
        self.read_only = True
        self.lock_message = ""
        self.reload(self.config)

    def reload(self, config: AppConfig | None = None) -> None:
        self.close()
        if config:
            self.config = config.normalized()
        self.root = server_root(self.config.server_root)
        self.read_only = self.config.role == ROLE_SUPERVISOR
        self.lock_message = "Режим руководителя: просмотр SQLite-профилей"
        if self.config.role == ROLE_SUPERVISOR:
            self.actor = Actor(
                slug=self.config.user_slug,
                name=self.config.user_name,
                role=self.config.role,
                source_kind=source_kind_for(self.config.role, self.config.user_slug, self.config.user_slug),
            )
            return

        owner_slug = self.active_profile_slug
        self.paths = profile_paths(self.root, owner_slug)
        owner_name = self.config.user_name if owner_slug == self.config.user_slug else read_profile_name(self.paths)
        if self.config.role == ROLE_SPECIALIST and owner_slug == self.config.user_slug:
            ensure_profile_metadata(self.paths, self.config.user_name)
        source_kind = source_kind_for(self.config.role, self.config.user_slug, owner_slug)
        self.actor = Actor(self.config.user_slug, self.config.user_name, self.config.role, source_kind)
        self.lock = ProfileLock(self.paths.lock_path, self.actor, self.session_id)
        lock_result = self.lock.acquire()
        self.read_only = not lock_result.can_write
        self.lock_message = lock_result.message
        self.repo = Repository(self.paths, self.actor, owner_name, read_only=self.read_only)
        if not self.read_only:
            self.export_current()

    def close(self) -> None:
        if self.repo:
            self.repo.close()
            self.repo = None
        if self.lock:
            self.lock.release()
            self.lock = None
        self.paths = None

    @property
    def active_profile_slug(self) -> str:
        if self.config.role == ROLE_SUPERVISOR:
            return self.config.active_profile_slug or self.config.user_slug
        if self.config.role:
            return self.config.active_profile_slug or self.config.user_slug
        return self.config.user_slug

    @property
    def mode_label(self) -> str:
        return ROLE_LABELS.get(self.config.role, self.config.role)

    def profile_options(self) -> list[tuple[str, str]]:
        return [(item.slug, item.name) for item in list_profiles(self.root)]

    def list_objects(self, filter_name: str = "all") -> list[dict[str, Any]]:
        if self.repo:
            return self.repo.list_objects(filter_name)
        rows = self._sqlite_objects()
        return [item for item in rows if _matches_export_object(item, filter_name)]

    def list_prescriptions(self, filter_name: str = "all") -> list[dict[str, Any]]:
        if self.config.role == ROLE_SUPERVISOR:
            return [item for item in self._sqlite_prescriptions() if _matches_export_prescription(item, filter_name)]
        if not self.repo:
            return []
        return self.repo.list_prescriptions(filter_name)

    def list_remarks(self, prescription_id: str | list[str] | tuple[str, ...] | set[str] | None = None, filter_name: str = "all") -> list[dict[str, Any]]:
        prescription_ids = _normalize_ids(prescription_id)
        if self.config.role == ROLE_SUPERVISOR:
            rows = self._sqlite_remarks()
            if prescription_ids:
                rows = [item for item in rows if item.get("prescription_id") in prescription_ids]
            return [item for item in rows if _matches_export_remark(item, filter_name)]
        if not self.repo:
            return []
        return self.repo.list_remarks(prescription_ids, filter_name)

    def list_audit_log(self) -> list[dict[str, Any]]:
        if self.repo:
            rows = self.repo.list_audit_log()
            for row in rows:
                row.setdefault("__profile_slug", self.paths.slug if self.paths else row.get("owner_slug", ""))
            return rows
        return self._sqlite_audit_log()

    def object_options(self) -> list[tuple[str, str]]:
        if self.repo:
            return [(item.get("id", ""), item.get("name", "")) for item in self._common_objects()]
        return [(item.get("id", ""), item.get("name", "")) for item in self._common_objects()]

    def prescription_options(self) -> list[tuple[str, str]]:
        if self.repo:
            return self.repo.prescription_options()
        return [
            (
                item.get("id", ""),
                " · ".join(
                    part for part in (item.get("number", ""), item.get("object_name", "") or item.get("project", "")) if part
                ).strip(),
            )
            for item in self._sqlite_prescriptions()
        ]

    def dashboard(self) -> dict[str, Any]:
        if self.repo:
            return self.repo.dashboard()
        prescriptions = self._sqlite_prescriptions()
        remarks = self._sqlite_remarks()
        projects: dict[str, dict[str, int]] = {}
        objects: dict[str, dict[str, int]] = {}
        for item in prescriptions:
            project = item.get("project") or "Без проекта"
            projects.setdefault(project, {"total": 0, "active": 0, "overdue": 0})
            projects[project]["total"] += 1
            if item.get("status") != PRESCRIPTION_DONE:
                projects[project]["active"] += 1
            if int(item.get("overdue_count") or 0):
                projects[project]["overdue"] += 1
            object_name = item.get("object_name") or item.get("project") or "Без объекта"
            objects.setdefault(object_name, {"total": 0, "active": 0, "overdue": 0})
            objects[object_name]["total"] += 1
            if item.get("status") != PRESCRIPTION_DONE:
                objects[object_name]["active"] += 1
            if int(item.get("overdue_count") or 0):
                objects[object_name]["overdue"] += 1
        return {
            "prescriptions_total": len(prescriptions),
            "prescriptions_active": sum(1 for item in prescriptions if item.get("status") != PRESCRIPTION_DONE),
            "prescriptions_overdue": sum(1 for item in prescriptions if int(item.get("overdue_count") or 0)),
            "near_due": sum(1 for item in prescriptions if _date_within_7_days(item.get("nearest_due_date", ""))),
            "remarks_open": sum(1 for item in remarks if item.get("status") not in REMARK_COMPLETED),
            "needs_owner_review": sum(1 for item in prescriptions if _not_owner(item))
            + sum(1 for item in remarks if _not_owner(item)),
            "objects": dict(sorted(objects.items())),
            "projects": dict(sorted(projects.items())),
        }

    def save_object(self, payload: dict[str, str]) -> str:
        self._require_write()
        assert self.repo is not None
        record_id = self.repo.save_object(payload)
        self.export_current()
        return record_id

    def save_prescription(self, payload: dict[str, str]) -> str:
        self._require_write()
        assert self.repo is not None
        payload = self._with_local_object(dict(payload))
        record_id = self.repo.save_prescription(payload)
        self.export_current()
        return record_id

    def save_remark(self, payload: dict[str, str]) -> str:
        self._require_write()
        assert self.repo is not None
        record_id = self.repo.save_remark(payload)
        self.export_current()
        return record_id

    def delete_prescriptions(self, prescription_ids: list[str]) -> int:
        self._require_write()
        assert self.repo is not None
        count = self.repo.delete_prescriptions(prescription_ids)
        self.export_current()
        return count

    def delete_objects(self, object_ids: list[str]) -> int:
        self._require_write()
        assert self.repo is not None
        count = self.repo.delete_objects(object_ids)
        self.export_current()
        return count

    def delete_remarks(self, remark_ids: list[str]) -> int:
        self._require_write()
        assert self.repo is not None
        count = self.repo.delete_remarks(remark_ids)
        self.export_current()
        return count

    def export_current(self) -> None:
        if not self.repo or not self.paths:
            return
        if self.read_only or self.repo.read_only:
            raise RuntimeError("Текущий режим открыт только для чтения.")
        write_xlsx(self.paths.export_path, self.repo.export_payload())

    def attachments_path(self, prescription_id: str) -> Path:
        if not self.repo or self.repo.read_only:
            path = self._record_attachment_path(self.list_prescriptions(), prescription_id)
            if path is None:
                raise RuntimeError("Папка вложений для предписания не найдена.")
            return path
        return self.repo.attachments_path(prescription_id)

    def copy_attachments(self, prescription_id: str, source_paths: list[str]) -> int:
        self._require_write()
        assert self.repo is not None
        return self.repo.copy_attachments(prescription_id, source_paths)

    def prescription_image_paths(self, prescription_id: str) -> list[Path]:
        if not self.repo or self.repo.read_only:
            path = self._record_attachment_path(self.list_prescriptions(), prescription_id)
            return _image_paths(path) if path is not None else []
        return _image_paths(self.repo.attachments_path(prescription_id))

    def remark_attachments_path(self, remark_id: str) -> Path:
        if not self.repo or self.repo.read_only:
            path = self._record_attachment_path(self.list_remarks(), remark_id)
            if path is None:
                raise RuntimeError("Папка вложений для замечания не найдена.")
            return path
        return self.repo.remark_attachments_path(remark_id)

    def copy_remark_attachments(self, remark_id: str, source_paths: list[str]) -> int:
        self._require_write()
        assert self.repo is not None
        return self.repo.copy_remark_attachments(remark_id, source_paths)

    def remark_image_paths(self, remark_id: str) -> list[Path]:
        if not self.repo or self.repo.read_only:
            path = self._record_attachment_path(self.list_remarks(), remark_id)
            return _image_paths(path) if path is not None else []
        return _image_paths(self.repo.remark_attachments_path(remark_id))

    def open_attachments(self, prescription_id: str) -> Path:
        path = self.attachments_path(prescription_id)
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        return path

    def open_remark_attachments(self, remark_id: str) -> Path:
        path = self.remark_attachments_path(remark_id)
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        return path

    def suggest_exchange_package_name(self, package_type: str, contractor: str = "", object_label: str = "") -> str:
        from .exchange import suggest_package_name

        return suggest_package_name(self, package_type, contractor, object_label)

    def export_exchange_package(
        self,
        output_path: str | Path,
        package_type: str,
        contractor: str = "",
        object_id: str = "",
        include_attachments: bool = True,
        mail_limit_mb: int = 22,
    ) -> dict[str, Any]:
        from .exchange import export_package

        return export_package(
            self,
            Path(output_path),
            package_type=package_type,
            contractor=contractor,
            object_id=object_id,
            include_attachments=include_attachments,
            mail_limit_mb=mail_limit_mb,
        )

    def inspect_exchange_package(self, package_path: str | Path) -> dict[str, Any]:
        from .exchange import inspect_package

        return inspect_package(self, Path(package_path))

    def import_exchange_package(self, package_path: str | Path) -> dict[str, Any]:
        self._require_write()
        from .exchange import import_package

        return import_package(self, Path(package_path))

    def seed_demo(self) -> None:
        self._require_write()
        assert self.repo is not None
        first_object_id = self.repo.save_object(
            {
                "name": "Жилой комплекс Северный",
                "address": "Корпус 1",
                "customer": "ООО Заказчик",
                "note": "Демо-объект для бетонных работ",
            }
        )
        second_object_id = self.repo.save_object(
            {
                "name": "Производственный блок Б",
                "address": "Блок 2",
                "customer": "АО Девелопмент",
                "note": "Демо-объект для монтажных работ",
            }
        )
        first_id = self.repo.save_prescription(
            {
                "object_id": first_object_id,
                "number": "ПР-2026-001",
                "project": "Проект А",
                "contractor": "ООО Подрядчик",
                "subject": "Контроль бетонных работ",
                "issued_date": date.today().isoformat(),
            }
        )
        self.repo.save_remark(
            {
                "prescription_id": first_id,
                "description": "Предоставить исполнительную схему на армирование.",
                "location": "Корпус 1, оси А-Б/1-4",
                "due_date": (date.today() + timedelta(days=3)).isoformat(),
                "status": "in_progress",
                "note": "",
            }
        )
        self.repo.save_remark(
            {
                "prescription_id": first_id,
                "description": "Устранить замечания по защитному слою.",
                "location": "Плита перекрытия +6.000",
                "due_date": (date.today() - timedelta(days=2)).isoformat(),
                "status": "not_started",
                "note": "",
            }
        )
        second_id = self.repo.save_prescription(
            {
                "object_id": second_object_id,
                "number": "ПР-2026-002",
                "project": "Проект Б",
                "contractor": "АО Монтаж",
                "subject": "Документация по сварочным работам",
                "issued_date": date.today().isoformat(),
            }
        )
        self.repo.save_remark(
            {
                "prescription_id": second_id,
                "description": "Передать журнал сварочных работ.",
                "location": "Блок 2",
                "due_date": (date.today() + timedelta(days=10)).isoformat(),
                "status": "not_started",
                "note": "",
            }
        )
        self.export_current()

    def _sqlite_objects(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for profile, repo in self._readonly_profile_repositories():
            try:
                for row in repo.list_objects():
                    row.setdefault("__profile_slug", profile.slug)
                    rows.append(row)
            finally:
                repo.close()
        return sorted(rows, key=lambda item: (item.get("name", ""), item.get("owner_slug", "")))

    def _sqlite_prescriptions(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for profile, repo in self._readonly_profile_repositories():
            try:
                for row in repo.list_prescriptions():
                    row.setdefault("__profile_slug", profile.slug)
                    rows.append(row)
            finally:
                repo.close()
        return sorted(
            rows,
            key=lambda item: (
                item.get("object_name") or item.get("project") or "",
                item.get("issued_date", ""),
                item.get("number", ""),
            ),
        )

    def _sqlite_remarks(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for profile, repo in self._readonly_profile_repositories():
            try:
                for row in repo.list_remarks():
                    row.setdefault("__profile_slug", profile.slug)
                    rows.append(row)
            finally:
                repo.close()
        return sorted(rows, key=lambda item: (item.get("due_date", ""), item.get("created_at", "")))

    def _sqlite_audit_log(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for profile, repo in self._readonly_profile_repositories():
            try:
                for row in repo.list_audit_log():
                    row.setdefault("__profile_slug", profile.slug)
                    rows.append(row)
            finally:
                repo.close()
        return sorted(rows, key=lambda item: (item.get("changed_at", ""), item.get("id", "")))

    def _readonly_profile_repositories(self) -> list[tuple[Any, Repository]]:
        repositories = []
        assert self.actor is not None
        for profile in list_profiles(self.root):
            paths = ProfilePaths(self.root, profile.slug)
            if not paths.db_path.exists():
                continue
            try:
                repositories.append((profile, Repository(paths, self.actor, profile.name, read_only=True)))
            except sqlite3.Error:
                continue
        return repositories

    def _common_objects(self) -> list[dict[str, str]]:
        by_name: dict[str, dict[str, str]] = {}
        if self.repo:
            for item in self.repo.list_objects():
                name = item.get("name", "").strip()
                if name:
                    by_name[name.lower()] = {key: "" if value is None else str(value) for key, value in item.items()}
        for item in self._sqlite_objects():
            name = item.get("name", "").strip()
            if name and name.lower() not in by_name:
                by_name[name.lower()] = {key: "" if value is None else str(value) for key, value in item.items()}
        return sorted(by_name.values(), key=lambda item: item.get("name", ""))

    def _with_local_object(self, payload: dict[str, str]) -> dict[str, str]:
        assert self.repo is not None
        object_id = payload.get("object_id", "").strip()
        if not object_id or self.repo.get_object(object_id):
            return payload
        source = next((item for item in self._common_objects() if item.get("id") == object_id), None)
        if source is None:
            return payload
        existing = self.repo.find_object_by_name(source.get("name", ""))
        if existing:
            payload["object_id"] = existing.get("id", "")
            return payload
        payload["object_id"] = self.repo.save_object(
            {
                "id": source.get("id", object_id),
                "name": source.get("name", ""),
                "address": source.get("address", ""),
                "customer": source.get("customer", ""),
                "note": source.get("note", ""),
            }
        )
        return payload

    def _record_attachment_path(self, rows: list[dict[str, Any]], record_id: str) -> Path | None:
        for row in rows:
            if row.get("id") != record_id:
                continue
            relative = row.get("attachment_folder", "").strip()
            if not relative:
                return None
            owner_slug = row.get("owner_slug", "").strip() or row.get("__profile_slug", "").strip()
            if not owner_slug:
                return None
            profile_dir = ProfilePaths(self.root, owner_slug).profile_dir
            target = (profile_dir / relative).resolve()
            base = profile_dir.resolve()
            if target.is_relative_to(base):
                return target
            return None
        return None

    def _require_write(self) -> None:
        if self.read_only or not self.repo:
            raise RuntimeError("Текущий режим открыт только для чтения.")


def _not_owner(item: dict[str, Any]) -> bool:
    return item.get("created_by_kind") != SOURCE_OWNER or item.get("updated_by_kind") != SOURCE_OWNER


def _normalize_ids(value: str | list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [item for item in value if item]


def _date_within_7_days(value: str) -> bool:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    today = date.today()
    return today <= parsed <= today + timedelta(days=7)


def _objects_from_prescriptions(prescriptions: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in prescriptions:
        object_id = item.get("object_id", "")
        name = item.get("object_name", "") or item.get("project", "") or "Без объекта"
        key = object_id or name
        grouped.setdefault(
            key,
            {
                "id": object_id or name,
                "name": name,
                "address": item.get("object_address", ""),
                "customer": item.get("object_customer", ""),
                "owner_slug": item.get("owner_slug", ""),
                "owner_name": item.get("owner_name", ""),
                "prescriptions_total": 0,
                "prescriptions_active": 0,
                "prescriptions_overdue": 0,
            },
        )
        grouped[key]["prescriptions_total"] += 1
        if item.get("status") != PRESCRIPTION_DONE:
            grouped[key]["prescriptions_active"] += 1
        if int(item.get("overdue_count") or 0):
            grouped[key]["prescriptions_overdue"] += 1
    return [dict(value) for value in sorted(grouped.values(), key=lambda row: row.get("name", ""))]


def _image_paths(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)


def _matches_export_prescription(item: dict[str, Any], filter_name: str) -> bool:
    if filter_name == "active":
        return item.get("status") != PRESCRIPTION_DONE
    if filter_name == "overdue":
        return int(item.get("overdue_count") or 0) > 0
    if filter_name == "near_due":
        return _date_within_7_days(item.get("nearest_due_date", ""))
    if filter_name == "not_owner":
        return _not_owner(item)
    return True


def _matches_export_object(item: dict[str, Any], filter_name: str) -> bool:
    if filter_name == "active":
        return int(item.get("prescriptions_active") or 0) > 0
    if filter_name == "overdue":
        return int(item.get("prescriptions_overdue") or 0) > 0
    if filter_name == "near_due":
        return str(item.get("near_due", "")).lower() == "true"
    if filter_name == "not_owner":
        return _not_owner(item)
    return True


def _matches_export_remark(item: dict[str, Any], filter_name: str) -> bool:
    if filter_name == "active":
        return item.get("status") not in REMARK_COMPLETED
    if filter_name == "overdue":
        return str(item.get("is_overdue", "")).lower() == "true"
    if filter_name == "not_owner":
        return _not_owner(item)
    return True
