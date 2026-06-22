from __future__ import annotations

import argparse
import random
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cir_app.config import AppConfig
from cir_app.constants import ROLE_SPECIALIST, ROLE_SUBSTITUTE
from cir_app.runtime import Runtime


USERS = [
    ("ivanov", "Иванов И.И."),
    ("petrov", "Петров П.П."),
    ("sidorova", "Сидорова А.А."),
    ("smirnov", "Смирнов С.С."),
    ("kuznecova", "Кузнецова Е.В."),
]

PROJECTS = [
    "ЖК Северный квартал",
    "Логистический центр Восток",
    "БЦ Горизонт",
    "Реконструкция ПС-220",
    "Производственный корпус N3",
]

CONTRACTORS = [
    "ООО СтройМонтаж",
    "АО Генподряд",
    "ООО БетонПроф",
    "ООО ИнжСети",
    "АО МеталлКаркас",
    "ООО ФасадСервис",
]

SUBJECTS = [
    "Нарушения при производстве бетонных работ",
    "Недостатки исполнительной документации",
    "Замечания по монтажу инженерных сетей",
    "Контроль сварочных и антикоррозионных работ",
    "Отступления от проектных решений",
    "Замечания по качеству отделочных работ",
]

LOCATIONS = [
    "Корпус 1, оси А-Б/1-4",
    "Корпус 2, отметка +6.000",
    "Блок Б, технический этаж",
    "Паркинг, зона P2",
    "Кровля, секция 3",
    "ИТП, помещение 014",
    "Фасад, южная сторона",
    "Лестничная клетка ЛК-2",
]

REMARKS = [
    "Предоставить исполнительную схему с подписями ответственных лиц.",
    "Устранить отклонение от проектной отметки.",
    "Передать акт освидетельствования скрытых работ.",
    "Выполнить фотофиксацию до закрытия последующими работами.",
    "Восстановить защитный слой бетона в зоне дефекта.",
    "Оформить общий журнал работ за отчетный период.",
    "Предоставить паспорта и сертификаты на примененные материалы.",
    "Устранить повреждение антикоррозионного покрытия.",
    "Проверить соответствие фактической трассировки проекту.",
    "Обеспечить уборку зоны работ перед повторным осмотром.",
    "Согласовать корректирующее мероприятие с проектной организацией.",
    "Предъявить участок стройконтролю до бетонирования.",
]

STATUSES = ["not_started", "in_progress", "done", "accepted"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a deterministic CIR demo server.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "generated_demo_server_data",
        help="Target server directory. Defaults to generated_demo_server_data.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the target directory if it already exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    random.seed(20260605)
    output_dir = args.output
    if output_dir.exists():
        if not args.force:
            raise SystemExit(f"Target already exists: {output_dir}. Use --force to overwrite it.")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)

    prescription_number = 1
    created_prescriptions = 0
    created_remarks = 0

    for user_slug, user_name in USERS:
        config = AppConfig(
            server_root=str(output_dir),
            user_slug=user_slug,
            user_name=user_name,
            role=ROLE_SPECIALIST,
            active_profile_slug=user_slug,
        )
        runtime = Runtime(config)
        try:
            object_ids = {
                project: runtime.save_object(
                    {
                        "name": project,
                        "address": random.choice(LOCATIONS),
                        "customer": random.choice(CONTRACTORS),
                        "note": "Демо-объект",
                    }
                )
                for project in PROJECTS
            }
            for _ in range(4):
                issued = date.today() - timedelta(days=random.randint(2, 75))
                project = random.choice(PROJECTS)
                prescription_id = runtime.save_prescription(
                    {
                        "object_id": object_ids[project],
                        "number": f"ПР-2026-{prescription_number:03d}",
                        "project": project,
                        "contractor": random.choice(CONTRACTORS),
                        "subject": random.choice(SUBJECTS),
                        "issued_date": issued.isoformat(),
                    }
                )
                created_prescriptions += 1
                prescription_number += 1

                remark_count = random.randint(10, 40)
                for _remark_index in range(remark_count):
                    due = issued + timedelta(days=random.randint(5, 65))
                    status = random.choices(STATUSES, weights=[42, 28, 22, 8], k=1)[0]
                    runtime.save_remark(
                        {
                            "prescription_id": prescription_id,
                            "description": random.choice(REMARKS),
                            "location": random.choice(LOCATIONS),
                            "due_date": due.isoformat(),
                            "status": status,
                            "note": random.choice(
                                [
                                    "",
                                    "Подрядчик уведомлен письмом.",
                                    "Требуется повторная проверка на площадке.",
                                    "Ожидается комплект исполнительной документации.",
                                ]
                            ),
                        }
                    )
                    created_remarks += 1
        finally:
            runtime.close()

    substitute_edits = 0
    substitutes = [
        ("rukovoditel", "Руководитель стройконтроля"),
        ("zam_skk", "Замещающий специалист"),
    ]
    for owner_slug, _owner_name in USERS:
        for substitute_slug, substitute_name in substitutes:
            config = AppConfig(
                server_root=str(output_dir),
                user_slug=substitute_slug,
                user_name=substitute_name,
                role=ROLE_SUBSTITUTE,
                active_profile_slug=owner_slug,
            )
            runtime = Runtime(config)
            try:
                remarks = runtime.list_remarks()
                random.shuffle(remarks)
                for remark in remarks[: random.randint(4, 8)]:
                    remark["note"] = "Изменено в период замещения. Требуется верификация владельцем."
                    if remark["status"] == "not_started":
                        remark["status"] = "in_progress"
                    runtime.save_remark(remark)
                    substitute_edits += 1
            finally:
                runtime.close()

    print(f"created_dir={output_dir}")
    print(f"profiles={len(USERS)}")
    print(f"prescriptions={created_prescriptions}")
    print(f"remarks={created_remarks}")
    print(f"substitute_edits={substitute_edits}")


if __name__ == "__main__":
    main()
