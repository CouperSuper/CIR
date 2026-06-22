from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

from .config import default_config_path, load_config, save_config
from .runtime import Runtime
from .ui.main_window import MainWindow, SetupDialog
from .ui.theme import apply_style

try:
    from tkinterdnd2 import TkinterDnD
except Exception:
    TkinterDnD = None


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def app_icon_path() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "cir_app" / "assets" / "app.ico"
    return Path(__file__).resolve().parent / "assets" / "app.ico"


def apply_app_icon(root: tk.Tk) -> None:
    icon_path = app_icon_path()
    if not icon_path.exists():
        return
    try:
        root.iconbitmap(default=str(icon_path))
    except tk.TclError:
        try:
            root.iconbitmap(str(icon_path))
        except tk.TclError:
            pass


def main() -> None:
    enable_windows_dpi_awareness()
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    apply_app_icon(root)
    apply_style(root)
    config = load_config()
    if not default_config_path().exists():
        dialog = SetupDialog(root, config)
        root.wait_window(dialog)
        if dialog.result:
            config = dialog.result
            save_config(config)
    runtime = Runtime(config)
    MainWindow(root, runtime)
    try:
        root.mainloop()
    finally:
        runtime.close()
