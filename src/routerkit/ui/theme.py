"""Colours, fonts, DPI and title-bar handling."""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)    # crisp text on scaled displays
    except Exception:  # noqa: BLE001
        pass

PALETTES = {
    "light": dict(
        bg="#eef1f6", card="#ffffff", border="#dfe3ea", text="#0f172a", muted="#64748b", subtle="#94a3b8",
        accent="#4f46e5", accent_hover="#4338ca", accent_soft="#e0e7ff", on_accent="#ffffff",
        btn="#eef1f6", btn_hover="#e2e7ef", btn_text="#0f172a", dis_bg="#f3f5f8", dis_fg="#b4bccb",
        ok="#16a34a", ok_soft="#dcfce7", bad="#dc2626", bad_hover="#b91c1c", bad_soft="#fee2e2", on_bad="#ffffff",
        warn="#d97706", warn_soft="#fef3c7", track="#e8ebf1", grid="#eef1f5", series2="#0891b2",
        log_bg="#f8fafc", log_fg="#334155", log_muted="#94a3b8", entry="#f8fafc",
    ),
    "dark": dict(
        bg="#0b0e14", card="#141923", border="#232a37", text="#e6e9ef", muted="#8b94a7", subtle="#5c6577",
        accent="#6366f1", accent_hover="#7c7ff5", accent_soft="#1f1d4a", on_accent="#ffffff",
        btn="#1c2230", btn_hover="#262e3f", btn_text="#e6e9ef", dis_bg="#161b25", dis_fg="#4b5466",
        ok="#34d399", ok_soft="#0f2e24", bad="#f87171", bad_hover="#fb8b8b", bad_soft="#3a1717", on_bad="#2a0b0b",
        warn="#fbbf24", warn_soft="#3a2a0a", track="#222938", grid="#1a202c", series2="#22d3ee",
        log_bg="#0f131b", log_fg="#c3cad8", log_muted="#5c6577", entry="#0f131b",
    ),
}


def system_theme() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
    except Exception:  # noqa: BLE001
        return "dark"


def resolve_theme(choice: str) -> str:
    return choice if choice in PALETTES else system_theme()


class Fonts:
    """Picks the best installed Segoe / Cascadia families once a Tk root exists."""

    def __init__(self, root: tk.Misc):
        fams = set(tkfont.families(root))
        pick = lambda *names: next((n for n in names if n in fams), "TkDefaultFont")  # noqa: E731
        self.text = pick("Segoe UI Variable Text", "Segoe UI", "Helvetica")
        self.display = pick("Segoe UI Variable Display", "Segoe UI", "Helvetica")
        self.mono = pick("Cascadia Mono", "Consolas", "Courier New")

    def ui(self, size: int, weight: str = "normal") -> tuple:
        return (self.text, size, weight)

    def big(self, size: int, weight: str = "bold") -> tuple:
        return (self.display, size, weight)

    def code(self, size: int = 9) -> tuple:
        return (self.mono, size)


def scale(root: tk.Misc) -> float:
    return root.winfo_fpixels("1i") / 96.0


def _colorref(hex_color: str) -> int:
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return r | (g << 8) | (b << 16)


def set_titlebar(win: tk.Misc, dark: bool) -> None:
    """Match the title bar to the window: dark/light mode, and on Windows 11 the caption
    colours themselves (this also wins over "show accent colour on title bars")."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):       # DWMWA_USE_IMMERSIVE_DARK_MODE (new id, then pre-20H1 id)
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), 4) == 0:
                break
        pal = PALETTES["dark" if dark else "light"]
        for attr, color in ((35, win.cget("bg")), (36, pal["text"])):   # DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR
            if isinstance(color, str) and color.startswith("#") and len(color) == 7:
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(ctypes.c_int(_colorref(color))), 4)
    except Exception:  # noqa: BLE001
        pass


def set_icon(root: tk.Tk, path) -> None:
    if path.exists():
        try:
            root.iconbitmap(default=str(path))
        except tk.TclError:
            pass
