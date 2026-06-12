"""t.statistics.stas.bot — Travian map.sql collector & analyzer."""

import sys as _sys

__version__ = "1.1.2"


def _force_utf8_stdio() -> None:
    """Reconfigure stdio to UTF-8 so non-ASCII names + box-drawing chars work on Windows."""
    for stream in (_sys.stdout, _sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if callable(reconfig):
            try:
                reconfig(encoding="utf-8", errors="replace")
            except Exception:
                pass


_force_utf8_stdio()
