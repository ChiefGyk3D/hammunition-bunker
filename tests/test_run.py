# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""One pass, end to end: the fake engine lists, the loopback publisher
serves, the engine's own Fetcher verifies, the volume is a temp directory."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from bunker import config, index, run, volume
from bunker.volume import Locked, RunLock
from tests.helpers import deferred, entry
from tests.scene import REGION, T0, TILE, Scene, md5, sha


def actions(report: run.RunReport) -> dict[str, str]:
    return {o.name: o.action for o in report.outcomes}


def test_first_run_fetches_everything(scene: Scene) -> None:
    report = scene.run()
    assert report.exit_code == 0, report.summary_lines()
    assert actions(report) == {"cty.dat": "fetched", REGION: "fetched", TILE: "fetched"}
    for unit, name, key in [
        ("country-files", "cty.dat", "cty"),
        ("osm-regions", REGION, "region"),
        ("dem-copernicus", TILE, "tile"),
    ]:
        e = scene.entry(unit, name)
        path = scene.file(unit, name)
        assert path.read_bytes() == scene.data[key]
        # The sidecar is sha256 of the bytes whatever the publisher's check was.
        assert volume.read_sidecar(path) == sha(scene.data[key]) == e.sha256
        assert e.status == "current" and e.reason is None
        assert e.fetched == e.verified == "2026-09-29T03:00:00Z"
    region = scene.entry("osm-regions", REGION)
    assert region.path == f"osm-regions/{REGION}/vermont-260101.osm.pbf"
    assert region.publisher_check == "md5-publisher"
    assert region.publisher_digest == md5(scene.data["region"])
    assert region.publisher_url == scene.region_url
    raw = json.loads((scene.root / "index.json").read_text())
    assert raw["engine"] == {"version": "0.16.0"}
    assert raw["last_run"]["fetched"] == 3 and raw["last_run"]["failed"] == 0


def test_second_run_fetches_nothing(scene: Scene) -> None:
    scene.run()
    before = scene.pub.total()
    scene.clock.advance(hours=1)
    report = scene.run()
    assert report.exit_code == 0
    assert scene.pub.total() == before
    assert set(actions(report).values()) == {"verified"}  # auto: small files every run
    assert report.counts()["fetched"] == 0


def test_corrupted_file_is_refetched_and_reported(scene: Scene) -> None:
    scene.run()
    path = scene.file("osm-regions", REGION)
    path.write_bytes(b"bit rot" + path.read_bytes()[7:])
    report = scene.run()
    outcome = next(o for o in report.outcomes if o.name == REGION)
    assert outcome.corrupted and outcome.action == "fetched"
    assert path.read_bytes() == scene.data["region"]
    assert report.counts()["corrupted"] == 1
    assert report.exit_code == 1  # corruption on the NAS is news even when repaired
    assert any("corrupted" in line for line in report.summary_lines())


def test_wrong_hash_keeps_previous_serving(scene: Scene) -> None:
    scene.run()
    good = scene.file("country-files", "cty.dat")
    # The engine now pins new bytes, and the publisher serves something else.
    new = b"new country files " * 50
    entries = scene.entries()
    entries[0]["digest"] = sha(new)
    entries[0]["size"] = len(scene.data["cty"])
    scene.list(entries)
    scene.clock.advance(days=2)
    report = scene.run()
    outcome = next(o for o in report.outcomes if o.name == "cty.dat")
    assert outcome.action == "failed"
    assert "does not match" in (outcome.reason or "")
    e = scene.entry("country-files", "cty.dat")
    assert e.status == "failed"
    assert good.read_bytes() == scene.data["cty"]  # still there, still served
    assert scene.file("country-files", "cty.dat") == good
    assert report.exit_code == 1


def test_incoming_left_clean(scene: Scene) -> None:
    entries = scene.entries()
    entries[1]["digest"] = "0" * 32  # the region's MD5 will not match
    scene.list(entries)
    scene.run()
    left = [p for p in (scene.root / ".incoming").rglob("*") if p.is_file()]
    assert left == []


def test_new_version_keeps_previous(scene: Scene) -> None:
    scene.run()
    old = scene.data["region"]
    scene.pub.put("/geofabrik/north-america/us/vermont-260201.osm.pbf", b"next month " * 999)
    entries = scene.entries()
    entries[1].update(
        url=scene.pub.base + "/geofabrik/north-america/us/vermont-260201.osm.pbf",
        digest=md5(b"next month " * 999),
        size=len(b"next month " * 999),
    )
    scene.list(entries)
    scene.clock.advance(days=1)
    report = scene.run()
    assert actions(report)[REGION] == "fetched"
    e = scene.entry("osm-regions", REGION)
    assert e.path == f"osm-regions/{REGION}/vermont-260201.osm.pbf"
    assert e.previous == f"osm-regions/{REGION}/vermont-260101.osm.pbf.previous"
    assert (scene.root / e.previous).read_bytes() == old


def test_cadence_per_unit(scene: Scene) -> None:
    scene.extra = '[schedule.units]\ncountry-files = "weekly"\ndem-copernicus = "never"\n'
    scene.run()
    new_cty, new_tile = b"cty v2 " * 70, b"tile v2 " * 900
    scene.publish(cty=new_cty, tile=new_tile)
    scene.clock.advance(days=3)
    report = scene.run()
    got = actions(report)
    assert got["cty.dat"] == "stale"  # weekly, fetched three days ago
    assert got[TILE] == "stale"  # never
    e = scene.entry("country-files", "cty.dat")
    assert e.status == "stale" and "weekly" in (e.reason or "")
    scene.clock.advance(days=4)
    assert actions(scene.run())["cty.dat"] == "fetched"  # a week has passed
    assert actions(scene.run())[TILE] == "stale"
    assert actions(scene.run(units=("dem-copernicus",)))[TILE] == "fetched"


def test_all_fetches_what_is_not_due(scene: Scene) -> None:
    scene.extra = '[schedule.units]\ndem-copernicus = "never"\n'
    scene.run()
    scene.publish(tile=b"tile v3 " * 900)
    assert actions(scene.run(all_=True))[TILE] == "fetched"


def test_unit_filter_touches_only_that_unit(scene: Scene) -> None:
    scene.run()
    report = scene.run(units=("osm-regions",))
    assert set(actions(report)) == {REGION}
    assert scene.entry("country-files", "cty.dat").status == "current"


def test_an_unknown_unit_filter_is_an_error(scene: Scene) -> None:
    report = scene.run(units=("osm-regionz",))
    assert report.exit_code == 1
    assert "osm-regionz" in (report.error or "")
    assert report.outcomes == []


def test_a_missing_file_is_fetched_even_on_never(scene: Scene) -> None:
    scene.extra = '[schedule.units]\ndem-copernicus = "never"\n'
    assert actions(scene.run())[TILE] == "fetched"


def test_verify_cadence_large_files(scene: Scene, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "LARGE", 10_000)  # the region and the tile are "large" here
    scene.run()
    scene.clock.advance(days=1)
    got = actions(scene.run())
    assert got["cty.dat"] == "verified"
    assert got[REGION] == got[TILE] == "unchanged"
    scene.clock.advance(days=30)
    assert actions(scene.run())[REGION] == "verified"


def test_lock(scene: Scene) -> None:
    with RunLock(scene.root), pytest.raises(Locked):
        scene.run()


def test_engine_failure_is_recorded(scene: Scene) -> None:
    scene.run()
    scene.engine.set_exit(2, "error: could not find the catalog\n")
    report = scene.run()
    assert report.exit_code == 1
    assert "could not find the catalog" in (report.error or "")
    idx = index.load(scene.root)
    assert len(idx.artifacts) == 3  # what it holds is still served
    assert idx.last_run is not None and "could not find" in idx.last_run["error"]
    lines = (scene.root / ".runs.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["error"].startswith("`hammunition")


def test_unsafe_artifact_fails_alone(scene: Scene) -> None:
    entries = scene.entries()
    entries.append(
        entry(
            "osm-regions",
            "../../../etc/cron.d/x",
            scene.cty_url,
            "sha256",
            sha(scene.data["cty"]),
            size=len(scene.data["cty"]),
        )
    )
    scene.list(entries)
    report = scene.run()
    got = actions(report)
    assert got["../../../etc/cron.d/x"] == "failed"
    assert got["cty.dat"] == "fetched"
    assert not (scene.tmp / "etc").exists()


def test_no_digest_is_never_fetched(scene: Scene) -> None:
    entries = scene.entries()
    entries[0]["digest"] = None
    scene.list(entries)
    report = scene.run()
    outcome = next(o for o in report.outcomes if o.name == "cty.dat")
    assert outcome.action == "failed" and "no digest" in (outcome.reason or "")
    assert scene.pub.requests("/cf/bigcty-20260906.zip") == 0


def test_a_size_that_disagrees_fails(scene: Scene) -> None:
    entries = scene.entries()
    entries[0]["size"] = 5  # the pin is right, the listed size is not
    scene.list(entries)
    report = scene.run()
    assert actions(report)["cty.dat"] == "failed"


def test_dropped_entries(scene: Scene) -> None:
    scene.run()
    scene.list([*scene.entries()[:1], deferred("osm-regions", "Geofabrik did not answer", REGION)])
    report = scene.run()
    idx = index.load(scene.root)
    names = {e.name for e in idx.artifacts}
    assert REGION in names  # deferred this time: kept, not dropped
    assert TILE not in names
    assert [d["name"] for d in report.dropped] == [TILE]
    assert scene.root.joinpath(f"dem-copernicus/{TILE}").is_dir()  # files are left for a person


def test_runs_jsonl_appends(scene: Scene) -> None:
    scene.run()
    scene.run()
    lines = [json.loads(x) for x in (scene.root / ".runs.jsonl").read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["counts"]["fetched"] == 3 and lines[1]["counts"]["fetched"] == 0


def test_two_downloads_at_a_time(scene: Scene) -> None:
    scene.pub.delay = 0.2
    scene.run()
    assert scene.pub.max_active == 2


def test_one_download_at_a_time(scene: Scene) -> None:
    scene.pub.delay = 0.1
    path = scene.tmp / "bunker.toml"
    path.write_text(
        f'[storage]\nroot = "{scene.root}"\ndownloads = 1\n'
        f'[selection]\nmap_regions = ["{REGION}"]\n'
    )
    run.run(config.load(path), now=scene.clock)
    assert scene.pub.max_active == 1


def test_deferred_are_recorded(scene: Scene) -> None:
    scene.list([*scene.entries(), deferred("kiwix-library", "no books selected")])
    report = scene.run()
    assert report.deferred == [
        {"unit": "kiwix-library", "name": None, "reason": "no books selected"}
    ]
    assert index.load(scene.root).deferred == report.deferred


def test_rate_limit_paces_bytes() -> None:
    slept: list[float] = []
    now = [0.0]

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limit = run.RateLimit(None, rate=1000, clock=clock, sleep=sleep)  # type: ignore[arg-type]
    for _ in range(3):
        limit.consume(1000)
    assert sum(slept) == pytest.approx(2.0)


def test_due_arithmetic() -> None:
    assert run.due("never", None, T0) is True  # never fetched at all
    assert run.due("never", T0 - timedelta(days=400), T0) is False
    assert run.due("daily", T0 - timedelta(hours=23, minutes=30), T0) is True  # within the slack
    assert run.due("daily", T0 - timedelta(hours=12), T0) is False
    assert run.due("weekly", T0 - timedelta(days=7), T0) is True
    assert run.due("monthly", T0 - timedelta(days=29), T0) is False


def test_an_unexpected_exception_fails_one_artifact_not_the_run(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    import http.client

    real = run._download

    def flaky(root: Path, artifact: Any, transport: Any) -> Any:
        if artifact.unit == "osm-regions":
            raise http.client.IncompleteRead(b"partial", 100)
        return real(root, artifact, transport)

    monkeypatch.setattr(run, "_download", flaky)
    report = scene.run()
    got = actions(report)
    assert got[REGION] == "failed"
    assert "IncompleteRead" in (next(o.reason for o in report.outcomes if o.name == REGION) or "")
    assert got["cty.dat"] == "fetched"
    assert (scene.root / ".runs.jsonl").read_text().strip()


def test_an_unreadable_held_file_fails_that_artifact(scene: Scene) -> None:
    import os

    scene.run()
    path = scene.file("country-files", "cty.dat")
    path.chmod(0)
    try:
        if os.access(path, os.R_OK):
            pytest.skip("running as a user who can read mode-000 files")
        report = scene.run()
    finally:
        path.chmod(0o644)
    got = actions(report)
    assert got["cty.dat"] == "failed"
    assert got[REGION] == "verified"


def test_a_stranded_partial_download_is_swept(scene: Scene) -> None:
    """A container killed mid-download leaves the engine's `.part.<pid>`;
    PID 1 again next start would collide with it."""
    import os

    folder = scene.root / ".incoming" / "osm-regions"
    folder.mkdir(parents=True)
    md5_hex = md5(scene.data["region"])
    stranded = folder / f"md5-{md5_hex}-vermont-260101.osm.pbf.part.{os.getpid()}"
    stranded.write_bytes(b"half a download")
    report = scene.run()
    assert actions(report)[REGION] == "fetched"
    assert not stranded.exists()


def test_a_region_listed_twice_is_fetched_once(scene: Scene) -> None:
    entries = scene.entries()
    scene.list([*entries, entries[1]])
    report = scene.run()
    assert [o.name for o in report.outcomes].count(REGION) == 1
    assert actions(report)[REGION] == "fetched"


def test_a_plain_http_publisher_is_disclosed(scene: Scene) -> None:
    """The spec: a publisher on plain HTTP is disclosed in the report."""
    report = scene.run()
    assert set(report.plain_http) == {  # the loopback publisher is http
        "country-files/cty.dat",
        f"osm-regions/{REGION}",
        f"dem-copernicus/{TILE}",
    }
    assert any("plain HTTP" in line for line in report.summary_lines())
    assert "plain HTTP" in (scene.root / "status.html").read_text()


def test_nested_names_that_collide_fail_by_name(scene: Scene) -> None:
    """`a` holding file `b` and artifact `a/b` want one path; the second fails
    by name rather than overwriting the first."""
    url_b = scene.pub.put("/x/b", b"file b")
    url_c = scene.pub.put("/y/c", b"file c")
    scene.list(
        [
            entry("u", "a", url_b, "sha256", sha(b"file b"), size=6),
            entry("u", "a/b", url_c, "sha256", sha(b"file c"), size=6),
        ]
    )
    report = scene.run()
    assert sorted(o.action for o in report.outcomes) == ["failed", "fetched"]
    won = next(o for o in report.outcomes if o.action == "fetched")
    held = scene.file("u", won.name)
    assert held.read_bytes() == (b"file b" if won.name == "a" else b"file c")
