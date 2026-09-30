# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scheduler: one pass at start, then one a day at ``[schedule] run_at``.

Per-unit cadence is the run's business (:func:`bunker.run.due`); the
scheduler only decides when a pass happens. A pass that raises is logged
and the schedule carries on: a publisher that is down on Tuesday must not
stop Wednesday's run.
"""

from __future__ import annotations

import sys
import threading
import traceback
from collections.abc import Callable
from datetime import datetime, time, timedelta

__all__ = ["loop", "next_run"]


def next_run(now: datetime, run_at: time) -> datetime:
    """The first *run_at* strictly after *now*, in *now*'s time zone."""
    today = now.replace(hour=run_at.hour, minute=run_at.minute, second=0, microsecond=0)
    return today if today > now else today + timedelta(days=1)


def _local_now() -> datetime:
    return datetime.now().astimezone()


def loop(
    run_at: time,
    stop: threading.Event,
    run_once: Callable[[], object],
    *,
    clock: Callable[[], datetime] = _local_now,
    wait: Callable[[float], bool] | None = None,
) -> None:
    """Run *run_once* now, then at every *run_at*, until *stop* is set.

    *wait(seconds)* returns True when the loop should stop; by default it
    is ``stop.wait``, so a SIGTERM ends the sleep at once."""
    sleep = wait if wait is not None else stop.wait
    while not stop.is_set():
        try:
            run_once()
        except Exception:  # keep scheduling; the traceback is the container's log
            traceback.print_exc(file=sys.stderr)
        if stop.is_set():
            break
        now = clock()
        seconds = (next_run(now, run_at) - now).total_seconds()
        if sleep(seconds):
            break
