"""Wi-Fi clients window: devices grouped by SSID, with Block / Unblock for the SSIDs the router can
block on. Router work runs on a background thread; results come back through root.after()."""
from __future__ import annotations

import threading
import tkinter as tk

from .. import actions
from ..config import Config
from .theme import set_titlebar
from .widgets import UI, Button, Card, Chip, confirm, label

VIEW_ONLY = "This router can't block devices on this network."


class ClientsWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, ui: UI, cfg: Config, on_close=None):
        super().__init__(parent)
        self.ui, self.cfg, self.on_close = ui, cfg, on_close
        self.busy = False
        self.buttons: list[Button] = []
        p, px = ui.p, ui.px
        self.title("Wi-Fi clients")
        self.configure(bg=p["bg"])
        self.geometry(f"{px(640)}x{px(700)}")
        self.minsize(px(520), px(420))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<F5>", lambda e: self.refresh())
        self.bind("<Escape>", lambda e: self.close())
        self.after(30, lambda: set_titlebar(self, ui.dark))

        head = tk.Frame(self, bg=p["bg"])
        head.pack(fill="x", padx=px(22), pady=(px(18), px(6)))
        label(head, ui, "Wi-Fi clients", 15, "bold", anchor="w").pack(side="left")
        self.b_refresh = Button(head, ui, "Refresh", self.refresh, "ghost", True)
        self.b_refresh.pack(side="right")
        self.lbl_status = label(self, ui, "", 9, fg="muted", anchor="w", justify="left", wraplength=px(580))
        self.lbl_status.pack(fill="x", padx=px(24))
        label(self, ui, "Block cuts the device's internet access; it stays connected to Wi-Fi. The router's "
                        "clock decides when its all-day rule runs, so expect about a minute a day without the block.",
              9, fg="subtle", anchor="w", justify="left", wraplength=px(580)).pack(fill="x", padx=px(24),
                                                                                  pady=(px(2), px(8)))

        # scrollable list
        wrap = tk.Frame(self, bg=p["bg"])
        wrap.pack(fill="both", expand=True, padx=(px(16), px(4)), pady=(0, px(14)))
        self.canvas = tk.Canvas(wrap, bg=p["bg"], highlightthickness=0, bd=0)
        bar = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.list = tk.Frame(self.canvas, bg=p["bg"])
        self._win = self.canvas.create_window(0, 0, window=self.list, anchor="nw")
        self.list.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.refresh()

    # ---------- background work ----------
    def _run(self, working: str, fn, done):
        if self.busy:
            return
        self.busy = True
        self._set_enabled(False)
        self.status(working, "muted")

        def worker():
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001
                res = (actions.FAILED, str(e))
            self.after(0, lambda: self._finish(res, done))

        threading.Thread(target=worker, daemon=True, name="clients").start()

    def _finish(self, res, done):
        if not self.winfo_exists():
            return
        self.busy = False
        self._set_enabled(True)
        done(*res)

    def _set_enabled(self, on: bool):
        self.b_refresh.set_enabled(on)
        for b in self.buttons:
            b.set_enabled(on)

    def status(self, text: str, color: str = "muted"):
        self.lbl_status.configure(text=text, fg=self.ui.p[color])

    def refresh(self):
        self._run("Reading the router…", lambda: actions.list_clients(self.cfg), self._show)

    def _show(self, rc, res):
        if rc != actions.OK:
            self.status(f"Could not read the router: {res}", "bad")
            return
        n = sum(max(s.reported, len(s.clients)) for s in res.ssids) + len(res.unknown)
        self.status(f"{n} device{'s' if n != 1 else ''} on Wi-Fi.", "muted")
        self.render(res)

    def toggle(self, client, block: bool):
        who = client.name or client.mac
        if block:
            ok = confirm(self, self.ui, "Block device", f"Block {who}?",
                         f"{client.mac} loses internet access until you unblock it. It stays on Wi-Fi.",
                         "Block", danger=True)
        else:
            ok = confirm(self, self.ui, "Unblock device", f"Unblock {who}?",
                         f"{client.mac} gets its internet access back.", "Unblock")
        if not ok:
            return

        def done(rc, err):
            if rc == actions.OK:
                self.status(f"{who}: internet {'blocked' if block else 'unblocked'}. Refreshing…", "ok")
                self.refresh()
            else:
                self.status(f"{'Block' if block else 'Unblock'} failed: {err}", "bad")

        self._run(f"{'Blocking' if block else 'Unblocking'} {who}…",
                  lambda: actions.set_blocked(self.cfg, client.mac, block), done)

    # ---------- rendering ----------
    def render(self, res):
        for child in self.list.winfo_children():
            child.destroy()
        self.buttons = []
        for s in res.ssids:
            self._section(f"{s.name}  ·  {s.band}", s.clients, s.can_block, "" if s.can_block else VIEW_ONLY,
                          s.reported - len(s.clients))
        if res.unknown:
            self._section("On Wi-Fi, network not known", res.unknown, False,
                          "The router didn't say which network these are on, so they can't be blocked here.")
        if res.blocked_offline:
            self._section("Blocked, not connected now", res.blocked_offline, True, "")
        self.canvas.yview_moveto(0)

    def _section(self, title: str, clients, can_block: bool, note: str, hidden: int = 0):
        """hidden: devices the router counts on this SSID but doesn't list."""
        ui, p, px = self.ui, self.ui.p, self.ui.px
        card = Card(self.list, ui, pad=16)
        card.pack(fill="x", pady=(0, px(12)), padx=(0, px(8)))
        b = card.body
        label(b, ui, f"{title}  ·  {len(clients) + max(hidden, 0)}", 11, "bold", anchor="w").pack(fill="x")
        if note:
            label(b, ui, note, 9, fg="subtle", anchor="w", justify="left", wraplength=px(520)).pack(fill="x")
        if hidden > 0:
            label(b, ui, f"The router reports {hidden} device{'s' if hidden > 1 else ''} here that it doesn't "
                         "list by name (fixed IP address, or an address it didn't hand out).", 10, fg="muted",
                  anchor="w", justify="left", wraplength=px(520)).pack(fill="x", pady=(px(6), 0))
        elif not clients:
            label(b, ui, "No devices.", 10, fg="muted", anchor="w").pack(fill="x", pady=(px(6), 0))
        for c in clients:
            row = tk.Frame(b, bg=p["card"])
            row.pack(fill="x", pady=(px(8), 0))
            text = tk.Frame(row, bg=p["card"])
            text.pack(side="left", fill="x", expand=True)
            label(text, ui, c.name or "(no name)", 10, "bold", anchor="w").pack(fill="x")
            detail = "  ·  ".join(x for x in (c.mac, c.ip, f"{c.rssi} dBm" if c.rssi else "") if x)
            label(text, ui, detail, 9, fg="muted", anchor="w").pack(fill="x")
            if can_block or c.blocked:
                btn = Button(row, ui, "Unblock" if c.blocked else "Block",
                             lambda c=c: self.toggle(c, not c.blocked), "secondary" if c.blocked else "danger", True)
                btn.pack(side="right")
                self.buttons.append(btn)
            if c.blocked:
                chip = Chip(row, ui)
                chip.set("Blocked", "bad", "bad_soft")
                chip.pack(side="right", padx=(0, px(8)))

    def close(self):
        if self.on_close:
            self.on_close()
        self.destroy()
