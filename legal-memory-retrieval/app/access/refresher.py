"""Keep compiled access current as time passes (plan 17, P1b).

The ACL is compiled when access data changes, but some changes happen by the clock alone:
a staffing assignment ends, a grant expires. ``acl_refresh_lapsed()`` (migration 20260928c)
recompiles exactly the matters and documents those affect; this runs it at start-up and
every few minutes in a daemon thread.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 600
_started = False
_stop = threading.Event()


def refresh_once() -> int:
    from app.db.connection import connect

    with connect() as conn:
        row = conn.execute("SELECT acl_refresh_lapsed() AS n").fetchone()
        conn.commit()
    n = row["n"] if isinstance(row, dict) else row[0]
    if n:
        log.info("recompiled access for %d matters after lapsed staffing or grants", n)
    return int(n or 0)


def _loop() -> None:
    while not _stop.is_set():
        try:
            refresh_once()
        except Exception:  # a failed pass is retried on the next tick
            log.exception("access refresh failed")
        _stop.wait(INTERVAL_SECONDS)


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    _stop.clear()
    threading.Thread(target=_loop, name="acl-refresh", daemon=True).start()


def stop() -> None:
    _stop.set()
