"""Small pieces of state shared between processes: the skip flag and the dashboard cache."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .config import DATA, ensure_dirs

SKIP_FLAG = DATA / "skip_next.flag"     # set from the dashboard, consumed by the next scheduled run
CACHE = DATA / "dashboard_cache.json"


def skip_is_set() -> bool:
    return SKIP_FLAG.exists()


def set_skip(on: bool) -> None:
    if on:
        ensure_dirs()
        SKIP_FLAG.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    else:
        SKIP_FLAG.unlink(missing_ok=True)


def consume_skip() -> bool:
    """True (and clears the flag) if the next run was marked to be skipped."""
    try:
        SKIP_FLAG.unlink()
        return True
    except FileNotFoundError:
        return False


def write_json_atomic(path: Path, data) -> None:
    ensure_dirs()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load_cache() -> dict:
    try:
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(updates: dict) -> None:
    d = load_cache()
    d.update(updates)
    try:
        write_json_atomic(CACHE, d)
    except OSError:
        pass
