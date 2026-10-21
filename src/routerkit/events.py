"""Logging setup, the human-readable activity log, and the structured event history.

router-auto-restart.log   one shared text log for every part of the app, tagged with its source
events.jsonl              one JSON object per line: restarts, login tests, outages; the dashboard's
                          uptime bar and "last restart" are computed from it

Passwords never appear in either file: nothing logs them, and SecretFilter redacts them anyway.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import LOGS, ensure_dirs

LOG_FILE = LOGS / "router-auto-restart.log"
EVENTS_FILE = LOGS / "events.jsonl"
MAX_LOG_BYTES = 1_000_000
LOG_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ (\w+) \[([\w-]+)\] (.*)$")


def _rotate(path: Path, limit: int) -> None:
    """Keep one previous generation; skipped if another process has the file open."""
    try:
        if path.exists() and path.stat().st_size > limit:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass


class SecretFilter(logging.Filter):
    """Replaces registered secrets (the router password and its URL-encoded form) in every
    log record, as a safety net: nothing is supposed to log them in the first place."""

    def __init__(self):
        super().__init__()
        self.secrets: set[str] = set()

    def add(self, secret: str | None) -> None:
        if secret and len(secret) >= 3:          # shorter strings would mangle ordinary words
            from urllib.parse import quote, quote_plus
            self.secrets.update({secret, quote_plus(secret), quote(secret, safe="")})

    def redact(self, text: str) -> str:
        for s in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(s, "***")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secrets:
            msg = record.getMessage()
            red = self.redact(msg)
            if red != msg:
                record.msg, record.args = red, ()
            if record.exc_info and not record.exc_text:
                record.exc_text = self.redact(logging.Formatter().formatException(record.exc_info))
            elif record.exc_text:
                record.exc_text = self.redact(record.exc_text)
        return True


REDACT = SecretFilter()


def protect(secret: str | None) -> None:
    """Make sure `secret` never reaches a log line."""
    REDACT.add(secret)


def setup_logging(source: str, console: bool = True) -> None:
    ensure_dirs()
    _rotate(LOG_FILE, MAX_LOG_BYTES)
    _rotate(EVENTS_FILE, 4 * MAX_LOG_BYTES)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if console and sys.stderr is not None:     # pythonw.exe has no console
        handlers.append(logging.StreamHandler())
    for h in handlers:
        h.addFilter(REDACT)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True,
                        format=f"%(asctime)s %(levelname)s [{source}] %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ---------- text log ----------

@dataclass(frozen=True)
class LogLine:
    time: datetime | None
    level: str
    source: str
    message: str


def parse_line(line: str) -> LogLine:
    m = LOG_RE.match(line)
    if not m:
        return LogLine(None, "INFO", "", line)
    return LogLine(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"), m.group(2), m.group(3), m.group(4))


def read_log_tail(n: int = 80, path: Path | None = None, max_bytes: int = 128_000) -> list[LogLine]:
    """Newest first."""
    path = path or LOG_FILE
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = raw.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]                     # first line is probably cut in half
    return [parse_line(x) for x in lines if x.strip()][-n:][::-1]


# ---------- structured events ----------

def record(kind: str, path: Path | None = None, **fields) -> dict:
    path = path or EVENTS_FILE
    ev = {"ts": round(time.time(), 3), "kind": kind, **fields}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, separators=(",", ":")) + "\n")
    except OSError as e:
        logging.getLogger(__name__).warning("could not write event: %s", e)
    return ev


def read_events(since: float | None = None, path: Path | None = None) -> list[dict]:
    """Oldest first. Lines another process is half-way through writing are skipped."""
    path = path or EVENTS_FILE
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and isinstance(ev.get("ts"), (int, float)) and "kind" in ev:
                    if since is None or ev["ts"] >= since:
                        out.append(ev)
    except OSError:
        pass
    return out


def last_reboot(events: list[dict]) -> float | None:
    for ev in reversed(events):
        if ev["kind"] == "reboot" and ev.get("ok"):
            return ev["ts"]
    return None


def outages(events: list[dict], now: float, ongoing_ok: bool = True) -> list[tuple[float, float, bool]]:
    """(start, end, ongoing) for every outage the watchdog reported.

    An outage that was started but never ended counts as ongoing only when `ongoing_ok`
    (the watchdog is running); otherwise it is dropped, since its end is unknown.
    """
    open_: dict[float, float] = {}
    done: list[tuple[float, float, bool]] = []
    for ev in events:
        since = ev.get("since")
        if not isinstance(since, (int, float)):
            continue
        if ev["kind"] == "outage_start":
            open_[since] = since
        elif ev["kind"] == "outage_end":
            open_.pop(since, None)
            until = ev.get("until", ev["ts"])
            if isinstance(until, (int, float)) and until >= since:
                done.append((since, until, False))
    if ongoing_ok and open_:
        start = max(open_)
        done.append((start, now, True))
    return sorted(done)


def uptime_summary(events: list[dict], now: float, window: float = 86400, ongoing_ok: bool = True) -> dict:
    start = now - window
    clipped = []
    for s, e, ongoing in outages(events, now, ongoing_ok):
        s2, e2 = max(s, start), min(e, now)
        if e2 > s2:
            clipped.append((s2, e2, ongoing))
    down = sum(e - s for s, e, _ in clipped)
    reboots = [ev["ts"] for ev in events if ev["kind"] == "reboot" and ev.get("ok") and ev["ts"] >= start]
    return {
        "start": start, "end": now, "outages": clipped, "reboots": reboots,
        "uptime_pct": 100.0 * (1 - down / window) if window > 0 else 100.0,
        "down_seconds": down,
        "longest": max((e - s for s, e, _ in clipped), default=0.0),
        "ongoing": any(o for _, _, o in clipped),
    }
