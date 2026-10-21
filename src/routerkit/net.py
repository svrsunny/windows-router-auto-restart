"""Reachability and latency checks (TCP connect, no admin rights needed)."""
from __future__ import annotations

import ipaddress
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests

from .config import DATA, Config

FORCE_DOWN = DATA / "force_down.flag"     # test hook: while it exists the internet counts as down
IP_SERVICES = ("https://checkip.amazonaws.com", "https://api.ipify.org", "https://icanhazip.com")

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="probe")


def tcp_ping(host: str, port: int, timeout: float = 1.5) -> float | None:
    """Milliseconds to open a TCP connection, or None if it failed."""
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout):
            return (time.perf_counter() - t0) * 1000
    except OSError:
        return None


@dataclass
class Probe:
    router_ms: float | None
    internet_ms: float | None

    @property
    def router_up(self) -> bool:
        return self.router_ms is not None

    @property
    def internet_up(self) -> bool:
        return self.internet_ms is not None


def probe(cfg: Config, router_timeout: float = 1.5, internet_timeout: float = 2.0) -> Probe:
    """Internet counts as down only when every target fails."""
    router = _pool.submit(tcp_ping, cfg.router_host, cfg.router_port, router_timeout)
    targets = [_pool.submit(tcp_ping, h, p, internet_timeout) for h, p in cfg.targets]
    ok = [ms for ms in (f.result() for f in targets) if ms is not None]
    internet = min(ok) if ok else None
    if FORCE_DOWN.exists():
        internet = None
    return Probe(router.result(), internet)


def router_up(cfg: Config, timeout: float = 1.5) -> bool:
    return tcp_ping(cfg.router_host, cfg.router_port, timeout) is not None


def fetch_public_ip(timeout: float = 4) -> str | None:
    """Ask an IP-echo service for our public address; returns a validated IP string or None."""
    for url in IP_SERVICES:
        try:
            return str(ipaddress.ip_address(requests.get(url, timeout=timeout).text.strip()))
        except (requests.RequestException, ValueError):
            continue
    return None
