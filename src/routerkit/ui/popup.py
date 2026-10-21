"""Corner pop-up the watchdog shows when the internet goes down and comes back."""
from __future__ import annotations

import time
import tkinter as tk
from typing import Callable

from ..util import clock, dur
from .theme import set_titlebar
from .widgets import UI, Button, label

REMIND_MS = 10 * 60 * 1000
BACK_CLOSE_MS = 12_000


def beep(kind: str) -> None:
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONHAND if kind == "down" else winsound.MB_OK)
    except Exception:  # noqa: BLE001
        pass


class Popup:
    def __init__(self, root: tk.Tk, ui: UI, open_dashboard: Callable[[], None] | None = None,
                 remind_ms=REMIND_MS, back_close_ms=BACK_CLOSE_MS):
        self.root, self.ui = root, ui
        self.remind_ms, self.back_close_ms = remind_ms, back_close_ms
        self.mode: str | None = None
        self.since: float | None = None
        self._remind_job = self._close_job = None
        p, px = ui.p, ui.px

        w = self.win = tk.Toplevel(root)
        w.withdraw()
        w.title("Internet watchdog")
        w.configure(bg=p["card"])
        w.resizable(False, False)
        w.attributes("-topmost", True)
        w.protocol("WM_DELETE_WINDOW", self.dismiss)
        self.strip = tk.Frame(w, bg=p["bad"], width=px(5))
        self.strip.pack(side="left", fill="y")
        inner = tk.Frame(w, bg=p["card"])
        inner.pack(side="left", fill="both", expand=True, padx=px(22), pady=px(18))
        self.lbl_title = label(inner, ui, "", 15, "bold", anchor="w")
        self.lbl_title.pack(fill="x")
        self.lbl_body = label(inner, ui, "", 10, fg="muted", anchor="w", justify="left", wraplength=px(360))
        self.lbl_body.pack(fill="x", pady=(px(6), px(2)))
        self.lbl_time = label(inner, ui, "", 11, "bold", anchor="w")
        self.lbl_time.pack(fill="x", pady=(px(6), px(16)))
        row = tk.Frame(inner, bg=p["card"])
        row.pack(fill="x")
        self.b_dismiss = Button(row, ui, "Dismiss", self.dismiss, "primary")
        self.b_remind = Button(row, ui, "Remind me in 10 min", self.remind)
        self.b_ok = Button(row, ui, "OK", self.dismiss, "primary")
        self.b_dash = Button(row, ui, "Dashboard", open_dashboard or (lambda: None), "ghost")
        self.has_dash = open_dashboard is not None
        self._tick()

    def _cancel_jobs(self):
        for j in (self._remind_job, self._close_job):
            if j:
                self.root.after_cancel(j)
        self._remind_job = self._close_job = None

    def _place(self):
        w, px = self.win, self.ui.px
        w.update_idletasks()
        x = w.winfo_screenwidth() - w.winfo_reqwidth() - px(24)
        w.geometry(f"+{max(0, x)}+{px(56)}")
        w.deiconify()
        w.attributes("-topmost", True)
        w.lift()
        w.after(40, lambda: set_titlebar(w, self.ui.dark))

    def _buttons(self, *btns):
        for b in (self.b_dismiss, self.b_remind, self.b_ok, self.b_dash):
            b.pack_forget()
        for b in btns:
            b.pack(side="left", padx=(0, self.ui.px(10)))
        if self.has_dash:
            self.b_dash.pack(side="right")

    def show_down(self, since: float):
        p = self.ui.p
        self._cancel_jobs()
        self.mode, self.since = "down", since
        self.strip.configure(bg=p["bad"])
        self.lbl_title.configure(text="●  No internet", fg=p["bad"])
        self.lbl_body.configure(text="Your router is reachable, but the internet isn't responding. "
                                     "This is usually your ISP or the fiber line.")
        self._buttons(self.b_dismiss, self.b_remind)
        self._update_time()
        self._place()
        beep("down")

    def show_back(self, since: float, end: float):
        p = self.ui.p
        self._cancel_jobs()
        self.mode, self.since = "back", since
        self.strip.configure(bg=p["ok"])
        self.lbl_title.configure(text="●  Internet is back", fg=p["ok"])
        self.lbl_body.configure(text="The connection has been restored.")
        self.lbl_time.configure(text=f"Down for {dur(end - since)}  ({clock(since)} – {clock(end)})")
        self._buttons(self.b_ok)
        self._place()
        beep("back")
        self._close_job = self.root.after(self.back_close_ms, self.dismiss)

    def _update_time(self):
        if self.mode == "down" and self.since is not None:
            self.lbl_time.configure(text=f"Down since {clock(self.since)}  ·  {dur(time.time() - self.since)}")

    def _tick(self):
        self._update_time()
        self.root.after(1000, self._tick)

    def reset(self):
        self._cancel_jobs()
        self.win.withdraw()
        self.mode = None

    def dismiss(self):
        self._cancel_jobs()
        self.win.withdraw()
        if self.mode == "back":
            self.mode = None

    def remind(self):
        self._cancel_jobs()
        self.win.withdraw()
        self._remind_job = self.root.after(self.remind_ms, self._remind_fire)

    def _remind_fire(self):
        self._remind_job = None
        if self.mode == "down":
            self._place()
            beep("down")
