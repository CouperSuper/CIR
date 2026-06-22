from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "main.py"
DIST_ROOT = PROJECT_ROOT / "dist"
APP_DIST = DIST_ROOT / "CIR"
BUILD_ROOT = PROJECT_ROOT / "build" / "pyinstaller"
DEMO_SOURCE = PROJECT_ROOT / "generated_demo_server_data"
DEMO_TARGET = APP_DIST / "server_data"
CONFIG_TARGET = APP_DIST / ".cir_app_config.json"
APP_ICON = PROJECT_ROOT / "cir_app" / "assets" / "app.ico"


def main() -> None:
    args = _parse_args()
    _require_pyinstaller()
    _require_tkinterdnd2()
    if args.clean:
        _remove(APP_DIST)
        _remove(BUILD_ROOT)
    APP_DIST.mkdir(parents=True, exist_ok=True)
    _build_exe(args.console)
    _copy_demo_server()
    _write_demo_config()
    print(f"Готово: {APP_DIST}")
    print(f"EXE: {APP_DIST / 'CIR.exe'}")
    print(f"Демо-сервер: {DEMO_TARGET}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Собрать CIR в Windows EXE.")
    parser.add_argument("--clean", action="store_true", help="Очистить build/dist перед сборкой.")
    parser.add_argument("--console", action="store_true", help="Оставить консоль у EXE для диагностики.")
    return parser.parse_args()


def _require_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise SystemExit("PyInstaller не установлен. Установите его командой: python -m pip install pyinstaller") from exc


def _require_tkinterdnd2() -> None:
    try:
        import tkinterdnd2  # noqa: F401
    except ImportError as exc:
        raise SystemExit("tkinterdnd2 is not installed. Install it with: python -m pip install tkinterdnd2") from exc


def _build_exe(console: bool) -> None:
    if not APP_ICON.exists():
        raise SystemExit(f"Не найдена иконка приложения: {APP_ICON}")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name",
        "CIR",
        "--distpath",
        str(APP_DIST),
        "--workpath",
        str(BUILD_ROOT),
        "--specpath",
        str(BUILD_ROOT),
        "--clean",
        "--icon",
        str(APP_ICON),
        "--add-data",
        f"{APP_ICON}{os.pathsep}{Path('cir_app') / 'assets'}",
        "--collect-all",
        "tkinterdnd2",
    ]
    command.append("--console" if console else "--windowed")
    command.append(str(ENTRYPOINT))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def _copy_demo_server() -> None:
    if not DEMO_SOURCE.exists():
        raise SystemExit(f"Не найдена папка демо-сервера: {DEMO_SOURCE}")
    _remove(DEMO_TARGET)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.lock", "*.sqlite-wal", "*.sqlite-shm")
    shutil.copytree(DEMO_SOURCE, DEMO_TARGET, ignore=ignore)


def _write_demo_config() -> None:
    payload = {
        "server_root": "server_data",
        "user_slug": "ivanov",
        "user_name": "Иванов И.И.",
        "role": "specialist",
        "active_profile_slug": "ivanov",
    }
    CONFIG_TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


if __name__ == "__main__":
    main()
