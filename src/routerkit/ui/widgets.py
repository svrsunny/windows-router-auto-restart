"""Canvas-drawn widgets: rounded cards, pill buttons, a progress ring, a latency chart,
a 24-hour uptime bar, and themed dialogs."""
from __future__ import annotations

import math
import re
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable, Sequence

from .theme import PALETTES, Fonts, scale, set_titlebar


class UI:
    """Theme context handed to every widget."""

    def __init__(self, root: tk.Misc, theme: str):
        self.theme = theme
        self.p = PALETTES[theme]
        self.f = Fonts(root)
        self.s = scale(root)

    @property
    def dark(self) -> bool:
        return self.theme == "dark"

    def px(self, n: float) -> int:
        return max(1, round(n * self.s))


def round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw) -> int:
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, splinesteps=16, **kw)


def label(parent, ui: UI, text="", size=10, weight="normal", fg="text", bg=None, **kw) -> tk.Label:
    return tk.Label(parent, text=text, font=ui.f.ui(size, weight), fg=ui.p.get(fg, fg),
                    bg=bg or parent.cget("bg"), **kw)


def caption(parent, ui: UI, text: str) -> tk.Label:
    return label(parent, ui, text.upper(), 8, "bold", "muted")


# ---------- containers ----------

class Card(tk.Frame):
    """Rounded card. Put children in `.body`; the card sizes itself to them like a normal frame.

    The rounded shape is drawn on a canvas placed behind the body (place() does not affect
    the frame's requested size)."""

    def __init__(self, parent, ui: UI, pad=18, radius=14, fill="card"):
        super().__init__(parent, bg=parent.cget("bg"))
        self.ui, self.r, self.fill = ui, ui.px(radius), ui.p[fill]
        self.shape = tk.Canvas(self, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.shape.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=self.fill)
        self.body.pack(fill="both", expand=True, padx=ui.px(pad), pady=ui.px(pad))
        tk.Misc.lower(self.shape, self.body)      # Canvas.lower() means tag_lower, so call the widget one
        self.shape.bind("<Configure>", self._draw)

    def _draw(self, e):
        self.shape.delete("all")
        round_rect(self.shape, 1, 1, e.width - 2, e.height - 2, self.r, fill=self.fill,
                   outline=self.ui.p["border"])


class Button(tk.Canvas):
    """Pill button. kind: primary | danger | secondary | ghost."""

    def __init__(self, parent, ui: UI, text: str, command: Callable[[], None], kind="secondary", small=False):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0, takefocus=1)
        self.ui, self.text, self.command, self.kind = ui, text, command, kind
        self.enabled, self.hover, self.pressed, self.focused = True, False, False, False
        self.font = tkfont.Font(self, font=ui.f.ui(9 if small else 10, "bold"))
        self.padx, self.pady = ui.px(12 if small else 18), ui.px(5 if small else 9)
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, pressed=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(pressed=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Return>", lambda e: self.invoke())
        self.bind("<space>", lambda e: self.invoke())
        self.bind("<FocusIn>", lambda e: self._set(focused=True))
        self.bind("<FocusOut>", lambda e: self._set(focused=False))
        self._draw()

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self._draw()

    def _colors(self):
        p = self.ui.p
        if not self.enabled:
            return p["dis_bg"], p["dis_fg"], p["dis_bg"]
        if self.kind == "primary":
            bg = p["accent_hover"] if self.hover else p["accent"]
            return bg, p["on_accent"], bg
        if self.kind == "danger":
            bg = p["bad_hover"] if self.hover else p["bad"]
            return bg, p["on_bad"], bg
        if self.kind == "ghost":
            bg = p["btn"] if self.hover else self.cget("bg")
            return bg, p["text"] if self.hover else p["muted"], bg
        bg = p["btn_hover"] if self.hover else p["btn"]
        return bg, p["btn_text"], p["border"]

    def _draw(self):
        w = self.font.measure(self.text) + 2 * self.padx
        h = self.font.metrics("linespace") + 2 * self.pady
        self.configure(width=w, height=h, cursor="hand2" if self.enabled else "arrow")
        self.delete("all")
        bg, fg, outline = self._colors()
        round_rect(self, 1, 1, w - 2, h - 2, h / 2, fill=bg, outline=outline)
        if self.focused and self.enabled:
            round_rect(self, 0, 0, w - 1, h - 1, h / 2, fill="", outline=self.ui.p["accent"], width=2)
        dy = 1 if (self.pressed and self.hover and self.enabled) else 0
        self.create_text(w / 2, h / 2 + dy, text=self.text, fill=fg, font=self.font)

    def _release(self, e):
        was = self.pressed
        self._set(pressed=False)
        if was and 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height():
            self.invoke()

    def invoke(self):
        if self.enabled:
            self.command()

    def set_text(self, text: str):
        if text != self.text:
            self.text = text
            self._draw()

    def set_enabled(self, on: bool):
        if on != self.enabled:
            self.enabled = on
            self._draw()


class Dot(tk.Canvas):
    def __init__(self, parent, ui: UI, size=10, color="subtle"):
        d = ui.px(size)
        super().__init__(parent, width=d, height=d, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.ui, self.d, self.color = ui, d, None
        self.set(color)

    def set(self, color: str):
        color = self.ui.p.get(color, color)
        if color != self.color:
            self.color = color
            self.delete("all")
            self.create_oval(1, 1, self.d - 1, self.d - 1, fill=color, outline=color)


class Chip(tk.Canvas):
    """Small rounded status label: a dot and text on a tinted background."""

    def __init__(self, parent, ui: UI):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0, height=1, width=1)
        self.ui = ui
        self.font = tkfont.Font(self, font=ui.f.ui(9, "bold"))
        self.state = None

    def set(self, text: str, color: str, soft: str):
        p = self.ui.p
        state = (text, color, soft)
        if state == self.state:
            return
        self.state = state
        px = self.ui.px
        d = px(8)
        w = px(12) + d + px(7) + self.font.measure(text) + px(12)
        h = self.font.metrics("linespace") + px(8)
        self.configure(width=w, height=h)
        self.delete("all")
        round_rect(self, 0, 0, w - 1, h - 1, h / 2, fill=p.get(soft, soft), outline=p.get(soft, soft))
        x = px(12)
        self.create_oval(x, h / 2 - d / 2, x + d, h / 2 + d / 2, fill=p.get(color, color), outline="")
        self.create_text(x + d + px(7), h / 2, text=text, anchor="w", fill=p.get(color, color), font=self.font)


# ---------- data widgets ----------

class Ring(tk.Canvas):
    def __init__(self, parent, ui: UI, size=150, thickness=11):
        self.size, self.th = ui.px(size), ui.px(thickness)
        super().__init__(parent, width=self.size, height=self.size, bg=parent.cget("bg"),
                         highlightthickness=0, bd=0)
        self.ui, self.state = ui, None

    def set(self, frac: float, color: str, top: str, bottom: str):
        frac = max(0.0, min(1.0, frac))
        state = (round(frac, 3), color, top, bottom)
        if state == self.state:
            return
        self.state = state
        p, s, th = self.ui.p, self.size, self.th
        color = p.get(color, color)
        self.delete("all")
        m = th / 2 + 2
        self.create_oval(m, m, s - m, s - m, outline=p["track"], width=th)
        if frac >= 0.999:
            self.create_oval(m, m, s - m, s - m, outline=color, width=th)
        elif frac > 0.002:
            self.create_arc(m, m, s - m, s - m, start=90, extent=-360 * frac, style="arc", outline=color, width=th)
            r, c = s / 2 - m, s / 2
            for ang in (90, 90 - 360 * frac):           # rounded caps
                x, y = c + r * math.cos(math.radians(ang)), c - r * math.sin(math.radians(ang))
                self.create_oval(x - th / 2, y - th / 2, x + th / 2, y + th / 2, fill=color, outline="")
        c = s / 2
        self.create_text(c, c - self.ui.px(9), text=top, fill=p["text"], font=self.ui.f.big(15, "bold"))
        self.create_text(c, c + self.ui.px(15), text=bottom, fill=p["muted"], font=self.ui.f.ui(9))


NICE = (5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000)


class Sparkline(tk.Canvas):
    """Line chart of recent latency samples; None marks a failed check."""

    def __init__(self, parent, ui: UI, height=110, capacity=120, left_label="", right_label="now"):
        super().__init__(parent, height=ui.px(height), bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.ui, self.capacity = ui, capacity
        self.left_label, self.right_label = left_label, right_label
        self.series: list[tuple[Sequence[float | None], str]] = []
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, series: list[tuple[Sequence[float | None], str]]):
        self.series = series
        self._draw()

    def _draw(self):
        p, px, f = self.ui.p, self.ui.px, self.ui.f
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20:
            return
        self.delete("all")
        left, top, bottom, right = px(44), px(6), h - px(18), w - px(4)
        vals = [v for s, _ in self.series for v in s if v is not None]
        peak = max(vals) * 1.15 if vals else 0
        vmax = next((n for n in NICE if n >= peak), NICE[-1])
        for frac in (0, 0.5, 1):
            y = bottom - (bottom - top) * frac
            self.create_line(left, y, right, y, fill=p["grid"] if frac else p["border"])
            self.create_text(left - px(8), y, text=f"{vmax * frac:g} ms", anchor="e", fill=p["subtle"],
                             font=f.ui(8))
        self.create_text(left, h - px(2), text=self.left_label, anchor="sw", fill=p["subtle"], font=f.ui(8))
        self.create_text(right, h - px(2), text=self.right_label, anchor="se", fill=p["subtle"], font=f.ui(8))
        step = (right - left) / max(1, self.capacity - 1)

        def xy(i, n, v):
            x = right - (n - 1 - i) * step
            return x, bottom - (bottom - top) * min(v, vmax) / vmax

        for values, color in self.series:
            color = p.get(color, color)
            n = len(values)
            run: list[float] = []
            for i, v in enumerate(list(values) + [None]):
                if v is None:
                    if len(run) >= 4:
                        self.create_line(*run, fill=color, width=2, capstyle="round", joinstyle="round")
                    elif len(run) == 2:
                        self.create_oval(run[0] - 2, run[1] - 2, run[0] + 2, run[1] + 2, fill=color, outline="")
                    run = []
                    if i < n:                       # failed check: red tick on the baseline
                        x = right - (n - 1 - i) * step
                        self.create_line(x, bottom - px(5), x, bottom, fill=p["bad"], width=max(2, int(step)))
                else:
                    run.extend(xy(i, n, v))
            if n and values[-1] is not None:
                x, y = xy(n - 1, n, values[-1])
                self.create_oval(x - px(4), y - px(4), x + px(4), y + px(4), fill=p["card"], outline=color, width=2)


class UptimeBar(tk.Canvas):
    def __init__(self, parent, ui: UI):
        super().__init__(parent, height=ui.px(44), bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.ui, self.summary, self.has_data = ui, None, False
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, summary: dict, has_data: bool):
        self.summary, self.has_data = summary, has_data
        self._draw()

    def _draw(self):
        p, px, f = self.ui.p, self.ui.px, self.ui.f
        w = self.winfo_width()
        if w < 20 or not self.summary:
            return
        self.delete("all")
        s = self.summary
        bh, r = px(16), px(5)
        x0, x1 = 1, w - 2
        span = s["end"] - s["start"]
        X = lambda t: x0 + (x1 - x0) * (t - s["start"]) / span  # noqa: E731
        if not self.has_data:
            round_rect(self, x0, 0, x1, bh, r, fill=p["track"], outline=p["track"])
            self.create_text(w / 2, bh / 2, text="no data yet", fill=p["subtle"], font=f.ui(8))
        else:
            round_rect(self, x0, 0, x1, bh, r, fill=p["ok"], outline=p["ok"])
            for a, b, _ in s["outages"]:
                xa, xb = X(a), max(X(a) + px(3), X(b))
                self.create_rectangle(xa, 0, min(xb, x1), bh, fill=p["bad"], outline="")
            for t in s["reboots"]:
                xt = X(t)
                self.create_rectangle(xt - 1, -1, xt + 1, bh + px(4), fill=p["accent"], outline="")
        for frac, text, anchor in ((0, "24h ago", "nw"), (0.5, "12h", "n"), (1, "now", "ne")):
            self.create_text(x0 + (x1 - x0) * frac, bh + px(8), text=text, anchor=anchor,
                             fill=p["subtle"], font=f.ui(8))


# ---------- dialogs ----------

class Dialog(tk.Toplevel):
    """Themed modal dialog. Subclasses fill self.content and call self.finish(result)."""

    def __init__(self, parent: tk.Misc, ui: UI, title: str, heading: str, message: str = "", width=420):
        super().__init__(parent)
        self.ui, self.result = ui, None
        p, px = ui.p, ui.px
        self.withdraw()
        self.title(title)
        self.configure(bg=p["card"])
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", lambda: self.finish(None))
        self.bind("<Escape>", lambda e: self.finish(None))
        wrap = tk.Frame(self, bg=p["card"])
        wrap.pack(fill="both", expand=True, padx=px(26), pady=px(22))
        label(wrap, ui, heading, 14, "bold", anchor="w").pack(fill="x")
        if message:
            label(wrap, ui, message, 10, fg="muted", anchor="w", justify="left",
                  wraplength=px(width)).pack(fill="x", pady=(px(6), 0))
        self.content = tk.Frame(wrap, bg=p["card"])
        self.content.pack(fill="x", pady=(px(14), 0))
        self.buttons = tk.Frame(wrap, bg=p["card"])
        self.buttons.pack(fill="x", pady=(px(18), 0))

    def add_buttons(self, ok_text: str, on_ok: Callable[[], None], kind="primary", cancel_text="Cancel"):
        px = self.ui.px
        ok = Button(self.buttons, self.ui, ok_text, on_ok, kind)
        ok.pack(side="right")
        if cancel_text:
            Button(self.buttons, self.ui, cancel_text, lambda: self.finish(None)).pack(side="right", padx=(0, px(10)))
        self.bind("<Return>", lambda e: on_ok())
        return ok

    def entry(self, caption_text: str, value: str = "", show: str = "", width=18) -> tk.Entry:
        p, px = self.ui.p, self.ui.px
        row = tk.Frame(self.content, bg=p["card"])
        row.pack(fill="x", pady=(0, px(10)))
        label(row, self.ui, caption_text, 10, fg="muted", anchor="w").pack(fill="x")
        e = tk.Entry(row, font=self.ui.f.ui(11), bg=p["entry"], fg=p["text"], insertbackground=p["text"],
                     relief="flat", highlightthickness=1, highlightbackground=p["border"],
                     highlightcolor=p["accent"], width=width, show=show,
                     selectbackground=p["accent"], selectforeground=p["on_accent"])
        e.insert(0, value)
        e.pack(anchor="w", pady=(px(4), 0), ipady=px(5), ipadx=px(6))
        return e

    def error(self, text: str):
        if not hasattr(self, "_err"):
            self._err = label(self.content, self.ui, "", 9, fg="bad", anchor="w", justify="left")
            self._err.pack(fill="x")
        self._err.configure(text=text)

    def finish(self, result):
        self.result = result
        self.grab_release()
        self.destroy()

    def run(self):
        self.update_idletasks()
        top = self.master.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.winfo_reqwidth()) // 2
        y = top.winfo_rooty() + max(0, (top.winfo_height() - self.winfo_reqheight()) // 3)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        set_titlebar(self, self.ui.dark)
        self.lift()
        self.grab_set()
        self.focus_force()
        self.wait_window()
        return self.result


def confirm(parent, ui: UI, title: str, heading: str, message: str, ok_text: str, danger=False) -> bool:
    d = Dialog(parent, ui, title, heading, message)
    d.add_buttons(ok_text, lambda: d.finish(True), "danger" if danger else "primary").focus_set()
    return bool(d.run())


def ask_schedule(parent, ui: UI, at: str, days: int, warn: float):
    """Returns (HH:MM, every_days, warn_minutes) or None."""
    d = Dialog(parent, ui, "Reboot schedule", "Reboot schedule",
               "The router reboots automatically at this time. A countdown window appears first, "
               "so you can postpone or skip.")
    e_at = d.entry("Time (24-hour, HH:MM)", at, width=8)
    e_days = d.entry("Every how many days", str(days), width=8)
    e_warn = d.entry("Countdown before the reboot (minutes, 0 = none)", f"{warn:g}", width=8)

    def ok():
        at_v, days_v, warn_v = e_at.get().strip(), e_days.get().strip(), e_warn.get().strip()
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", at_v):
            return d.error("Time must look like 04:00 or 14:50.")
        h, mnt = at_v.split(":")
        at_v = f"{int(h):02d}:{mnt}"
        if not days_v.isdigit() or not 1 <= int(days_v) <= 365:
            return d.error("Days must be a whole number from 1 to 365.")
        try:
            w = float(warn_v)
        except ValueError:
            w = -1.0
        if not 0 <= w <= 120:                  # also rejects nan
            return d.error("Countdown must be a number of minutes from 0 to 120.")
        d.finish((at_v, int(days_v), w))

    d.add_buttons("Save schedule", ok)
    e_at.focus_set()
    return d.run()


def ask_password(parent, ui: UI, username: str):
    d = Dialog(parent, ui, "Router password", "Router password",
               f"Enter the password for the router's '{username}' account. It is stored in Windows "
               "Credential Manager, encrypted for your Windows account.")
    e = d.entry("Password", show="•", width=26)

    def ok():
        if not e.get():
            return d.error("Enter a password.")
        d.finish(e.get())

    d.add_buttons("Save", ok)
    e.focus_set()
    return d.run()
