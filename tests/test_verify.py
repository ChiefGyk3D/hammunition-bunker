# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import pytest

from bunker import index, verify
from bunker.volume import Locked, RunLock
from tests.scene import REGION, Scene


def test_verify_rehashes_and_fetches_nothing(scene: Scene) -> None:
    scene.run()
    before = scene.pub.total()
    calls = len(scene.engine.calls())
    scene.clock.advance(days=1)
    report = verify.verify(scene.cfg(), now=scene.clock)
    assert report.exit_code == 0
    assert {r.name for r in report.results if r.ok} == {
        "cty.dat",
        REGION,
        "Copernicus_DSM_COG_10_N44_00_W073_00_DEM",
    }
    assert scene.pub.total() == before
    assert len(scene.engine.calls()) == calls  # the engine is not asked either
    assert scene.entry("country-files", "cty.dat").verified == "2026-09-30T03:00:00Z"


def test_verify_marks_corruption(scene: Scene) -> None:
    scene.run()
    path = scene.file("osm-regions", REGION)
    path.write_bytes(b"x" + path.read_bytes()[1:])
    report = verify.verify(scene.cfg(), now=scene.clock)
    assert report.exit_code == 1
    bad = [r for r in report.results if not r.ok]
    assert [r.name for r in bad] == [REGION]
    e = scene.entry("osm-regions", REGION)
    assert e.status == "corrupted" and "no longer match" in (e.reason or "")
    assert path.exists()  # verify changes nothing on disk but the index; the next run re-fetches


def test_verify_a_missing_file(scene: Scene) -> None:
    scene.run()
    scene.file("country-files", "cty.dat").unlink()
    report = verify.verify(scene.cfg(), now=scene.clock)
    assert report.exit_code == 1
    assert "missing" in (scene.entry("country-files", "cty.dat").reason or "")


def test_verify_one_unit(scene: Scene) -> None:
    scene.run()
    report = verify.verify(scene.cfg(), units=("osm-regions",), now=scene.clock)
    assert [r.name for r in report.results] == [REGION]


def test_verify_takes_the_lock(scene: Scene) -> None:
    scene.run()
    with RunLock(scene.root), pytest.raises(Locked):
        verify.verify(scene.cfg(), now=scene.clock)


def test_verify_rewrites_the_status_page(scene: Scene) -> None:
    scene.run()
    (scene.root / "status.html").unlink()
    verify.verify(scene.cfg(), now=scene.clock)
    assert (scene.root / "status.html").exists()
    assert index.load(scene.root).artifacts


def test_a_run_after_verify_refetches_what_verify_found(scene: Scene) -> None:
    """A corruption `bunker verify` found is not undone by a run whose verify
    cadence is not due: the entry's status says the bytes are bad."""
    scene.extra = '[verify]\ndefault = "monthly"\n'
    scene.run()
    path = scene.file("osm-regions", REGION)
    path.write_bytes(b"x" + path.read_bytes()[1:])
    assert verify.verify(scene.cfg(), now=scene.clock).exit_code == 1
    scene.clock.advance(hours=2)
    report = scene.run()
    outcome = next(o for o in report.outcomes if o.name == REGION)
    assert outcome.corrupted and outcome.action == "fetched"
    assert path.read_bytes() == scene.data["region"]
    assert scene.entry("osm-regions", REGION).status == "current"
