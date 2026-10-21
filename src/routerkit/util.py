"""Small formatting helpers shared by the CLI and the UIs."""
from __future__ import annotations

from datetime import datetime, timedelta


def dur(seconds: float) -> str:
    """'1h 05m', '4m 12s', '9s'."""
    s = int(max(0, seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def human(td: timedelta, seconds: bool = False) -> str:
    s = int(max(0, td.total_seconds()))
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m:02d}m" + (f" {s:02d}s" if seconds else "")
    return f"{m}m {s:02d}s" if seconds else f"{m}m"


def ago(td: timedelta) -> str:
    return "just now" if td.total_seconds() < 60 else human(td) + " ago"


def clock(dt: datetime | float) -> str:
    if not isinstance(dt, datetime):
        dt = datetime.fromtimestamp(dt)
    return dt.strftime("%I:%M %p").lstrip("0")


def fmt(dt: datetime) -> str:
    """'Sat 24 Oct, 2:50 PM'."""
    return f"{dt:%a} {dt.day} {dt:%b}, {clock(dt)}"


def fmt_short(dt: datetime) -> str:
    """'24 Oct, 2:50 PM'."""
    return f"{dt.day} {dt:%b}, {clock(dt)}"
