from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "main.py"
DIST_ROOT = PROJECT_ROOT / "dist"
BUILD_ROOT = PROJECT_ROOT / "build" / "release"
DEMO_SOURCE = PROJECT_ROOT / "generated_demo_server_data"
APP_ICON = PROJECT_ROOT / "cir_app" / "assets" / "app.ico"


def main() -> None:
    args = _parse_args()
    _require_pyinstaller()
    _require_tkinterdnd2()
    _require_demo_server()
    release_name = args.version
    release_dist = DIST_ROOT / release_name
    release_build = BUILD_ROOT / release_name
    if args.clean:
        _safe_rmtree(release_dist)
        _safe_rmtree(release_build)
    release_dist.mkdir(parents=True, exist_ok=True)
    release_build.mkdir(parents=True, exist_ok=True)

    app_exe = _build_app_exe(release_dist, release_build, release_name, console=args.console)
    full_exe = release_dist / f"CIR-{release_name}-full.exe"
    shutil.copy2(app_exe, full_exe)

    portable_dir = release_dist / f"CIR-{release_name}-portable"
    _prepare_portable(portable_dir, app_exe)
    portable_zip = release_dist / f"CIR-{release_name}-portable.zip"
    _zip_folder(portable_dir, portable_zip)

    installer_exe = _build_installer(release_dist, release_build, release_name, portable_dir)

    print(f"Release: {release_dist}")
    print(f"Portable folder: {portable_dir}")
    print(f"Portable zip: {portable_zip}")
    print(f"Full EXE: {full_exe}")
    print(f"Installer: {installer_exe}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build CIR release artifacts.")
    parser.add_argument("--version", default="v3", help="Release version label, e.g. v3 or v0.3.0.")
    parser.add_argument("--clean", action="store_true", help="Clean this release output before building.")
    parser.add_argument("--console", action="store_true", help="Build the main app with a diagnostic console.")
    return parser.parse_args()


def _require_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise SystemExit("PyInstaller is not installed. Run: python -m pip install pyinstaller") from exc


def _require_tkinterdnd2() -> None:
    try:
        import tkinterdnd2  # noqa: F401
    except ImportError as exc:
        raise SystemExit("tkinterdnd2 is not installed. Run: python -m pip install tkinterdnd2") from exc


def _require_demo_server() -> None:
    if not DEMO_SOURCE.exists():
        raise SystemExit(f"Demo server not found: {DEMO_SOURCE}")
    if not APP_ICON.exists():
        raise SystemExit(f"Application icon not found: {APP_ICON}")


def _build_app_exe(release_dist: Path, release_build: Path, release_name: str, *, console: bool) -> Path:
    app_dist = release_build / "app-dist"
    app_work = release_build / "pyinstaller-app"
    app_spec = release_build / "spec-app"
    _safe_rmtree(app_dist)
    _safe_rmtree(app_work)
    app_dist.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name",
        "CIR",
        "--distpath",
        str(app_dist),
        "--workpath",
        str(app_work),
        "--specpath",
        str(app_spec),
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
    app_exe = app_dist / "CIR.exe"
    if not app_exe.exists():
        raise SystemExit("PyInstaller finished without CIR.exe")
    return app_exe


def _prepare_portable(portable_dir: Path, app_exe: Path) -> None:
    _safe_rmtree(portable_dir)
    portable_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(app_exe, portable_dir / "CIR.exe")
    _copy_demo_server(portable_dir / "generated_demo_server_data")
    config = {
        "server_root": "generated_demo_server_data",
        "user_slug": "ivanov",
        "user_name": "Иванов И.И.",
        "role": "specialist",
        "active_profile_slug": "ivanov",
    }
    (portable_dir / ".cir_app_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _copy_demo_server(target: Path) -> None:
    _safe_rmtree(target)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.lock", "*.sqlite-wal", "*.sqlite-shm")
    shutil.copytree(DEMO_SOURCE, target, ignore=ignore)


def _zip_folder(source_dir: Path, target_zip: Path) -> None:
    if target_zip.exists():
        target_zip.unlink()
    archive_base = target_zip.with_suffix("")
    shutil.make_archive(str(archive_base), "zip", root_dir=source_dir.parent, base_dir=source_dir.name)


def _build_installer(release_dist: Path, release_build: Path, release_name: str, portable_dir: Path) -> Path:
    payload_zip = release_build / f"CIR-{release_name}-installer-payload.zip"
    _zip_folder(portable_dir, payload_zip)
    installer_script = release_build / "installer_bootstrap.py"
    _write_installer_script(installer_script, payload_zip.name)
    installer_work = release_build / "pyinstaller-installer"
    installer_spec = release_build / "spec-installer"
    _safe_rmtree(installer_work)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        f"CIR-{release_name}-Setup",
        "--distpath",
        str(release_dist),
        "--workpath",
        str(installer_work),
        "--specpath",
        str(installer_spec),
        "--clean",
        "--icon",
        str(APP_ICON),
        "--add-data",
        f"{payload_zip}{os.pathsep}.",
        str(installer_script),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    installer_exe = release_dist / f"CIR-{release_name}-Setup.exe"
    if not installer_exe.exists():
        raise SystemExit("PyInstaller finished without installer EXE")
    return installer_exe


def _write_installer_script(path: Path, payload_name: str) -> None:
    script = f'''
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk


PAYLOAD_NAME = {payload_name!r}
APP_FOLDER_NAME = "CIR"


def payload_path() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / PAYLOAD_NAME
    return Path(__file__).resolve().with_name(PAYLOAD_NAME)


def default_install_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(root) / "Programs" / APP_FOLDER_NAME


def create_shortcut(install_dir: Path) -> None:
    target = install_dir / "CIR.exe"
    if not target.exists():
        return
    desktop = Path.home() / "Desktop" / "CIR.lnk"
    ps = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut('{{desktop}}'); "
        f"$shortcut.TargetPath = '{{target}}'; "
        f"$shortcut.WorkingDirectory = '{{install_dir}}'; "
        "$shortcut.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def install() -> None:
    root = tk.Tk()
    root.withdraw()
    default_dir = default_install_dir()
    use_default = messagebox.askyesno(
        "CIR Setup",
        f"Install CIR to the default folder?\\n\\n{{default_dir}}\\n\\nChoose No to select another folder.",
    )
    if use_default:
        install_dir = default_dir
    else:
        selected = filedialog.askdirectory(title="Select CIR installation folder", initialdir=str(default_dir.parent))
        if not selected:
            return
        install_dir = Path(selected)

    if install_dir.exists() and any(install_dir.iterdir()):
        confirmed = messagebox.askyesno(
            "CIR Setup",
            f"The folder already contains files:\\n\\n{{install_dir}}\\n\\nExisting CIR files may be replaced. Continue?",
        )
        if not confirmed:
            return

    install_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload_path(), "r") as archive:
        temp_dir = install_dir.parent / f".{{install_dir.name}}_installing"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            archive.extractall(temp_dir)
            package_root = next(temp_dir.iterdir())
            for item in package_root.iterdir():
                destination = install_dir / item.name
                if destination.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                shutil.move(str(item), str(destination))
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

    create_shortcut(install_dir)
    messagebox.showinfo("CIR Setup", f"CIR installed successfully.\\n\\n{{install_dir}}")


if __name__ == "__main__":
    install()
'''
    path.write_text(textwrap.dedent(script).lstrip(), encoding="utf-8")


def _safe_rmtree(path: Path) -> None:
    if not path.exists():
        return
    resolved = path.resolve()
    project = PROJECT_ROOT.resolve()
    if resolved == project or project not in resolved.parents:
        raise RuntimeError(f"Refusing to remove outside project: {resolved}")
    shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
