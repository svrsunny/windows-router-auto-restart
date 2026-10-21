"""Countdown window shown before a scheduled reboot."""
from __future__ import annotations

import logging
import time
import tkinter as tk
from datetime import datetime

from ..config import ICON
from ..util import clock
from .theme import resolve_theme, set_icon, set_titlebar
from .widgets import UI, Button, Ring, label

log = logging.getLogger(__name__)


def confirm_reboot(theme: str = "system", warn_secs: float = 600, postpone_secs=(1800, 3600),
                   reshow_before: float = 300) -> str:
    """Returns 'reboot' or 'skip'.

    Buttons: Reboot now, Postpone 30 min, Postpone 1 hour, Skip this time.
    Closing the window counts as skip. Ignoring it reboots when the countdown ends.
    After a postpone the window hides and comes back `reshow_before` seconds before the new time.
    """
    if warn_secs <= 0:
        return "reboot"
    result = {"choice": "reboot"}
    state = {"deadline": time.time() + warn_secs, "hidden": False, "after": None}

    root = tk.Tk()
    root.withdraw()
    ui = UI(root, resolve_theme(theme))
    p, px = ui.p, ui.px
    set_icon(root, ICON)
    root.title("Router reboot")
    root.configure(bg=p["card"])
    root.resizable(False, False)
    root.attributes("-topmost", True)

    wrap = tk.Frame(root, bg=p["card"])
    wrap.pack(padx=px(28), pady=px(24))
    top = tk.Frame(wrap, bg=p["card"])
    top.pack(fill="x")
    ring = Ring(top, ui, size=118, thickness=9)
    ring.pack(side="left")
    text = tk.Frame(top, bg=p["card"])
    text.pack(side="left", fill="both", expand=True, padx=(px(22), 0))
    label(text, ui, "SCHEDULED REBOOT", 8, "bold", "muted", anchor="w").pack(fill="x")
    title = label(text, ui, "", 16, "bold", anchor="w")
    title.pack(fill="x", pady=(px(4), 0))
    label(text, ui, "Your internet will drop for a few minutes while the router restarts.", 10, fg="muted",
          anchor="w", justify="left", wraplength=px(330)).pack(fill="x", pady=(px(6), 0))
    row = tk.Frame(wrap, bg=p["card"])
    row.pack(fill="x", pady=(px(22), 0))

    def finish(choice: str) -> None:
        result["choice"] = choice
        if state["after"] is not None:
            root.after_cancel(state["after"])
        root.destroy()

    def postpone(secs: float) -> None:
        state["deadline"] += secs
        state["hidden"] = True
        root.withdraw()
        log.info("reboot postponed by %d min (now due %s)", secs // 60, clock(state["deadline"]))

    def show() -> None:
        state["hidden"] = False
        root.deiconify()
        root.attributes("-topmost", True)
        root.lift()
        root.bell()

    def tick() -> None:
        left = state["deadline"] - time.time()
        if left <= 0:
            finish("reboot")
            return
        if state["hidden"]:
            if left <= reshow_before:
                show()
        else:
            m, s = divmod(int(left + 0.999), 60)
            at = datetime.fromtimestamp(state["deadline"])
            title.configure(text=f"Rebooting at {clock(at)}")
            ring.set(left / warn_secs if left <= warn_secs else 1.0, "warn" if left > 60 else "bad",
                     f"{m:02d}:{s:02d}", "remaining")
        state["after"] = root.after(250, tick)

    Button(row, ui, "Reboot now", lambda: finish("reboot"), "danger").pack(side="left")
    for secs in postpone_secs:
        txt = f"Postpone {int(secs // 3600)} h" if secs % 3600 == 0 else f"Postpone {int(secs // 60)} min"
        Button(row, ui, txt, lambda secs=secs: postpone(secs)).pack(side="left", padx=(px(10), 0))
    Button(row, ui, "Skip this time", lambda: finish("skip"), "ghost").pack(side="right")
    root.protocol("WM_DELETE_WINDOW", lambda: finish("skip"))

    tick()
    root.update_idletasks()
    root.geometry(f"+{(root.winfo_screenwidth() - root.winfo_reqwidth()) // 2}+{root.winfo_screenheight() // 4}")
    root.deiconify()
    set_titlebar(root, ui.dark)
    root.lift()
    root.bell()
    root.mainloop()
    return result["choice"]
