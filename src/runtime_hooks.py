"""Lightweight hooks for cross-module notifications (e.g. after map.sql ingest)."""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

_after_fetch: list[Callable[[], None]] = []


def register_after_fetch(fn: Callable[[], None]) -> None:
    _after_fetch.append(fn)


def notify_after_fetch() -> None:
    for fn in _after_fetch:
        try:
            fn()
        except Exception:
            log.exception("after_fetch hook failed")
