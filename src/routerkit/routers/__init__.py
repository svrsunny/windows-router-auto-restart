"""Router adapters.

Each supported router model has its own module, because routers differ in how they log in
(captchas, tokens, cookies, checksums) and which request restarts them. Nothing here guesses
endpoints: an adapter only implements a flow that was verified on a real device.

To add a model, copy template.py, implement it, register it in ADAPTERS, and document it in
docs/router-compatibility.md.
"""
from __future__ import annotations

from .base import RouterAdapter, RouterError, SessionBusyError
from .gx_gpon import GxGponE4222

ADAPTERS: dict[str, type[RouterAdapter]] = {
    GxGponE4222.model_id: GxGponE4222,
}


def get_adapter(cfg, password: str, session=None) -> RouterAdapter:
    try:
        cls = ADAPTERS[cfg.router_model]
    except KeyError:
        raise RouterError(f"unsupported router_model '{cfg.router_model}'") from None
    return cls(cfg.router_url, cfg.username, password, timeout=cfg.request_timeout, verify=cfg.tls_verify,
               attempts=cfg.login_attempts, retry_delay=cfg.retry_delay, session=session)


__all__ = ["ADAPTERS", "RouterAdapter", "RouterError", "SessionBusyError", "get_adapter"]
