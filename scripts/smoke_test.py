from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cir_app.config import AppConfig
from cir_app.paths import profile_paths
from cir_app.profile_meta import read_profile_name
from cir_app.runtime import Runtime
from cir_app.ui.main_window import parse_excel_remarks
from cir_app.xlsx_export import read_sheet


def main() -> None:
    with TemporaryDirectory() as directory:
        owner = AppConfig(
            server_root=directory,
            user_slug="ivanov",
            user_name="Иванов И.И.",
            role="specialist",
            active_profile_slug="ivanov",
        )
        runtime = Runtime(owner)
        try:
            runtime.seed_demo()
            assert read_profile_name(profile_paths(Path(directory), "ivanov")) == "Иванов И.И."
            export_path = Path(directory) / "profiles" / "ivanov" / "export.xlsx"
            objects = read_sheet(export_path, "Objects")
            assert len(objects) == 2
            prescriptions = read_sheet(export_path, "Prescriptions")
            assert len(prescriptions) == 2
            assert all(item["object_id"] for item in prescriptions)
            (runtime.attachments_path(prescriptions[0]["id"]) / "prescription-photo.jpg").write_bytes(b"fake image")
            first_remark = runtime.list_remarks()[0]
            first_remark["internal_code"] = "PHOTO-001"
            runtime.save_remark(first_remark)
            remark_folder = runtime.remark_attachments_path(first_remark["id"])
            assert "PHOTO-001" in remark_folder.name
            (remark_folder / "remark-photo.jpg").write_bytes(b"fake image")
            pasted = parse_excel_remarks(
                "Номер замечания\tОписание\tМесто\tСрок\tСтатус\tКомментарий\n"
                "RM-X01\tПроверить узел крепления\tКорпус 1\t05.06.2026\tВ работе\tИз Excel\n"
            )
            assert pasted[0]["internal_code"] == "RM-X01"
            assert pasted[0]["due_date"] == "2026-06-05"
            pasted[0]["prescription_id"] = prescriptions[0]["id"]
            runtime.save_remark(pasted[0])
            audit_rows = read_sheet(export_path, "AuditLog")
            assert any(row["entity_type"] == "remark" and row["action"] == "create" for row in audit_rows)

            blocked_substitute = Runtime(
                AppConfig(
                    server_root=directory,
                    user_slug="petrov",
                    user_name="Петров П.П.",
                    role="substitute",
                    active_profile_slug="ivanov",
                )
            )
            try:
                assert blocked_substitute.read_only
                assert "только для чтения" in blocked_substitute.lock_message
            finally:
                blocked_substitute.close()

            second_window = Runtime(owner)
            try:
                assert second_window.read_only
                assert "только для чтения" in second_window.lock_message
            finally:
                second_window.close()

            assignment_package = Path(directory) / "assignment.cirx"
            response_package = Path(directory) / "response.cirx"
            export_result = runtime.export_exchange_package(assignment_package, "assignment", include_attachments=False)
            assert export_result["remarks"] >= 2

            contractor_runtime = Runtime(
                AppConfig(
                    server_root=str(Path(directory) / "contractor_server"),
                    user_slug="ooo_beton",
                    user_name="ООО БетонПроф",
                    role="specialist",
                    active_profile_slug="ooo_beton",
                )
            )
            try:
                import_result = contractor_runtime.import_exchange_package(assignment_package)
                assert import_result["remarks"] >= 2
                contractor_remark = next(item for item in contractor_runtime.list_remarks() if item["id"] == first_remark["id"])
                contractor_photo = Path(directory) / "contractor-photo.jpg"
                contractor_photo.write_bytes(b"contractor photo")
                assert contractor_runtime.copy_remark_attachments(contractor_remark["id"], [str(contractor_photo)]) == 1
                contractor_remark["status"] = "done"
                contractor_remark["note"] = "Устранено подрядчиком, фото приложено."
                contractor_runtime.save_remark(contractor_remark)
                response_result = contractor_runtime.export_exchange_package(response_package, "response", include_attachments=True)
                assert response_result["remarks"] == 1
                assert response_result["attachments"] == 1
            finally:
                contractor_runtime.close()

            preview = runtime.inspect_exchange_package(response_package)
            assert preview["package_type"] == "response"
            assert preview["remarks"] == 1
            assert preview["attachments"] == 1
            office_import = runtime.import_exchange_package(response_package)
            assert office_import["remarks"] == 1
            assert office_import["attachments"] == 1
            imported_packages = read_sheet(export_path, "ImportedPackages")
            assert len(imported_packages) == 1
            assert imported_packages[0]["package_type"] == "response"
            updated_remark = next(item for item in runtime.list_remarks() if item["id"] == first_remark["id"])
            assert updated_remark["status"] == "done"
            assert updated_remark["note"] == "Устранено подрядчиком, фото приложено."
            assert updated_remark["source_label"] == "Подрядчик"
            assert updated_remark["needs_owner_review"]
            assert any(path.name.startswith("contractor-photo") for path in runtime.remark_image_paths(first_remark["id"]))
            try:
                runtime.import_exchange_package(response_package)
            except RuntimeError:
                pass
            else:
                raise AssertionError("duplicate exchange package import should be blocked")
        finally:
            runtime.close()

        renamed_owner = Runtime(
            AppConfig(
                server_root=directory,
                user_slug="ivanov",
                user_name="Иванов Иван Иванович",
                role="specialist",
                active_profile_slug="ivanov",
            )
        )
        renamed_owner.close()
        assert read_profile_name(profile_paths(Path(directory), "ivanov")) == "Иванов Иван Иванович"

        substitute = AppConfig(
            server_root=directory,
            user_slug="petrov",
            user_name="Петров П.П.",
            role="substitute",
            active_profile_slug="ivanov",
        )
        runtime = Runtime(substitute)
        first_remark["note"] = "Внесено в период замещения"
        runtime.save_remark(first_remark)
        runtime.close()

        runtime = Runtime(owner)
        assert runtime.dashboard()["needs_owner_review"] == 1
        assert len(runtime.list_objects()) == 2
        assert runtime.list_remarks(filter_name="not_owner")[0]["source_label"] == "Замещающий"
        assert len(runtime.list_remarks([prescriptions[0]["id"]])) >= 1
        linked_object_id = runtime.object_options()[0][0]
        try:
            runtime.delete_objects([linked_object_id])
        except RuntimeError:
            pass
        else:
            raise AssertionError("linked object deletion should be blocked")
        free_object_id = runtime.save_object({"name": "Свободный объект", "address": "", "customer": "", "note": ""})
        assert runtime.delete_objects([free_object_id]) == 1
        new_id = runtime.save_prescription(
            {
                "object_id": linked_object_id,
                "number": "DELETE-ME",
                "project": "Тест",
                "contractor": "Тест",
                "subject": "Тестовое удаление",
                "issued_date": "2026-06-05",
            }
        )
        assert runtime.delete_prescriptions([new_id]) == 1
        runtime.close()

        second_owner = Runtime(
            AppConfig(
                server_root=directory,
                user_slug="sidorov",
                user_name="Сидоров С.С.",
                role="specialist",
                active_profile_slug="sidorov",
            )
        )
        try:
            shared_options = second_owner.object_options()
            assert any(label == objects[0]["name"] for _, label in shared_options)
            shared_object_id = next(record_id for record_id, label in shared_options if label == objects[0]["name"])
            shared_prescription_id = second_owner.save_prescription(
                {
                    "object_id": shared_object_id,
                    "number": "COMMON-OBJECT",
                    "project": "Общий список",
                    "contractor": "Тест",
                    "subject": "Проверка общего объекта",
                    "issued_date": "2026-06-05",
                }
            )
            saved = second_owner.list_prescriptions()
            assert saved[0]["id"] == shared_prescription_id
            assert saved[0]["object_name"] == objects[0]["name"]
        finally:
            second_owner.close()

        supervisor = Runtime(
            AppConfig(
                server_root=directory,
                user_slug="boss",
                user_name="Руководитель",
                role="supervisor",
                active_profile_slug="",
            )
        )
        try:
            export_path.unlink(missing_ok=True)
            assert len(supervisor.list_prescriptions()) >= 2
            assert [path.name for path in supervisor.prescription_image_paths(prescriptions[0]["id"])] == ["prescription-photo.jpg"]
            supervisor_remark_images = [path.name for path in supervisor.remark_image_paths(first_remark["id"])]
            assert "remark-photo.jpg" in supervisor_remark_images
            assert any(name.startswith("contractor-photo") for name in supervisor_remark_images)
        finally:
            supervisor.close()

    with TemporaryDirectory() as directory:
        profile_dir = Path(directory) / "profiles" / "legacy"
        profile_dir.mkdir(parents=True)
        connection = sqlite3.connect(profile_dir / "cir.sqlite")
        connection.execute(
            """
            CREATE TABLE prescriptions (
                id TEXT PRIMARY KEY,
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
            )
            """
        )
        connection.execute(
            """
            INSERT INTO prescriptions (
                id, number, project, contractor, subject, issued_date, owner_slug, owner_name,
                attachment_folder, created_at, created_by_slug, created_by_name, created_by_kind,
                updated_at, updated_by_slug, updated_by_name, updated_by_kind
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-prescription",
                "ПР-OLD-001",
                "Старый объект",
                "ООО Ретро",
                "Миграция проекта в объект",
                "2026-06-01",
                "legacy",
                "Legacy User",
                "",
                "2026-06-01T00:00:00",
                "legacy",
                "Legacy User",
                "owner",
                "2026-06-01T00:00:00",
                "legacy",
                "Legacy User",
                "owner",
            ),
        )
        connection.commit()
        connection.close()
        runtime = Runtime(
            AppConfig(
                server_root=directory,
                user_slug="legacy",
                user_name="Legacy User",
                role="specialist",
                active_profile_slug="legacy",
            )
        )
        try:
            migrated_objects = runtime.list_objects()
            migrated_prescriptions = runtime.list_prescriptions()
            assert len(migrated_objects) == 1
            assert migrated_objects[0]["name"] == "Старый объект"
            assert migrated_prescriptions[0]["object_id"] == migrated_objects[0]["id"]
        finally:
            runtime.close()

    with TemporaryDirectory() as directory:
        profile_dir = Path(directory) / "profiles" / "legacy_sqlite"
        profile_dir.mkdir(parents=True)
        connection = sqlite3.connect(profile_dir / "cir.sqlite")
        connection.execute(
            """
            CREATE TABLE prescriptions (
                id TEXT PRIMARY KEY,
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
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO prescriptions (
                id, number, project, contractor, subject, issued_date, owner_slug, owner_name,
                attachment_folder, created_at, created_by_slug, created_by_name, created_by_kind,
                updated_at, updated_by_slug, updated_by_name, updated_by_kind
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "old-sqlite-1",
                    "ПР-OLD-001",
                    "Старый объект 1",
                    "ООО Ретро",
                    "Проверка старой базы",
                    "2026-06-01",
                    "legacy_sqlite",
                    "Legacy SQLite",
                    "",
                    "2026-06-01T00:00:00",
                    "legacy_sqlite",
                    "Legacy SQLite",
                    "owner",
                    "2026-06-01T00:00:00",
                    "legacy_sqlite",
                    "Legacy SQLite",
                    "owner",
                ),
                (
                    "old-sqlite-2",
                    "ПР-OLD-002",
                    "Старый объект 2",
                    "ООО Ретро",
                    "Проверка старой базы",
                    "2026-06-02",
                    "legacy_sqlite",
                    "Legacy SQLite",
                    "",
                    "2026-06-02T00:00:00",
                    "legacy_sqlite",
                    "Legacy SQLite",
                    "owner",
                    "2026-06-02T00:00:00",
                    "legacy_sqlite",
                    "Legacy SQLite",
                    "owner",
                ),
            ],
        )
        connection.commit()
        connection.close()
        supervisor = Runtime(
            AppConfig(
                server_root=directory,
                user_slug="boss",
                user_name="Руководитель",
                role="supervisor",
                active_profile_slug="",
            )
        )
        try:
            recovered = supervisor.list_objects()
            assert [item["id"] for item in recovered] == ["Старый объект 1", "Старый объект 2"]
            assert len(supervisor.list_prescriptions()) == 2
        finally:
            supervisor.close()

    print("smoke_test: ok")


if __name__ == "__main__":
    main()
