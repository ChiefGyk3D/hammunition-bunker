# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bunker import index
from bunker.index import Entry, Index, IndexRefused


def an_entry(**over: Any) -> Entry:
    fields: dict[str, Any] = {
        "unit": "osm-regions",
        "name": "north-america/us/vermont",
        "path": "osm-regions/north-america/us/vermont/vermont-260101.osm.pbf",
        "sha256": "a" * 64,
        "size": 12,
        "publisher_check": "md5-publisher",
        "publisher_digest": "b" * 32,
        "publisher_url": "https://download.geofabrik.de/north-america/us/vermont-260101.osm.pbf",
        "licence": "ODbL 1.0",
        "fetched": "2026-09-22T03:10:41Z",
        "verified": "2026-09-29T03:00:12Z",
        "status": "current",
        "reason": None,
        "previous": None,
    }
    fields.update(over)
    return Entry(**fields)


def test_absent_is_empty(tmp_path: Path) -> None:
    loaded = index.load(tmp_path)
    assert loaded.artifacts == [] and loaded.last_run is None


def test_round_trip(tmp_path: Path) -> None:
    idx = Index(
        engine_version="0.21.0",
        artifacts=[an_entry()],
        deferred=[{"unit": "kiwix-library", "name": None, "reason": "no books selected"}],
        declined=[{"unit": "acma-register", "name": "spectra_rrl.zip", "reason": "disabled"}],
        last_run={"started": "s", "finished": "f", "fetched": 1, "verified": 0, "failed": 0},
    )
    index.save(tmp_path, idx, generated="2026-09-29T23:00:00Z")
    raw = json.loads((tmp_path / "index.json").read_text())
    assert raw["kind"] == "bunker-index"
    assert raw["version"] == 2
    assert raw["generated"] == "2026-09-29T23:00:00Z"
    assert raw["engine"] == {"version": "0.21.0"}
    assert raw["artifacts"][0]["status"] == "current"
    loaded = index.load(tmp_path)
    assert loaded.artifacts == [an_entry()]
    assert loaded.find("osm-regions", "north-america/us/vermont") == an_entry()
    assert loaded.deferred == idx.deferred
    assert loaded.declined == idx.declined
    assert loaded.last_run == idx.last_run


def test_save_leaves_no_temporary(tmp_path: Path) -> None:
    index.save(tmp_path, Index(), generated="g")
    assert [p.name for p in tmp_path.iterdir()] == ["index.json"]


@pytest.mark.parametrize(
    "text",
    ["{not json", "[]", '{"kind": "something-else", "version": 1}', '{"kind": "bunker-index"}'],
)
def test_index_corrupt_refuses(tmp_path: Path, text: str) -> None:
    (tmp_path / "index.json").write_text(text)
    with pytest.raises(IndexRefused, match=r"index\.json.*[Mm]ove it aside"):
        index.load(tmp_path)


def test_an_entry_missing_a_field_refuses(tmp_path: Path) -> None:
    index.save(tmp_path, Index(artifacts=[an_entry()]), generated="g")
    raw = json.loads((tmp_path / "index.json").read_text())
    del raw["artifacts"][0]["sha256"]
    (tmp_path / "index.json").write_text(json.dumps(raw))
    with pytest.raises(IndexRefused, match="sha256"):
        index.load(tmp_path)


def test_index_newer_refuses(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text(json.dumps({"kind": "bunker-index", "version": 3}))
    with pytest.raises(IndexRefused, match="newer"):
        index.load(tmp_path)


def test_an_older_index_is_upgraded_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upgrades are applied in order and written back."""

    def v0_to_v1(raw: dict[str, Any]) -> dict[str, Any]:
        return {**raw, "version": 1, "artifacts": [], "deferred": [], "last_run": None}

    monkeypatch.setitem(index.UPGRADES, 0, v0_to_v1)
    (tmp_path / "index.json").write_text(json.dumps({"kind": "bunker-index", "version": 0}))
    assert index.load(tmp_path).artifacts == []
    assert json.loads((tmp_path / "index.json").read_text())["version"] == 2


def test_version_1_index_is_upgraded_without_reclassifying_deferred(
    tmp_path: Path,
) -> None:
    index.save(
        tmp_path,
        Index(deferred=[{"unit": "acma-register", "name": "spectra_rrl.zip", "reason": "old"}]),
        generated="g",
    )
    path = tmp_path / "index.json"
    raw = json.loads(path.read_text())
    raw["version"] = 1
    del raw["declined"]
    path.write_text(json.dumps(raw))

    loaded = index.load(tmp_path)
    upgraded = json.loads(path.read_text())
    assert loaded.deferred == [
        {"unit": "acma-register", "name": "spectra_rrl.zip", "reason": "old"}
    ]
    assert loaded.declined == []
    assert upgraded["version"] == 2 and upgraded["declined"] == []
    assert upgraded["deferred"] == loaded.deferred


def test_an_older_index_with_no_upgrade_refuses(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text(json.dumps({"kind": "bunker-index", "version": 0}))
    with pytest.raises(IndexRefused, match="no upgrade"):
        index.load(tmp_path)


def test_ensure_writes_an_empty_index_only_when_absent(tmp_path: Path) -> None:
    index.ensure(tmp_path, generated="g1")
    assert json.loads((tmp_path / "index.json").read_text())["artifacts"] == []
    index.save(tmp_path, Index(artifacts=[an_entry()]), generated="g2")
    index.ensure(tmp_path, generated="g3")
    assert len(index.load(tmp_path).artifacts) == 1


# Findings of the Atheris targets in fuzz/ (each input is the bytes the fuzzer found).


def test_an_index_that_is_not_utf8_is_refused_not_a_traceback(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_bytes(b"\xc2\x00{}")
    with pytest.raises(IndexRefused, match="not JSON"):
        index.load(tmp_path)


def _entry_dict() -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(an_entry())


def _doc(**over: Any) -> dict[str, Any]:
    from dataclasses import asdict

    doc: dict[str, Any] = {
        "kind": index.KIND,
        "version": index.INDEX_VERSION,
        "generated": "2026-10-04T00:00:00Z",
        "engine": {"version": "0.21.0"},
        "artifacts": [asdict(an_entry())],
        "deferred": [],
        "declined": [],
        "last_run": None,
    }
    doc.update(over)
    return doc


@pytest.mark.parametrize(
    ("what", "over"),
    [
        ("deferred is a number", {"deferred": 7}),
        ("declined is an object", {"declined": {"unit": "u"}}),
        ("a deferred row is text", {"deferred": ["x"]}),
        ("a deferred value is an object", {"deferred": [{"unit": {}, "reason": "r"}]}),
        ("last_run is a list", {"last_run": [1]}),
        ("plain_http is a number", {"last_run": {"plain_http": 3}}),
        ("engine version is a number", {"engine": {"version": 3}}),
        ("generated is a number", {"generated": 3}),
        ("an entry's unit is a list", {"artifacts": [{**_entry_dict(), "unit": ["x"]}]}),
        ("an entry's size is text", {"artifacts": [{**_entry_dict(), "size": "12"}]}),
        ("an entry's size is a bool", {"artifacts": [{**_entry_dict(), "size": True}]}),
        ("an entry's path is a number", {"artifacts": [{**_entry_dict(), "path": 5}]}),
    ],
)
def test_a_wrong_typed_field_is_refused_by_name_not_a_traceback_later(
    tmp_path: Path, what: str, over: dict[str, Any]
) -> None:
    (tmp_path / "index.json").write_text(json.dumps(_doc(**over)), encoding="utf-8")
    with pytest.raises(IndexRefused, match="mv "):
        index.load(tmp_path)
