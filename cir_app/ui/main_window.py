from __future__ import annotations

import csv
import calendar
import io
import json
import os
import re
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cir_app.config import AppConfig, save_config, slugify
from cir_app.constants import (
    REMARK_COMPLETED,
    REMARK_IN_PROGRESS,
    REMARK_STATUS_LABELS,
    ROLE_LABELS,
    ROLE_SPECIALIST,
    ROLE_SUBSTITUTE,
    ROLE_SUPERVISOR,
)
from cir_app.profile_meta import list_profiles
from cir_app.runtime import Runtime

from .theme import (
    ACCENT,
    ACCENT_DARK,
    ACCENT_SOFT,
    BG,
    BORDER,
    DANGER,
    DANGER_SOFT,
    GRID,
    MUTED,
    PANEL,
    PANEL_ALT,
    SIDEBAR,
    SUCCESS,
    SURFACE,
    TEXT,
    WARNING,
    WARNING_SOFT,
    Card,
    apply_style,
    draw_icon_badge as _draw_icon_badge,
    draw_progress_bar as _draw_bar,
    draw_soft_bar as _draw_soft_bar,
    font_tuple,
    grid_treeview_with_scrollbars,
    make_status_chip,
    stripe_treeview,
    style_text_widget,
    style_treeview,
)

try:
    from tkinterdnd2 import DND_FILES
except Exception:
    DND_FILES = None

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None


_FILE_DROP_ZONES: list[tuple[tk.Widget, object]] = []


def bind_debounced_event(widget: tk.Widget, sequence: str, callback, delay: int = 160) -> None:
    after_id: str | None = None

    def run_callback() -> None:
        nonlocal after_id
        after_id = None
        try:
            if not widget.winfo_exists():
                return
        except tk.TclError:
            return
        callback()

    def schedule(_event=None) -> None:
        nonlocal after_id
        if after_id is not None:
            try:
                widget.after_cancel(after_id)
            except tk.TclError:
                pass
        after_id = widget.after(delay, run_callback)

    widget.bind(sequence, schedule, add="+")


def register_file_drop_zone(widget: tk.Widget, callback) -> None:
    _FILE_DROP_ZONES.append((widget, callback))


def dispatch_file_drop(root: tk.Widget, paths: list[str], x_root: int | None = None, y_root: int | None = None) -> bool:
    if not paths:
        return False
    if x_root is None or y_root is None:
        return False
    target = None
    try:
        target = root.winfo_containing(x_root, y_root)
    except tk.TclError:
        target = None
    if target is None:
        return False
    for widget, callback in reversed(_FILE_DROP_ZONES):
        if not _widget_exists(widget):
            continue
        if target is not None and not _is_widget_or_descendant(target, widget):
            continue
        callback(paths)
        return True
    return False


def drop_event_paths(widget: tk.Widget, data: object) -> list[str]:
    if not data:
        return []
    try:
        values = widget.tk.splitlist(str(data))
    except tk.TclError:
        values = re.split(r"[\r\n]+", str(data))
    result = []
    for raw in values:
        value = str(raw).strip().strip('"').strip()
        if value:
            result.append(value)
    return result


def queue_file_drop(
    widget: tk.Widget,
    callback,
    paths: list[str],
    x_root: int | None = None,
    y_root: int | None = None,
) -> None:
    values = [str(path) for path in paths if str(path).strip()]
    if not values:
        return
    try:
        widget.after_idle(lambda items=values, x=x_root, y=y_root: _call_drop_callback(callback, items, x, y))
    except tk.TclError:
        return


FILTERS = {
    "all": "Все",
    "active": "На контроле",
    "overdue": "Просрочено",
    "near_due": "Ближайшие 7 дней",
    "not_owner": "Внесено не владельцем",
}

ALL_PROJECTS = "Все проекты"
ALL_OBJECTS = "Все объекты"
UNASSIGNED_OBJECT = "Без объекта"
ALL_CONTRACTORS = "Все подрядчики"
IMAGE_EXTENSIONS = {".png", ".gif", ".ppm", ".pgm", ".jpg", ".jpeg", ".bmp", ".webp"}
MONTH_NAMES = (
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)

AUDIT_ENTITY_LABELS = {
    "object": "Объект",
    "prescription": "Предписание",
    "remark": "Замечание",
    "package": "Пакет",
}

AUDIT_ACTION_LABELS = {
    "create": "Создание",
    "update": "Изменение",
    "delete": "Удаление",
    "add_attachments": "Вложения",
    "import_package": "Импорт",
}


class MainWindow:
    def __init__(self, root: tk.Tk, runtime: Runtime):
        self.root = root
        self.runtime = runtime
        self.root.title("CIR · Construction Inspection Register")
        self.root.geometry("1920x1080")
        self.root.minsize(1366, 768)
        apply_style(root)
        self.active_page_name = "dashboard"

        self.shell = tk.Frame(root, bg=BG)
        self.shell.pack(fill="both", expand=True)
        self.shell.columnconfigure(1, weight=1)
        self.shell.rowconfigure(0, weight=1)

        self.sidebar = ttk.Frame(self.shell, style="Sidebar.TFrame", width=212)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        self.content = ttk.Frame(self.shell)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.page_host = ttk.Frame(self.content)
        self.page_host.grid(row=0, column=0, sticky="nsew", padx=20, pady=(10, 14))
        self.page_host.rowconfigure(0, weight=1)
        self.page_host.columnconfigure(0, weight=1)

        self.pages = {
            "dashboard": DashboardPage(self.page_host, self),
            "objects": ObjectsPage(self.page_host, self),
            "prescriptions": PrescriptionsPage(self.page_host, self),
            "remarks": RemarksPage(self.page_host, self),
            "exchange": ExchangePage(self.page_host, self),
            "audit": AuditPage(self.page_host, self),
            "settings": SettingsPage(self.page_host, self),
        }
        self.mounted_page_name = ""

        self.status_label = make_status_chip(self.content)
        self.status_label.place(relx=1.0, x=-12, y=8, anchor="ne")

        self._build_sidebar()
        self.show_page("dashboard")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after_idle(self._enable_root_file_drop)
        self.root.after(250, self._show_lock_warning_if_needed)

    def _build_sidebar(self) -> None:
        tk.Label(
            self.sidebar,
            text="CIR",
            bg=SIDEBAR,
            fg=TEXT,
            font=font_tuple(self.root, 28, "bold"),
            anchor="w",
        ).pack(fill="x", padx=16, pady=(18, 0))
        tk.Label(
            self.sidebar,
            text="Construction Inspection Register",
            bg=SIDEBAR,
            fg=MUTED,
            font=font_tuple(self.root, 11),
            anchor="w",
            wraplength=172,
        ).pack(fill="x", padx=18, pady=(0, 16))
        self.nav_buttons = {}
        for key, text in (
            ("dashboard", "Обзор"),
            ("objects", "Объекты"),
            ("prescriptions", "Предписания"),
            ("remarks", "Замечания"),
            ("exchange", "Обмен"),
            ("audit", "Журнал"),
        ):
            button = ttk.Button(self.sidebar, text=text, style="Nav.TButton", command=lambda value=key: self.show_page(value))
            button.pack(fill="x", padx=10, pady=3)
            self.nav_buttons[key] = button
        tk.Frame(self.sidebar, bg=SIDEBAR).pack(fill="both", expand=True)
        button = ttk.Button(self.sidebar, text="Настройки", style="Nav.TButton", command=lambda: self.show_page("settings"))
        button.pack(fill="x", padx=10, pady=(3, 16))
        self.nav_buttons["settings"] = button

    def show_page(self, name: str, **kwargs) -> None:
        self.update_status()
        for key, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if key == name else "Nav.TButton")
        if self.mounted_page_name and self.mounted_page_name != name:
            self.pages[self.mounted_page_name].grid_remove()
        page = self.pages[name]
        if self.mounted_page_name != name:
            page.grid(row=0, column=0, sticky="nsew")
            self.mounted_page_name = name
        self.active_page_name = name
        page.refresh(**kwargs)

    def update_status(self) -> None:
        profile = self.runtime.active_profile_slug
        mode = self.runtime.mode_label
        access = "только чтение" if self.runtime.read_only else "редактирование"
        self.status_label.configure(text=f"{mode} · профиль: {profile} · {access} · {self.runtime.lock_message}")

    def reload_runtime(self, config: AppConfig) -> None:
        self.runtime.reload(config)
        save_config(self.runtime.config)
        self.update_status()
        self.pages[self.active_page_name].refresh()

    def _on_close(self) -> None:
        self.runtime.close()
        self.root.destroy()

    def _show_lock_warning_if_needed(self) -> None:
        if self.runtime.config.role == ROLE_SUPERVISOR:
            return
        if not self.runtime.read_only:
            return
        messagebox.showwarning(
            "CIR",
            f"{self.runtime.lock_message}\n\n"
            "Можно просматривать данные, но сохранять изменения в этом окне нельзя.",
        )

    def _enable_root_file_drop(self) -> None:
        if DND_FILES is None or not hasattr(self.root, "drop_target_register"):
            return
        try:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_root_file_drop)
        except Exception:
            return

    def _on_root_file_drop(self, event) -> None:
        paths = drop_event_paths(self.root, getattr(event, "data", ""))
        queue_file_drop(
            self.root,
            self._handle_root_file_drop,
            paths,
            getattr(event, "x_root", None),
            getattr(event, "y_root", None),
        )

    def _handle_root_file_drop(self, paths: list[str], x_root: int | None = None, y_root: int | None = None) -> None:
        if dispatch_file_drop(self.root, paths, x_root, y_root):
            return
        page = self.pages.get(self.active_page_name) or self.pages.get("prescriptions")
        current = self.root.focus_get()
        if current is not None:
            for name, candidate in self.pages.items():
                if _is_widget_or_descendant(current, candidate):
                    page = candidate
                    break
        if hasattr(page, "copy_attachment_paths"):
            page.copy_attachment_paths(paths)


class DashboardPage(ttk.Frame):
    def __init__(self, master, app: MainWindow):
        super().__init__(master)
        self.app = app
        self.prescriptions: list[dict] = []
        self.gantt_filter_name = "all"
        self.gantt_project = ""
        self.gantt_contractor = ""
        self.gantt: GanttChart | None = None
        self.gantt_filter_label: ttk.Label | None = None
        self.project_tree: ttk.Treeview | None = None
        self.contractor_tree: ttk.Treeview | None = None
        self.project_tree_items: dict[str, str] = {}
        self.contractor_tree_items: dict[str, str] = {}

    def refresh(self, **kwargs) -> None:
        _clear(self)
        data = self.app.runtime.dashboard()
        prescriptions = self.app.runtime.list_prescriptions()
        self.prescriptions = prescriptions
        ttk.Label(self, text="Обзор", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self, text="Контроль сроков, исполнения и изменений за период замещения", style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(1, 8)
        )

        metrics = ttk.Frame(self)
        metrics.grid(row=2, column=0, sticky="ew")
        for column in range(6):
            metrics.columnconfigure(column, weight=1)

        cards = [
            ("На контроле", data["prescriptions_active"], "active", ACCENT, "OK"),
            ("Просрочено", data["prescriptions_overdue"], "overdue", DANGER, "!"),
            ("Ближайшие 7 дней", data["near_due"], "near_due", WARNING, "7"),
            ("Открытые замечания", data["remarks_open"], None, ACCENT, "RM"),
            ("Внесено не владельцем", data["needs_owner_review"], "not_owner", DANGER if data["needs_owner_review"] else MUTED, "ID"),
            ("Всего предписаний", data["prescriptions_total"], "all", MUTED, "#"),
        ]
        for index, (title, value, filter_name, color, icon) in enumerate(cards):
            target_filter = filter_name or "active"
            card = MetricCard(
                metrics,
                title,
                value,
                color,
                icon,
                command=lambda f=target_filter: self.apply_gantt_filter(filter_name=f),
                open_prescriptions_command=lambda f=target_filter: self._open_metric_prescriptions(f),
                open_remarks_command=lambda f=target_filter: self._open_metric_remarks(f),
            )
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0), pady=(0, 9))

        status_panel = ttk.Frame(self)
        status_panel.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        status_panel.columnconfigure(0, weight=1)
        StatusBars(status_panel, prescriptions).grid(row=0, column=0, sticky="ew")

        body = ttk.Frame(self)
        body.grid(row=4, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        self.columnconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        left.rowconfigure(3, weight=1)

        ttk.Label(left, text="Объекты", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        project_card = Card(left, radius=12, shadow=True)
        project_card.grid(row=1, column=0, sticky="nsew")
        project_card.rowconfigure(0, weight=1)
        project_card.columnconfigure(0, weight=1)
        tree = ttk.Treeview(project_card, columns=("project", "total", "active", "overdue"), show="headings", height=8)
        self.project_tree = tree
        self.project_tree_items = {}
        style_treeview(tree)
        for key, title, width in (
            ("project", "Объект", 260),
            ("total", "Всего", 90),
            ("active", "На контроле", 120),
            ("overdue", "Просрочено", 120),
        ):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        grid_treeview_with_scrollbars(project_card, tree, padx=8, pady=8)
        for project, item in data.get("objects", data["projects"]).items():
            item_id = tree.insert("", "end", values=(project, item["total"], item["active"], item["overdue"]))
            self.project_tree_items[project] = item_id
        stripe_treeview(tree)
        tree.bind("<ButtonRelease-1>", lambda event: self._filter_gantt_from_tree(tree, event, "project"))
        tree.bind("<Control-c>", lambda event: copy_treeview_to_clipboard(tree))
        tree.bind("<Button-3>", lambda event: show_tree_copy_menu(tree, event))

        ttk.Label(left, text="Подрядчики", style="Section.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 4))
        contractors = _contractor_summary(prescriptions)
        contractor_card = Card(left, radius=12, shadow=True)
        contractor_card.grid(row=3, column=0, sticky="nsew")
        contractor_card.rowconfigure(0, weight=1)
        contractor_card.columnconfigure(0, weight=1)
        contractor_tree = ttk.Treeview(contractor_card, columns=("contractor", "total", "active", "overdue"), show="headings", height=8)
        self.contractor_tree = contractor_tree
        self.contractor_tree_items = {}
        style_treeview(contractor_tree)
        for key, title, width in (
            ("contractor", "Подрядчик", 260),
            ("total", "Всего", 90),
            ("active", "На контроле", 120),
            ("overdue", "Просрочено", 120),
        ):
            contractor_tree.heading(key, text=title)
            contractor_tree.column(key, width=width, anchor="w")
        grid_treeview_with_scrollbars(contractor_card, contractor_tree, padx=8, pady=8)
        for contractor, item in contractors.items():
            item_id = contractor_tree.insert("", "end", values=(contractor, item["total"], item["active"], item["overdue"]))
            self.contractor_tree_items[contractor] = item_id
        stripe_treeview(contractor_tree)
        contractor_tree.bind("<ButtonRelease-1>", lambda event: self._filter_gantt_from_tree(contractor_tree, event, "contractor"))
        contractor_tree.bind("<Control-c>", lambda event: copy_treeview_to_clipboard(contractor_tree))
        contractor_tree.bind("<Button-3>", lambda event: show_tree_copy_menu(contractor_tree, event))

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        header = ttk.Frame(right)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Сроки по предписаниям", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.gantt_filter_label = ttk.Label(header, text="", style="Subtitle.TLabel")
        self.gantt_filter_label.grid(row=0, column=1, sticky="e", padx=(12, 8))
        ttk.Button(header, text="Сбросить", style="Ghost.TButton", command=self.reset_gantt_filter).grid(row=0, column=2, sticky="e")
        self.gantt = GanttChart(right, self._open_prescription, self._open_remarks)
        self.gantt.grid(row=1, column=0, sticky="nsew")
        self._redraw_gantt()
        self._update_cross_highlights()

    def apply_gantt_filter(self, filter_name: str | None = None, project: str | None = None, contractor: str | None = None) -> None:
        if filter_name is not None:
            self.gantt_filter_name = filter_name
            if filter_name == "all":
                self.gantt_project = ""
                self.gantt_contractor = ""
        if project is not None:
            self.gantt_project = project
        if contractor is not None:
            self.gantt_contractor = contractor
        self._redraw_gantt()
        self._update_cross_highlights()

    def reset_gantt_filter(self) -> None:
        self.gantt_filter_name = "all"
        self.gantt_project = ""
        self.gantt_contractor = ""
        self._redraw_gantt()
        self._update_cross_highlights()

    def _filter_gantt_from_tree(self, tree: ttk.Treeview, event, kind: str) -> None:
        item_id = tree.identify_row(event.y)
        if not item_id:
            return
        values = tree.item(item_id, "values")
        if not values:
            return
        value = str(values[0])
        if kind == "project":
            if self.gantt_project == value:
                tree.selection_remove(item_id)
                self.apply_gantt_filter(project="")
            else:
                self.apply_gantt_filter(project=value)
        else:
            if self.gantt_contractor == value:
                tree.selection_remove(item_id)
                self.apply_gantt_filter(contractor="")
            else:
                self.apply_gantt_filter(contractor=value)

    def _redraw_gantt(self) -> None:
        records = [
            item
            for item in self.prescriptions
            if _matches_prescription_filter(item, self.gantt_filter_name)
            and (not self.gantt_project or _object_display_name(item) == self.gantt_project)
            and (not self.gantt_contractor or (item.get("contractor") or "Без подрядчика") == self.gantt_contractor)
        ]
        if self.gantt:
            self.gantt.draw(records)
        if self.gantt_filter_label:
            parts = []
            if self.gantt_filter_name != "all":
                parts.append(FILTERS.get(self.gantt_filter_name, self.gantt_filter_name))
            if self.gantt_project:
                parts.append(self.gantt_project)
            if self.gantt_contractor:
                parts.append(self.gantt_contractor)
            label = " · ".join(parts) if parts else "Все предписания"
            self.gantt_filter_label.configure(text=f"{label} · {len(records)}")

    def _update_cross_highlights(self) -> None:
        if self.project_tree:
            related_projects = self._projects_for_contractor(self.gantt_contractor) if self.gantt_contractor else set()
            for project, item_id in self.project_tree_items.items():
                tags = []
                if self.gantt_project == project:
                    tags.append("selected_filter")
                elif project in related_projects:
                    tags.append("cross_highlight")
                self.project_tree.item(item_id, tags=tuple(tags))
            stripe_treeview(self.project_tree)
        if self.contractor_tree:
            related_contractors = self._contractors_for_project(self.gantt_project) if self.gantt_project else set()
            for contractor, item_id in self.contractor_tree_items.items():
                tags = []
                if self.gantt_contractor == contractor:
                    tags.append("selected_filter")
                elif contractor in related_contractors:
                    tags.append("cross_highlight")
                self.contractor_tree.item(item_id, tags=tuple(tags))
            stripe_treeview(self.contractor_tree)

    def _contractors_for_project(self, project: str) -> set[str]:
        return {
            item.get("contractor") or "Без подрядчика"
            for item in self.prescriptions
            if _object_display_name(item) == project
        }

    def _projects_for_contractor(self, contractor: str) -> set[str]:
        return {
            _object_display_name(item)
            for item in self.prescriptions
            if (item.get("contractor") or "Без подрядчика") == contractor
        }

    def _open_prescription(self, prescription_id: str) -> None:
        self.app.show_page("prescriptions", selected_id=prescription_id)

    def _open_remarks(self, prescription_id: str) -> None:
        self.app.show_page("remarks", prescription_ids=[prescription_id])

    def _open_metric_prescriptions(self, filter_name: str) -> None:
        self.app.show_page("prescriptions", filter_name=filter_name)

    def _open_metric_remarks(self, filter_name: str) -> None:
        self.app.show_page("remarks", filter_name=filter_name, clear_context=True)


class MetricCard(Card):
    def __init__(
        self,
        master,
        title: str,
        value: int,
        color: str,
        icon: str,
        command=None,
        open_prescriptions_command=None,
        open_remarks_command=None,
    ):
        super().__init__(master, radius=14, shadow=True, cursor="hand2" if command else "")
        self.configure(height=86)
        self.grid_propagate(False)
        self.command = command
        self.open_prescriptions_command = open_prescriptions_command
        self.open_remarks_command = open_remarks_command
        badge = tk.Canvas(self, width=36, height=36, bg=PANEL, highlightthickness=0, bd=0)
        badge.place(x=10, y=12)
        _draw_icon_badge(badge, color, icon)
        tk.Label(self, text=title, bg=PANEL, fg=MUTED, font=font_tuple(self, 11), anchor="w", justify="left", wraplength=132).place(
            x=54, y=8, relwidth=1.0, width=-62, height=36
        )
        tk.Label(self, text=str(value), bg=PANEL, fg=TEXT, font=font_tuple(self, 25, "bold"), anchor="w").place(
            x=54, y=44, relwidth=1.0, width=-62, height=32
        )
        if command:
            self.bind("<Button-1>", lambda event: command())
            for child in self.winfo_children():
                child.bind("<Button-1>", lambda event: command())
        if open_prescriptions_command or open_remarks_command:
            self.bind("<Button-3>", self._show_menu)
            for child in self.winfo_children():
                child.bind("<Button-3>", self._show_menu)

    def _show_menu(self, event) -> None:
        menu = tk.Menu(self, tearoff=False)
        if self.open_prescriptions_command:
            menu.add_command(label="Перейти в предписания", command=self.open_prescriptions_command)
        if self.open_remarks_command:
            menu.add_command(label="Перейти в замечания", command=self.open_remarks_command)
        menu.tk_popup(event.x_root, event.y_root)


class AttachmentArea(Card):
    def __init__(self, master, open_command, add_command, paste_command, drop_command=None, show_add_button: bool = True):
        super().__init__(master, radius=16, shadow=False, surface=PANEL_ALT)
        self.open_command = open_command
        self.add_command = add_command
        self.paste_command = paste_command
        self.drop_command = drop_command or (lambda paths: None)
        self.show_add_button = show_add_button
        self.columnconfigure(0, weight=1)
        tk.Label(self, text="Вложения", bg=PANEL_ALT, fg=MUTED, anchor="w").grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        ttk.Button(self, text="Папка", style="Ghost.TButton", command=open_command).grid(row=0, column=1, sticky="e", padx=(4, 0), pady=5)
        if show_add_button:
            ttk.Button(self, text="Добавить", command=add_command).grid(row=0, column=2, sticky="e", padx=(4, 10), pady=5)
            self.bind("<Button-1>", lambda event: add_command())
        self.bind("<Control-v>", lambda event: paste_command())
        self.bind("<Button-3>", self._show_menu)
        for child in self.winfo_children():
            child.bind("<Control-v>", lambda event: paste_command())
            child.bind("<Button-3>", self._show_menu)
        self.after_idle(self._enable_drop)
        self.bind("<Map>", lambda event: self.after_idle(self._enable_drop))
        register_file_drop_zone(self, self.drop_command)

    def _show_menu(self, event) -> None:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Открыть папку", command=self.open_command)
        if self.show_add_button:
            menu.add_command(label="Добавить файлы", command=self.add_command)
        menu.add_command(label="Вставить файлы из буфера", command=self.paste_command)
        menu.tk_popup(event.x_root, event.y_root)

    def _enable_drop(self) -> None:
        targets = [self, *self.winfo_children()]
        if DND_FILES:
            for target in targets:
                if not hasattr(target, "drop_target_register"):
                    continue
                try:
                    target.drop_target_register(DND_FILES)
                    target.dnd_bind("<<Drop>>", self._on_drop)
                except Exception:
                    continue

    def _on_drop(self, event) -> None:
        paths = drop_event_paths(self, getattr(event, "data", ""))
        queue_file_drop(self, self.drop_command, paths)


class ImageGallery(Card):
    def __init__(self, master, drop_command=None):
        super().__init__(master)
        self.paths: list[Path] = []
        self.labels: list[str] = []
        self.index = 0
        self.layout_var = tk.StringVar(value="bottom")
        self.photo = None
        self.photo_cache: dict[tuple[str, int, int, float], object] = {}
        self.draw_after_id: str | None = None
        self.drop_command = drop_command
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=PANEL)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        header.columnconfigure(0, weight=1)
        self.title_label = tk.Label(header, text="Изображения", bg=PANEL, fg=MUTED, anchor="w")
        self.title_label.grid(row=0, column=0, sticky="ew")
        ttk.Button(header, text="‹", style="Ghost.TButton", width=3, command=self.previous).grid(row=0, column=1, padx=(4, 0))
        ttk.Button(header, text="›", style="Ghost.TButton", width=3, command=self.next).grid(row=0, column=2, padx=(4, 0))
        ttk.Button(header, text="Снизу", style="Ghost.TButton", width=8, command=lambda: self.set_layout("bottom")).grid(row=0, column=3, padx=(8, 0))
        ttk.Button(header, text="Справа", style="Ghost.TButton", width=8, command=lambda: self.set_layout("right")).grid(row=0, column=4, padx=(4, 0))

        self.body = tk.Frame(self, bg=PANEL)
        self.body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.viewer = tk.Canvas(self.body, bg=PANEL_ALT, highlightthickness=1, highlightbackground=BORDER, bd=0)
        self.viewer.bind("<Configure>", lambda event: self._schedule_draw_current())
        self.viewer.bind("<Double-1>", lambda event: self.next())
        self.thumbs = tk.Frame(self.body, bg=PANEL)
        self.set_layout("bottom")
        self.set_paths([])
        self.after_idle(self._enable_drop)
        self.bind("<Map>", lambda event: self.after_idle(self._enable_drop))
        if self.drop_command:
            register_file_drop_zone(self, self.drop_command)

    def set_paths(self, paths: list[Path]) -> None:
        self.set_items([(Path(path), Path(path).name) for path in paths])

    def set_items(self, items: list[tuple[Path, str]]) -> None:
        current = self.paths[self.index] if self.paths and self.index < len(self.paths) else None
        next_paths = [Path(path) for path, _label in items]
        next_labels = [label for _path, label in items]
        if next_paths == self.paths and next_labels == self.labels:
            return
        self.paths = next_paths
        self.labels = next_labels
        if current in self.paths:
            self.index = self.paths.index(current)
        else:
            self.index = 0
        self.photo_cache = {}
        self._draw_thumbs()
        self._schedule_draw_current()

    def set_layout(self, value: str) -> None:
        self.layout_var.set(value)
        self.viewer.grid_forget()
        self.thumbs.grid_forget()
        for column in range(2):
            self.body.columnconfigure(column, weight=0)
        for row in range(2):
            self.body.rowconfigure(row, weight=0)
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        if value == "right":
            self.viewer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            self.thumbs.grid(row=0, column=1, sticky="ns")
        else:
            self.viewer.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
            self.thumbs.grid(row=1, column=0, sticky="ew")
        self._draw_thumbs()
        self._schedule_draw_current()

    def previous(self) -> None:
        if not self.paths:
            return
        self.index = (self.index - 1) % len(self.paths)
        self._draw_thumbs()
        self._schedule_draw_current()

    def next(self) -> None:
        if not self.paths:
            return
        self.index = (self.index + 1) % len(self.paths)
        self._draw_thumbs()
        self._schedule_draw_current()

    def _schedule_draw_current(self) -> None:
        if self.draw_after_id:
            self.after_cancel(self.draw_after_id)
        self.draw_after_id = self.after(80, self._draw_current)

    def _draw_current(self) -> None:
        self.draw_after_id = None
        self.viewer.delete("all")
        self.photo = None
        count = len(self.paths)
        self.title_label.configure(text=f"Изображения: {count}" if count else "Изображения")
        width = max(self.viewer.winfo_width(), 220)
        height = max(self.viewer.winfo_height(), 160)
        if not self.paths:
            self.viewer.create_text(width / 2, height / 2, text="Нет изображений", fill=MUTED, font=font_tuple(self, 13))
            return
        path = self.paths[self.index]
        label = self.labels[self.index] if self.index < len(self.labels) else path.name
        try:
            self.photo = self._photo_for_path(path, width - 18, height - 30)
            self.viewer.create_image(width / 2, height / 2, image=self.photo, anchor="center")
        except Exception:
            self.viewer.create_text(
                width / 2,
                height / 2,
                text=f"{label}\nПредпросмотр недоступен",
                fill=MUTED,
                font=font_tuple(self, 13),
                justify="center",
            )
        self.viewer.create_text(10, height - 18, text=label, anchor="w", fill=MUTED, font=font_tuple(self, 12))

    def _draw_thumbs(self) -> None:
        _clear(self.thumbs)
        if not self.paths:
            return
        vertical = self.layout_var.get() == "right"
        for position, path in enumerate(self.paths):
            label = self.labels[position] if position < len(self.labels) else path.name
            button = tk.Button(
                self.thumbs,
                text=f"{position + 1}. {_shorten(label, 18)}",
                command=lambda index=position: self._select(index),
                bg=ACCENT_SOFT if position == self.index else PANEL,
                activebackground=ACCENT,
                fg=TEXT,
                relief="flat",
                bd=0,
                highlightbackground=BORDER,
                highlightthickness=1,
                font=font_tuple(self, 12, "bold" if position == self.index else "normal"),
                width=16,
                height=1,
                anchor="w",
            )
            if vertical:
                button.grid(row=position, column=0, sticky="ew", pady=(0, 4))
            else:
                button.grid(row=0, column=position, sticky="w", padx=(0, 4))

    def _select(self, index: int) -> None:
        self.index = index
        self._draw_thumbs()
        self._schedule_draw_current()

    def _photo_for_path(self, path: Path, max_width: int, max_height: int):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0
        key = (str(path), max(max_width // 40, 1), max(max_height // 40, 1), mtime)
        if key not in self.photo_cache:
            self.photo_cache[key] = _photo_for_canvas(path, max_width, max_height)
            if len(self.photo_cache) > 12:
                self.photo_cache.pop(next(iter(self.photo_cache)))
        return self.photo_cache[key]

    def _enable_drop(self) -> None:
        if not self.drop_command:
            return
        targets = [self, self.body, self.viewer, self.thumbs, *self.winfo_children()]
        if DND_FILES:
            for target in targets:
                if not hasattr(target, "drop_target_register"):
                    continue
                try:
                    target.drop_target_register(DND_FILES)
                    target.dnd_bind("<<Drop>>", self._on_drop)
                except Exception:
                    continue

    def _on_drop(self, event) -> None:
        paths = drop_event_paths(self, getattr(event, "data", ""))
        if self.drop_command:
            queue_file_drop(self, self.drop_command, paths)


class StatusBars(tk.Frame):
    def __init__(self, master, prescriptions: list[dict]):
        super().__init__(master, bg=BG)
        self.columnconfigure(0, weight=1)
        total = max(len(prescriptions), 1)
        groups = [
            ("Не исполняется", sum(1 for item in prescriptions if str(item.get("status", "")).startswith("Не исполняется")), DANGER),
            ("Исполняется", sum(1 for item in prescriptions if str(item.get("status", "")).startswith("Исполняется")), ACCENT),
            ("Выполнено", sum(1 for item in prescriptions if str(item.get("status", "")).startswith("Выполнено")), SUCCESS),
            ("С просрочкой", sum(1 for item in prescriptions if int(item.get("overdue_count") or 0)), WARNING),
        ]
        for index, (label, value, color) in enumerate(groups):
            self.columnconfigure(index, weight=1)
            panel = Card(self, radius=12, shadow=True)
            panel.configure(height=62)
            panel.grid_propagate(False)
            panel.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 10, 0))
            panel.columnconfigure(0, weight=1)
            tk.Label(panel, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 11), anchor="w").grid(
                row=0, column=0, sticky="ew", padx=10, pady=(7, 0)
            )
            tk.Label(panel, text=f"{value} · {round(value / total * 100)}%", bg=PANEL, fg=color, font=font_tuple(self, 12, "bold"), anchor="w").grid(
                row=1, column=0, sticky="ew", padx=10
            )
            bar = tk.Canvas(panel, height=8, bg=PANEL, bd=0, highlightthickness=0)
            bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 6))
            bind_debounced_event(bar, "<Configure>", lambda b=bar, v=value, c=color, t=total: _draw_bar(b, v, t, c), delay=80)


class GanttChart(Card):
    def __init__(self, master, open_prescription_command=None, open_remarks_command=None):
        super().__init__(master, radius=14, shadow=True)
        self.prescriptions: list[dict] = []
        self.row_items: list[tuple[int, int, dict]] = []
        self.draw_after_id: str | None = None
        self.open_prescription_command = open_prescription_command
        self.open_remarks_command = open_remarks_command
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=10, padx=(0, 8))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.bind("<Configure>", lambda event: self._schedule_draw())
        self.canvas.bind("<Button-2>", self._open_from_event)
        self.canvas.bind("<Button-3>", self._show_context_menu)

    def draw(self, prescriptions: list[dict]) -> None:
        self.prescriptions = prescriptions
        self._schedule_draw(20)

    def _schedule_draw(self, delay: int = 80) -> None:
        if self.draw_after_id is not None:
            try:
                self.after_cancel(self.draw_after_id)
            except tk.TclError:
                pass
        self.draw_after_id = self.after(delay, self._draw)

    def _draw(self) -> None:
        self.draw_after_id = None
        self.canvas.delete("all")
        self.row_items = []
        prescriptions = sorted(
            self.prescriptions,
            key=lambda item: (_parse_iso(item.get("nearest_due_date", "")) or _parse_iso(item.get("due_date", "")) or date.max),
        )
        width = max(self.canvas.winfo_width(), 640)
        height = max(self.canvas.winfo_height(), 220)
        if not prescriptions:
            self.canvas.create_rectangle(0, 0, width, height, fill=PANEL, outline=BORDER)
            self.canvas.create_text(20, 20, text="Нет данных", anchor="nw", fill=MUTED)
            return
        today = date.today()
        dates = []
        for item in prescriptions:
            dates.append(_parse_iso(item.get("issued_date", "")) or today)
            dates.append(_parse_iso(item.get("due_date", "")) or _parse_iso(item.get("nearest_due_date", "")) or today + timedelta(days=14))
        start = min(dates + [today]) - timedelta(days=3)
        end = max(dates + [today + timedelta(days=14)]) + timedelta(days=3)
        span = max((end - start).days, 1)
        label_width = 145
        chart_width = max(width - label_width - 24, 240)
        row_h = 24
        top = 30
        bottom = top + len(prescriptions) * row_h
        total_height = max(height, bottom + 12)
        self.canvas.create_rectangle(0, 0, width, total_height, fill=PANEL, outline=BORDER)

        week = start - timedelta(days=start.weekday())
        while week <= end:
            x = label_width + (week - start).days / span * chart_width
            if label_width <= x <= label_width + chart_width:
                self.canvas.create_line(x, top - 4, x, bottom, fill=GRID)
            week += timedelta(days=7)

        month = date(start.year, start.month, 1)
        last_label_x = -999
        while month <= end:
            x = label_width + (month - start).days / span * chart_width
            if label_width <= x <= label_width + chart_width:
                self.canvas.create_line(x, 20, x, bottom, fill=BORDER, width=1)
                if x - last_label_x > 72:
                    self.canvas.create_text(x + 4, 8, text=f"{month.month:02d}.{month.year}", anchor="nw", fill=MUTED, font=font_tuple(self, 11))
                    last_label_x = x
            month = date(month.year + (1 if month.month == 12 else 0), 1 if month.month == 12 else month.month + 1, 1)

        today_x = label_width + (today - start).days / span * chart_width
        self.canvas.create_line(today_x, top - 5, today_x, bottom, fill=DANGER, width=1)

        for index, item in enumerate(prescriptions):
            y = top + index * row_h
            issued = _parse_iso(item.get("issued_date", "")) or today
            due = _parse_iso(item.get("due_date", "")) or _parse_iso(item.get("nearest_due_date", "")) or issued + timedelta(days=14)
            x1 = label_width + (issued - start).days / span * chart_width
            x2 = label_width + (due - start).days / span * chart_width
            if x2 < x1:
                x1, x2 = x2, x1
            color = SUCCESS if item.get("is_done") else ACCENT
            if int(item.get("overdue_count") or 0):
                color = DANGER
            elif item.get("near_due"):
                color = WARNING
            label = _object_display_name(item)
            self.canvas.create_text(10, y + 7, text=_shorten(label, 21), anchor="w", fill=TEXT, font=font_tuple(self, 12))
            bar_left = x1
            bar_right = max(x2, x1 + 6)
            _draw_soft_bar(self.canvas, bar_left, y + 7, bar_right, y + 19, color)
            percent_text = str(item.get("percent", "0")) + "%"
            label_room = max(len(percent_text) * 6 + 10, 34)
            chart_right = label_width + chart_width
            if bar_right + label_room <= chart_right:
                percent_x = bar_right + 5
                percent_fill = MUTED
            elif bar_right - bar_left > label_room + 8:
                percent_x = bar_right - label_room
                percent_fill = PANEL
            else:
                percent_x = min(max(bar_right + 4, label_width + 4), width - label_room)
                percent_fill = MUTED
            self.canvas.create_text(percent_x, y + 5, text=percent_text, anchor="nw", fill=percent_fill, font=font_tuple(self, 10, "bold"))
            self.row_items.append((y, y + row_h, item))
        self.canvas.configure(scrollregion=(0, 0, width, bottom + 12))

    def _item_at(self, y: int) -> dict | None:
        canvas_y = int(self.canvas.canvasy(y))
        for top, bottom, item in self.row_items:
            if top <= canvas_y <= bottom:
                return item
        return None

    def _open_from_event(self, event) -> None:
        item = self._item_at(event.y)
        if item and self.open_prescription_command:
            self.open_prescription_command(item.get("id", ""))

    def _show_context_menu(self, event) -> None:
        item = self._item_at(event.y)
        if not item:
            return
        prescription_id = item.get("id", "")
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Перейти в предписание", command=lambda: self.open_prescription_command and self.open_prescription_command(prescription_id))
        menu.add_command(label="Перейти в замечания", command=lambda: self.open_remarks_command and self.open_remarks_command(prescription_id))
        menu.tk_popup(event.x_root, event.y_root)


class ObjectsPage(ttk.Frame):
    def __init__(self, master, app: MainWindow):
        super().__init__(master)
        self.app = app
        self.records: dict[str, dict] = {}
        self.selected_id = ""
        self.filter_var = tk.StringVar(value=FILTERS["all"])
        self.search_var = tk.StringVar()
        self.fields: dict[str, tk.Widget] = {}
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="Объекты", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        toolbar.columnconfigure(3, weight=1)
        ttk.Combobox(toolbar, textvariable=self.filter_var, values=list(FILTERS.values()), width=24, state="readonly").grid(row=0, column=0, sticky="w")
        ttk.Button(toolbar, text="Применить", command=self.refresh).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(toolbar, text="Новое", command=self.new_record).grid(row=0, column=2, padx=(8, 0))
        search = ttk.Entry(toolbar, textvariable=self.search_var)
        search.grid(row=0, column=3, sticky="ew", padx=(12, 0))
        bind_debounced_event(search, "<KeyRelease>", self.refresh)

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.grid(row=2, column=0, sticky="nsew")

        list_panel = Card(panes, radius=14, shadow=True)
        list_panel.rowconfigure(0, weight=1)
        list_panel.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            list_panel,
            columns=("address", "customer", "prescriptions", "active", "overdue", "source"),
            show="tree headings",
            selectmode="extended",
        )
        style_treeview(self.tree)
        self.tree.heading("#0", text="Объект")
        self.tree.column("#0", width=260, anchor="w", stretch=False)
        for key, title, width in (
            ("address", "Адрес", 180),
            ("customer", "Заказчик", 150),
            ("prescriptions", "Предписаний", 92),
            ("active", "На контроле", 96),
            ("overdue", "Просрочено", 92),
            ("source", "Источник", 104),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w", stretch=False)
        grid_treeview_with_scrollbars(list_panel, self.tree, padx=10, pady=10)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda event: self.open_prescriptions())
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind("<Control-c>", lambda event: self.copy_selected_rows())
        panes.add(list_panel, weight=4)

        form = Card(panes, radius=14, shadow=True)
        form.columnconfigure(1, weight=1)
        form.rowconfigure(3, weight=1)
        panes.add(form, weight=2)
        self._entry(form, "name", "Название", 0)
        self._entry(form, "address", "Адрес", 1)
        self._entry(form, "customer", "Заказчик", 2)
        self._text(form, "note", "Комментарий", 3, height=7)
        actions = ttk.Frame(form, style="Panel.TFrame")
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 12))
        for index in range(3):
            actions.columnconfigure(index, weight=1)
        ttk.Button(actions, text="Удалить", command=self.delete_selected).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Предписания", style="Ghost.TButton", command=self.open_prescriptions).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(actions, text="Сохранить", style="Primary.TButton", command=self.save).grid(row=0, column=2, sticky="ew", padx=(6, 0))

    def _entry(self, parent, key: str, label: str, row: int) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 11)).grid(row=row, column=0, sticky="w", padx=12, pady=(8, 0))
        entry = ttk.Entry(parent)
        entry.grid(row=row, column=1, sticky="ew", padx=12, pady=(8, 0))
        bind_standard_context_menu(entry)
        self.fields[key] = entry

    def _text(self, parent, key: str, label: str, row: int, height: int) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 11)).grid(row=row, column=0, sticky="nw", padx=12, pady=(8, 0))
        text = tk.Text(parent, height=height, wrap="word")
        style_text_widget(text)
        text.grid(row=row, column=1, sticky="nsew", padx=12, pady=(8, 0))
        bind_standard_context_menu(text)
        self.fields[key] = text

    def refresh(self, filter_name: str | None = None, selected_id: str | None = None, **kwargs) -> None:
        if filter_name:
            self.filter_var.set(FILTERS.get(filter_name, FILTERS["all"]))
        current_filter = _filter_key(self.filter_var.get())
        query = self.search_var.get().lower().strip()
        self.records = {}
        self.tree.delete(*self.tree.get_children())
        for item in self.app.runtime.list_objects(current_filter):
            haystack = " ".join(str(item.get(key, "")) for key in ("name", "address", "customer", "note")).lower()
            if query and query not in haystack:
                continue
            record_id = item.get("id", "")
            self.records[record_id] = item
            self.tree.insert(
                "",
                "end",
                iid=record_id,
                text=item.get("name", ""),
                values=(
                    item.get("address", ""),
                    item.get("customer", ""),
                    item.get("prescriptions_total", ""),
                    item.get("prescriptions_active", ""),
                    item.get("prescriptions_overdue", ""),
                    item.get("source_label", ""),
                ),
                tags=(_object_status_tag(item),),
            )
        stripe_treeview(self.tree)
        self._set_form_state()
        target_id = selected_id or self.selected_id
        if target_id in self.records:
            self.tree.selection_set(target_id)
            self.tree.focus(target_id)
            self.tree.see(target_id)
            self._on_select()

    def new_record(self) -> None:
        self.selected_id = ""
        for widget in self.fields.values():
            _set_widget_value(widget, "")

    def save(self) -> None:
        if self.app.runtime.read_only:
            messagebox.showinfo("CIR", "Текущий режим открыт только для чтения.")
            return
        payload = {"id": self.selected_id}
        for key, widget in self.fields.items():
            payload[key] = _get_widget_value(widget)
        if not payload["name"].strip():
            messagebox.showwarning("CIR", "Название объекта обязательно.")
            return
        try:
            self.selected_id = self.app.runtime.save_object(payload)
            self.refresh(selected_id=self.selected_id)
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def delete_selected(self) -> None:
        if self.app.runtime.read_only:
            messagebox.showinfo("CIR", "Текущий режим открыт только для чтения.")
            return
        ids = self._selected_object_ids()
        if not ids:
            messagebox.showinfo("CIR", "Выберите объект.")
            return
        if not messagebox.askyesno("CIR", f"Удалить выбранные объекты: {len(ids)}?"):
            return
        try:
            self.app.runtime.delete_objects(ids)
            self.selected_id = ""
            self.new_record()
            self.refresh()
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def open_prescriptions(self) -> None:
        ids = self._selected_object_ids()
        if not ids:
            messagebox.showinfo("CIR", "Выберите объект.")
            return
        self.app.show_page("prescriptions", object_id=ids[0])

    def copy_selected_rows(self) -> None:
        rows = []
        for item_id in self._selected_object_ids():
            item = self.records.get(item_id, {})
            rows.append(
                [
                    item.get("name", ""),
                    item.get("address", ""),
                    item.get("customer", ""),
                    item.get("prescriptions_total", ""),
                    item.get("prescriptions_active", ""),
                    item.get("prescriptions_overdue", ""),
                    item.get("source_label", ""),
                ]
            )
        copy_rows_to_clipboard(self, [["Объект", "Адрес", "Заказчик", "Предписаний", "На контроле", "Просрочено", "Источник"]] + rows)

    def _on_select(self, event=None) -> None:
        ids = self._selected_object_ids()
        if not ids:
            return
        self.selected_id = ids[0]
        item = self.records.get(self.selected_id, {})
        for key, widget in self.fields.items():
            _set_widget_value(widget, item.get(key, ""))

    def _show_context_menu(self, event) -> None:
        item_id = self.tree.identify_row(event.y)
        if item_id and item_id not in self.tree.selection():
            self.tree.selection_set(item_id)
            self._on_select()
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Открыть предписания", command=self.open_prescriptions)
        menu.add_command(label="Копировать строки", command=self.copy_selected_rows)
        menu.add_separator()
        menu.add_command(label="Новое", command=self.new_record)
        menu.add_command(label="Удалить", command=self.delete_selected)
        menu.tk_popup(event.x_root, event.y_root)

    def _selected_object_ids(self) -> list[str]:
        result = [item_id for item_id in self.tree.selection() if item_id in self.records]
        if not result and self.selected_id:
            result.append(self.selected_id)
        seen: set[str] = set()
        return [item for item in result if not (item in seen or seen.add(item))]

    def _set_form_state(self) -> None:
        state = "disabled" if self.app.runtime.read_only else "normal"
        for widget in self.fields.values():
            widget.configure(state=state)


class PrescriptionsPage(ttk.Frame):
    def __init__(self, master, app: MainWindow):
        super().__init__(master)
        self.app = app
        self.records: dict[str, dict] = {}
        self.selected_id = ""
        self.object_lookup: dict[str, str] = {}
        self.filter_var = tk.StringVar(value=FILTERS["all"])
        self.object_var = tk.StringVar(value=ALL_OBJECTS)
        self.project_var = tk.StringVar(value=ALL_PROJECTS)
        self.contractor_var = tk.StringVar(value=ALL_CONTRACTORS)
        self.search_var = tk.StringVar()
        self.image_scope = tk.StringVar(value="prescription")
        self.fields: dict[str, tk.Widget] = {}
        self.calendar_window: tk.Toplevel | None = None
        self.column_labels = {
            "project": "Проект",
            "contractor": "Подрядчик",
            "status": "Статус",
            "nearest": "Ближайший срок",
            "remarks": "Замечаний",
            "source": "Источник",
        }
        self.optional_columns = ("nearest", "remarks", "source")
        self.visible_optional_columns = set(self.optional_columns)
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="Предписания", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        toolbar.columnconfigure(7, weight=1)
        ttk.Combobox(toolbar, textvariable=self.filter_var, values=list(FILTERS.values()), width=24, state="readonly").grid(row=0, column=0, sticky="w")
        ttk.Button(toolbar, text="Применить", command=self.refresh).grid(row=0, column=1, padx=(8, 14))
        self.object_combo = ttk.Combobox(toolbar, textvariable=self.object_var, values=[ALL_OBJECTS], width=26, state="readonly")
        self.object_combo.grid(row=0, column=2, sticky="w")
        self.object_combo.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        self.project_combo = ttk.Combobox(toolbar, textvariable=self.project_var, values=[ALL_PROJECTS], width=22, state="readonly")
        self.project_combo.grid(row=0, column=3, sticky="w", padx=(8, 0))
        self.project_combo.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        self.contractor_combo = ttk.Combobox(toolbar, textvariable=self.contractor_var, values=[ALL_CONTRACTORS], width=22, state="readonly")
        self.contractor_combo.grid(row=0, column=4, sticky="w", padx=(8, 0))
        self.contractor_combo.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        columns_button = ttk.Button(toolbar, text="Колонки", style="Ghost.TButton")
        columns_button.grid(row=0, column=5, sticky="w", padx=(8, 0))
        columns_button.configure(command=lambda button=columns_button: self._show_column_menu_for_widget(button))
        search = ttk.Entry(toolbar, textvariable=self.search_var)
        search.grid(row=0, column=7, sticky="ew", padx=(12, 0))
        bind_debounced_event(search, "<KeyRelease>", self.refresh)

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.grid(row=2, column=0, sticky="nsew")

        list_panel = Card(panes, radius=18, shadow=True)
        list_panel.rowconfigure(0, weight=1)
        list_panel.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            list_panel,
            columns=("project", "contractor", "status", "nearest", "remarks", "source"),
            show="tree headings",
            selectmode="extended",
        )
        style_treeview(self.tree)
        columns = (
            ("project", "Проект", 120),
            ("contractor", "Подрядчик", 140),
            ("status", "Статус", 160),
            ("nearest", "Ближайший срок", 112),
            ("remarks", "Замечаний", 78),
            ("source", "Источник", 112),
        )
        self.tree.heading("#0", text="Объект / предписание")
        self.tree.column("#0", width=260, anchor="w", stretch=False)
        for key, title, width in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w", stretch=False)
        self._apply_column_visibility()
        grid_treeview_with_scrollbars(list_panel, self.tree, padx=10, pady=10)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-1>", self._maybe_show_column_menu)
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind("<Control-c>", lambda event: self.copy_selected_rows())
        panes.add(list_panel, weight=4)

        form = Card(panes, radius=14, shadow=True)
        form.columnconfigure(1, weight=1)
        panes.add(form, weight=2)
        form.rowconfigure(9, weight=1)
        self._entry(form, "number", "Номер", 0)
        self._combo(form, "object_id", "Объект", 1)
        self._entry(form, "project", "Проект", 2)
        self._entry(form, "contractor", "Подрядчик", 3)
        self._date_entry(form, "issued_date", "Дата", 4, self._open_issued_date_calendar)
        self._text(form, "subject", "Содержание", 5, height=5)
        actions = ttk.Frame(form, style="Panel.TFrame")
        actions.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 10))
        for index in range(3):
            actions.columnconfigure(index, weight=1)
        ttk.Button(actions, text="Новое", command=self.new_record).grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))
        ttk.Button(actions, text="Удалить", command=self.delete_selected).grid(row=0, column=1, sticky="ew", padx=6, pady=(0, 8))
        ttk.Button(actions, text="Сохранить", style="Primary.TButton", command=self.save).grid(row=0, column=2, sticky="ew", padx=(6, 0), pady=(0, 8))
        ttk.Button(actions, text="Замечания", style="Ghost.TButton", command=self.add_remark).grid(row=1, column=0, columnspan=3, sticky="ew")
        AttachmentArea(form, self.open_folder, self.add_files, self.paste_files_from_clipboard, self.copy_attachment_paths).grid(
            row=7, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10)
        )
        gallery_modes = ttk.Frame(form, style="Panel.TFrame")
        gallery_modes.grid(row=8, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 6))
        for column in range(4):
            gallery_modes.columnconfigure(column, weight=1)
        for column, (label, scope) in enumerate(
            (
                ("Предписание", "prescription"),
                ("Замечания", "remarks_all"),
                ("Открытые", "remarks_open"),
                ("Исполненные", "remarks_done"),
            )
        ):
            ttk.Radiobutton(
                gallery_modes,
                text=label,
                value=scope,
                variable=self.image_scope,
                command=self._refresh_gallery,
            ).grid(row=0, column=column, sticky="w", padx=(0 if column == 0 else 6, 0))
        self.gallery = ImageGallery(form, self.copy_attachment_paths)
        self.gallery.grid(row=9, column=0, columnspan=2, sticky="nsew", padx=12, pady=(0, 12))

    def _entry(self, parent, key: str, label: str, row: int) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 11)).grid(row=row, column=0, sticky="w", padx=12, pady=(8, 0))
        entry = ttk.Entry(parent)
        entry.grid(row=row, column=1, sticky="ew", padx=12, pady=(8, 0))
        bind_standard_context_menu(entry)
        self.fields[key] = entry

    def _date_entry(self, parent, key: str, label: str, row: int, calendar_command) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 11)).grid(row=row, column=0, sticky="w", padx=12, pady=(8, 0))
        holder = tk.Frame(parent, bg=PANEL)
        holder.grid(row=row, column=1, sticky="ew", padx=12, pady=(8, 0))
        holder.columnconfigure(0, weight=1)
        entry = ttk.Entry(holder)
        entry.grid(row=0, column=0, sticky="ew")
        bind_standard_context_menu(entry)
        bind_date_mask(entry)
        ttk.Button(holder, text="...", style="Ghost.TButton", width=3, command=calendar_command).grid(row=0, column=1, sticky="e", padx=(6, 0))
        self.fields[key] = entry

    def _text(self, parent, key: str, label: str, row: int, height: int = 5) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 11)).grid(row=row, column=0, sticky="nw", padx=12, pady=(8, 0))
        text = tk.Text(parent, height=height, wrap="word")
        style_text_widget(text)
        text.grid(row=row, column=1, sticky="ew", padx=12, pady=(8, 0))
        bind_standard_context_menu(text)
        self.fields[key] = text

    def _combo(self, parent, key: str, label: str, row: int, values: list[str] | None = None) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 11)).grid(row=row, column=0, sticky="w", padx=12, pady=(8, 0))
        combo = ttk.Combobox(parent, values=values or [], state="readonly")
        combo.grid(row=row, column=1, sticky="ew", padx=12, pady=(8, 0))
        self.fields[key] = combo

    def _apply_column_visibility(self) -> None:
        if not hasattr(self, "tree"):
            return
        display_columns = ["project", "contractor", "status"]
        display_columns.extend(key for key in self.optional_columns if key in self.visible_optional_columns)
        self.tree.configure(displaycolumns=display_columns)

    def _show_column_menu_for_widget(self, widget: tk.Widget) -> None:
        self._show_column_menu(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())

    def _open_issued_date_calendar(self) -> None:
        entry = self.fields.get("issued_date")
        if entry is None:
            return
        open_date_picker(
            self,
            _get_widget_value(entry),
            entry.winfo_rootx(),
            entry.winfo_rooty() + entry.winfo_height(),
            "Дата предписания",
            lambda selected: _set_widget_value(entry, _format_date_for_display(selected.isoformat()) if selected else ""),
        )

    def _show_column_menu(self, x_root: int, y_root: int) -> None:
        menu = tk.Menu(self, tearoff=False)
        for key in self.optional_columns:
            is_visible = key in self.visible_optional_columns
            action = "Убрать" if is_visible else "Добавить"
            menu.add_command(label=f"{action}: {self.column_labels[key]}", command=lambda column=key: self._toggle_column(column))
        menu.add_separator()
        menu.add_command(label="Показать все", command=self._show_all_columns)
        menu.tk_popup(x_root, y_root)

    def _toggle_column(self, key: str) -> None:
        if key in self.visible_optional_columns:
            self.visible_optional_columns.remove(key)
        else:
            self.visible_optional_columns.add(key)
        self._apply_column_visibility()

    def _show_all_columns(self) -> None:
        self.visible_optional_columns = set(self.optional_columns)
        self._apply_column_visibility()

    def _maybe_show_column_menu(self, event) -> str | None:
        if self.tree.identify_region(event.x, event.y) == "heading":
            self._show_column_menu(event.x_root, event.y_root)
            return "break"
        return None

    def refresh(self, filter_name: str | None = None, **kwargs) -> None:
        select_after = kwargs.get("selected_id") or kwargs.get("prescription_id")
        target_object_id = kwargs.get("object_id")
        if filter_name:
            self.filter_var.set(FILTERS.get(filter_name, FILTERS["all"]))
        if select_after:
            self.filter_var.set(FILTERS["all"])
            self.object_var.set(ALL_OBJECTS)
            self.project_var.set(ALL_PROJECTS)
            self.contractor_var.set(ALL_CONTRACTORS)
            self.search_var.set("")
        current_filter = _filter_key(self.filter_var.get())
        records = self.app.runtime.list_prescriptions(current_filter)
        object_options = self.app.runtime.object_options()
        self.object_lookup = {label: record_id for record_id, label in object_options}
        object_labels = [ALL_OBJECTS] + [label for _, label in object_options]
        if any(not item.get("object_id") for item in records):
            object_labels.append(UNASSIGNED_OBJECT)
        self.object_combo.configure(values=object_labels)
        object_field = self.fields.get("object_id")
        if isinstance(object_field, ttk.Combobox):
            object_field.configure(values=[label for _, label in object_options])
        if target_object_id:
            self.object_var.set(self._object_label(target_object_id))
        projects = [ALL_PROJECTS] + sorted({item.get("project") or "Без проекта" for item in records})
        contractors = [ALL_CONTRACTORS] + sorted({item.get("contractor") or "Без подрядчика" for item in records})
        self.project_combo.configure(values=projects)
        self.contractor_combo.configure(values=contractors)
        if self.object_var.get() not in object_labels:
            self.object_var.set(ALL_OBJECTS)
        if self.project_var.get() not in projects:
            self.project_var.set(ALL_PROJECTS)
        if self.contractor_var.get() not in contractors:
            self.contractor_var.set(ALL_CONTRACTORS)
        selected_object_label = self.object_var.get()
        selected_object_id = self._object_id_from_label(selected_object_label)
        selected_project = self.project_var.get()
        selected_contractor = self.contractor_var.get()
        query = self.search_var.get().lower().strip()
        self.records = {}
        self.tree.delete(*self.tree.get_children())
        grouped: dict[tuple[str, str], list[dict]] = {}
        for item in records:
            object_id = item.get("object_id", "")
            object_name = _object_display_name(item)
            project = item.get("project") or "Без проекта"
            contractor = item.get("contractor") or "Без подрядчика"
            if selected_object_id is not None:
                if selected_object_id:
                    if object_id != selected_object_id and object_name != selected_object_label:
                        continue
                elif object_id:
                    continue
            if selected_project != ALL_PROJECTS and project != selected_project:
                continue
            if selected_contractor != ALL_CONTRACTORS and contractor != selected_contractor:
                continue
            haystack = " ".join(str(item.get(key, "")) for key in ("number", "object_name", "project", "contractor", "subject")).lower()
            if query and query not in haystack:
                continue
            record_id = item.get("id", "")
            self.records[record_id] = item
            grouped.setdefault((object_id, object_name), []).append(item)
        for (object_id, object_name), items in sorted(grouped.items(), key=lambda pair: pair[0][1]):
            object_node = f"object::{object_id or object_name}"
            active_count = sum(1 for item in items if not item.get("is_done"))
            overdue_count = sum(1 for item in items if item.get("overdue_count"))
            self.tree.insert(
                "",
                "end",
                iid=object_node,
                text=f"{object_name} ({len(items)})",
                values=("", "", f"На контроле: {active_count}", "", f"Просрочено: {overdue_count}", ""),
                open=True,
                tags=("group",),
            )
            for item in items:
                record_id = item.get("id", "")
                self.tree.insert(
                    object_node,
                    "end",
                    iid=record_id,
                    text=item.get("number", ""),
                    values=(
                        item.get("project", ""),
                        item.get("contractor", ""),
                        item.get("status", ""),
                        _format_date_for_display(item.get("nearest_due_date", "")),
                        item.get("remarks_total", ""),
                        item.get("source_label", ""),
                    ),
                    tags=(_prescription_status_tag(item),),
                )
        stripe_treeview(self.tree)
        self._set_form_state()
        if select_after and select_after in self.records:
            self.tree.selection_set(select_after)
            self.tree.focus(select_after)
            self.tree.see(select_after)
            self._on_select()
        self._refresh_gallery()

    def new_record(self) -> None:
        self.selected_id = ""
        for key, widget in self.fields.items():
            _set_widget_value(widget, "")
        object_id = self._object_id_from_label(self.object_var.get())
        if object_id:
            _set_widget_value(self.fields["object_id"], self._object_label(object_id))
        self._refresh_gallery()

    def save(self) -> None:
        if self.app.runtime.read_only:
            messagebox.showinfo("CIR", "Текущий режим открыт только для чтения.")
            return
        payload = {"id": self.selected_id}
        for key, widget in self.fields.items():
            payload[key] = _get_widget_value(widget)
        payload["object_id"] = self._object_id_from_label(payload.get("object_id", "")) or ""
        payload["issued_date"] = _normalize_date(payload.get("issued_date", ""))
        if not payload["object_id"]:
            messagebox.showwarning("CIR", "Выберите объект.")
            return
        if not payload["number"].strip():
            messagebox.showwarning("CIR", "Номер предписания обязателен.")
            return
        self.selected_id = self.app.runtime.save_prescription(payload)
        self.refresh()
        self.tree.selection_set(self.selected_id)

    def add_remark(self) -> None:
        ids = self._selected_prescription_ids()
        if not ids:
            messagebox.showinfo("CIR", "Выберите предписание.")
            return
        self.app.show_page("remarks", prescription_ids=ids)

    def delete_selected(self) -> None:
        if self.app.runtime.read_only:
            messagebox.showinfo("CIR", "Текущий режим открыт только для чтения.")
            return
        ids = self._selected_prescription_ids()
        if not ids:
            messagebox.showinfo("CIR", "Выберите предписание.")
            return
        if not messagebox.askyesno("CIR", f"Удалить выбранные предписания: {len(ids)}?"):
            return
        try:
            self.app.runtime.delete_prescriptions(ids)
            self.selected_id = ""
            self.new_record()
            self.refresh()
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def open_folder(self) -> None:
        selected_id = self._single_selected_prescription_id()
        if not selected_id:
            messagebox.showinfo("CIR", "Выберите предписание.")
            return
        try:
            path = self.app.runtime.open_attachments(selected_id)
            messagebox.showinfo("CIR", f"Папка вложений:\n{path}")
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def add_files(self) -> None:
        selected_id = self._single_selected_prescription_id()
        if not selected_id:
            messagebox.showinfo("CIR", "Выберите предписание.")
            return
        files = filedialog.askopenfilenames(title="Добавить вложения")
        if not files:
            return
        self.copy_attachment_paths(list(files), selected_id)

    def copy_attachment_paths(self, paths: list[str], selected_id: str | None = None) -> None:
        paths = _existing_file_paths(paths)
        if not paths:
            messagebox.showinfo("CIR", "В перетаскивании не найдены файлы.")
            return
        selected_id = selected_id or self._single_selected_prescription_id()
        if not selected_id:
            messagebox.showinfo("CIR", "Выберите предписание.")
            return
        try:
            count = self.app.runtime.copy_attachments(selected_id, paths)
            self._refresh_gallery(selected_id)
            messagebox.showinfo("CIR", f"Добавлено файлов: {count}")
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def paste_files_from_clipboard(self) -> None:
        selected_id = self._single_selected_prescription_id()
        if not selected_id:
            messagebox.showinfo("CIR", "Выберите предписание.")
            return
        paths = clipboard_file_paths(self.root_clipboard_get)
        if not paths:
            messagebox.showinfo("CIR", "В буфере не найдены файлы.")
            return
        self.copy_attachment_paths(paths, selected_id)

    def root_clipboard_get(self) -> str:
        try:
            return self.winfo_toplevel().clipboard_get()
        except tk.TclError:
            return ""

    def _on_select(self, event=None) -> None:
        ids = self._selected_prescription_ids()
        if not ids:
            return
        self.selected_id = ids[0]
        item = self.records.get(self.selected_id, {})
        for key, widget in self.fields.items():
            value = item.get(key, "")
            if key == "object_id":
                value = self._object_label(value)
            if key == "issued_date":
                value = _format_date_for_display(value)
            _set_widget_value(widget, value)
        self._refresh_gallery(self.selected_id)

    def _on_double_click(self, event=None) -> None:
        clicked = self.tree.identify_row(event.y) if event else ""
        if clicked and clicked in self.records:
            ids = [clicked]
        elif clicked and clicked.startswith("object::"):
            ids = [child for child in self.tree.get_children(clicked) if child in self.records]
        else:
            ids = self._selected_prescription_ids()
        if ids:
            self.app.show_page("remarks", prescription_ids=ids)

    def _show_context_menu(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) == "heading":
            self._show_column_menu(event.x_root, event.y_root)
            return
        item_id = self.tree.identify_row(event.y)
        if item_id and item_id not in self.tree.selection():
            self.tree.selection_set(item_id)
            self._on_select()
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Открыть замечания", command=self.add_remark)
        menu.add_command(label="Копировать строки", command=self.copy_selected_rows)
        menu.add_separator()
        menu.add_command(label="Открыть папку", command=self.open_folder)
        menu.add_command(label="Добавить файлы", command=self.add_files)
        menu.add_command(label="Вставить файлы из буфера", command=self.paste_files_from_clipboard)
        menu.add_separator()
        menu.add_command(label="Новое", command=self.new_record)
        menu.add_command(label="Удалить", command=self.delete_selected)
        menu.tk_popup(event.x_root, event.y_root)

    def copy_selected_rows(self) -> None:
        rows = []
        for item_id in self._selected_prescription_ids():
            item = self.records.get(item_id, {})
            rows.append(
                [
                    item.get("number", ""),
                    _object_display_name(item),
                    item.get("project", ""),
                    item.get("contractor", ""),
                    item.get("status", ""),
                    _format_date_for_display(item.get("nearest_due_date", "")),
                    item.get("remarks_total", ""),
                    item.get("source_label", ""),
                ]
            )
        copy_rows_to_clipboard(self, [["Номер", "Объект", "Проект", "Подрядчик", "Статус", "Ближайший срок", "Замечаний", "Источник"]] + rows)

    def _selected_prescription_ids(self) -> list[str]:
        result: list[str] = []
        for item_id in self.tree.selection():
            if item_id in self.records:
                result.append(item_id)
            elif item_id.startswith("object::"):
                result.extend(child for child in self.tree.get_children(item_id) if child in self.records)
        if not result and self.selected_id:
            result.append(self.selected_id)
        seen: set[str] = set()
        return [item for item in result if not (item in seen or seen.add(item))]

    def _single_selected_prescription_id(self) -> str:
        ids = self._selected_prescription_ids()
        return ids[0] if ids else ""

    def _object_label(self, object_id: str) -> str:
        for label, record_id in self.object_lookup.items():
            if record_id == object_id:
                return label
        return ""

    def _object_id_from_label(self, label: str) -> str | None:
        if label == ALL_OBJECTS:
            return None
        if label == UNASSIGNED_OBJECT:
            return ""
        return self.object_lookup.get(label, label if label in self.object_lookup.values() else "")

    def _refresh_gallery(self, selected_id: str | None = None) -> None:
        selected_id = selected_id if selected_id is not None else self._single_selected_prescription_id()
        if not selected_id:
            self.gallery.set_paths([])
            return
        scope = self.image_scope.get()
        if scope == "prescription":
            self.gallery.set_paths(self.app.runtime.prescription_image_paths(selected_id))
            return
        items: list[tuple[Path, str]] = []
        for remark in self.app.runtime.list_remarks(selected_id):
            is_done = remark.get("status") in REMARK_COMPLETED
            if scope == "remarks_open" and is_done:
                continue
            if scope == "remarks_done" and not is_done:
                continue
            prefix = remark.get("internal_code") or remark.get("description") or "Замечание"
            status = remark.get("status_label", "")
            for path in self.app.runtime.remark_image_paths(remark.get("id", "")):
                items.append((path, f"{prefix} · {status} · {path.name}".strip(" ·")))
        self.gallery.set_items(items)

    def _set_form_state(self) -> None:
        state = "disabled" if self.app.runtime.read_only else "normal"
        for widget in self.fields.values():
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="disabled" if self.app.runtime.read_only else "readonly")
            elif isinstance(widget, tk.Text):
                widget.configure(state=state)
            else:
                widget.configure(state=state)


class RemarksPage(ttk.Frame):
    def __init__(self, master, app: MainWindow):
        super().__init__(master)
        self.app = app
        self.records: dict[str, dict] = {}
        self.selected_id = ""
        self.prescription_lookup: dict[str, str] = {}
        self.current_prescription_ids: list[str] = []
        self.filter_var = tk.StringVar(value=FILTERS["all"])
        self.object_var = tk.StringVar(value=ALL_OBJECTS)
        self.project_var = tk.StringVar(value=ALL_PROJECTS)
        self.contractor_var = tk.StringVar(value=ALL_CONTRACTORS)
        self.fields: dict[str, tk.Widget] = {}
        self.prescription_nodes: dict[str, str] = {}
        self.object_nodes: dict[str, str] = {}
        self.remark_order: list[str] = []
        self.cell_editor: tk.Widget | None = None
        self.cell_editor_after_id: str | None = None
        self.calendar_window: tk.Toplevel | None = None
        self.column_labels = {
            "contractor": "Подрядчик",
            "due": "Срок",
            "status": "Статус",
            "location": "Место",
            "description": "Описание",
            "note": "Комментарий",
            "source": "Источник",
        }
        self.optional_columns = ("contractor", "location", "description", "note", "source")
        self.visible_optional_columns = set(self.optional_columns)
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="Замечания", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.context_label = ttk.Label(self, text="", style="Subtitle.TLabel")
        self.context_label.grid(row=0, column=0, sticky="e")
        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        toolbar.columnconfigure(9, weight=1)
        ttk.Combobox(toolbar, textvariable=self.filter_var, values=list(FILTERS.values()), width=18, state="readonly").grid(row=0, column=0, sticky="w")
        ttk.Button(toolbar, text="Применить", command=self.refresh).grid(row=0, column=1, padx=(8, 0))
        self.object_combo = ttk.Combobox(toolbar, textvariable=self.object_var, values=[ALL_OBJECTS], width=22, state="readonly")
        self.object_combo.grid(row=0, column=2, sticky="w", padx=(8, 0))
        self.object_combo.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        self.project_combo = ttk.Combobox(toolbar, textvariable=self.project_var, values=[ALL_PROJECTS], width=20, state="readonly")
        self.project_combo.grid(row=0, column=3, sticky="w", padx=(8, 0))
        self.project_combo.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        self.contractor_combo = ttk.Combobox(toolbar, textvariable=self.contractor_var, values=[ALL_CONTRACTORS], width=20, state="readonly")
        self.contractor_combo.grid(row=0, column=4, sticky="w", padx=(8, 0))
        self.contractor_combo.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        columns_button = ttk.Button(toolbar, text="Колонки", style="Ghost.TButton")
        columns_button.grid(row=0, column=5, sticky="w", padx=(8, 0))
        columns_button.configure(command=lambda button=columns_button: self._show_column_menu_for_widget(button))
        ttk.Button(toolbar, text="Сбросить", style="Ghost.TButton", command=self.clear_context).grid(row=0, column=6, padx=(8, 0))
        ttk.Button(toolbar, text="Новое", command=self.new_record).grid(row=0, column=7, padx=(8, 0))
        ttk.Button(toolbar, text="Из Excel", style="Ghost.TButton", command=self.paste_from_excel).grid(row=0, column=8, padx=(8, 0))

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.grid(row=2, column=0, sticky="nsew")
        list_panel = Card(panes, radius=14, shadow=True)
        list_panel.rowconfigure(0, weight=1)
        list_panel.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            list_panel,
            columns=("contractor", "due", "status", "location", "description", "note", "source"),
            show="tree headings",
            selectmode="extended",
        )
        style_treeview(self.tree)
        self.tree.heading("#0", text="Объект / предписание / замечание")
        self.tree.column("#0", width=250, anchor="w", stretch=False)
        for key, title, width in (
            ("contractor", "Подрядчик", 120),
            ("due", "Срок", 86),
            ("status", "Статус", 100),
            ("location", "Место", 140),
            ("description", "Описание", 280),
            ("note", "Комментарий", 160),
            ("source", "Источник", 104),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w", stretch=False)
        self._apply_column_visibility()
        grid_treeview_with_scrollbars(list_panel, self.tree, padx=10, pady=10)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._edit_cell_from_event)
        self.tree.bind("<Button-1>", self._maybe_show_column_menu)
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind("<KeyPress>", self._dismiss_cell_editor_from_key, add="+")
        self.tree.bind("<Insert>", lambda event: self.new_record())
        self.tree.bind("<Control-c>", lambda event: self.copy_selected_rows())
        self.tree.bind("<Control-v>", lambda event: self.paste_from_excel())
        panes.add(list_panel, weight=4)

        form = Card(panes, radius=14, shadow=True)
        form.columnconfigure(1, weight=1)
        form.rowconfigure(9, weight=1)
        panes.add(form, weight=2)
        self._combo(form, "prescription_id", "Предписание", 0)
        self._entry(form, "internal_code", "Номер замечания", 1)
        self._text(form, "description", "Описание", 2, height=5)
        self._entry(form, "location", "Место", 3)
        self._date_entry(form, "due_date", "Срок", 4, self._open_due_date_field_calendar)
        self._combo(form, "status", "Статус", 5, values=list(REMARK_STATUS_LABELS.values()))
        self._text(form, "note", "Комментарий", 6, height=4)
        actions = ttk.Frame(form, style="Panel.TFrame")
        actions.grid(row=7, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 10))
        for index in range(3):
            actions.columnconfigure(index, weight=1)
        ttk.Button(actions, text="Новое", command=self.new_record).grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))
        ttk.Button(actions, text="Удалить", command=self.delete_selected).grid(row=0, column=1, sticky="ew", padx=6, pady=(0, 8))
        ttk.Button(actions, text="Сохранить", style="Primary.TButton", command=self.save).grid(row=0, column=2, sticky="ew", padx=(6, 0), pady=(0, 8))
        ttk.Button(actions, text="Папка вложений", style="Ghost.TButton", command=self.open_folder).grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Вставить из Excel", style="Ghost.TButton", command=self.paste_from_excel).grid(row=1, column=2, sticky="ew", padx=(6, 0))
        AttachmentArea(form, self.open_folder, self.add_files, self.paste_files_from_clipboard, self.copy_attachment_paths, show_add_button=False).grid(
            row=8, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10)
        )
        self.gallery = ImageGallery(form, self.copy_attachment_paths)
        self.gallery.grid(row=9, column=0, columnspan=2, sticky="nsew", padx=12, pady=(0, 12))

    def _entry(self, parent, key: str, label: str, row: int) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 11)).grid(row=row, column=0, sticky="w", padx=12, pady=(8, 0))
        entry = ttk.Entry(parent)
        entry.grid(row=row, column=1, sticky="ew", padx=12, pady=(8, 0))
        bind_standard_context_menu(entry)
        self.fields[key] = entry

    def _date_entry(self, parent, key: str, label: str, row: int, calendar_command) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 11)).grid(row=row, column=0, sticky="w", padx=12, pady=(8, 0))
        holder = tk.Frame(parent, bg=PANEL)
        holder.grid(row=row, column=1, sticky="ew", padx=12, pady=(8, 0))
        holder.columnconfigure(0, weight=1)
        entry = ttk.Entry(holder)
        entry.grid(row=0, column=0, sticky="ew")
        bind_standard_context_menu(entry)
        bind_date_mask(entry)
        ttk.Button(holder, text="...", style="Ghost.TButton", width=3, command=calendar_command).grid(row=0, column=1, sticky="e", padx=(6, 0))
        self.fields[key] = entry

    def _text(self, parent, key: str, label: str, row: int, height: int) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 11)).grid(row=row, column=0, sticky="nw", padx=12, pady=(8, 0))
        text = tk.Text(parent, height=height, wrap="word")
        style_text_widget(text)
        text.grid(row=row, column=1, sticky="ew", padx=12, pady=(8, 0))
        bind_standard_context_menu(text)
        self.fields[key] = text

    def _combo(self, parent, key: str, label: str, row: int, values: list[str] | None = None) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 11)).grid(row=row, column=0, sticky="w", padx=12, pady=(8, 0))
        combo = ttk.Combobox(parent, values=values or [], state="readonly")
        combo.grid(row=row, column=1, sticky="ew", padx=12, pady=(8, 0))
        self.fields[key] = combo

    def _apply_column_visibility(self) -> None:
        if not hasattr(self, "tree"):
            return
        display_columns = []
        for key in ("contractor", "due", "status", "location", "description", "note", "source"):
            if key in ("due", "status") or key in self.visible_optional_columns:
                display_columns.append(key)
        self.tree.configure(displaycolumns=display_columns)

    def _show_column_menu_for_widget(self, widget: tk.Widget) -> None:
        self._show_column_menu(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())

    def _open_due_date_field_calendar(self) -> None:
        entry = self.fields.get("due_date")
        if entry is None:
            return
        open_date_picker(
            self,
            _get_widget_value(entry),
            entry.winfo_rootx(),
            entry.winfo_rooty() + entry.winfo_height(),
            "Срок замечания",
            lambda selected: _set_widget_value(entry, _format_date_for_display(selected.isoformat()) if selected else ""),
        )

    def _show_column_menu(self, x_root: int, y_root: int) -> None:
        menu = tk.Menu(self, tearoff=False)
        for key in self.optional_columns:
            is_visible = key in self.visible_optional_columns
            action = "Убрать" if is_visible else "Добавить"
            menu.add_command(label=f"{action}: {self.column_labels[key]}", command=lambda column=key: self._toggle_column(column))
        menu.add_separator()
        menu.add_command(label="Показать все", command=self._show_all_columns)
        menu.tk_popup(x_root, y_root)

    def _toggle_column(self, key: str) -> None:
        if key in self.visible_optional_columns:
            self.visible_optional_columns.remove(key)
        else:
            self.visible_optional_columns.add(key)
        self._apply_column_visibility()

    def _show_all_columns(self) -> None:
        self.visible_optional_columns = set(self.optional_columns)
        self._apply_column_visibility()

    def _maybe_show_column_menu(self, event) -> str | None:
        if self.tree.identify_region(event.x, event.y) == "heading":
            self._show_column_menu(event.x_root, event.y_root)
            return "break"
        self._destroy_cell_editor()
        return None

    def refresh(
        self,
        prescription_id: str | None = None,
        prescription_ids: list[str] | tuple[str, ...] | set[str] | None = None,
        filter_name: str | None = None,
        object_id: str | None = None,
        project: str | None = None,
        contractor: str | None = None,
        selected_id: str | None = None,
        clear_context: bool = False,
        **kwargs,
    ) -> None:
        self._destroy_cell_editor()
        if clear_context:
            self.current_prescription_ids = []
        if prescription_id:
            self.current_prescription_ids = [prescription_id]
        if prescription_ids is not None:
            self.current_prescription_ids = [item for item in prescription_ids if item]
        if filter_name:
            self.filter_var.set(FILTERS.get(filter_name, FILTERS["all"]))
        if object_id is not None:
            self.object_var.set(self._object_filter_label(object_id))
        if project:
            self.project_var.set(project)
        if contractor:
            self.contractor_var.set(contractor)
        options = self.app.runtime.prescription_options()
        self.prescription_lookup = {label: record_id for record_id, label in options}
        prescription_combo = self.fields["prescription_id"]
        assert isinstance(prescription_combo, ttk.Combobox)
        prescription_combo.configure(values=list(self.prescription_lookup.keys()))
        if len(self.current_prescription_ids) == 1:
            self._set_prescription_combo(self.current_prescription_ids[0])
        elif len(self.current_prescription_ids) > 1:
            prescription_combo.set("")
        current_filter = _filter_key(self.filter_var.get())
        records = self.app.runtime.list_remarks(self.current_prescription_ids, current_filter)
        objects = [ALL_OBJECTS] + sorted({_object_display_name(item) for item in records})
        self.object_combo.configure(values=objects)
        if self.object_var.get() not in objects:
            self.object_var.set(ALL_OBJECTS)
        selected_object = self.object_var.get()
        object_records = [item for item in records if selected_object == ALL_OBJECTS or _object_display_name(item) == selected_object]
        projects = [ALL_PROJECTS] + sorted({item.get("project") or "Без проекта" for item in object_records})
        self.project_combo.configure(values=projects)
        if self.project_var.get() not in projects:
            self.project_var.set(ALL_PROJECTS)
        selected_project = self.project_var.get()
        project_records = [
            item for item in object_records if selected_project == ALL_PROJECTS or (item.get("project") or "Без проекта") == selected_project
        ]
        contractors = [ALL_CONTRACTORS] + sorted({item.get("contractor") or "Без подрядчика" for item in project_records})
        self.contractor_combo.configure(values=contractors)
        if self.contractor_var.get() not in contractors:
            self.contractor_var.set(ALL_CONTRACTORS)
        selected_contractor = self.contractor_var.get()
        self.records = {}
        self.prescription_nodes = {}
        self.object_nodes = {}
        self.remark_order = []
        self.tree.delete(*self.tree.get_children())
        grouped: dict[tuple[str, str], dict[str, list[dict]]] = {}
        prescription_labels = {record_id: label for label, record_id in self.prescription_lookup.items()}
        for item in project_records:
            contractor = item.get("contractor") or "Без подрядчика"
            if selected_contractor != ALL_CONTRACTORS and contractor != selected_contractor:
                continue
            object_id_value = item.get("object_id", "")
            object_name = _object_display_name(item)
            prescription_id = item.get("prescription_id", "")
            grouped.setdefault((object_id_value, object_name), {}).setdefault(prescription_id, []).append(item)
            record_id = item.get("id", "")
            self.records[record_id] = item
        for (object_id_value, object_name), prescriptions in sorted(grouped.items(), key=lambda pair: pair[0][1]):
            object_node = f"object::{object_id_value or object_name}"
            total = sum(len(items) for items in prescriptions.values())
            self.object_nodes[object_node] = object_name
            self.tree.insert("", "end", iid=object_node, text=f"{object_name} ({total})", values=("", "", "", "", "", "", ""), open=True, tags=("group",))
            for prescription_id, items in sorted(
                prescriptions.items(),
                key=lambda pair: prescription_labels.get(pair[0], pair[0]),
            ):
                label = prescription_labels.get(prescription_id, items[0].get("prescription_number", "Предписание"))
                contractor_name = items[0].get("contractor", "")
                prescription_node = f"prescription::{prescription_id}"
                self.prescription_nodes[prescription_node] = prescription_id
                self.tree.insert(
                    object_node,
                    "end",
                    iid=prescription_node,
                    text=f"{label} ({len(items)})",
                    values=(contractor_name, "", "", "", "", "", ""),
                    open=True,
                    tags=("group",),
                )
                for item in items:
                    record_id = item.get("id", "")
                    self.remark_order.append(record_id)
                    self.tree.insert(
                        prescription_node,
                        "end",
                        iid=record_id,
                        text=item.get("internal_code", ""),
                        values=(
                            item.get("contractor", ""),
                            _format_date_for_display(item.get("due_date", "")),
                            item.get("status_label", ""),
                            item.get("location", ""),
                            item.get("description", ""),
                            item.get("note", ""),
                            item.get("source_label", ""),
                        ),
                        tags=(_remark_status_tag(item),),
                    )
        stripe_treeview(self.tree)
        self._update_context_label()
        self._set_form_state()
        target_id = selected_id or self.selected_id
        if target_id in self.records:
            self.tree.selection_set(target_id)
            self.tree.focus(target_id)
            self.tree.see(target_id)
            self._on_select()
        else:
            self._refresh_gallery()

    def clear_context(self) -> None:
        self.current_prescription_ids = []
        self.filter_var.set(FILTERS["all"])
        self.object_var.set(ALL_OBJECTS)
        self.project_var.set(ALL_PROJECTS)
        self.contractor_var.set(ALL_CONTRACTORS)
        self.refresh(clear_context=True)

    def new_record(self) -> None:
        if self.app.runtime.read_only:
            messagebox.showinfo("CIR", "Текущий режим открыт только для чтения.")
            return
        prescription_id = self._target_prescription_id_for_insert()
        if not prescription_id:
            messagebox.showwarning("CIR", "Выберите предписание или замечание в нужном объекте.")
            return
        payload = {
            "prescription_id": prescription_id,
            "internal_code": self._next_internal_code(prescription_id),
            "description": "",
            "location": "",
            "due_date": "",
            "status": REMARK_IN_PROGRESS,
            "note": "",
        }
        try:
            self.selected_id = self.app.runtime.save_remark(payload)
            self.refresh(prescription_ids=self.current_prescription_ids or None, selected_id=self.selected_id)
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def save(self) -> None:
        if self.app.runtime.read_only:
            messagebox.showinfo("CIR", "Текущий режим открыт только для чтения.")
            return
        display = _get_widget_value(self.fields["prescription_id"])
        prescription_id = self.prescription_lookup.get(display, display)
        if not prescription_id:
            messagebox.showwarning("CIR", "Выберите предписание.")
            return
        reverse_status = {label: key for key, label in REMARK_STATUS_LABELS.items()}
        payload = {
            "id": self.selected_id,
            "prescription_id": prescription_id,
            "internal_code": _get_widget_value(self.fields["internal_code"]),
            "description": _get_widget_value(self.fields["description"]),
            "location": _get_widget_value(self.fields["location"]),
            "due_date": _normalize_date(_get_widget_value(self.fields["due_date"])),
            "status": reverse_status.get(_get_widget_value(self.fields["status"]), "not_started"),
            "note": _get_widget_value(self.fields["note"]),
        }
        self.selected_id = self.app.runtime.save_remark(payload)
        self.refresh()
        self.tree.selection_set(self.selected_id)

    def paste_from_excel(self) -> None:
        if self.app.runtime.read_only:
            messagebox.showinfo("CIR", "Текущий режим открыт только для чтения.")
            return
        try:
            text = self.winfo_toplevel().clipboard_get()
        except tk.TclError:
            text = ""
        rows = parse_excel_remarks(text)
        if not rows:
            messagebox.showinfo("CIR", "В буфере нет строк замечаний.")
            return
        targets = self._selected_remark_ids()
        updated = 0
        inserted = 0
        try:
            for target_id, row in zip(targets, rows):
                existing = dict(self.records.get(target_id, {}))
                if not existing:
                    continue
                payload = {
                    "id": target_id,
                    "prescription_id": existing.get("prescription_id", ""),
                    "internal_code": existing.get("internal_code", "") or row.get("internal_code", ""),
                    "description": row.get("description", ""),
                    "location": row.get("location", ""),
                    "due_date": row.get("due_date", ""),
                    "status": row.get("status") or existing.get("status", REMARK_IN_PROGRESS),
                    "note": row.get("note", ""),
                }
                self.app.runtime.save_remark(payload)
                updated += 1
            extra_rows = rows[updated:]
            if extra_rows:
                prescription_id = self._target_prescription_id_for_insert()
                if not prescription_id:
                    messagebox.showwarning("CIR", "Выберите предписание или замечание для вставки.")
                    return
                for row in extra_rows:
                    row["prescription_id"] = prescription_id
                    self.app.runtime.save_remark(row)
                    inserted += 1
            self.refresh(prescription_ids=self.current_prescription_ids or None)
            messagebox.showinfo("CIR", f"Обновлено строк: {updated}. Добавлено строк: {inserted}.")
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def delete_selected(self) -> None:
        if self.app.runtime.read_only:
            messagebox.showinfo("CIR", "Текущий режим открыт только для чтения.")
            return
        ids = self._selected_remark_ids()
        if not ids:
            messagebox.showinfo("CIR", "Выберите замечание.")
            return
        if not messagebox.askyesno("CIR", f"Удалить выбранные замечания: {len(ids)}?"):
            return
        try:
            self.app.runtime.delete_remarks(ids)
            self.selected_id = ""
            for widget in self.fields.values():
                _set_widget_value(widget, "")
            self.refresh()
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def open_folder(self) -> None:
        kind, target_id = self._attachment_target()
        if not target_id:
            messagebox.showinfo("CIR", "Выберите замечание или предписание.")
            return
        try:
            if kind == "remark":
                path = self.app.runtime.open_remark_attachments(target_id)
            else:
                path = self.app.runtime.open_attachments(target_id)
            messagebox.showinfo("CIR", f"Папка вложений:\n{path}")
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def add_files(self) -> None:
        kind, target_id = self._attachment_target()
        if not target_id:
            messagebox.showinfo("CIR", "Выберите замечание или предписание.")
            return
        files = filedialog.askopenfilenames(title="Добавить вложения")
        if not files:
            return
        self.copy_attachment_paths(list(files), target_id if kind == "remark" else None)

    def copy_attachment_paths(self, paths: list[str], selected_id: str | None = None) -> None:
        paths = _existing_file_paths(paths)
        if not paths:
            messagebox.showinfo("CIR", "В перетаскивании не найдены файлы.")
            return
        kind, target_id = ("remark", selected_id) if selected_id else self._attachment_target()
        if not target_id:
            messagebox.showinfo("CIR", "Выберите замечание или предписание.")
            return
        try:
            if kind == "remark":
                count = self.app.runtime.copy_remark_attachments(target_id, paths)
            else:
                count = self.app.runtime.copy_attachments(target_id, paths)
            self._refresh_gallery()
            messagebox.showinfo("CIR", f"Добавлено файлов: {count}")
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def paste_files_from_clipboard(self) -> None:
        if not self._attachment_target()[1]:
            messagebox.showinfo("CIR", "Выберите замечание или предписание.")
            return
        paths = clipboard_file_paths(self.root_clipboard_get)
        if not paths:
            messagebox.showinfo("CIR", "В буфере не найдены файлы.")
            return
        self.copy_attachment_paths(paths)

    def root_clipboard_get(self) -> str:
        try:
            return self.winfo_toplevel().clipboard_get()
        except tk.TclError:
            return ""

    def _on_select(self, event=None) -> None:
        self._destroy_cell_editor()
        selection = self.tree.selection()
        if not selection:
            return
        item_id = selection[0]
        if item_id not in self.records:
            self.selected_id = ""
            prescription_id = self._prescription_id_from_tree_item(item_id)
            if prescription_id:
                self._set_prescription_combo(prescription_id)
            self._refresh_gallery()
            return
        self.selected_id = item_id
        item = self.records.get(self.selected_id, {})
        for label, record_id in self.prescription_lookup.items():
            if record_id == item.get("prescription_id"):
                _set_widget_value(self.fields["prescription_id"], label)
                break
        _set_widget_value(self.fields["internal_code"], item.get("internal_code", ""))
        _set_widget_value(self.fields["description"], item.get("description", ""))
        _set_widget_value(self.fields["location"], item.get("location", ""))
        _set_widget_value(self.fields["due_date"], _format_date_for_display(item.get("due_date", "")))
        _set_widget_value(self.fields["status"], item.get("status_label", ""))
        _set_widget_value(self.fields["note"], item.get("note", ""))
        self._refresh_gallery()

    def _show_context_menu(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) == "heading":
            self._show_column_menu(event.x_root, event.y_root)
            return
        item_id = self.tree.identify_row(event.y)
        if item_id and item_id not in self.tree.selection():
            self.tree.selection_set(item_id)
            self._on_select()
        column_id = self.tree.identify_column(event.x)
        field = self._editable_field(column_id)
        menu = tk.Menu(self, tearoff=False)
        if item_id in self.records and field:
            menu.add_command(label="Редактировать ячейку", command=lambda: self._edit_cell(item_id, column_id))
            if field == "due_date":
                menu.add_command(label="Открыть в календаре", command=lambda: self._open_calendar(item_id, event.x_root, event.y_root))
            menu.add_separator()
        menu.add_command(label="Новое замечание", command=self.new_record)
        menu.add_separator()
        menu.add_command(label="Копировать строки", command=self.copy_selected_rows)
        menu.add_command(label="Вставить из Excel", command=self.paste_from_excel)
        menu.add_separator()
        menu.add_command(label="Открыть папку", command=self.open_folder)
        menu.add_command(label="Вставить файлы из буфера", command=self.paste_files_from_clipboard)
        menu.add_command(label="Удалить", command=self.delete_selected)
        menu.tk_popup(event.x_root, event.y_root)

    def _edit_cell_from_event(self, event) -> None:
        item_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        if item_id in self.records and self._editable_field(column_id):
            self._edit_cell(item_id, column_id)

    def _edit_cell(self, item_id: str, column_id: str) -> None:
        self._destroy_cell_editor()
        field = self._editable_field(column_id)
        if not field:
            return
        bbox = self.tree.bbox(item_id, column_id)
        if not bbox:
            return
        x, y, width, height = bbox
        value = self._cell_value(item_id, field)
        if field == "status":
            status_value = value or REMARK_STATUS_LABELS[REMARK_IN_PROGRESS]
            value_var = tk.StringVar(value=status_value)
            editor = ttk.Combobox(self.tree, values=list(REMARK_STATUS_LABELS.values()), state="normal", textvariable=value_var)
            editor.set(status_value)
            editor.value_var = value_var
            editor.place(x=x, y=y, width=width, height=height)
            editor.focus_set()
            editor.selection_clear()
            editor.after_idle(lambda current=editor, current_value=status_value: current.set(current_value) if _widget_exists(current) else None)
            editor.bind("<<ComboboxSelected>>", lambda event, var=value_var: self._commit_cell_editor(item_id, field, var.get()))
            editor.bind("<Return>", lambda event, var=value_var: self._commit_cell_editor(item_id, field, var.get()))
            editor.bind("<Escape>", self._cancel_cell_editor)
            editor.bind("<Tab>", self._cancel_cell_editor)
            editor.bind("<FocusOut>", lambda event, current=editor: self._schedule_status_editor_cleanup(current))
            editor.bind("<KeyPress>", self._block_status_editor_typing, add="+")
        elif field in ("description", "note"):
            editor = tk.Text(self.tree, wrap="word")
            style_text_widget(editor)
            editor.insert("1.0", value)
            editor.place(x=x, y=y, width=max(width, 260), height=max(height * 3, 86))
            editor.focus_set()
            editor.bind("<Control-Return>", lambda event: self._commit_cell_editor(item_id, field, editor.get("1.0", "end").strip()))
            editor.bind("<Escape>", lambda event: self._destroy_cell_editor())
            editor.bind("<FocusOut>", lambda event: self._commit_cell_editor(item_id, field, editor.get("1.0", "end").strip()))
        else:
            editor = ttk.Entry(self.tree)
            editor.insert(0, value)
            editor.place(x=x, y=y, width=width, height=height)
            editor.focus_set()
            editor.selection_range(0, "end")
            editor.bind("<Return>", lambda event: self._commit_cell_editor(item_id, field, editor.get()))
            editor.bind("<Escape>", lambda event: self._destroy_cell_editor())
            editor.bind("<FocusOut>", lambda event: self._commit_cell_editor(item_id, field, editor.get()))
        self.cell_editor = editor

    def _commit_cell_editor(self, item_id: str, field: str, value: str) -> None:
        if self.cell_editor is None:
            return
        self._destroy_cell_editor()
        if field == "due_date":
            value = _normalize_date(value)
        self._save_remark_patch(item_id, {field: value})

    def _cancel_cell_editor(self, event=None) -> str:
        self._destroy_cell_editor()
        return "break"

    def _dismiss_cell_editor_from_key(self, event=None) -> None:
        if self.cell_editor is not None:
            self._destroy_cell_editor()

    def _block_status_editor_typing(self, event=None) -> str | None:
        if event is None:
            return None
        if event.keysym in {"Return", "Escape", "Tab", "Up", "Down", "Left", "Right", "Home", "End"}:
            return None
        return "break"

    def _schedule_status_editor_cleanup(self, editor: tk.Widget) -> None:
        if self.cell_editor_after_id:
            try:
                self.after_cancel(self.cell_editor_after_id)
            except tk.TclError:
                pass
        self.cell_editor_after_id = self.after(120, lambda current=editor: self._destroy_status_editor_if_inactive(current))

    def _destroy_status_editor_if_inactive(self, editor: tk.Widget) -> None:
        self.cell_editor_after_id = None
        if self.cell_editor is not editor:
            return
        if isinstance(editor, ttk.Combobox) and self._combobox_popdown_is_mapped(editor):
            self._schedule_status_editor_cleanup(editor)
            return
        focus = self.focus_get()
        if focus is editor:
            return
        self._destroy_cell_editor()

    def _combobox_popdown_is_mapped(self, combo: ttk.Combobox) -> bool:
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", combo)
            return bool(int(combo.tk.call("winfo", "ismapped", popdown)))
        except tk.TclError:
            return False

    def _destroy_cell_editor(self) -> None:
        if self.cell_editor_after_id:
            try:
                self.after_cancel(self.cell_editor_after_id)
            except tk.TclError:
                pass
            self.cell_editor_after_id = None
        if self.cell_editor is not None:
            try:
                self.cell_editor.destroy()
            except tk.TclError:
                pass
            self.cell_editor = None

    def _save_remark_patch(self, item_id: str, changes: dict[str, str]) -> None:
        if self.app.runtime.read_only:
            messagebox.showinfo("CIR", "Текущий режим открыт только для чтения.")
            return
        item = dict(self.records.get(item_id, {}))
        if not item:
            return
        reverse_status = {label: key for key, label in REMARK_STATUS_LABELS.items()}
        status_value = changes.get("status", item.get("status", REMARK_IN_PROGRESS))
        payload = {
            "id": item_id,
            "prescription_id": changes.get("prescription_id", item.get("prescription_id", "")),
            "internal_code": changes.get("internal_code", item.get("internal_code", "")),
            "description": changes.get("description", item.get("description", "")),
            "location": changes.get("location", item.get("location", "")),
            "due_date": changes.get("due_date", item.get("due_date", "")),
            "status": reverse_status.get(status_value, status_value or REMARK_IN_PROGRESS),
            "note": changes.get("note", item.get("note", "")),
        }
        try:
            saved_id = self.app.runtime.save_remark(payload)
            self.selected_id = saved_id
            self.refresh(prescription_ids=self.current_prescription_ids or None, selected_id=saved_id)
            if saved_id not in self.records:
                self.gallery.set_paths(self.app.runtime.remark_image_paths(saved_id))
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def _open_calendar(self, item_id: str, x_root: int, y_root: int) -> None:
        open_date_picker(
            self,
            self.records.get(item_id, {}).get("due_date", ""),
            x_root,
            y_root,
            "Срок замечания",
            lambda selected: self._save_remark_patch(item_id, {"due_date": selected.isoformat() if selected else ""}),
        )

    def _build_calendar(self, item_id: str, year: int, month: int, selected_date: date | None) -> None:
        assert self.calendar_window is not None
        _clear(self.calendar_window)
        outer = tk.Frame(self.calendar_window, bg=BG)
        outer.pack(fill="both", expand=True, padx=10, pady=10)
        frame = Card(outer, radius=14, shadow=True)
        frame.pack(fill="both", expand=True)
        for column in range(7):
            frame.columnconfigure(column, weight=1, uniform="calendar")

        header = tk.Frame(frame, bg=PANEL)
        header.grid(row=0, column=0, columnspan=7, sticky="ew", padx=12, pady=(10, 6))
        header.columnconfigure(1, weight=1)
        previous_month = date(year, month, 1) - timedelta(days=1)
        next_month = date(year, month, calendar.monthrange(year, month)[1]) + timedelta(days=1)
        self._calendar_nav_button(header, "‹", lambda: self._build_calendar(item_id, previous_month.year, previous_month.month, selected_date)).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(
            header,
            text=_month_title(year, month),
            bg=PANEL,
            fg=TEXT,
            font=font_tuple(self, 18, "bold"),
            anchor="center",
        ).grid(row=0, column=1, sticky="ew")
        self._calendar_nav_button(header, "›", lambda: self._build_calendar(item_id, next_month.year, next_month.month, selected_date)).grid(
            row=0, column=2, sticky="e"
        )

        today = date.today()
        selected_caption = selected_date.strftime("%d.%m.%Y") if selected_date else "не задан"
        tk.Label(
            frame,
            text=f"Выбранный срок: {selected_caption}",
            bg=PANEL,
            fg=MUTED,
            font=font_tuple(self, 12),
            anchor="center",
        ).grid(row=1, column=0, columnspan=7, sticky="ew", padx=12, pady=(0, 8))

        for column, label in enumerate(("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")):
            tk.Label(frame, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 12, "bold"), anchor="center").grid(
                row=2, column=column, sticky="ew", padx=2, pady=(0, 3)
            )
        month_weeks = calendar.monthcalendar(year, month)
        for row_index, week in enumerate(month_weeks, start=3):
            for column, day in enumerate(week):
                if not day:
                    tk.Label(frame, text="", bg=PANEL).grid(row=row_index, column=column, sticky="nsew", padx=2, pady=2)
                    continue
                value = date(year, month, day)
                self._calendar_day_button(frame, item_id, value, selected_date, today, column).grid(
                    row=row_index, column=column, sticky="nsew", padx=2, pady=2
                )

        footer = tk.Frame(frame, bg=PANEL)
        footer.grid(row=3 + len(month_weeks), column=0, columnspan=7, sticky="ew", padx=12, pady=(8, 10))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=1)
        tk.Button(
            footer,
            text="Сегодня",
            command=lambda: self._build_calendar(item_id, today.year, today.month, selected_date),
            bg=ACCENT_SOFT,
            fg=ACCENT_DARK,
            activebackground=ACCENT,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            font=font_tuple(self, 12, "bold"),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        tk.Button(
            footer,
            text="Очистить срок",
            command=lambda: self._select_calendar_date(item_id, None),
            bg=SURFACE,
            fg=MUTED,
            activebackground=PANEL,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            font=font_tuple(self, 12),
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _calendar_nav_button(self, parent: tk.Widget, text: str, command) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=SURFACE,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            width=4,
            height=1,
            font=font_tuple(self, 16, "bold"),
        )

    def _calendar_day_button(self, parent: tk.Widget, item_id: str, value: date, selected_date: date | None, today: date, column: int) -> tk.Button:
        is_selected = selected_date == value
        is_today = today == value
        is_weekend = column >= 5
        bg = PANEL
        fg = TEXT
        active_bg = ACCENT_SOFT
        relief = "flat"
        highlight = PANEL
        if is_weekend:
            fg = DANGER
            bg = DANGER_SOFT
        if is_today:
            bg = WARNING_SOFT
            fg = WARNING
            highlight = WARNING
        if is_selected:
            bg = ACCENT
            fg = TEXT
            active_bg = ACCENT_DARK
            highlight = ACCENT
        return tk.Button(
            parent,
            text=str(value.day),
            command=lambda selected=value: self._select_calendar_date(item_id, selected),
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            relief=relief,
            bd=0,
            highlightbackground=highlight,
            highlightthickness=1 if is_today and not is_selected else 0,
            width=4,
            height=1,
            font=font_tuple(self, 12, "bold" if is_selected else "normal"),
            cursor="hand2",
        )

    def _select_calendar_date(self, item_id: str, selected: date | None) -> None:
        if self.calendar_window is not None:
            self.calendar_window.destroy()
            self.calendar_window = None
        self._save_remark_patch(item_id, {"due_date": selected.isoformat() if selected else ""})

    def _editable_field(self, column_id: str) -> str:
        if column_id == "#0":
            return "internal_code"
        try:
            display_index = int(column_id.replace("#", "")) - 1
        except ValueError:
            return ""
        display_value = self.tree.cget("displaycolumns")
        if isinstance(display_value, str):
            display_columns = list(self.tk.splitlist(display_value))
        else:
            display_columns = list(display_value)
        if display_columns == ["#all"]:
            columns_value = self.tree.cget("columns")
            if isinstance(columns_value, str):
                display_columns = list(self.tk.splitlist(columns_value))
            else:
                display_columns = list(columns_value)
        if display_index < 0 or display_index >= len(display_columns):
            return ""
        mapping = {
            "due": "due_date",
            "status": "status",
            "location": "location",
            "description": "description",
            "note": "note",
        }
        return mapping.get(str(display_columns[display_index]), "")

    def _cell_value(self, item_id: str, field: str) -> str:
        item = self.records.get(item_id, {})
        if field == "status":
            return item.get("status_label", "")
        if field == "due_date":
            return _format_date_for_display(item.get("due_date", ""))
        return item.get(field, "")

    def copy_selected_rows(self) -> None:
        rows = []
        for item_id in self._selected_remark_ids():
            item = self.records.get(item_id, {})
            rows.append(
                [
                    item.get("internal_code", ""),
                    _object_display_name(item),
                    item.get("prescription_number", ""),
                    item.get("contractor", ""),
                    _format_date_for_display(item.get("due_date", "")),
                    item.get("status_label", ""),
                    item.get("location", ""),
                    item.get("description", ""),
                    item.get("note", ""),
                    item.get("source_label", ""),
                ]
            )
        copy_rows_to_clipboard(
            self,
            [["Номер замечания", "Объект", "Предписание", "Подрядчик", "Срок", "Статус", "Место", "Описание", "Комментарий", "Источник"]] + rows,
        )

    def _selected_remark_ids(self) -> list[str]:
        selected = set(self.tree.selection())
        result = [item_id for item_id in self.remark_order if item_id in selected and item_id in self.records]
        if not result and self.selected_id:
            result.append(self.selected_id)
        seen: set[str] = set()
        return [item for item in result if not (item in seen or seen.add(item))]

    def _set_prescription_combo(self, prescription_id: str) -> None:
        for label, record_id in self.prescription_lookup.items():
            if record_id == prescription_id:
                _set_widget_value(self.fields["prescription_id"], label)
                return

    def _target_prescription_id_for_insert(self) -> str:
        selection = self.tree.selection()
        if selection:
            prescription_id = self._prescription_id_from_tree_item(selection[0])
            if prescription_id:
                return prescription_id
        display = _get_widget_value(self.fields["prescription_id"])
        prescription_id = self.prescription_lookup.get(display, display)
        if prescription_id:
            return prescription_id
        if len(self.current_prescription_ids) == 1:
            return self.current_prescription_ids[0]
        return ""

    def _prescription_id_from_tree_item(self, item_id: str) -> str:
        if item_id in self.records:
            return self.records[item_id].get("prescription_id", "")
        if item_id in self.prescription_nodes:
            return self.prescription_nodes[item_id]
        if item_id in self.object_nodes:
            for prescription_node in self.tree.get_children(item_id):
                prescription_id = self.prescription_nodes.get(prescription_node, "")
                if prescription_id:
                    return prescription_id
        return ""

    def _object_filter_label(self, object_id: str) -> str:
        if not object_id:
            return UNASSIGNED_OBJECT
        for item in self.app.runtime.list_objects():
            if item.get("id") == object_id:
                return item.get("name", "")
        return ALL_OBJECTS

    def _attachment_target(self) -> tuple[str, str]:
        if self.selected_id and self.selected_id in self.records:
            return "remark", self.selected_id
        prescription_id = ""
        selection = self.tree.selection()
        if selection:
            prescription_id = self._prescription_id_from_tree_item(selection[0])
        if not prescription_id:
            prescription_id = self._target_prescription_id_for_insert()
        return ("prescription", prescription_id) if prescription_id else ("", "")

    def _refresh_gallery(self) -> None:
        kind, target_id = self._attachment_target()
        if not target_id:
            self.gallery.set_paths([])
            return
        if kind == "remark":
            self.gallery.set_paths(self.app.runtime.remark_image_paths(target_id))
        else:
            self.gallery.set_paths(self.app.runtime.prescription_image_paths(target_id))

    def _next_internal_code(self, prescription_id: str) -> str:
        anchor = self.tree.selection()[0] if self.tree.selection() else self.selected_id
        anchor_index = self.remark_order.index(anchor) if anchor in self.remark_order else len(self.remark_order)
        previous_code = ""
        for record_id in reversed(self.remark_order[:anchor_index] or self.remark_order):
            item = self.records.get(record_id, {})
            if item.get("prescription_id") == prescription_id:
                previous_code = item.get("internal_code", "")
                break
        if not previous_code:
            existing = self.app.runtime.list_remarks(prescription_id)
            if existing:
                previous_code = existing[-1].get("internal_code", "")
        return _increment_code(previous_code)

    def _update_context_label(self) -> None:
        if not self.current_prescription_ids:
            self.context_label.configure(text="Все замечания")
        elif len(self.current_prescription_ids) == 1:
            number = ""
            for record_id, label in ((value, key) for key, value in self.prescription_lookup.items()):
                if record_id == self.current_prescription_ids[0]:
                    number = label
                    break
            self.context_label.configure(text=f"Контекст: {number or '1 предписание'}")
        else:
            self.context_label.configure(text=f"Контекст: {len(self.current_prescription_ids)} предписаний")

    def _set_form_state(self) -> None:
        state = "disabled" if self.app.runtime.read_only else "normal"
        for widget in self.fields.values():
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="disabled" if self.app.runtime.read_only else "readonly")
            else:
                widget.configure(state=state)


class ExchangePage(ttk.Frame):
    def __init__(self, master, app: MainWindow):
        super().__init__(master)
        self.app = app
        self.object_var = tk.StringVar(value=ALL_OBJECTS)
        self.contractor_var = tk.StringVar(value=ALL_CONTRACTORS)
        self.include_attachments_var = tk.BooleanVar(value=True)
        self.object_lookup: dict[str, str] = {}
        self.output: tk.Text | None = None

    def refresh(self, **kwargs) -> None:
        _clear(self)
        ttk.Label(self, text="Обмен", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self, text="Пакеты CIR для передачи данных и фото по замечаниям через почту", style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(1, 8)
        )
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        body = ttk.Frame(self)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        form = Card(body, radius=12, shadow=True)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Объект", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=12, pady=(14, 4))
        object_values = [ALL_OBJECTS]
        self.object_lookup = {}
        for object_id, label in self.app.runtime.object_options():
            if not label:
                continue
            object_values.append(label)
            self.object_lookup[label] = object_id
        object_combo = ttk.Combobox(form, textvariable=self.object_var, values=object_values, state="readonly")
        object_combo.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10))
        if self.object_var.get() not in object_values:
            self.object_var.set(ALL_OBJECTS)

        ttk.Label(form, text="Подрядчик", style="Field.TLabel").grid(row=2, column=0, sticky="w", padx=12, pady=(0, 4))
        contractors = sorted({item.get("contractor", "") for item in self.app.runtime.list_prescriptions() if item.get("contractor", "")})
        contractor_values = [ALL_CONTRACTORS] + contractors
        contractor_combo = ttk.Combobox(form, textvariable=self.contractor_var, values=contractor_values, state="readonly")
        contractor_combo.grid(row=3, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10))
        if self.contractor_var.get() not in contractor_values:
            self.contractor_var.set(ALL_CONTRACTORS)

        ttk.Checkbutton(form, text="Включать фото по замечаниям", variable=self.include_attachments_var).grid(
            row=4, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12)
        )
        ttk.Button(form, text="Экспорт для подрядчика", command=lambda: self.export_package("assignment")).grid(
            row=5, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 8)
        )
        ttk.Button(form, text="Экспорт ответа", command=lambda: self.export_package("response")).grid(
            row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 8)
        )
        ttk.Button(form, text="Импорт пакета", style="Accent.TButton", command=self.import_package).grid(
            row=7, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 14)
        )

        detail = Card(body, radius=12, shadow=True)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.rowconfigure(1, weight=1)
        detail.columnconfigure(0, weight=1)
        tk.Label(detail, text="Результат", bg=PANEL, fg=MUTED, anchor="w").grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        self.output = tk.Text(detail, height=24, wrap="word", relief="flat", bd=0)
        style_text_widget(self.output)
        self.output.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self._write_output("Выберите фильтры и создайте пакет обмена или импортируйте полученный .cirx.")

    def export_package(self, package_type: str) -> None:
        contractor = "" if self.contractor_var.get() == ALL_CONTRACTORS else self.contractor_var.get()
        object_label = "" if self.object_var.get() == ALL_OBJECTS else self.object_var.get()
        object_id = self.object_lookup.get(object_label, "")
        default_name = self.app.runtime.suggest_exchange_package_name(package_type, contractor, object_label)
        path = filedialog.asksaveasfilename(
            title="Сохранить пакет CIR",
            defaultextension=".cirx",
            initialfile=default_name,
            filetypes=[("CIR exchange package", "*.cirx")],
        )
        if not path:
            return
        try:
            result = self.app.runtime.export_exchange_package(
                path,
                package_type=package_type,
                contractor=contractor,
                object_id=object_id,
                include_attachments=self.include_attachments_var.get(),
            )
            text = _format_exchange_export_result(result)
            self._write_output(text)
            if result.get("size_warning"):
                messagebox.showwarning(
                    "CIR",
                    f"Пакет создан, но размер {result['size_mb']} МБ выше безопасного лимита {result['mail_limit_mb']} МБ для почты.",
                )
            else:
                messagebox.showinfo("CIR", "Пакет обмена создан.")
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))
            self._write_output(str(exc))

    def import_package(self) -> None:
        if self.app.runtime.read_only:
            messagebox.showinfo("CIR", "Текущий режим открыт только для чтения.")
            return
        path = filedialog.askopenfilename(title="Импортировать пакет CIR", filetypes=[("CIR exchange package", "*.cirx")])
        if not path:
            return
        try:
            preview = self.app.runtime.inspect_exchange_package(path)
            preview_text = _format_exchange_preview(preview)
            self._write_output(preview_text)
            if preview.get("duplicate"):
                messagebox.showinfo("CIR", "Этот пакет уже импортирован.")
                return
            if not messagebox.askyesno("CIR", preview_text + "\n\nИмпортировать пакет?"):
                return
            result = self.app.runtime.import_exchange_package(path)
            result_text = _format_exchange_import_result(result)
            self._write_output(result_text)
            messagebox.showinfo("CIR", "Пакет импортирован.")
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))
            self._write_output(str(exc))

    def _write_output(self, value: str) -> None:
        if not self.output:
            return
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", value)
        self.output.configure(state="disabled")


class AuditPage(ttk.Frame):
    def __init__(self, master, app: MainWindow):
        super().__init__(master)
        self.app = app
        self.records: dict[str, dict] = {}
        self.tree: ttk.Treeview | None = None
        self.detail: tk.Text | None = None

    def refresh(self, **kwargs) -> None:
        _clear(self)
        ttk.Label(self, text="Журнал", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self, text="История создания, изменения, удаления и добавления вложений", style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(1, 8)
        )
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        body = ttk.Frame(self)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        table_card = Card(body, radius=12, shadow=True)
        table_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        table_card.rowconfigure(0, weight=1)
        table_card.columnconfigure(0, weight=1)

        tree = ttk.Treeview(
            table_card,
            columns=("changed_at", "profile", "entity", "action", "actor", "summary"),
            show="headings",
            height=24,
        )
        self.tree = tree
        style_treeview(tree)
        for key, title, width in (
            ("changed_at", "Время", 150),
            ("profile", "Профиль", 150),
            ("entity", "Раздел", 110),
            ("action", "Действие", 110),
            ("actor", "Автор", 170),
            ("summary", "Событие", 360),
        ):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        grid_treeview_with_scrollbars(table_card, tree, padx=8, pady=8)
        tree.bind("<<TreeviewSelect>>", self._on_select)
        tree.bind("<Control-c>", lambda event: self.copy_selected_rows())
        tree.bind("<Button-3>", self._show_context_menu)

        detail_card = Card(body, radius=12, shadow=True)
        detail_card.grid(row=0, column=1, sticky="nsew")
        detail_card.rowconfigure(1, weight=1)
        detail_card.columnconfigure(0, weight=1)
        tk.Label(detail_card, text="Детали", bg=PANEL, fg=MUTED, anchor="w").grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        self.detail = tk.Text(detail_card, height=24, wrap="word", relief="flat", bd=0)
        style_text_widget(self.detail)
        self.detail.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        rows = list(reversed(self.app.runtime.list_audit_log()))
        self.records = {}
        for index, item in enumerate(rows):
            record_id = item.get("id") or f"audit-{index}"
            self.records[record_id] = item
            tree.insert(
                "",
                "end",
                iid=record_id,
                values=(
                    item.get("changed_at", ""),
                    item.get("owner_name") or item.get("owner_slug") or item.get("__profile_slug", ""),
                    AUDIT_ENTITY_LABELS.get(item.get("entity_type", ""), item.get("entity_type", "")),
                    AUDIT_ACTION_LABELS.get(item.get("action", ""), item.get("action", "")),
                    item.get("actor_name") or item.get("actor_slug", ""),
                    item.get("summary", ""),
                ),
            )
        stripe_treeview(tree)
        if rows:
            first_id = next(iter(self.records))
            tree.selection_set(first_id)
            tree.focus(first_id)
            self._on_select()
        else:
            self._set_detail("Журнал пока пуст.")

    def copy_selected_rows(self) -> None:
        if not self.tree:
            return
        rows = [["Время", "Профиль", "Раздел", "Действие", "Автор", "Событие"]]
        for item_id in self.tree.selection() or self.tree.get_children(""):
            rows.append(list(self.tree.item(item_id, "values")))
        copy_rows_to_clipboard(self, rows)

    def _on_select(self, event=None) -> None:
        if not self.tree:
            return
        selection = self.tree.selection()
        if not selection:
            return
        item = self.records.get(selection[0], {})
        self._set_detail(_format_audit_detail(item))

    def _set_detail(self, value: str) -> None:
        if not self.detail:
            return
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", value)
        self.detail.configure(state="disabled")

    def _show_context_menu(self, event) -> None:
        if not self.tree:
            return
        item_id = self.tree.identify_row(event.y)
        if item_id and item_id not in self.tree.selection():
            self.tree.selection_set(item_id)
            self._on_select()
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Копировать строки", command=self.copy_selected_rows)
        menu.tk_popup(event.x_root, event.y_root)


class SettingsPage(ttk.Frame):
    def __init__(self, master, app: MainWindow):
        super().__init__(master)
        self.app = app
        self.server_root = tk.StringVar()
        self.user_name = tk.StringVar()
        self.user_slug = tk.StringVar()
        self.role = tk.StringVar()
        self.active_profile = tk.StringVar()
        self.user_slug_entry: ttk.Entry | None = None
        self.profile_combo: ttk.Combobox | None = None
        self.demo_button: ttk.Button | None = None
        self.profile_lookup: dict[str, str] = {}
        self.user_slug.trace_add("write", lambda *_args: self._sync_specialist_profile())
        self.server_root.trace_add("write", lambda *_args: self._update_demo_button_state())
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="Настройки", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        panel = Card(self)
        panel.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        panel.columnconfigure(1, weight=1)
        rows = [
            ("Серверная папка", self.server_root),
            ("Имя пользователя", self.user_name),
            ("Код пользователя", self.user_slug),
            ("Роль", self.role),
            ("Профиль для работы", self.active_profile),
        ]
        for row, (label, variable) in enumerate(rows):
            tk.Label(panel, text=label, bg=PANEL, fg=MUTED, font=font_tuple(self, 12)).grid(row=row, column=0, sticky="w", padx=14, pady=(14, 0))
            if label == "Роль":
                widget = ttk.Combobox(panel, textvariable=variable, values=list(ROLE_LABELS.values()), state="readonly")
                widget.bind("<<ComboboxSelected>>", lambda event: self._update_role_state())
            elif label == "Профиль для работы":
                widget = ttk.Combobox(panel, textvariable=variable, values=[], state="readonly")
                self.profile_combo = widget
            else:
                widget = ttk.Entry(panel, textvariable=variable)
                if label == "Код пользователя":
                    self.user_slug_entry = widget
            widget.grid(row=row, column=1, sticky="ew", padx=14, pady=(14, 0))
            if label == "Серверная папка":
                ttk.Button(panel, text="Выбрать", command=self.browse).grid(row=row, column=2, sticky="ew", padx=(0, 14), pady=(14, 0))
        actions = ttk.Frame(panel, style="Panel.TFrame")
        actions.grid(row=len(rows), column=0, columnspan=3, sticky="ew", padx=14, pady=14)
        for column in range(4):
            actions.columnconfigure(column, weight=1)
        ttk.Button(actions, text="Сохранить", style="Primary.TButton", command=self.save).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Обновить выгрузку", command=self.rebuild_export).grid(row=0, column=1, sticky="ew", padx=6)
        self.demo_button = ttk.Button(actions, text="Демо-данные", command=self.seed_demo)
        self.demo_button.grid(row=0, column=2, sticky="ew", padx=6)
        ttk.Button(actions, text="Обновить", command=self.refresh).grid(row=0, column=3, sticky="ew", padx=(6, 0))

    def refresh(self, **kwargs) -> None:
        config = self.app.runtime.config
        self.server_root.set(config.server_root)
        self.user_name.set(config.user_name)
        self.user_slug.set(config.user_slug)
        self.role.set(ROLE_LABELS.get(config.role, config.role))
        self._refresh_profile_options(config.active_profile_slug)
        self._update_role_state()
        self._update_demo_button_state()

    def browse(self) -> None:
        directory = filedialog.askdirectory(title="Серверная папка CIR")
        if directory:
            self.server_root.set(directory)
            self._refresh_profile_options(self._selected_profile_slug())

    def save(self) -> None:
        config = self._config_from_form()
        self.app.reload_runtime(config)
        messagebox.showinfo("CIR", "Настройки сохранены.")

    def _config_from_form(self) -> AppConfig:
        role = self._selected_role()
        user_slug = slugify(self.user_slug.get() or self.user_name.get())
        active_profile = user_slug if role == ROLE_SPECIALIST else (self._selected_profile_slug() or user_slug)
        return AppConfig(
            server_root=self.server_root.get().strip(),
            user_slug=user_slug,
            user_name=self.user_name.get(),
            role=role,
            active_profile_slug=active_profile,
        ).normalized()

    def _selected_role(self) -> str:
        reverse_roles = {label: key for key, label in ROLE_LABELS.items()}
        return reverse_roles.get(self.role.get(), ROLE_SPECIALIST)

    def _is_runtime_config(self, config: AppConfig) -> bool:
        current = self.app.runtime.config.normalized()
        target = config.normalized()
        return (
            Path(current.server_root) == Path(target.server_root)
            and current.user_slug == target.user_slug
            and current.user_name == target.user_name
            and current.role == target.role
            and current.active_profile_slug == target.active_profile_slug
        )

    def _refresh_profile_options(self, selected_slug: str = "") -> None:
        profiles = []
        root = Path(self.server_root.get() or self.app.runtime.config.server_root)
        try:
            profiles = list_profiles(root)
        except OSError:
            profiles = []
        values = []
        self.profile_lookup = {}
        seen: set[str] = set()
        for profile in profiles:
            label = _profile_option_label(profile.slug, profile.name)
            values.append(label)
            self.profile_lookup[label] = profile.slug
            seen.add(profile.slug)
        current_slug = selected_slug or self.app.runtime.config.active_profile_slug or self.user_slug.get()
        if current_slug and current_slug not in seen:
            label = _profile_option_label(current_slug, current_slug)
            values.insert(0, label)
            self.profile_lookup[label] = current_slug
        if self.profile_combo is not None:
            self.profile_combo.configure(values=values)
        selected_label = next((label for label, slug in self.profile_lookup.items() if slug == current_slug), "")
        self.active_profile.set(selected_label or (values[0] if values else current_slug))

    def _selected_profile_slug(self) -> str:
        value = self.active_profile.get().strip()
        return self.profile_lookup.get(value, slugify(value) if value else "")

    def _update_role_state(self) -> None:
        role = self._selected_role()
        if self.user_slug_entry is not None:
            self.user_slug_entry.configure(state="normal")
        if self.profile_combo is not None:
            if role == ROLE_SPECIALIST:
                self._select_profile_slug(slugify(self.user_slug.get() or self.user_name.get()))
                self.profile_combo.configure(state="disabled")
            else:
                self.profile_combo.configure(state="readonly")
        self._update_demo_button_state()

    def _sync_specialist_profile(self) -> None:
        if self._selected_role() != ROLE_SPECIALIST:
            return
        self._select_profile_slug(slugify(self.user_slug.get() or self.user_name.get()))
        self._update_demo_button_state()

    def _select_profile_slug(self, slug: str) -> None:
        slug = slugify(slug)
        for label, profile_slug in self.profile_lookup.items():
            if profile_slug == slug:
                self.active_profile.set(label)
                return
        label = _profile_option_label(slug, slug)
        self.profile_lookup[label] = slug
        if self.profile_combo is not None:
            values = list(self.profile_combo.cget("values"))
            if label not in values:
                self.profile_combo.configure(values=(label, *values))
        self.active_profile.set(label)

    def rebuild_export(self) -> None:
        try:
            self.app.runtime.export_current()
            messagebox.showinfo("CIR", "Выгрузка обновлена.")
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))

    def _update_demo_button_state(self) -> None:
        if self.demo_button is None:
            return
        has_repository = bool(self.server_root.get().strip())
        role = self._selected_role()
        config = self._config_from_form() if has_repository else None
        same_runtime = config is not None and self._is_runtime_config(config)
        locked_here = same_runtime and self.app.runtime.read_only
        enabled = has_repository and role != ROLE_SUPERVISOR and not locked_here
        self.demo_button.configure(state="normal" if enabled else "disabled")

    def _current_data_counts(self) -> tuple[int, int, int]:
        return (
            len(self.app.runtime.list_objects()),
            len(self.app.runtime.list_prescriptions()),
            len(self.app.runtime.list_remarks()),
        )

    def _confirm_demo_seed(self) -> bool:
        objects, prescriptions, remarks = self._current_data_counts()
        if objects == 0 and prescriptions == 0 and remarks == 0:
            return True
        return messagebox.askyesno(
            "CIR",
            "ВНИМАНИЕ!\n\n"
            "В ВЫБРАННУЮ СЕРВЕРНУЮ ПАПКУ БУДУТ ДОБАВЛЕНЫ ДЕМО-ПРОЕКТЫ.\n"
            "ЭТО ИЗМЕНИТ ДАННЫЕ В РЕПОЗИТОРИИ, ГДЕ ПРОГРАММА ХРАНИТ ИНФОРМАЦИЮ.\n\n"
            f"Сейчас найдено: объектов — {objects}, предписаний — {prescriptions}, замечаний — {remarks}.\n\n"
            "Продолжить добавление демо-данных?",
        )

    def seed_demo(self) -> None:
        try:
            config = self._config_from_form()
            if not config.server_root.strip():
                messagebox.showwarning("CIR", "Сначала укажите серверную папку.")
                return
            if config.role == ROLE_SUPERVISOR:
                messagebox.showwarning("CIR", "Демо-данные можно добавить только в режиме редактирования.")
                return
            if not self._is_runtime_config(config):
                if not messagebox.askyesno("CIR", "Настройки будут сохранены перед добавлением демо-данных. Продолжить?"):
                    return
                self.app.reload_runtime(config)
                self.refresh()
            if self.app.runtime.read_only:
                messagebox.showwarning("CIR", f"{self.app.runtime.lock_message}\n\nДемо-данные сейчас добавить нельзя.")
                return
            if not self._confirm_demo_seed():
                return
            self.app.runtime.seed_demo()
            self.refresh()
            messagebox.showinfo("CIR", "Демо-данные добавлены.")
        except Exception as exc:
            messagebox.showerror("CIR", str(exc))


class SetupDialog(tk.Toplevel):
    def __init__(self, master: tk.Tk, config: AppConfig):
        super().__init__(master)
        self.title("Первичная регистрация CIR")
        self.result: AppConfig | None = None
        self.resizable(False, False)
        self.server_root = tk.StringVar(value=config.server_root)
        self.user_name = tk.StringVar(value=config.user_name)
        self.user_slug = tk.StringVar(value=config.user_slug)
        self.role = tk.StringVar(value=ROLE_LABELS[config.role])
        self.transient(master)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=18)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)
        rows = [
            ("Серверная папка", self.server_root),
            ("Имя пользователя", self.user_name),
            ("Код пользователя", self.user_slug),
            ("Роль", self.role),
        ]
        for row, (label, variable) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=(0, 10))
            if label == "Роль":
                widget = ttk.Combobox(frame, textvariable=variable, values=[ROLE_LABELS[ROLE_SPECIALIST], ROLE_LABELS[ROLE_SUPERVISOR]], state="readonly", width=34)
            else:
                widget = ttk.Entry(frame, textvariable=variable, width=38)
            widget.grid(row=row, column=1, sticky="ew", pady=(0, 10))
            if label == "Серверная папка":
                ttk.Button(frame, text="Выбрать", command=self.browse).grid(row=row, column=2, padx=(8, 0), pady=(0, 10))
        ttk.Button(frame, text="Продолжить", style="Primary.TButton", command=self.submit).grid(row=len(rows), column=0, columnspan=3, sticky="ew")

    def browse(self) -> None:
        directory = filedialog.askdirectory(title="Серверная папка CIR")
        if directory:
            self.server_root.set(directory)

    def submit(self) -> None:
        reverse_roles = {label: key for key, label in ROLE_LABELS.items()}
        user_slug = slugify(self.user_slug.get() or self.user_name.get())
        self.result = AppConfig(
            server_root=self.server_root.get(),
            user_slug=user_slug,
            user_name=self.user_name.get(),
            role=reverse_roles.get(self.role.get(), ROLE_SPECIALIST),
            active_profile_slug=user_slug,
        ).normalized()
        self.destroy()


def _clear(widget: tk.Widget) -> None:
    for child in widget.winfo_children():
        child.destroy()


def _filter_key(label: str) -> str:
    for key, value in FILTERS.items():
        if value == label:
            return key
    return "all"


def _get_widget_value(widget: tk.Widget) -> str:
    if isinstance(widget, tk.Text):
        return widget.get("1.0", "end").strip()
    if isinstance(widget, ttk.Combobox):
        return widget.get().strip()
    if isinstance(widget, ttk.Entry):
        return widget.get().strip()
    return ""


def _set_widget_value(widget: tk.Widget, value: str) -> None:
    state = str(widget.cget("state")) if "state" in widget.keys() else "normal"
    if state == "disabled":
        widget.configure(state="normal")
    if isinstance(widget, tk.Text):
        widget.delete("1.0", "end")
        widget.insert("1.0", value or "")
    elif isinstance(widget, ttk.Combobox):
        widget.set(value or "")
    elif isinstance(widget, ttk.Entry):
        widget.delete(0, "end")
        widget.insert(0, value or "")
    if state == "disabled":
        widget.configure(state="disabled")


def _widget_exists(widget: tk.Widget) -> bool:
    try:
        return bool(widget.winfo_exists())
    except tk.TclError:
        return False


def _is_widget_or_descendant(widget: tk.Widget, ancestor: tk.Widget) -> bool:
    current: tk.Widget | None = widget
    while current is not None:
        if current == ancestor:
            return True
        try:
            parent_name = current.winfo_parent()
            current = current.nametowidget(parent_name) if parent_name else None
        except (KeyError, tk.TclError):
            return False
    return False


def _call_drop_callback(callback, paths: list[str], x_root: int | None = None, y_root: int | None = None) -> None:
    try:
        callback(paths, x_root, y_root)
    except TypeError:
        callback(paths)


def _photo_for_canvas(path: Path, max_width: int, max_height: int):
    if Image is not None and ImageTk is not None:
        image = Image.open(path)
        image.thumbnail((max(max_width, 1), max(max_height, 1)))
        return ImageTk.PhotoImage(image)
    photo = tk.PhotoImage(file=str(path))
    width = max(photo.width(), 1)
    height = max(photo.height(), 1)
    factor = max(1, (width + max_width - 1) // max(max_width, 1), (height + max_height - 1) // max(max_height, 1))
    return photo.subsample(factor, factor) if factor > 1 else photo


def _is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def bind_standard_context_menu(widget: tk.Widget) -> None:
    def show(event) -> None:
        menu = tk.Menu(widget, tearoff=False)
        menu.add_command(label="Вырезать", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="Копировать", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="Вставить", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Выделить всё", command=lambda: _select_all(widget))
        menu.tk_popup(event.x_root, event.y_root)

    widget.bind("<Button-3>", show)


def bind_date_mask(entry: ttk.Entry) -> None:
    entry.bind("<KeyRelease>", _mask_date_entry, add="+")
    entry.bind("<FocusOut>", _format_date_entry_on_blur, add="+")


def _mask_date_entry(event) -> None:
    entry = event.widget
    if not isinstance(entry, ttk.Entry):
        return
    if getattr(event, "keysym", "") in {"BackSpace", "Delete", "Left", "Right", "Home", "End", "Tab", "Escape"}:
        return
    raw = entry.get()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw.strip()):
        return
    digits = re.sub(r"\D", "", raw)[:8]
    if len(digits) <= 2:
        masked = digits
    elif len(digits) <= 4:
        masked = f"{digits[:2]}.{digits[2:]}"
    else:
        masked = f"{digits[:2]}.{digits[2:4]}.{digits[4:]}"
    if masked != raw:
        entry.delete(0, "end")
        entry.insert(0, masked)
        entry.icursor("end")


def _format_date_entry_on_blur(event) -> None:
    entry = event.widget
    if not isinstance(entry, ttk.Entry):
        return
    _set_widget_value(entry, _format_date_for_display(entry.get()))


def _select_all(widget: tk.Widget) -> None:
    if isinstance(widget, tk.Text):
        widget.tag_add("sel", "1.0", "end")
    elif isinstance(widget, ttk.Entry):
        widget.selection_range(0, "end")
    widget.focus_set()


def copy_rows_to_clipboard(widget: tk.Widget, rows: list[list[object]]) -> None:
    if not rows:
        return
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerows(rows)
    root = widget.winfo_toplevel()
    root.clipboard_clear()
    root.clipboard_append(output.getvalue())


def _format_audit_detail(item: dict) -> str:
    lines = [
        f"Время: {item.get('changed_at', '')}",
        f"Профиль: {item.get('owner_name') or item.get('owner_slug') or item.get('__profile_slug', '')}",
        f"Раздел: {AUDIT_ENTITY_LABELS.get(item.get('entity_type', ''), item.get('entity_type', ''))}",
        f"Действие: {AUDIT_ACTION_LABELS.get(item.get('action', ''), item.get('action', ''))}",
        f"Автор: {item.get('actor_name') or item.get('actor_slug', '')}",
        f"Источник: {item.get('actor_kind', '')}",
        f"Событие: {item.get('summary', '')}",
        "",
        "Изменения:",
    ]
    raw = item.get("changes_json", "")
    if not raw:
        lines.append("{}")
        return "\n".join(lines)
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        lines.append(str(raw))
    else:
        lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def _format_exchange_preview(item: dict) -> str:
    lines = [
        "Предпросмотр пакета",
        f"Тип: {_exchange_package_type_label(item.get('package_type', ''))}",
        f"Отправитель: {item.get('sender', '')}",
        f"Создан: {item.get('created_at', '')}",
        f"Размер: {item.get('size_mb', '')} МБ",
        "",
        f"Объекты: {item.get('objects', 0)} (новых: {item.get('objects_new', 0)})",
        f"Предписания: {item.get('prescriptions', 0)} (новых: {item.get('prescriptions_new', 0)})",
        f"Замечания: {item.get('remarks', 0)} (новых: {item.get('remarks_new', 0)})",
        f"Фото по замечаниям: {item.get('attachments', 0)}",
    ]
    if item.get("conflicts"):
        lines.append("")
        lines.append(f"Конфликты защищенных полей: {item.get('conflicts')}")
        for conflict in item.get("conflict_items", []):
            lines.append(f"- {conflict.get('internal_code') or conflict.get('remark_id')}: {conflict.get('fields')}")
        lines.append("При импорте ответа эти поля не будут перезаписаны.")
    if item.get("duplicate"):
        lines.append("")
        lines.append("Пакет уже был импортирован.")
    return "\n".join(lines)


def _format_exchange_export_result(item: dict) -> str:
    return "\n".join(
        [
            "Пакет создан",
            f"Тип: {_exchange_package_type_label(item.get('package_type', ''))}",
            f"Файл: {item.get('path', '')}",
            f"Размер: {item.get('size_mb', '')} МБ",
            f"Объекты: {item.get('objects', 0)}",
            f"Предписания: {item.get('prescriptions', 0)}",
            f"Замечания: {item.get('remarks', 0)}",
            f"Фото по замечаниям: {item.get('attachments', 0)}",
        ]
    )


def _format_exchange_import_result(item: dict) -> str:
    return "\n".join(
        [
            "Пакет импортирован",
            f"Тип: {_exchange_package_type_label(item.get('package_type', ''))}",
            f"Отправитель: {item.get('sender', '')}",
            f"Объекты применены: {item.get('objects', 0)}",
            f"Предписания применены: {item.get('prescriptions', 0)}",
            f"Замечания применены: {item.get('remarks', 0)}",
            f"Фото добавлено: {item.get('attachments', 0)}",
            f"Конфликты защищенных полей: {item.get('conflicts', 0)}",
        ]
    )


def _exchange_package_type_label(value: str) -> str:
    if value == "assignment":
        return "Задание подрядчику"
    if value == "response":
        return "Ответ подрядчика"
    return value


def _profile_option_label(slug: str, name: str) -> str:
    slug = (slug or "").strip()
    name = (name or "").strip()
    if name and name != slug:
        return f"{slug} · {name}"
    return slug


def parse_excel_remarks(text: str) -> list[dict[str, str]]:
    text = text.strip("\ufeff\r\n ")
    if not text:
        return []
    rows = [row for row in csv.reader(io.StringIO(text), delimiter="\t") if any(cell.strip() for cell in row)]
    if not rows:
        return []
    header_map = _excel_header_map(rows[0])
    if header_map:
        data_rows = rows[1:]
    else:
        data_rows = rows
    result: list[dict[str, str]] = []
    for row in data_rows:
        if header_map:
            payload = {
                "internal_code": _cell(row, header_map.get("internal_code")),
                "description": _cell(row, header_map.get("description")),
                "location": _cell(row, header_map.get("location")),
                "due_date": _normalize_date(_cell(row, header_map.get("due_date"))),
                "status": _status_key(_cell(row, header_map.get("status"))),
                "note": _cell(row, header_map.get("note")),
            }
        else:
            padded = row + [""] * 6
            payload = {
                "internal_code": padded[0].strip(),
                "description": padded[1].strip(),
                "location": padded[2].strip(),
                "due_date": _normalize_date(padded[3].strip()),
                "status": _status_key(padded[4].strip()),
                "note": padded[5].strip(),
            }
            if not payload["description"] and padded[0].strip():
                payload["internal_code"] = ""
                payload["description"] = padded[0].strip()
                payload["location"] = padded[1].strip()
                payload["due_date"] = _normalize_date(padded[2].strip())
                payload["status"] = _status_key(padded[3].strip())
                payload["note"] = padded[4].strip()
        if payload["description"]:
            result.append(payload)
    return result


def _excel_header_map(row: list[str]) -> dict[str, int]:
    aliases = {
        "internal_code": ("номер замечания", "номер", "код", "remark", "remark number"),
        "description": ("описание", "замечание", "текст", "description"),
        "location": ("место", "участок", "локация", "location"),
        "due_date": ("срок", "дата", "due", "due date"),
        "status": ("статус", "status"),
        "note": ("комментарий", "примечание", "note"),
    }
    normalized = [_normalize_header(cell) for cell in row]
    result: dict[str, int] = {}
    for key, values in aliases.items():
        for index, cell in enumerate(normalized):
            if cell in values:
                result[key] = index
                break
    return result if "description" in result else {}


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _normalize_date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            return value
    match = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})", value)
    if not match:
        return value
    day, month, year = match.groups()
    if len(year) == 2:
        year = f"20{year}"
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return value


def _parse_date_value(value: str) -> date | None:
    normalized = _normalize_date(value)
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _format_date_for_display(value: str) -> str:
    parsed = _parse_date_value(value)
    return parsed.strftime("%d.%m.%Y") if parsed else (value or "")


def open_date_picker(owner: tk.Widget, selected_value: str, x_root: int, y_root: int, title: str, on_select) -> None:
    current_window = getattr(owner, "calendar_window", None)
    if current_window is not None:
        try:
            current_window.destroy()
        except tk.TclError:
            pass
    selected_date = _parse_date_value(selected_value)
    visible = selected_date or date.today()
    window = tk.Toplevel(owner)
    setattr(owner, "calendar_window", window)
    window.title(title)
    window.configure(bg=BG)
    window.resizable(False, False)
    popup_width = 420
    popup_height = 350
    screen_width = max(owner.winfo_screenwidth(), popup_width)
    screen_height = max(owner.winfo_screenheight(), popup_height)
    x = min(max(0, x_root), max(0, screen_width - popup_width - 12))
    y = min(max(0, y_root), max(0, screen_height - popup_height - 44))
    window.geometry(f"{popup_width}x{popup_height}+{x}+{y}")
    window.transient(owner.winfo_toplevel())

    def close() -> None:
        try:
            window.destroy()
        except tk.TclError:
            pass
        if getattr(owner, "calendar_window", None) is window:
            setattr(owner, "calendar_window", None)

    def choose(value: date | None) -> None:
        close()
        on_select(value)

    def build(year: int, month: int) -> None:
        _clear(window)
        outer = tk.Frame(window, bg=BG)
        outer.pack(fill="both", expand=True, padx=10, pady=10)
        frame = Card(outer, radius=14, shadow=True)
        frame.pack(fill="both", expand=True)
        for column in range(7):
            frame.columnconfigure(column, weight=1, uniform="calendar")

        header = tk.Frame(frame, bg=PANEL)
        header.grid(row=0, column=0, columnspan=7, sticky="ew", padx=12, pady=(10, 6))
        header.columnconfigure(1, weight=1)
        previous_month = date(year, month, 1) - timedelta(days=1)
        next_month = date(year, month, calendar.monthrange(year, month)[1]) + timedelta(days=1)
        _calendar_nav_button(header, "‹", lambda: build(previous_month.year, previous_month.month)).grid(row=0, column=0, sticky="w")
        tk.Label(header, text=_month_title(year, month), bg=PANEL, fg=TEXT, font=font_tuple(owner, 18, "bold"), anchor="center").grid(
            row=0, column=1, sticky="ew"
        )
        _calendar_nav_button(header, "›", lambda: build(next_month.year, next_month.month)).grid(row=0, column=2, sticky="e")

        caption = selected_date.strftime("%d.%m.%Y") if selected_date else "не задан"
        tk.Label(frame, text=f"Выбранная дата: {caption}", bg=PANEL, fg=MUTED, font=font_tuple(owner, 12), anchor="center").grid(
            row=1, column=0, columnspan=7, sticky="ew", padx=12, pady=(0, 8)
        )
        for column, label in enumerate(("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")):
            tk.Label(frame, text=label, bg=PANEL, fg=MUTED, font=font_tuple(owner, 12, "bold"), anchor="center").grid(
                row=2, column=column, sticky="ew", padx=2, pady=(0, 3)
            )
        month_weeks = calendar.monthcalendar(year, month)
        today = date.today()
        for row_index, week in enumerate(month_weeks, start=3):
            for column, day in enumerate(week):
                if not day:
                    tk.Label(frame, text="", bg=PANEL).grid(row=row_index, column=column, sticky="nsew", padx=2, pady=2)
                    continue
                value = date(year, month, day)
                _calendar_day_button(frame, value, selected_date, today, column, lambda selected=value: choose(selected)).grid(
                    row=row_index, column=column, sticky="nsew", padx=2, pady=2
                )

        footer = tk.Frame(frame, bg=PANEL)
        footer.grid(row=3 + len(month_weeks), column=0, columnspan=7, sticky="ew", padx=12, pady=(8, 10))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=1)
        tk.Button(
            footer,
            text="Сегодня",
            command=lambda: choose(today),
            bg=ACCENT_SOFT,
            fg=ACCENT_DARK,
            activebackground=ACCENT,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            font=font_tuple(owner, 12, "bold"),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        tk.Button(
            footer,
            text="Очистить срок",
            command=lambda: choose(None),
            bg=SURFACE,
            fg=MUTED,
            activebackground=PANEL,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            font=font_tuple(owner, 12),
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    window.bind("<Escape>", lambda event: close())
    build(visible.year, visible.month)


def _calendar_nav_button(parent: tk.Widget, text: str, command) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=SURFACE,
        fg=TEXT,
        activebackground=PANEL,
        activeforeground=TEXT,
        relief="flat",
        bd=0,
        width=4,
        height=1,
        font=font_tuple(parent, 16, "bold"),
    )


def _calendar_day_button(parent: tk.Widget, value: date, selected_date: date | None, today: date, column: int, command) -> tk.Button:
    is_selected = selected_date == value
    is_today = today == value
    is_weekend = column >= 5
    bg = PANEL
    fg = TEXT
    active_bg = ACCENT_SOFT
    highlight = PANEL
    if is_weekend:
        fg = DANGER
        bg = DANGER_SOFT
    if is_today:
        bg = WARNING_SOFT
        fg = WARNING
        highlight = WARNING
    if is_selected:
        bg = ACCENT
        fg = TEXT
        active_bg = ACCENT_DARK
        highlight = ACCENT
    return tk.Button(
        parent,
        text=str(value.day),
        command=command,
        bg=bg,
        fg=fg,
        activebackground=active_bg,
        activeforeground=fg,
        relief="flat",
        bd=0,
        highlightbackground=highlight,
        highlightthickness=1 if is_today and not is_selected else 0,
        width=4,
        height=1,
        font=font_tuple(parent, 12, "bold" if is_selected else "normal"),
        cursor="hand2",
    )


def _status_key(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return "not_started"
    reverse = {label.lower(): key for key, label in REMARK_STATUS_LABELS.items()}
    if value in reverse:
        return reverse[value]
    if value in ("не начато", "нет", "not_started", "not started"):
        return "not_started"
    if value in ("в работе", "исполняется", "in_progress", "in progress"):
        return "in_progress"
    if value in ("выполнено", "done"):
        return "done"
    if value in ("принято", "accepted"):
        return "accepted"
    return "not_started"


def clipboard_file_paths(text_getter) -> list[str]:
    paths = _windows_clipboard_file_paths()
    if paths:
        return paths
    text = text_getter()
    result = []
    for raw in re.split(r"[\r\n]+", text):
        value = raw.strip().strip('"')
        if value and os.path.isfile(value):
            result.append(value)
    return result


def _existing_file_paths(paths: list[str]) -> list[str]:
    result = []
    for raw in paths:
        value = str(raw).strip().strip('"')
        if value and os.path.isfile(value):
            result.append(value)
    return result


def _windows_clipboard_file_paths() -> list[str]:
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        CF_HDROP = 15
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        if not user32.OpenClipboard(None):
            return []
        try:
            handle = user32.GetClipboardData(CF_HDROP)
            if not handle:
                return []
            count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
            result = []
            for index in range(count):
                length = shell32.DragQueryFileW(handle, index, None, 0)
                buffer = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(handle, index, buffer, length + 1)
                if os.path.isfile(buffer.value):
                    result.append(buffer.value)
            return result
        finally:
            user32.CloseClipboard()
    except Exception:
        return []




def _parse_iso(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _shorten(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "..."


def _month_title(year: int, month: int) -> str:
    if 1 <= month <= 12:
        return f"{MONTH_NAMES[month]} {year}"
    return f"{month:02d}.{year}"


def _increment_code(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "RM-001"
    match = re.search(r"(\d+)(\D*)$", value)
    if not match:
        return f"{value}-1"
    number, suffix = match.groups()
    start, end = match.span(1)
    return f"{value[:start]}{int(number) + 1:0{len(number)}d}{suffix}"


def _matches_prescription_filter(item: dict, filter_name: str) -> bool:
    if filter_name == "active":
        return not item.get("is_done")
    if filter_name == "overdue":
        return bool(item.get("overdue_count"))
    if filter_name == "near_due":
        return bool(item.get("near_due"))
    if filter_name == "not_owner":
        return bool(item.get("needs_owner_review"))
    return True


def _object_display_name(item: dict) -> str:
    return item.get("object_name") or item.get("object_display_name") or item.get("project") or UNASSIGNED_OBJECT


def _object_status_tag(item: dict) -> str:
    if int(item.get("prescriptions_overdue") or 0):
        return "status_danger"
    if item.get("near_due"):
        return "status_warning"
    if int(item.get("prescriptions_active") or 0):
        return "status_neutral"
    return "status_success" if int(item.get("prescriptions_total") or 0) else "status_neutral"


def _prescription_status_tag(item: dict) -> str:
    if int(item.get("overdue_count") or 0):
        return "status_danger"
    if item.get("near_due"):
        return "status_warning"
    if item.get("is_done"):
        return "status_success"
    return "status_neutral"


def _remark_status_tag(item: dict) -> str:
    status = item.get("status", "")
    if status in REMARK_COMPLETED:
        return "status_success"
    due_date = _parse_iso(item.get("due_date", ""))
    if due_date and due_date < date.today():
        return "status_danger"
    if status == REMARK_IN_PROGRESS:
        return "status_warning"
    return "status_neutral"


def _contractor_summary(prescriptions: list[dict]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for item in prescriptions:
        contractor = item.get("contractor") or "Без подрядчика"
        result.setdefault(contractor, {"total": 0, "active": 0, "overdue": 0})
        result[contractor]["total"] += 1
        if not item.get("is_done") and item.get("status") != "Выполнено в полном объеме":
            result[contractor]["active"] += 1
        if int(item.get("overdue_count") or 0):
            result[contractor]["overdue"] += 1
    return dict(sorted(result.items()))


def copy_treeview_to_clipboard(tree: ttk.Treeview) -> None:
    columns = list(tree["columns"])
    headers = [tree.heading(column).get("text", column) for column in columns]
    rows = [headers]
    selected = tree.selection() or tree.get_children("")
    for item_id in selected:
        rows.append(list(tree.item(item_id, "values")))
    copy_rows_to_clipboard(tree, rows)


def show_tree_copy_menu(tree: ttk.Treeview, event) -> None:
    item_id = tree.identify_row(event.y)
    if item_id and item_id not in tree.selection():
        tree.selection_set(item_id)
    menu = tk.Menu(tree, tearoff=False)
    menu.add_command(label="Копировать строки", command=lambda: copy_treeview_to_clipboard(tree))
    menu.tk_popup(event.x_root, event.y_root)
