"""Watchdog decision logic: no UI and no network, so it is easy to test."""
from __future__ import annotations

from typing import Callable

FAILS_NEEDED = 3            # consecutive failed checks before alerting (~10-15 s)
REBOOT_GRACE = 5 * 60       # stay quiet this long after a router reboot we sent
ROUTER_GRACE = 5 * 60       # ... or after the router was last seen unreachable (e.g. power cut)
RESUME_GRACE = 60           # ... or after this PC wakes from sleep
RESUME_GAP = 30             # a gap this long between checks means the PC slept


class Monitor:
    """Turns a stream of (router_up, internet_up) checks into events:

    ("alert", outage_start)              internet down while the router answers
    ("recovered", outage_start, now)     internet back after an alert
    ("reset", outage_start, last_check)  the PC slept during an alerted outage
    """

    def __init__(self, fails_needed=FAILS_NEEDED, reboot_grace=REBOOT_GRACE, router_grace=ROUTER_GRACE,
                 resume_grace=RESUME_GRACE, resume_gap=RESUME_GAP):
        self.fails_needed, self.reboot_grace = fails_needed, reboot_grace
        self.router_grace, self.resume_grace, self.resume_gap = router_grace, resume_grace, resume_gap
        self.fails = 0
        self.outage_start: float | None = None
        self.alerted = False
        self.router_last_down: float | None = None
        self.resume_until = 0.0
        self.last_step: float | None = None

    def in_grace(self, now: float, last_reboot: float | None) -> bool:
        if now < self.resume_until:
            return True
        if self.router_last_down is not None and now - self.router_last_down < self.router_grace:
            return True
        return bool(last_reboot and now - last_reboot < self.reboot_grace)

    def step(self, now: float, router_up: bool, internet_up: bool,
             last_reboot_fn: Callable[[], float | None] | None = None) -> list[tuple]:
        events: list[tuple] = []
        lr = last_reboot_fn() if last_reboot_fn else None
        if self.last_step is not None and now - self.last_step > self.resume_gap:
            # Big gap between checks: the PC slept. Start fresh instead of reporting a bogus
            # "down for 9 hours", and stay quiet while Wi-Fi and the link come back up.
            self.resume_until = now + self.resume_grace
            if self.alerted:
                events.append(("reset", self.outage_start, self.last_step))
            self.fails, self.outage_start, self.alerted = 0, None, False
        self.last_step = now
        if not router_up and now >= self.resume_until:   # the PC's own Wi-Fi coming back is not a router outage
            # router downtime right after a reboot we sent is already covered by reboot_grace,
            # so it must not stretch the quiet period past it
            explained = lr is not None and 0 <= now - lr < self.reboot_grace + 600
            if not explained:
                self.router_last_down = now
        if internet_up:
            if self.alerted:
                events.append(("recovered", self.outage_start, now))
            self.fails, self.outage_start, self.alerted = 0, None, False
            return events
        if self.fails == 0:
            self.outage_start = now
        self.fails += 1
        # alert only when the router itself answers (otherwise it is rebooting / this PC is off the LAN)
        if self.fails >= self.fails_needed and router_up and not self.alerted and not self.in_grace(now, lr):
            self.alerted = True
            events.append(("alert", self.outage_start))
        return events
