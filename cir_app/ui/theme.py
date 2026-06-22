from __future__ import annotations

import tkinter as tk
from tkinter import font, ttk


COLOR_BG = "#F7F5EF"
COLOR_SURFACE = "#FFFFFF"
COLOR_SURFACE_ALT = "#F1EFE8"
COLOR_PRIMARY = "#9EEBCC"
COLOR_PRIMARY_HOVER = "#B8F5DD"
COLOR_PRIMARY_DARK = "#70C9A8"
COLOR_NAV_HOVER = "#DDF8ED"
COLOR_FOCUS = "#00CFCC"
COLOR_BORDER = "#E2DED2"
COLOR_TEXT = "#2C2C2C"
COLOR_TEXT_MUTED = "#77746B"
COLOR_DANGER = "#EF7777"
COLOR_WARNING = "#E8C756"
COLOR_SUCCESS = "#7DD6B6"
COLOR_NEUTRAL = "#77756D"
COLOR_DANGER_SOFT = "#FFF0F0"
COLOR_WARNING_SOFT = "#FFF8D9"
COLOR_SUCCESS_SOFT = "#EFFBF6"

COLOR_SIDEBAR = "#EDEAE1"
COLOR_TABLE_ALT = "#FAF9F5"
COLOR_SELECTION = "#D9F7EA"
COLOR_PROGRESS_BG = "#DEDACF"
COLOR_GRID = "#EAE5D8"
COLOR_INPUT_BORDER = "#D8D3C7"
COLOR_BORDER_HOVER = "#D6D0C3"
COLOR_SECONDARY_HOVER = "#F6F3EC"
COLOR_HEADER_TEXT = "#3A3935"
COLOR_HIGHLIGHT = "#FFFFFF"
COLOR_SHADOW_1 = "#E8E2D6"
COLOR_SHADOW_2 = "#DDD6C8"
COLOR_SHADOW_3 = "#D0C7B8"
COLOR_SCROLLBAR = "#CFC8B8"
COLOR_SCROLLBAR_HOVER = "#BEB6A5"

FONT_FAMILY = "Manrope"
FONT_FALLBACKS = ("Manrope", "Inter", "Segoe UI")
FONT_DISPLAY_SIZE = 30
FONT_H1_SIZE = 22
FONT_H2_SIZE = 17
FONT_BODY_SIZE = 12
FONT_TABLE_SIZE = 12
FONT_CAPTION_SIZE = 11
FONT_NUMBER_SIZE = 28

FONT_DISPLAY_WEIGHT = "bold"
FONT_H1_WEIGHT = "bold"
FONT_H2_WEIGHT = "bold"
FONT_BODY_WEIGHT = "normal"
FONT_CAPTION_WEIGHT = "normal"
FONT_NUMBER_WEIGHT = "bold"

RADIUS_CARD = 14
RADIUS_CARD_LARGE = 16
RADIUS_CONTROL = 10
RADIUS_CHIP = 10
RADIUS_PROGRESS = 6

SPACE_PAGE = 24
SPACE_SECTION = 14
SPACE_CARD = 12
SPACE_CONTROL_X = 14
SPACE_CONTROL_Y = 7

BG = COLOR_BG
PANEL = COLOR_SURFACE
PANEL_ALT = COLOR_SURFACE_ALT
SIDEBAR = COLOR_SIDEBAR
BORDER = COLOR_BORDER
GRID = COLOR_GRID
TEXT = COLOR_TEXT
MUTED = COLOR_TEXT_MUTED
ACCENT = COLOR_PRIMARY
ACCENT_HOVER = COLOR_PRIMARY_HOVER
ACCENT_DARK = COLOR_PRIMARY_DARK
ACCENT_SOFT = COLOR_SELECTION
FOCUS = COLOR_FOCUS
DANGER = COLOR_DANGER
WARNING = COLOR_WARNING
SUCCESS = COLOR_SUCCESS
NEUTRAL = COLOR_NEUTRAL
DANGER_SOFT = COLOR_DANGER_SOFT
WARNING_SOFT = COLOR_WARNING_SOFT
SURFACE = COLOR_SURFACE
SURFACE_ALT = COLOR_SURFACE_ALT
SURFACE_DARK = COLOR_PROGRESS_BG
SHADOW = COLOR_SHADOW_3
LIGHT = COLOR_SURFACE

_active_font_family = FONT_FAMILY


def resolve_font_family(root: tk.Misc | None = None) -> str:
    try:
        families = set(font.families(root))
    except tk.TclError:
        families = set()
    for family in FONT_FALLBACKS:
        if not families or family in families:
            return family
    return "Segoe UI"


def _pixel_size(size: int) -> int:
    return -abs(size)


def font_tuple(root: tk.Misc | None, size: int, weight: str = "normal") -> tuple:
    family = resolve_font_family(root)
    return (family, _pixel_size(size), "bold") if weight == "bold" else (family, _pixel_size(size))


def active_font(size: int, weight: str = "normal") -> tuple:
    return (_active_font_family, _pixel_size(size), "bold") if weight == "bold" else (_active_font_family, _pixel_size(size))


def apply_style(root: tk.Tk) -> None:
    global _active_font_family
    _active_font_family = resolve_font_family(root)

    root.configure(bg=COLOR_BG)
    root.option_add("*Font", active_font(FONT_BODY_SIZE, FONT_BODY_WEIGHT))
    root.option_add("*Menu.background", COLOR_SURFACE)
    root.option_add("*Menu.foreground", COLOR_TEXT)
    root.option_add("*Menu.activeBackground", COLOR_SELECTION)
    root.option_add("*Menu.activeForeground", COLOR_TEXT)
    root.option_add("*Menu.borderWidth", 0)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=active_font(FONT_BODY_SIZE), background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure("TFrame", background=COLOR_BG)
    style.configure("Panel.TFrame", background=COLOR_SURFACE)
    style.configure("Sidebar.TFrame", background=COLOR_SIDEBAR)
    style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=active_font(FONT_BODY_SIZE))
    style.configure("Muted.TLabel", background=COLOR_BG, foreground=COLOR_TEXT_MUTED, font=active_font(FONT_CAPTION_SIZE))
    style.configure("Panel.TLabel", background=COLOR_SURFACE, foreground=COLOR_TEXT, font=active_font(FONT_BODY_SIZE))
    style.configure("Title.TLabel", font=active_font(FONT_H1_SIZE, "bold"), background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure("Section.TLabel", font=active_font(FONT_H2_SIZE, "bold"), background=COLOR_BG, foreground=COLOR_TEXT)
    style.configure("Subtitle.TLabel", font=active_font(FONT_CAPTION_SIZE), background=COLOR_BG, foreground=COLOR_TEXT_MUTED)
    style.configure(
        "Status.TLabel",
        font=active_font(FONT_CAPTION_SIZE),
        background=COLOR_SURFACE,
        foreground=COLOR_TEXT_MUTED,
        padding=(12, 6),
        borderwidth=1,
        relief="solid",
    )

    style.configure(
        "Nav.TButton",
        anchor="w",
        padding=(14, 9),
        background=COLOR_SIDEBAR,
        foreground=COLOR_TEXT,
        font=active_font(FONT_BODY_SIZE),
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "NavActive.TButton",
        anchor="w",
        padding=(14, 9),
        background=COLOR_PRIMARY,
        foreground=COLOR_TEXT,
        font=active_font(FONT_BODY_SIZE, "bold"),
        borderwidth=1,
        bordercolor=COLOR_PRIMARY_DARK,
        relief="flat",
    )
    style.map(
        "Nav.TButton",
        background=[("active", COLOR_NAV_HOVER), ("pressed", COLOR_PRIMARY_HOVER)],
        foreground=[("pressed", COLOR_TEXT)],
    )
    style.map(
        "NavActive.TButton",
        background=[("active", COLOR_PRIMARY_HOVER), ("pressed", COLOR_PRIMARY_DARK)],
        foreground=[("pressed", COLOR_TEXT)],
    )

    style.configure(
        "TButton",
        padding=(SPACE_CONTROL_X, SPACE_CONTROL_Y),
        background=COLOR_SURFACE,
        foreground=COLOR_TEXT,
        font=active_font(FONT_BODY_SIZE, "bold"),
        borderwidth=1,
        relief="flat",
        bordercolor=COLOR_BORDER,
        lightcolor=COLOR_SURFACE,
        darkcolor=COLOR_BORDER,
        focusthickness=2,
        focuscolor=COLOR_FOCUS,
    )
    style.map(
        "TButton",
        background=[("disabled", COLOR_SURFACE_ALT), ("pressed", COLOR_SURFACE_ALT), ("active", COLOR_SECONDARY_HOVER)],
        foreground=[("disabled", COLOR_TEXT_MUTED)],
        bordercolor=[("focus", COLOR_FOCUS), ("active", COLOR_BORDER_HOVER)],
    )
    style.configure(
        "Primary.TButton",
        padding=(SPACE_CONTROL_X, SPACE_CONTROL_Y),
        background=COLOR_PRIMARY,
        foreground=COLOR_TEXT,
        font=active_font(FONT_BODY_SIZE, "bold"),
        borderwidth=0,
        relief="flat",
        focusthickness=2,
        focuscolor=COLOR_FOCUS,
    )
    style.map(
        "Primary.TButton",
        background=[("active", COLOR_PRIMARY_HOVER), ("pressed", COLOR_PRIMARY_DARK), ("disabled", COLOR_SURFACE_ALT)],
        foreground=[("disabled", COLOR_TEXT_MUTED)],
    )
    style.configure(
        "Ghost.TButton",
        padding=(12, 6),
        background=COLOR_BG,
        foreground=COLOR_TEXT,
        font=active_font(FONT_BODY_SIZE, "bold"),
        borderwidth=0,
        relief="flat",
        focusthickness=1,
        focuscolor=COLOR_FOCUS,
    )
    style.map(
        "Ghost.TButton",
        background=[("active", COLOR_SURFACE_ALT), ("pressed", COLOR_BORDER), ("disabled", COLOR_BG)],
        foreground=[("disabled", COLOR_TEXT_MUTED)],
    )

    style.configure(
        "TEntry",
        padding=(9, 5),
        fieldbackground=COLOR_SURFACE,
        foreground=COLOR_TEXT,
        font=active_font(FONT_BODY_SIZE),
        borderwidth=1,
        bordercolor=COLOR_INPUT_BORDER,
        lightcolor=COLOR_SURFACE,
        darkcolor=COLOR_BORDER,
        insertcolor=COLOR_TEXT,
    )
    style.map("TEntry", bordercolor=[("focus", COLOR_FOCUS)], lightcolor=[("focus", COLOR_FOCUS)])
    style.configure(
        "TCombobox",
        padding=(9, 5),
        fieldbackground=COLOR_SURFACE,
        background=COLOR_SURFACE,
        foreground=COLOR_TEXT,
        font=active_font(FONT_BODY_SIZE),
        borderwidth=1,
        bordercolor=COLOR_INPUT_BORDER,
        arrowcolor=COLOR_TEXT,
        lightcolor=COLOR_SURFACE,
        darkcolor=COLOR_BORDER,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", COLOR_SURFACE)],
        background=[("active", COLOR_PRIMARY_HOVER)],
        bordercolor=[("focus", COLOR_FOCUS), ("active", COLOR_PRIMARY_DARK)],
        selectbackground=[("readonly", COLOR_SELECTION)],
        selectforeground=[("readonly", COLOR_TEXT)],
    )

    style.configure(
        "Treeview",
        rowheight=30,
        fieldbackground=COLOR_SURFACE,
        background=COLOR_SURFACE,
        foreground=COLOR_TEXT,
        font=active_font(FONT_TABLE_SIZE),
        borderwidth=0,
        bordercolor=COLOR_BORDER,
        lightcolor=COLOR_SURFACE,
        darkcolor=COLOR_BORDER,
    )
    style.configure(
        "Treeview.Heading",
        font=active_font(FONT_TABLE_SIZE, "bold"),
        background=COLOR_SURFACE_ALT,
        foreground=COLOR_HEADER_TEXT,
        borderwidth=0,
        bordercolor=COLOR_BORDER,
        padding=(6, 5),
        relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", COLOR_SELECTION)],
        foreground=[("selected", COLOR_TEXT)],
    )
    style.map("Treeview.Heading", background=[("active", COLOR_SURFACE_ALT)])
    style.configure(
        "Horizontal.TScrollbar",
        background=COLOR_SCROLLBAR,
        troughcolor=COLOR_SURFACE_ALT,
        bordercolor=COLOR_SURFACE_ALT,
        arrowcolor=COLOR_TEXT_MUTED,
        arrowsize=9,
        width=10,
    )
    style.configure(
        "Vertical.TScrollbar",
        background=COLOR_SCROLLBAR,
        troughcolor=COLOR_SURFACE_ALT,
        bordercolor=COLOR_SURFACE_ALT,
        arrowcolor=COLOR_TEXT_MUTED,
        arrowsize=9,
        width=10,
    )
    style.map(
        "Horizontal.TScrollbar",
        background=[("active", COLOR_SCROLLBAR_HOVER), ("pressed", COLOR_SCROLLBAR_HOVER)],
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", COLOR_SCROLLBAR_HOVER), ("pressed", COLOR_SCROLLBAR_HOVER)],
    )
    style.configure("TPanedwindow", background=COLOR_BG)
    style.configure("Sash", background=COLOR_BORDER)
    style.configure("TRadiobutton", background=COLOR_SURFACE, foreground=COLOR_TEXT, font=active_font(FONT_CAPTION_SIZE))


def widget_background(widget: tk.Misc, fallback: str = COLOR_BG) -> str:
    try:
        return str(widget.cget("bg"))
    except (tk.TclError, KeyError):
        return fallback


def draw_round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs) -> int:
    radius = min(radius, abs(x2 - x1) / 2, abs(y2 - y1) / 2)
    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=16, **kwargs)


def draw_soft_panel(
    canvas: tk.Canvas,
    width: int,
    height: int,
    *,
    radius: int = RADIUS_CARD,
    fill: str = COLOR_SURFACE,
    border: str = COLOR_BORDER,
    shadow: bool = True,
    background: str = COLOR_BG,
) -> None:
    canvas.delete("theme_panel")
    canvas.configure(bg=background)
    if width <= 4 or height <= 4:
        return
    if shadow:
        draw_round_rect(canvas, 5, 7, width - 3, height - 3, radius, fill=COLOR_SHADOW_1, outline="", tags="theme_panel")
        draw_round_rect(canvas, 3, 5, width - 5, height - 5, radius, fill=COLOR_SHADOW_2, outline="", tags="theme_panel")
    draw_round_rect(canvas, 1, 1, width - 7, height - 8, radius, fill=fill, outline=border, tags="theme_panel")
    canvas.create_line(14, 3, width - 24, 3, fill=COLOR_HIGHLIGHT, tags="theme_panel")
    canvas.tag_lower("theme_panel")


class Card(tk.Frame):
    def __init__(
        self,
        master,
        *,
        radius: int = RADIUS_CARD,
        shadow: bool = True,
        surface: str = COLOR_SURFACE,
        **kwargs,
    ):
        outer_bg = kwargs.pop("bg", widget_background(master))
        super().__init__(master, bg=outer_bg, highlightthickness=0, bd=0, **kwargs)
        self._theme_radius = radius
        self._theme_shadow = shadow
        self._theme_surface = surface
        self._theme_outer_bg = outer_bg
        self._theme_draw_after_id: str | None = None
        self._theme_last_size: tuple[int, int] = (0, 0)
        self._theme_canvas = tk.Canvas(self, bg=outer_bg, highlightthickness=0, bd=0)
        self._theme_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._theme_canvas.tk.call("lower", self._theme_canvas._w)
        self.bind("<Configure>", self._draw_theme_panel, add="+")

    def _draw_theme_panel(self, event=None) -> None:
        width = max(int(getattr(event, "width", self.winfo_width())), 1)
        height = max(int(getattr(event, "height", self.winfo_height())), 1)
        if (width, height) == self._theme_last_size:
            return
        self._theme_last_size = (width, height)
        if self._theme_draw_after_id is not None:
            return
        self._theme_draw_after_id = self.after(35, self._draw_theme_panel_now)

    def _draw_theme_panel_now(self) -> None:
        self._theme_draw_after_id = None
        width, height = self._theme_last_size
        draw_soft_panel(
            self._theme_canvas,
            width,
            height,
            radius=self._theme_radius,
            fill=self._theme_surface,
            shadow=self._theme_shadow,
            background=self._theme_outer_bg,
        )


class Chip(tk.Canvas):
    def __init__(
        self,
        master,
        text: str = "",
        *,
        fill: str = COLOR_SURFACE,
        foreground: str = COLOR_TEXT_MUTED,
        border: str = COLOR_BORDER,
        **kwargs,
    ):
        super().__init__(master, height=30, bg=widget_background(master), highlightthickness=0, bd=0, **kwargs)
        self.text = text
        self.fill = fill
        self.foreground = foreground
        self.border = border
        self.bind("<Configure>", lambda _event: self.redraw())
        self.redraw()

    def configure(self, cnf=None, **kwargs):  # type: ignore[override]
        if "text" in kwargs:
            self.text = kwargs.pop("text")
        if "fill" in kwargs:
            self.fill = kwargs.pop("fill")
        if "foreground" in kwargs:
            self.foreground = kwargs.pop("foreground")
        if "border" in kwargs:
            self.border = kwargs.pop("border")
        result = super().configure(cnf, **kwargs)
        self.redraw()
        return result

    config = configure

    def redraw(self) -> None:
        self.delete("all")
        try:
            text_width = font.Font(font=active_font(FONT_CAPTION_SIZE)).measure(self.text)
        except tk.TclError:
            text_width = len(self.text) * 7
        target_width = max(36, text_width + 26)
        try:
            if int(float(self.cget("width"))) != target_width:
                tk.Canvas.configure(self, width=target_width)
        except tk.TclError:
            pass
        width = max(target_width, self.winfo_width(), 24)
        draw_round_rect(self, 1, 1, width - 2, 28, RADIUS_CHIP, fill=self.fill, outline=self.border)
        self.create_text(13, 15, text=self.text, anchor="w", fill=self.foreground, font=active_font(FONT_CAPTION_SIZE))


def make_status_chip(parent: tk.Misc) -> Chip:
    return Chip(
        parent,
        fill=COLOR_SURFACE,
        foreground=COLOR_TEXT_MUTED,
        border=COLOR_BORDER,
    )


def style_text_widget(widget: tk.Text) -> None:
    widget.configure(
        bg=COLOR_SURFACE,
        fg=COLOR_TEXT,
        insertbackground=COLOR_TEXT,
        selectbackground=COLOR_SELECTION,
        selectforeground=COLOR_TEXT,
        relief="flat",
        bd=0,
        highlightbackground=COLOR_INPUT_BORDER,
        highlightcolor=COLOR_FOCUS,
        highlightthickness=1,
        font=active_font(FONT_BODY_SIZE),
        padx=9,
        pady=5,
    )


def style_treeview(tree: ttk.Treeview) -> None:
    tree.configure(style="Treeview")
    tree.tag_configure("even", background=COLOR_SURFACE, foreground=COLOR_TEXT, font=active_font(FONT_TABLE_SIZE))
    tree.tag_configure("odd", background=COLOR_TABLE_ALT, foreground=COLOR_TEXT, font=active_font(FONT_TABLE_SIZE))
    tree.tag_configure("group", background=COLOR_SURFACE_ALT, foreground=COLOR_TEXT, font=active_font(FONT_TABLE_SIZE, "bold"))
    tree.tag_configure("status_success", background=COLOR_SUCCESS_SOFT, foreground=COLOR_TEXT, font=active_font(FONT_TABLE_SIZE))
    tree.tag_configure("status_warning", background=COLOR_WARNING_SOFT, foreground=COLOR_TEXT, font=active_font(FONT_TABLE_SIZE))
    tree.tag_configure("status_danger", background=COLOR_DANGER_SOFT, foreground=COLOR_TEXT, font=active_font(FONT_TABLE_SIZE))
    tree.tag_configure("status_neutral", background=COLOR_SURFACE, foreground=COLOR_TEXT, font=active_font(FONT_TABLE_SIZE))
    tree.tag_configure("cross_highlight", background=COLOR_WARNING_SOFT, foreground=COLOR_TEXT, font=active_font(FONT_TABLE_SIZE, "bold"))
    tree.tag_configure("selected_filter", background=COLOR_SELECTION, foreground=COLOR_TEXT, font=active_font(FONT_TABLE_SIZE, "bold"))


def stripe_treeview(tree: ttk.Treeview) -> None:
    stripe_tags = {"even", "odd"}

    def walk(parent: str = "") -> None:
        for index, item_id in enumerate(tree.get_children(parent)):
            existing = [tag for tag in tree.item(item_id, "tags") if tag not in stripe_tags]
            if "group" in existing:
                tree.item(item_id, tags=tuple(existing))
            else:
                tree.item(item_id, tags=(("odd" if index % 2 else "even"), *existing))
            walk(item_id)

    walk("")


def grid_treeview_with_scrollbars(container: tk.Widget, tree: ttk.Treeview, *, padx: int = 10, pady: int = 10) -> tuple[ttk.Scrollbar, ttk.Scrollbar]:
    container.rowconfigure(0, weight=1)
    container.columnconfigure(0, weight=1)
    vertical = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(container, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky="nsew", padx=(padx, 0), pady=(pady, 0))
    vertical.grid(row=0, column=1, sticky="ns", padx=(0, padx), pady=(pady, 0))
    horizontal.grid(row=1, column=0, sticky="ew", padx=(padx, 0), pady=(0, pady))
    return vertical, horizontal


def draw_icon_badge(canvas: tk.Canvas, color: str, text: str) -> None:
    canvas.delete("all")
    try:
        width = int(float(canvas.cget("width")))
        height = int(float(canvas.cget("height")))
    except tk.TclError:
        width = height = 42
    size = max(min(width, height), 30)
    margin = max(size * 0.14, 4)
    radius = max(size * 0.28, 8)
    draw_round_rect(canvas, margin + 3, margin + 4, size - margin + 3, size - margin + 4, radius, fill=COLOR_SHADOW_2, outline="")
    draw_round_rect(canvas, margin, margin, size - margin, size - margin, radius, fill=COLOR_SURFACE_ALT, outline=COLOR_BORDER)
    draw_round_rect(canvas, margin + 4, margin + 4, size - margin - 4, size - margin - 4, max(radius - 2, 6), fill=color, outline="")
    canvas.create_line(margin + 10, margin + 7, size - margin - 11, margin + 7, fill=COLOR_HIGHLIGHT, width=1)
    canvas.create_text(size / 2, size / 2, text=text, fill=COLOR_TEXT, font=active_font(10, "bold"))


def draw_grid_background(canvas: tk.Canvas, width: int, height: int, fill: str = COLOR_SURFACE) -> None:
    canvas.create_rectangle(0, 0, width, height, fill=fill, outline=COLOR_BORDER)
    for x in range(0, width + 1, 20):
        color_value = COLOR_BORDER if x % 100 == 0 else COLOR_GRID
        canvas.create_line(x, 0, x, height, fill=color_value)
    for y in range(0, height + 1, 20):
        color_value = COLOR_BORDER if y % 100 == 0 else COLOR_GRID
        canvas.create_line(0, y, width, y, fill=color_value)


def draw_soft_bar(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, color: str) -> None:
    if x2 < x1:
        x1, x2 = x2, x1
    height = max(y2 - y1, 6)
    middle = y1 + height / 2
    x2 = max(x2, x1 + 10)
    canvas.create_line(x1, middle + 2, x2, middle + 2, fill=COLOR_SHADOW_2, width=height, capstyle="round")
    canvas.create_line(x1, middle, x2, middle, fill=color, width=height, capstyle="round")
    canvas.create_line(x1 + 4, middle - height / 4, max(x1 + 4, x2 - 10), middle - height / 4, fill=COLOR_HIGHLIGHT, width=1, capstyle="round")


def draw_progress_bar(canvas: tk.Canvas, value: int, total: int, color: str) -> None:
    canvas.delete("all")
    width = max(canvas.winfo_width(), 1)
    y = 4
    canvas.create_line(5, y, width - 5, y, fill=COLOR_PROGRESS_BG, width=6, capstyle="round")
    fill_width = max(5, (width - 10) * value / max(total, 1) + 5)
    canvas.create_line(5, y, fill_width, y, fill=color, width=6, capstyle="round")


def draw_token(canvas: tk.Canvas, color: str) -> None:
    canvas.delete("all")
    draw_round_rect(canvas, 11, 13, 43, 45, 12, fill=COLOR_SHADOW_2, outline="")
    draw_round_rect(canvas, 7, 7, 39, 39, 12, fill=color, outline=COLOR_BORDER)
    canvas.create_line(14, 11, 31, 11, fill=COLOR_HIGHLIGHT, width=2)
