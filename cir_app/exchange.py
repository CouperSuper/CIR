from __future__ import annotations

import hashlib
import json
import re
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import REMARK_DONE, REMARK_IN_PROGRESS, REMARK_NOT_STARTED, SOURCE_CONTRACTOR
from .storage import safe_folder_name


PACKAGE_FORMAT = "CIRX"
SCHEMA_VERSION = 1
DEFAULT_MAIL_LIMIT_MB = 22
IMAGE_EXTENSIONS = {".png", ".gif", ".jpg", ".jpeg", ".bmp", ".webp"}
RESPONSE_STATUSES = {REMARK_NOT_STARTED, REMARK_IN_PROGRESS, REMARK_DONE}


def suggest_package_name(runtime, package_type: str, contractor: str = "", object_label: str = "") -> str:
    kind = "для_подрядчика" if package_type == "assignment" else "ответ"
    parts = ["CIR", kind, contractor, object_label, datetime.now().strftime("%Y-%m-%d_%H-%M")]
    return "_".join(safe_folder_name(part) for part in parts if part).strip("_") + ".cirx"


def export_package(
    runtime,
    output_path: Path,
    package_type: str,
    contractor: str = "",
    object_id: str = "",
    include_attachments: bool = True,
    mail_limit_mb: int = DEFAULT_MAIL_LIMIT_MB,
) -> dict[str, Any]:
    if package_type not in {"assignment", "response"}:
        raise ValueError("Неизвестный тип пакета обмена.")
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".cirx":
        output_path = output_path.with_suffix(".cirx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    objects, prescriptions, remarks = _filtered_records(runtime, contractor, object_id, package_type)
    package_id = str(uuid.uuid4())
    manifest = {
        "format": PACKAGE_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "package_id": package_id,
        "package_type": package_type,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_profile_slug": runtime.active_profile_slug,
        "source_user_slug": runtime.config.user_slug,
        "source_user_name": runtime.config.user_name,
        "source_role": runtime.config.role,
        "filters": {
            "contractor": contractor,
            "object_id": object_id,
        },
        "counts": {
            "objects": len(objects),
            "prescriptions": len(prescriptions),
            "remarks": len(remarks),
        },
    }
    data = {
        "objects": objects,
        "prescriptions": prescriptions,
        "remarks": remarks,
    }
    checksums: dict[str, str] = {}

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _json_bytes(manifest))
        archive.writestr("data.json", _json_bytes(data))
        if include_attachments:
            for remark in remarks:
                for path in _remark_image_paths(runtime, remark.get("id", "")):
                    archive_name = f"attachments/remarks/{remark.get('id', '')}/{path.name}"
                    archive.write(path, archive_name)
                    checksums[archive_name] = _hash_file(path)
        archive.writestr("checksums.json", _json_bytes(checksums))

    size_bytes = output_path.stat().st_size
    return {
        "path": str(output_path),
        "package_id": package_id,
        "package_type": package_type,
        "objects": len(objects),
        "prescriptions": len(prescriptions),
        "remarks": len(remarks),
        "attachments": len(checksums),
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / 1024 / 1024, 2),
        "size_warning": size_bytes > mail_limit_mb * 1024 * 1024,
        "mail_limit_mb": mail_limit_mb,
    }


def inspect_package(runtime, package_path: Path) -> dict[str, Any]:
    loaded = _load_package(package_path)
    data = loaded["data"]
    manifest = loaded["manifest"]
    existing_objects = {item.get("id", ""): item for item in runtime.list_objects()}
    existing_prescriptions = {item.get("id", ""): item for item in runtime.list_prescriptions()}
    existing_remarks = {item.get("id", ""): item for item in runtime.list_remarks()}

    package_hash = _hash_file(Path(package_path))
    duplicate = bool(runtime.repo and runtime.repo.has_imported_package(manifest.get("package_id", ""), package_hash))
    package_type = manifest.get("package_type", "")
    conflicts = _response_conflicts(data.get("remarks", []), existing_remarks) if package_type == "response" else []
    return {
        "package_id": manifest.get("package_id", ""),
        "package_type": package_type,
        "created_at": manifest.get("created_at", ""),
        "sender": manifest.get("source_user_name", "") or manifest.get("source_user_slug", ""),
        "objects": len(data.get("objects", [])),
        "objects_new": sum(1 for item in data.get("objects", []) if item.get("id", "") not in existing_objects),
        "prescriptions": len(data.get("prescriptions", [])),
        "prescriptions_new": sum(1 for item in data.get("prescriptions", []) if item.get("id", "") not in existing_prescriptions),
        "remarks": len(data.get("remarks", [])),
        "remarks_new": sum(1 for item in data.get("remarks", []) if item.get("id", "") not in existing_remarks),
        "attachments": len(loaded["attachment_names"]),
        "conflicts": len(conflicts),
        "conflict_items": conflicts[:10],
        "duplicate": duplicate,
        "size_mb": round(Path(package_path).stat().st_size / 1024 / 1024, 2),
    }


def import_package(runtime, package_path: Path) -> dict[str, Any]:
    if runtime.read_only or not runtime.repo:
        raise RuntimeError("Текущий режим открыт только для чтения.")
    loaded = _load_package(package_path)
    manifest = loaded["manifest"]
    data = loaded["data"]
    package_id = manifest.get("package_id", "")
    package_hash = _hash_file(Path(package_path))
    if runtime.repo.has_imported_package(package_id, package_hash):
        raise RuntimeError("Этот пакет уже импортирован.")

    package_type = manifest.get("package_type", "")
    if package_type == "assignment":
        result = _import_assignment(runtime, data)
    elif package_type == "response":
        result = _import_response(runtime, data, manifest, loaded)
    else:
        raise RuntimeError("Неизвестный тип пакета обмена.")

    result.update(
        {
            "package_id": package_id,
            "package_type": package_type,
            "sender": manifest.get("source_user_name", "") or manifest.get("source_user_slug", ""),
        }
    )
    runtime.repo.record_imported_package(
        package_id=package_id,
        package_type=package_type,
        package_name=Path(package_path).name,
        package_hash=package_hash,
        sender_slug=manifest.get("source_user_slug", ""),
        sender_name=manifest.get("source_user_name", ""),
        summary=result,
    )
    runtime.export_current()
    return result


def _import_assignment(runtime, data: dict[str, Any]) -> dict[str, Any]:
    assert runtime.repo is not None
    objects = 0
    prescriptions = 0
    remarks = 0
    for item in data.get("objects", []):
        runtime.repo.save_object(_object_payload(item))
        objects += 1
    for item in data.get("prescriptions", []):
        runtime.repo.save_prescription(_prescription_payload(item))
        prescriptions += 1
    for item in data.get("remarks", []):
        runtime.repo.save_remark(_remark_payload(item), audit_prefix="Импорт задания: ")
        remarks += 1
    return {"objects": objects, "prescriptions": prescriptions, "remarks": remarks, "attachments": 0, "conflicts": 0}


def _import_response(runtime, data: dict[str, Any], manifest: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    assert runtime.repo is not None
    sender_slug = manifest.get("source_user_slug", "") or "contractor"
    sender_name = manifest.get("source_user_name", "") or sender_slug
    objects = 0
    prescriptions = 0
    remarks = 0
    conflicts = _response_conflicts(data.get("remarks", []), {item.get("id", ""): item for item in runtime.list_remarks()})

    for item in data.get("objects", []):
        if not runtime.repo.get_object(item.get("id", "")):
            runtime.repo.save_object(_object_payload(item))
            objects += 1
    for item in data.get("prescriptions", []):
        if not runtime.repo.get_prescription(item.get("id", "")):
            runtime.repo.save_prescription(_prescription_payload(item))
            prescriptions += 1
    for item in data.get("remarks", []):
        existing = runtime.repo.get_remark(item.get("id", ""))
        payload = _response_remark_payload(item, existing)
        runtime.repo.save_remark(
            payload,
            actor_slug=sender_slug,
            actor_name=sender_name,
            actor_kind=SOURCE_CONTRACTOR,
            audit_prefix="Импорт ответа подрядчика: ",
        )
        remarks += 1

    attachment_count = _import_attachments(runtime, loaded, sender_slug, sender_name, SOURCE_CONTRACTOR)
    return {
        "objects": objects,
        "prescriptions": prescriptions,
        "remarks": remarks,
        "attachments": attachment_count,
        "conflicts": len(conflicts),
    }


def _import_attachments(runtime, loaded: dict[str, Any], sender_slug: str, sender_name: str, actor_kind: str) -> int:
    assert runtime.repo is not None
    count = 0
    with zipfile.ZipFile(loaded["path"], "r") as archive:
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            for archive_name in loaded["attachment_names"]:
                remark_id = _remark_id_from_attachment_name(archive_name)
                if not remark_id:
                    continue
                target = temp_root / safe_folder_name(remark_id) / Path(archive_name).name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(archive_name))
                count += runtime.repo.copy_remark_attachments(
                    remark_id,
                    [str(target)],
                    actor_slug=sender_slug,
                    actor_name=sender_name,
                    actor_kind=actor_kind,
                    audit_prefix="Импорт ответа подрядчика: ",
                )
    return count


def _filtered_records(runtime, contractor: str, object_id: str, package_type: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    prescriptions = runtime.list_prescriptions()
    if contractor:
        prescriptions = [item for item in prescriptions if item.get("contractor", "") == contractor]
    if object_id:
        prescriptions = [item for item in prescriptions if item.get("object_id", "") == object_id]
    prescription_ids = {item.get("id", "") for item in prescriptions}
    object_ids = {item.get("object_id", "") for item in prescriptions if item.get("object_id", "")}
    remarks = [item for item in runtime.list_remarks() if item.get("prescription_id", "") in prescription_ids]
    if package_type == "response":
        remarks = [item for item in remarks if _has_response_content(runtime, item)]
        prescription_ids = {item.get("prescription_id", "") for item in remarks}
        prescriptions = [item for item in prescriptions if item.get("id", "") in prescription_ids]
        object_ids = {item.get("object_id", "") for item in prescriptions if item.get("object_id", "")}
    objects = [item for item in runtime.list_objects() if item.get("id", "") in object_ids or (object_id and item.get("id", "") == object_id)]
    return [_clean_record(item) for item in objects], [_clean_record(item) for item in prescriptions], [_clean_record(item) for item in remarks]


def _has_response_content(runtime, remark: dict[str, Any]) -> bool:
    if str(remark.get("updated_at", "") or "") != str(remark.get("created_at", "") or ""):
        return True
    return bool(_remark_image_paths(runtime, remark.get("id", "")))


def _remark_image_paths(runtime, remark_id: str) -> list[Path]:
    if not remark_id:
        return []
    try:
        folder = runtime.remark_attachments_path(remark_id)
    except Exception:
        return []
    if not folder.exists():
        return []
    return sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)


def _load_package(package_path: Path) -> dict[str, Any]:
    path = Path(package_path)
    with zipfile.ZipFile(path, "r") as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != PACKAGE_FORMAT:
            raise RuntimeError("Файл не является пакетом CIR.")
        if int(manifest.get("schema_version") or 0) > SCHEMA_VERSION:
            raise RuntimeError("Пакет создан более новой версией CIR.")
        data = json.loads(archive.read("data.json").decode("utf-8"))
        attachment_names = [
            name
            for name in archive.namelist()
            if name.startswith("attachments/remarks/") and not name.endswith("/")
        ]
    return {"path": path, "manifest": manifest, "data": data, "attachment_names": attachment_names}


def _response_conflicts(remarks: list[dict[str, Any]], existing_remarks: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    result = []
    protected_fields = ("prescription_id", "description", "location", "due_date")
    for item in remarks:
        existing = existing_remarks.get(item.get("id", ""))
        if not existing:
            continue
        changed = []
        for field in protected_fields:
            if str(existing.get(field, "") or "") != str(item.get(field, "") or ""):
                changed.append(field)
        if changed:
            result.append(
                {
                    "remark_id": item.get("id", ""),
                    "internal_code": item.get("internal_code", ""),
                    "fields": ", ".join(changed),
                }
            )
    return result


def _response_remark_payload(item: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, str]:
    status = str(item.get("status", "") or "")
    if status not in RESPONSE_STATUSES:
        status = REMARK_DONE if status == "accepted" else (existing or {}).get("status", REMARK_NOT_STARTED)
    if existing:
        return {
            "id": existing.get("id", ""),
            "prescription_id": existing.get("prescription_id", ""),
            "internal_code": existing.get("internal_code", "") or item.get("internal_code", ""),
            "description": existing.get("description", ""),
            "location": existing.get("location", ""),
            "due_date": existing.get("due_date", ""),
            "status": status,
            "note": str(item.get("note", "") or ""),
        }
    payload = _remark_payload(item)
    payload["status"] = status
    return payload


def _object_payload(item: dict[str, Any]) -> dict[str, str]:
    return {key: str(item.get(key, "") or "") for key in ("id", "name", "address", "customer", "note")}


def _prescription_payload(item: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(item.get(key, "") or "")
        for key in ("id", "object_id", "number", "project", "contractor", "subject", "issued_date")
    }


def _remark_payload(item: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(item.get(key, "") or "")
        for key in ("id", "prescription_id", "internal_code", "description", "location", "due_date", "status", "note")
    }


def _clean_record(item: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in item.items():
        if key.startswith("__"):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
        else:
            result[key] = str(value)
    return result


def _remark_id_from_attachment_name(value: str) -> str:
    match = re.fullmatch(r"attachments/remarks/([^/]+)/[^/]+", value)
    return match.group(1) if match else ""


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
