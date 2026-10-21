"""Paths and settings.

Settings are read from config/config.json (created by scripts/Configure.ps1; never committed),
then the environment variables ROUTER_URL / ROUTER_USER override the address and username.
There is deliberately no built-in router address: every installation configures its own.

Set ROUTER_AUTO_RESTART_HOME to keep config/, data/ and logs/ somewhere other than the
repository folder (the tests use this).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent.parent          # repository root
HOME = Path(os.environ.get("ROUTER_AUTO_RESTART_HOME") or ROOT)
CONFIG_FILE = HOME / "config" / "config.json"
DATA = HOME / "data"
LOGS = HOME / "logs"
ICON = ROOT / "assets" / "router-auto-restart.ico"
CLI = ROOT / "src" / "routerctl.py"
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

log = logging.getLogger(__name__)


class ConfigError(Exception):
    """The configuration is missing or invalid; the message says how to fix it."""


@dataclass
class Config:
    router_url: str = ""                       # e.g. http://192.0.2.1 (documentation address)
    router_model: str = ""                     # adapter id, see routerkit.routers.ADAPTERS
    username: str = "admin"
    restart_time: str = "04:00"                # HH:MM, local time
    interval_days: int = 3
    warn_minutes: float = 10                   # countdown window before a scheduled restart (0 = none)
    postpone_minutes: list = field(default_factory=lambda: [30, 60])
    task_name: str = "RouterAutoRestart"
    watchdog_task_name: str = "RouterAutoRestart-Watchdog"
    request_timeout: float = 10                # seconds per HTTP request
    login_attempts: int = 3
    retry_delay: float = 5                     # seconds between login attempts
    reboot_cooldown_minutes: float = 10        # refuse a second restart this soon after one succeeded
    reboot_wait_seconds: int = 300             # how long to follow the router through its restart
    tls_ca_bundle: str = ""                    # for https routers with their own CA; TLS is never disabled
    probe_targets: list = field(default_factory=lambda: [["1.1.1.1", 443], ["8.8.8.8", 443], ["9.9.9.9", 443]])
    dns_check_host: str = "example.com"
    theme: str = "system"                      # system | light | dark

    @property
    def router_host(self) -> str:
        return urlparse(self.router_url).hostname or ""

    @property
    def router_port(self) -> int:
        u = urlparse(self.router_url)
        return u.port or (443 if u.scheme == "https" else 80)

    @property
    def targets(self) -> list[tuple[str, int]]:
        return [(str(h), int(p)) for h, p in self.probe_targets]

    @property
    def tls_verify(self):
        """Value for requests' `verify=`: a CA bundle path, or True. Never False."""
        return self.tls_ca_bundle or True


def _num(v, lo, hi, integer=False) -> bool:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    if integer and not isinstance(v, int):
        return False
    return lo <= v <= hi


def _url_ok(v) -> bool:
    if not isinstance(v, str):
        return False
    u = urlparse(v)
    try:
        u.port
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.hostname) and "@" not in u.netloc   # no user:pass@ in URLs


VALIDATORS = {
    "router_url": _url_ok,
    "router_model": lambda v: isinstance(v, str) and bool(v.strip()),
    "username": lambda v: isinstance(v, str) and bool(v.strip()),
    "restart_time": lambda v: isinstance(v, str) and bool(TIME_RE.match(v)),
    "interval_days": lambda v: _num(v, 1, 365, integer=True),
    "warn_minutes": lambda v: _num(v, 0, 120),
    "postpone_minutes": lambda v: isinstance(v, list) and all(_num(x, 1, 24 * 60) for x in v),
    "task_name": lambda v: isinstance(v, str) and bool(re.fullmatch(r"[\w .-]{1,100}", v)),
    "watchdog_task_name": lambda v: isinstance(v, str) and bool(re.fullmatch(r"[\w .-]{1,100}", v)),
    "request_timeout": lambda v: _num(v, 1, 120),
    "login_attempts": lambda v: _num(v, 1, 10, integer=True),
    "retry_delay": lambda v: _num(v, 0, 120),
    "reboot_cooldown_minutes": lambda v: _num(v, 0, 24 * 60),
    "reboot_wait_seconds": lambda v: _num(v, 0, 1800, integer=True),
    "tls_ca_bundle": lambda v: isinstance(v, str),
    "probe_targets": lambda v: isinstance(v, list) and len(v) > 0 and all(
        isinstance(t, list) and len(t) == 2 and isinstance(t[0], str) and _num(t[1], 1, 65535, True) for t in v),
    "dns_check_host": lambda v: isinstance(v, str) and bool(v.strip()),
    "theme": lambda v: v in ("system", "light", "dark"),
}


def parse_config(data: dict) -> tuple[Config, list[str]]:
    """Build a Config from a dict; returns (config, list of problems)."""
    cfg, problems = Config(), []
    known = {f.name for f in fields(Config)}
    if not isinstance(data, dict):
        return cfg, ["the file must contain a JSON object"]
    for key, value in data.items():
        if key.startswith("_"):
            continue                              # comments
        if key not in known:
            problems.append(f"unknown setting '{key}'")
        elif not VALIDATORS[key](value):
            problems.append(f"invalid value for '{key}'")
        else:
            setattr(cfg, key, value)
    env_url, env_user = os.environ.get("ROUTER_URL"), os.environ.get("ROUTER_USER")
    if env_url:
        if _url_ok(env_url):
            cfg.router_url = env_url
        else:
            problems.append("ROUTER_URL environment variable is not a valid http(s) URL")
    if env_user and env_user.strip():
        cfg.username = env_user
    cfg.router_url = cfg.router_url.rstrip("/")
    if not cfg.router_url:
        problems.append("'router_url' is not set")
    if not cfg.router_model:
        problems.append("'router_model' is not set")
    else:
        from .routers import ADAPTERS
        if cfg.router_model not in ADAPTERS:
            problems.append(f"router_model '{cfg.router_model}' is not supported "
                            f"(supported: {', '.join(sorted(ADAPTERS))})")
    if cfg.tls_ca_bundle and not Path(cfg.tls_ca_bundle).is_file():
        problems.append("'tls_ca_bundle' does not point to an existing file")
    return cfg, problems


def load_config(path: Path | None = None, strict: bool = True) -> Config:
    """Load and validate. With strict=True any problem raises ConfigError."""
    path = path or CONFIG_FILE
    if not path.exists():
        if strict:
            raise ConfigError(f"No configuration found at {path}.\n"
                              "Run  .\\scripts\\Configure.ps1  to create it.")
        data = {}
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))     # tolerate a BOM from PowerShell 5.1
        except (OSError, ValueError) as e:
            raise ConfigError(f"Could not read {path}: {e}") from e
    cfg, problems = parse_config(data)
    if problems and strict:
        raise ConfigError(f"Problems in {path}:\n  - " + "\n  - ".join(problems) +
                          "\nFix the file or run  .\\scripts\\Configure.ps1  again.")
    for p in problems:
        log.warning("config: %s", p)
    return cfg


def ensure_dirs() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
