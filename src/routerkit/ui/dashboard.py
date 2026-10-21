"""Dashboard: schedule countdown, connection status, latency chart, 24-hour uptime and activity."""
from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime, timedelta

from .. import actions, credentials, events, net, scheduler, state, watchdog
from ..config import CLI, ICON, LOGS, ROOT, Config, ensure_dirs
from ..routers import ADAPTERS
from ..util import ago, clock, dur, fmt, fmt_short, human
from .theme import resolve_theme, set_icon, set_titlebar
from .widgets import (UI, Button, Card, Chip, Dot, Ring, Sparkline, UptimeBar, ask_password, ask_schedule,
                      caption, confirm, label, round_rect)

log = logging.getLogger(__name__)

SAMPLE_EVERY = 3.0          # seconds between connection checks
FAST_EVERY = 1.0            # while following a reboot
SAMPLES = 120               # 6 minutes of history in the latency chart
APP_ID = "RouterAutoRestart.Dashboard"   # must match the shortcut made by scripts/New-Shortcut.ps1


class App:
    def __init__(self, root: tk.Tk, cfg: Config):
        self.root, self.cfg = root, cfg
        cache = state.load_cache()
        self.theme = cache.get("theme") if cache.get("theme") in ("light", "dark") else resolve_theme(cfg.theme)
        self.q: queue.Queue = queue.Queue()
        self.fast_wake, self.slow_wake, self.ip_wake = threading.Event(), threading.Event(), threading.Event()
        self.fast_until = 0.0
        self.gen = 0                # bumped after every action so stale task polls are ignored
        self.busy = False
        self.fresh = False
        self.last_ip = cache.get("ip")
        self.m = {
            "task": None, "log": [], "events": [], "router_ms": None, "internet_ms": None,
            "router": None, "internet": None, "skip": state.skip_is_set(), "ip": cache.get("ip"),
            "watchdog": None, "pw_source": credentials.get_password()[1],
        }
        self.r_samples: deque = deque(maxlen=SAMPLES)
        self.i_samples: deque = deque(maxlen=SAMPLES)
        self._status_job = None
        self._log_shown = None

        root.title("Router Control")
        set_icon(root, ICON)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.ui = UI(root, self.theme)
        px = self.ui.px
        w, h = min(px(1040), sw - px(40)), min(px(860), sh - px(90))
        root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        root.minsize(min(px(920), sw - px(40)), min(px(720), sh - px(90)))
        root.bind("<F5>", lambda e: self.refresh())
        self.build()
        for target in (self.fast_loop, self.slow_loop, self.ip_loop):
            threading.Thread(target=target, daemon=True, name=target.__name__).start()
        root.after(100, self.drain)
        root.after(1000, self.tick)

    # ---------- layout ----------
    def build(self):
        if self._status_job:
            self.root.after_cancel(self._status_job)
            self._status_job = None
        for child in self.root.winfo_children():
            child.destroy()
        ui = self.ui = UI(self.root, self.theme)
        p, px = ui.p, ui.px
        gap = px(14)
        self.root.configure(bg=p["bg"])
        self.root.after(30, lambda: set_titlebar(self.root, ui.dark))

        outer = tk.Frame(self.root, bg=p["bg"])
        outer.pack(fill="both", expand=True, padx=px(26), pady=px(20))

        # header
        head = tk.Frame(outer, bg=p["bg"])
        head.pack(fill="x")
        logo = tk.Canvas(head, width=px(40), height=px(40), bg=p["bg"], highlightthickness=0)
        logo.pack(side="left")
        self._draw_logo(logo, px(40))
        titles = tk.Frame(head, bg=p["bg"])
        titles.pack(side="left", padx=(px(12), 0))
        label(titles, ui, "Router Control", 17, "bold", anchor="w").pack(fill="x")
        self.lbl_sub = label(titles, ui, "", 9, fg="muted", anchor="w")
        self.lbl_sub.pack(fill="x")
        self.b_theme = Button(head, ui, "Light mode" if ui.dark else "Dark mode", self.toggle_theme, "ghost", True)
        self.b_theme.pack(side="right")
        self.chip = Chip(head, ui)
        self.chip.pack(side="right", padx=(0, px(10)))

        grid = tk.Frame(outer, bg=p["bg"])
        grid.pack(fill="x", pady=(px(18), 0))
        grid.columnconfigure(0, weight=3, uniform="col")
        grid.columnconfigure(1, weight=2, uniform="col")

        # hero: next reboot
        hero = Card(grid, ui, pad=22)
        hero.grid(row=0, column=0, sticky="nsew", padx=(0, gap // 2), pady=(0, gap))
        hb = hero.body
        self.ring = Ring(hb, ui, size=150)
        self.ring.pack(side="left", anchor="n")
        col = tk.Frame(hb, bg=p["card"])
        col.pack(side="left", fill="both", expand=True, padx=(px(24), 0))
        caption(col, ui, "Next reboot").pack(anchor="w")
        self.lbl_count = tk.Label(col, text="…", font=ui.f.big(30, "bold"), bg=p["card"], fg=p["text"],
                                  anchor="w")
        self.lbl_count.pack(fill="x", pady=(px(2), 0))
        self.lbl_detail = label(col, ui, "", 10, fg="muted", anchor="w", justify="left", wraplength=px(330))
        self.lbl_detail.pack(fill="x")
        self.lbl_detail2 = label(col, ui, "", 9, fg="subtle", anchor="w", justify="left", wraplength=px(330))
        self.lbl_detail2.pack(fill="x", pady=(px(2), 0))
        hrow = tk.Frame(col, bg=p["card"])
        hrow.pack(fill="x", pady=(px(12), 0))
        self.b_sched = Button(hrow, ui, "Edit schedule", self.edit_schedule, "secondary", True)
        self.b_sched.pack(side="left")
        self.skip_chip = Chip(hrow, ui)

        # connection
        conn = Card(grid, ui, pad=20)
        conn.grid(row=0, column=1, sticky="nsew", padx=(gap // 2, 0), pady=(0, gap))
        caption(conn.body, ui, "Connection").pack(anchor="w", pady=(0, px(6)))
        self.rows = {}
        for key, name in (("router", "Router"), ("internet", "Internet"), ("ip", "Public IP"),
                          ("watchdog", "Watchdog"), ("password", "Password")):
            self.rows[key] = self._conn_row(conn.body, name)
        self.b_copy = Button(self.rows["ip"]["frame"], ui, "Copy", self.copy_ip, "ghost", True)
        self.b_wd = Button(self.rows["watchdog"]["frame"], ui, "Start", self.start_watchdog, "ghost", True)
        self.b_pw = Button(self.rows["password"]["frame"], ui, "Change", self.change_password, "ghost", True)

        # latency
        lat = Card(grid, ui, pad=20)
        lat.grid(row=1, column=0, sticky="nsew", padx=(0, gap // 2))
        lh = tk.Frame(lat.body, bg=p["card"])
        lh.pack(fill="x")
        caption(lh, ui, "Latency").pack(side="left")
        self.leg_i = label(lh, ui, "", 9, "bold", fg="muted")
        self.leg_i.pack(side="right")
        Dot(lh, ui, 9, "series2").pack(side="right", padx=(px(14), px(6)))
        self.leg_r = label(lh, ui, "", 9, "bold", fg="muted")
        self.leg_r.pack(side="right")
        Dot(lh, ui, 9, "accent").pack(side="right", padx=(0, px(6)))
        self.spark = Sparkline(lat.body, ui, height=118, capacity=SAMPLES,
                               left_label=f"{dur(SAMPLES * SAMPLE_EVERY)} ago")
        self.spark.pack(fill="x", pady=(px(10), 0))

        # uptime
        up = Card(grid, ui, pad=20)
        up.grid(row=1, column=1, sticky="nsew", padx=(gap // 2, 0))
        caption(up.body, ui, "Last 24 hours").pack(anchor="w")
        urow = tk.Frame(up.body, bg=p["card"])
        urow.pack(fill="x", pady=(px(4), 0))
        self.lbl_pct = tk.Label(urow, text="…", font=ui.f.big(24, "bold"), bg=p["card"], fg=p["text"])
        self.lbl_pct.pack(side="left")
        label(urow, ui, "uptime", 10, fg="muted").pack(side="left", padx=(px(8), 0), pady=(px(10), 0))
        self.lbl_out = label(up.body, ui, "", 9, fg="muted", anchor="w", justify="left", wraplength=px(300))
        self.lbl_out.pack(fill="x")
        self.lbl_rb = label(up.body, ui, "", 9, fg="muted", anchor="w", justify="left", wraplength=px(300))
        self.lbl_rb.pack(fill="x", pady=(0, px(10)))
        self.bar = UptimeBar(up.body, ui)
        self.bar.pack(fill="x")

        # actions
        bar = tk.Frame(outer, bg=p["bg"])
        bar.pack(fill="x", pady=(gap + px(4), 0))
        self.b_reboot = Button(bar, ui, "Reboot now", self.reboot_now, "danger")
        self.b_test = Button(bar, ui, "Test login", self.test_login)
        self.b_skip = Button(bar, ui, "Skip next run", self.toggle_skip)
        self.b_pause = Button(bar, ui, "Pause schedule", self.toggle_pause)
        for b in (self.b_reboot, self.b_test, self.b_skip, self.b_pause):
            b.pack(side="left", padx=(0, px(10)))
        self.b_refresh = Button(bar, ui, "Refresh", self.refresh, "ghost")
        self.b_refresh.pack(side="right")
        Button(bar, ui, "Open logs", self.open_logs, "ghost").pack(side="right", padx=(0, px(4)))

        srow = tk.Frame(outer, bg=p["bg"])
        srow.pack(fill="x", pady=(px(10), px(8)))
        self.status_dot = Dot(srow, ui, 8, p["bg"])
        self.status_dot.pack(side="left", padx=(px(4), px(8)))
        self.lbl_status = label(srow, ui, "", 10, fg="muted", anchor="w", justify="left", wraplength=px(860))
        self.lbl_status.pack(side="left", fill="x", expand=True)

        # activity
        act = Card(outer, ui, pad=18, fill="log_bg")
        act.pack(fill="both", expand=True)
        ab = act.body
        label(ab, ui, "RECENT ACTIVITY", 8, "bold", "log_muted", bg=p["log_bg"], anchor="w").pack(fill="x")
        self.text = tk.Text(ab, bg=p["log_bg"], fg=p["log_fg"], font=ui.f.code(9), relief="flat", bd=0,
                            highlightthickness=0, wrap="none", height=4, state="disabled", padx=0,
                            pady=px(6), insertwidth=0, cursor="arrow", spacing1=px(2), spacing3=px(2),
                            selectbackground=p["accent"], selectforeground=p["on_accent"])
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("time", foreground=p["log_muted"])
        self.text.tag_configure("src", foreground=p["accent"])
        self.text.tag_configure("WARNING", foreground=p["warn"])
        self.text.tag_configure("ERROR", foreground=p["bad"])

        self._log_shown = None
        self.render_all()

    def _draw_logo(self, c: tk.Canvas, s: int):
        p, px = self.ui.p, self.ui.px
        round_rect(c, 0, 0, s - 1, s - 1, px(11), fill=p["accent"], outline=p["accent"])
        cx, cy = s / 2, s * 0.64
        for r in (px(13), px(8.5)):
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=45, extent=90, style="arc",
                         outline=p["on_accent"], width=px(2.4))
        d = px(2.6)
        c.create_oval(cx - d, cy - d, cx + d, cy + d, fill=p["on_accent"], outline="")

    def _conn_row(self, parent, name: str) -> dict:
        p, px, ui = self.ui.p, self.ui.px, self.ui
        f = tk.Frame(parent, bg=p["card"])
        f.pack(fill="x", pady=px(5))
        label(f, ui, name, 10, fg="muted", width=10, anchor="w").pack(side="left")
        dot = Dot(f, ui, 9)
        dot.pack(side="left", padx=(0, px(8)))
        val = label(f, ui, "…", 10, "bold", anchor="w")
        val.pack(side="left")
        extra = label(f, ui, "", 9, fg="subtle", anchor="e")
        extra.pack(side="right")
        return {"frame": f, "dot": dot, "val": val, "extra": extra}

    # ---------- background polling ----------
    def fast_loop(self):
        while True:
            try:
                pr = net.probe(self.cfg)
                self.q.put({"kind": "fast", "probe": pr, "log": events.read_log_tail(80),
                            "events": events.read_events(since=time.time() - 25 * 3600),
                            "skip": state.skip_is_set(), "watchdog": watchdog.is_running()})
            except Exception:  # noqa: BLE001
                log.exception("status poll failed")
            self.fast_wake.wait(FAST_EVERY if time.time() < self.fast_until else SAMPLE_EVERY)
            self.fast_wake.clear()

    def slow_loop(self):
        while True:
            gen = self.gen
            self.q.put({"kind": "slow", "gen": gen, "task": scheduler.query_task(self.cfg.task_name)})
            self.slow_wake.wait(20)
            self.slow_wake.clear()

    def ip_loop(self):
        while True:
            if self.m.get("internet") is False:          # no point asking while offline
                self.ip_wake.wait(5)
                self.ip_wake.clear()
                continue
            ip = net.fetch_public_ip()
            self.q.put({"kind": "ip", "ip": ip})
            self.ip_wake.wait(300 if ip else 15)        # re-check every 5 min; retry soon if it failed
            self.ip_wake.clear()

    def refresh(self):
        self.fast_wake.set()
        self.slow_wake.set()

    def drain(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg["kind"]
                if kind == "fast":
                    pr = msg["probe"]
                    if pr.internet_up and self.m["internet"] is False:
                        self.m["ip"] = None                # connection came back: the address may have changed
                        self.ip_wake.set()
                    self.m.update(router=pr.router_up, internet=pr.internet_up, router_ms=pr.router_ms,
                                  internet_ms=pr.internet_ms, log=msg["log"], events=msg["events"],
                                  skip=msg["skip"], watchdog=msg["watchdog"])
                    self.r_samples.append(pr.router_ms)
                    self.i_samples.append(pr.internet_ms)
                    self.render_all()
                elif kind == "slow":
                    if self.busy or msg["gen"] != self.gen:
                        continue                           # an action is in flight or finished since
                    self.m["task"] = msg["task"]
                    self.fresh = True
                    self.render_all()
                elif kind == "ip":
                    ip = msg["ip"]
                    if ip:
                        if self.last_ip and ip != self.last_ip:
                            self.set_status(f"Public IP changed: {self.last_ip} → {ip}", "ok")
                        self.last_ip = self.m["ip"] = ip
                        state.save_cache({"ip": ip})
                        self.render_conn()
                elif kind == "progress":
                    self.set_status(msg["text"], "info")
                elif kind == "done":
                    self.finish_action(msg)
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def tick(self):
        self.render_hero()
        self.render_uptime()
        self.root.after(1000, self.tick)

    # ---------- rendering ----------
    def render_all(self):
        self.render_header()
        self.render_hero()
        self.render_conn()
        self.render_latency()
        self.render_uptime()
        self.render_buttons()
        self.render_log()

    def _task(self):
        t = self.m["task"]
        return t if t and "error" not in t and not t.get("missing") else None

    def render_header(self):
        t = self.m["task"]
        model = ADAPTERS[self.cfg.router_model].display_name if self.cfg.router_model in ADAPTERS else "Router"
        sub = f"{model}  ·  {self.cfg.router_host}  ·  task ‘{self.cfg.task_name}’"
        self.lbl_sub.configure(text=sub + ("" if self.fresh else "  ·  updating…"))
        if t is None:
            self.chip.set("Loading", "muted", "btn")
        elif "error" in t:
            self.chip.set("Error", "bad", "bad_soft")
        elif t.get("missing"):
            self.chip.set("No schedule", "muted", "btn")
        elif t["state"] == "Disabled":
            self.chip.set("Paused", "warn", "warn_soft")
        elif t["state"] == "Running":
            self.chip.set("Running", "accent", "accent_soft")
        else:
            self.chip.set("Active", "ok", "ok_soft")

    def render_hero(self):
        p, t = self.ui.p, self.m["task"]
        detail2, sched_text, sched_kind = "", "Edit schedule", "secondary"
        if t is None:
            big, col, detail = "…", "muted", "Reading the schedule…"
            self.ring.set(0, "accent", "…", "")
        elif "error" in t:
            big, col, detail = "Unavailable", "bad", f"Could not read the task: {t['error']}"
            self.ring.set(0, "bad", "!", "error")
        elif t.get("missing"):
            big, col = "Not set up", "text"
            detail = "No automatic reboot is scheduled yet. Set one up to reboot the router every few days."
            sched_text, sched_kind = "Set up schedule", "primary"
            self.ring.set(0, "accent", "—", "no schedule")
        else:
            if t.get("days") and t.get("at"):
                every = "every day" if t["days"] == 1 else f"every {t['days']} days"
                detail2 = f"Runs {every} at {clock(datetime.strptime(t['at'], '%H:%M'))}"
            if t.get("last"):
                detail2 += ("  ·  " if detail2 else "") + \
                    f"last run {fmt_short(t['last'])}: {scheduler.result_text(t['result'])}"
            if t["state"] == "Disabled":
                big, col, detail = "Paused", "warn", "No automatic reboots until you resume the schedule."
                self.ring.set(1, "warn", "‖", "paused")
            elif t["state"] == "Running":
                big, col, detail = "Running now", "accent", "The countdown window is open or the reboot is in progress."
                self.ring.set(1, "accent", "now", "running")
            elif not t["next"]:
                big, col, detail = "—", "muted", "No next run is scheduled."
                self.ring.set(0, "muted", "—", "")
            else:
                left = (t["next"] - datetime.now()).total_seconds()
                big = human(timedelta(seconds=left), seconds=True) if left > 0 else "due now"
                col = "text"
                warn = t.get("warn") if t.get("warn") is not None else self.cfg.warn_minutes
                if warn:
                    boom = clock(t["next"] + timedelta(minutes=warn))
                    detail = f"{fmt(t['next'])}  ·  countdown first, reboot around {boom}"
                else:
                    detail = f"{fmt(t['next'])}  ·  reboots without a countdown"
                if t.get("days"):
                    period = t["days"] * 86400
                elif t.get("last"):
                    period = (t["next"] - t["last"]).total_seconds()
                else:
                    period = 0
                frac = 1 - left / period if period > 0 else 0
                skip = self.m["skip"]
                self.ring.set(frac, "warn" if skip else "accent", clock(t["next"]),
                              f"{t['next']:%a} {t['next'].day} {t['next']:%b}")
        self.lbl_count.configure(text=big, fg=p[col])
        self.lbl_detail.configure(text=detail, fg=p["bad"] if t and "error" in t else p["muted"])
        self.lbl_detail2.configure(text=detail2)
        self.b_sched.set_text(sched_text)
        if self.b_sched.kind != sched_kind:
            self.b_sched.kind = sched_kind
            self.b_sched._draw()
        show_skip = bool(self.m["skip"] and self._task() and self._task()["state"] != "Disabled")
        if show_skip:
            self.skip_chip.set("Next run will be skipped", "warn", "warn_soft")
            if not self.skip_chip.winfo_ismapped():
                self.skip_chip.pack(side="left", padx=(self.ui.px(10), 0))
        elif self.skip_chip.winfo_ismapped():
            self.skip_chip.pack_forget()

    def render_conn(self):
        m, rows = self.m, self.rows
        for key, up, ms, sub in (("router", m["router"], m["router_ms"], self.cfg.router_host),
                                 ("internet", m["internet"], m["internet_ms"], "")):
            r = rows[key]
            if up is None:
                r["dot"].set("subtle")
                r["val"].configure(text="Checking…")
                r["extra"].configure(text=sub)
            else:
                r["dot"].set("ok" if up else "bad")
                r["val"].configure(text="Online" if up else "Offline")
                r["extra"].configure(text=f"{ms:.0f} ms" if up and ms is not None else sub)
        r = rows["ip"]
        ip_ok = bool(m["ip"] and m["internet"])
        r["dot"].set("accent" if ip_ok else "subtle")
        if m["internet"] is False:
            r["val"].configure(text="No connection")
        else:
            r["val"].configure(text=m["ip"] or "Checking…")
        self._toggle(self.b_copy, ip_ok)
        r = rows["watchdog"]
        wd = m["watchdog"]
        r["dot"].set("subtle" if wd is None else ("ok" if wd else "warn"))
        r["val"].configure(text="…" if wd is None else ("Running" if wd else "Not running"))
        self._toggle(self.b_wd, wd is False)
        r = rows["password"]
        src = m["pw_source"]
        r["dot"].set("bad" if src == "not set" else "ok")
        r["val"].configure(text="Not set" if src == "not set" else "Saved")
        r["extra"].configure(text="" if src == "not set" else src)
        self.b_pw.set_text("Set" if src == "not set" else "Change")
        self._toggle(self.b_pw, True)

    def _toggle(self, btn: Button, show: bool):
        if show and not btn.winfo_ismapped():
            btn.pack(side="right", padx=(self.ui.px(8), 0))
        elif not show and btn.winfo_ismapped():
            btn.pack_forget()

    def render_latency(self):
        self.spark.set([(list(self.r_samples), "accent"), (list(self.i_samples), "series2")])
        m = self.m
        fmt_ms = lambda up, ms: "…" if up is None else (f"{ms:.0f} ms" if up and ms is not None else "down")  # noqa: E731
        self.leg_r.configure(text=f"Router {fmt_ms(m['router'], m['router_ms'])}")
        self.leg_i.configure(text=f"Internet {fmt_ms(m['internet'], m['internet_ms'])}")

    def render_uptime(self):
        p, evs, now = self.ui.p, self.m["events"], time.time()
        has_data = any(e["kind"].startswith("outage") for e in evs) or bool(self.m["watchdog"])
        s = events.uptime_summary(evs, now, ongoing_ok=bool(self.m["watchdog"]))
        self.bar.set(s, has_data)
        if not has_data:
            self.lbl_pct.configure(text="—", fg=p["muted"])
            self.lbl_out.configure(text="Start the watchdog to record outages.", fg=p["warn"])
        else:
            pct = s["uptime_pct"]
            self.lbl_pct.configure(text=f"{pct:.2f}%" if pct < 100 else "100%",
                                   fg=p["ok"] if pct >= 99.5 else p["warn"] if pct >= 97 else p["bad"])
            n = len(s["outages"])
            if s["ongoing"]:
                start = s["outages"][-1][0]
                text, col = f"Internet down right now, since {clock(start)} ({dur(now - start)})", p["bad"]
            elif n:
                text = f"{n} outage{'s' if n > 1 else ''}  ·  {dur(s['down_seconds'])} total  ·  " \
                       f"longest {dur(s['longest'])}"
                col = p["muted"]
            else:
                text, col = "No internet outages recorded", p["muted"]
            if not self.m["watchdog"]:
                text += "  ·  watchdog not running"
            self.lbl_out.configure(text=text, fg=col)
        lr = events.last_reboot(evs)
        if lr:
            rec = next((e for e in reversed(evs) if e["kind"] == "reboot_recovered" and e["ts"] >= lr), None)
            text = f"Last reboot {ago(timedelta(seconds=now - lr))}"
            if rec and rec.get("internet_s"):
                text += f"  ·  online again after {dur(rec['internet_s'])}"
            elif rec and rec.get("router_s"):
                text += f"  ·  router back after {dur(rec['router_s'])}"
            self.lbl_rb.configure(text=text)
        else:
            self.lbl_rb.configure(text="No reboots in the last 24 hours")

    def render_buttons(self):
        t = self._task()
        paused = bool(t and t["state"] == "Disabled")
        self.b_skip.set_text("Undo skip" if self.m["skip"] else "Skip next run")
        self.b_pause.set_text("Resume schedule" if paused else "Pause schedule")
        for b in (self.b_reboot, self.b_test, self.b_refresh, self.b_sched):
            b.set_enabled(not self.busy)
        self.b_pause.set_enabled(not self.busy and t is not None)
        self.b_skip.set_enabled(not self.busy and t is not None and not paused)

    def render_log(self):
        shown = [(x.time, x.level, x.source, x.message) for x in self.m["log"]]
        if shown == self._log_shown:
            return
        self._log_shown = shown
        tx = self.text
        top = tx.yview()[0]
        tx.configure(state="normal")
        tx.delete("1.0", "end")
        if not shown:
            tx.insert("end", "Nothing yet. Actions and watchdog alerts will show up here.", "time")
        for dt, lvl, src, msg in shown:
            tx.insert("end", (f"{dt:%d %b  %H:%M:%S}" if dt else " " * 16) + "   ", "time")
            tx.insert("end", f"{src:<9} " if src else " " * 10, "src")
            tx.insert("end", msg + "\n", lvl if lvl in ("WARNING", "ERROR") else ())
        tx.configure(state="disabled")
        tx.yview_moveto(top)

    def set_status(self, msg: str, kind: str = "info"):
        p = self.ui.p
        col = {"info": p["accent"], "ok": p["ok"], "bad": p["bad"], "warn": p["warn"]}[kind]
        self.lbl_status.configure(text=msg, fg=p["text"] if kind == "info" else col)
        self.status_dot.set(col)
        if self._status_job:
            self.root.after_cancel(self._status_job)
            self._status_job = None
        if kind != "info":
            self._status_job = self.root.after(10000, self.clear_status)

    def clear_status(self):
        self._status_job = None
        self.lbl_status.configure(text="")
        self.status_dot.set(self.ui.p["bg"])

    # ---------- actions ----------
    def run_bg(self, working: str, fn, ok: str, fail: str, on_ok=None, on_fail=None):
        """fn returns 0 on success, 2 for 'no password', anything else for failure."""
        if self.busy:
            return
        self.busy = True
        self.set_status(working, "info")
        self.render_buttons()

        def worker():
            err = ""
            try:
                rc = fn()
            except Exception as e:  # noqa: BLE001
                rc, err = -1, str(e)
            self.q.put({"kind": "done", "rc": rc, "ok": ok, "fail": fail, "on_ok": on_ok, "on_fail": on_fail,
                        "err": err})

        threading.Thread(target=worker, daemon=True, name="action").start()

    def finish_action(self, msg):
        self.busy = False
        self.gen += 1
        rc = msg["rc"]
        if isinstance(rc, tuple):                   # scheduler calls return (ok, error text)
            rc, err = (0, "") if rc[0] else (1, rc[1])
            msg["err"] = msg["err"] or err
        if rc == 0:
            self.set_status(msg["ok"], "ok")
            if msg["on_ok"]:
                msg["on_ok"]()
        elif rc == actions.NO_PASSWORD:
            self.set_status("The router password isn't set yet.", "bad")
            self.root.after(50, self.change_password)
        elif rc == actions.NOT_VERIFIED:
            self.set_status("Restart request sent, but recovery wasn't confirmed – see the activity log.", "warn")
        elif rc == actions.BLOCKED:
            self.set_status("Restart refused: one is already running or the router was just restarted "
                            f"(cooldown {self.cfg.reboot_cooldown_minutes:g} min).", "warn")
        else:
            self.set_status(msg["fail"] + (f" ({msg['err']})" if msg["err"] else ""), "bad")
            if msg["on_fail"]:
                msg["on_fail"]()
        self.render_all()
        self.refresh()

    def progress(self, text: str):
        self.q.put({"kind": "progress", "text": text})        # called from the worker thread

    def reboot_now(self):
        if not confirm(self.root, self.ui, "Reboot router", "Reboot the router now?",
                       "It restarts immediately and your internet drops for a few minutes. "
                       "The dashboard will follow it until it is back.", "Reboot now", danger=True):
            return
        self.fast_until = time.time() + self.cfg.reboot_wait_seconds + 240   # 1 s checks while it restarts
        self.run_bg("Starting reboot…", lambda: actions.run_reboot(self.cfg, wait=True, progress=self.progress),
                    "Reboot finished – timings are in the activity log.", "Reboot failed – see the activity log.")

    def test_login(self):
        self.run_bg("Testing login…", lambda: actions.run_reboot(self.cfg, dry_run=True),
                    "Login works (dry run, nothing rebooted).", "Login failed – see the activity log.")

    def toggle_skip(self):
        on = not state.skip_is_set()
        state.set_skip(on)
        self.m["skip"] = state.skip_is_set()
        log.info("next scheduled run will be skipped" if on else "skip removed")
        self.set_status("The next scheduled run will be skipped; the one after it stays on schedule." if on
                        else "Skip removed – the next scheduled run will go ahead.", "ok")
        self.render_all()

    def toggle_pause(self):
        t = self._task()
        if not t:
            return
        paused = t["state"] == "Disabled"
        old_state = t["state"]
        t["state"] = "Ready" if paused else "Disabled"      # optimistic; reverted if it fails
        self.render_all()

        def revert():
            t["state"] = old_state

        name = self.cfg.task_name
        self.run_bg("Updating schedule…", lambda: scheduler.set_enabled(name, paused),
                    "Schedule resumed." if paused else "Schedule paused – no automatic reboots until you resume it.",
                    "Could not change the schedule.", on_fail=revert)

    def edit_schedule(self):
        t = self._task()
        at = (t or {}).get("at") or self.cfg.restart_time
        days = (t or {}).get("days") or self.cfg.interval_days
        warn = (t or {}).get("warn")
        res = ask_schedule(self.root, self.ui, at, days, self.cfg.warn_minutes if warn is None else warn)
        if not res:
            return
        at, days, warn = res
        name = self.cfg.task_name
        every = "every day" if days == 1 else f"every {days} days"
        self.run_bg("Saving schedule…", lambda: scheduler.install_reboot_task(name, at, days, warn),
                    f"Schedule saved: {every} at {at}.", "Could not save the schedule.")

    def change_password(self):
        pw = ask_password(self.root, self.ui, self.cfg.username)
        if not pw:
            return
        try:
            credentials.vault_write(pw, self.cfg.username)
        except (OSError, ValueError) as e:
            self.set_status(f"Could not save the password: {e}", "bad")
            return
        self.m["pw_source"] = credentials.get_password()[1]
        if self.m["pw_source"] == "environment":
            self.set_status("Saved. Note: ROUTER_PASS in this process's environment still takes priority.", "warn")
        else:
            self.set_status("Password saved to Windows Credential Manager.", "ok")
        log.info("router password updated in Credential Manager")
        self.render_conn()

    def start_watchdog(self):
        try:
            subprocess.Popen([scheduler.pythonw(), str(CLI), "watchdog"], cwd=str(ROOT),
                             creationflags=scheduler.NO_WINDOW)
            self.set_status("Watchdog started.", "ok")
        except OSError as e:
            self.set_status(f"Could not start the watchdog: {e}", "bad")
        self.root.after(1500, self.fast_wake.set)

    def copy_ip(self):
        ip = self.m.get("ip")
        if ip:
            self.root.clipboard_clear()
            self.root.clipboard_append(ip)
            self.set_status(f"Copied {ip} to the clipboard.", "ok")

    def open_logs(self):
        ensure_dirs()
        try:
            os.startfile(str(LOGS))  # type: ignore[attr-defined]
        except (OSError, AttributeError) as e:
            self.set_status(f"Could not open {LOGS}: {e}", "bad")

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        state.save_cache({"theme": self.theme})
        self.build()


def set_app_id(app_id: str = APP_ID) -> None:
    """Give the window its own taskbar identity (instead of pythonw.exe's), so it groups with
    the pinned shortcut created by scripts/New-Shortcut.ps1."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:  # noqa: BLE001
            pass


def run(cfg: Config) -> int:
    set_app_id()
    root = tk.Tk()
    App(root, cfg)
    root.mainloop()
    return 0
