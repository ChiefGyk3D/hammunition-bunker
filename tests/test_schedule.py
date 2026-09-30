# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import threading
from datetime import UTC, datetime, time

from bunker import schedule


def at(h: int, m: int, day: int = 29) -> datetime:
    return datetime(2026, 9, day, h, m, tzinfo=UTC)


def test_next_run_later_today() -> None:
    assert schedule.next_run(at(1, 0), time(3, 0)) == at(3, 0)


def test_next_run_tomorrow_once_passed() -> None:
    assert schedule.next_run(at(3, 0), time(3, 0)) == at(3, 0, 30)
    assert schedule.next_run(at(23, 59), time(3, 0)) == at(3, 0, 30)


class FakeTime:
    def __init__(self, stop: threading.Event, runs_before_stop: int) -> None:
        self.now = at(1, 0)
        self.stop = stop
        self.waits: list[float] = []
        self.left = runs_before_stop

    def clock(self) -> datetime:
        return self.now

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        self.now = self.now.replace(hour=3) if self.now.hour < 3 else self.now
        return self.stop.is_set()


def test_the_loop_runs_at_start_then_on_the_hour() -> None:
    stop = threading.Event()
    runs: list[datetime] = []
    fake = FakeTime(stop, 2)

    def run_once() -> None:
        runs.append(fake.now)
        if len(runs) == 2:
            stop.set()

    schedule.loop(time(3, 0), stop, run_once, clock=fake.clock, wait=fake.wait)
    assert runs == [at(1, 0), at(3, 0)]
    assert fake.waits == [2 * 3600.0]


def test_a_stop_during_the_wait_runs_nothing_more() -> None:
    stop = threading.Event()
    runs: list[int] = []

    def wait(seconds: float) -> bool:
        stop.set()
        return True

    schedule.loop(time(3, 0), stop, lambda: runs.append(1), clock=lambda: at(1, 0), wait=wait)
    assert runs == [1]


def test_a_run_that_raises_does_not_stop_the_schedule() -> None:
    stop = threading.Event()
    calls: list[int] = []

    def run_once() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the engine fell over")
        stop.set()

    schedule.loop(time(3, 0), stop, run_once, clock=lambda: at(1, 0), wait=lambda s: False)
    assert len(calls) == 2
