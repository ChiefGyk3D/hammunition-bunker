# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

import pytest

from bunker import config, engine
from bunker.engine import EngineError
from tests.conftest import FakeEngine
from tests.helpers import artifacts_doc, config_text, deferred, entry

SHA = "a" * 64
MD5 = "b" * 32


def cfg(tmp_path: Path, selection: str = "", extra: str = "") -> config.Config:
    path = tmp_path / "bunker.toml"
    path.write_text(config_text(str(tmp_path / "vol"), selection=selection, extra=extra))
    return config.load(path)


def test_argv_carries_the_selection(tmp_path: Path) -> None:
    c = cfg(
        tmp_path,
        selection=(
            'map_regions = ["north-america/us/vermont", "north-america/us/delaware"]\n'
            'map_freshness = "monthly"\nunits = ["osm-regions", "dem-copernicus"]'
        ),
        extra='[engine]\ncommand = ["hammunition"]\ncatalog = "/opt/h/catalog"\n',
    )
    assert engine.argv(c) == [
        "hammunition",
        "--catalog",
        "/opt/h/catalog",
        "artifacts",
        "--json",
        "--map-freshness",
        "monthly",
        "--map-regions",
        "north-america/us/vermont,north-america/us/delaware",
        "--units",
        "osm-regions,dem-copernicus",
    ]


def test_argv_without_regions_or_units(tmp_path: Path) -> None:
    assert engine.argv(cfg(tmp_path)) == [
        "hammunition",
        "artifacts",
        "--json",
        "--map-freshness",
        "yearly",
    ]


def test_a_canned_document_parses(tmp_path: Path, fake_engine: FakeEngine) -> None:
    fake_engine.set_doc(
        artifacts_doc(
            [
                entry("country-files", "cty.dat", "https://p/cty.dat", "sha256", SHA, size=10),
                entry(
                    "osm-regions",
                    "north-america/us/vermont",
                    "https://p/vermont-260101.osm.pbf",
                    "md5-publisher",
                    MD5,
                    checksum_url="https://p/vermont-260101.osm.pbf.md5",
                    size=20,
                    licence="ODbL 1.0",
                ),
                deferred("dem-copernicus", "its outline could not be read", "north-america/us/x"),
            ]
        )
    )
    listing = engine.ask_engine(cfg(tmp_path))
    assert listing.engine_version == "0.16.0"
    assert [a.name for a in listing.artifacts] == ["cty.dat", "north-america/us/vermont"]
    region = listing.artifacts[1]
    assert region.check == "md5-publisher"
    assert region.digest == MD5
    assert region.checksum_url == "https://p/vermont-260101.osm.pbf.md5"
    assert region.size == 20
    assert listing.deferred == (
        engine.Deferred("dem-copernicus", "north-america/us/x", "its outline could not be read"),
    )
    assert listing.licences == {
        "country-files": "Public domain",
        "osm-regions": "ODbL 1.0",
        "dem-copernicus": "ODbL 1.0",
    }
    assert fake_engine.calls()[-1][:2] == ["artifacts", "--json"]


def test_non_zero_exit_carries_the_engines_stderr(tmp_path: Path, fake_engine: FakeEngine) -> None:
    fake_engine.set_exit(2, "error: not in the catalog: osm-regionz\n")
    with pytest.raises(EngineError, match=r"exited 2.*not in the catalog: osm-regionz"):
        engine.ask_engine(cfg(tmp_path))


def test_stdout_that_is_not_json(tmp_path: Path, fake_engine: FakeEngine) -> None:
    fake_engine.set_doc("Remote data artifacts for 2 unit(s)")
    with pytest.raises(EngineError, match="not a JSON document"):
        engine.ask_engine(cfg(tmp_path))


def test_an_unknown_schema_major_is_refused_by_name(
    tmp_path: Path, fake_engine: FakeEngine
) -> None:
    doc = artifacts_doc([])
    doc["schema"] = "hammunition/2"
    fake_engine.set_doc(doc)
    with pytest.raises(EngineError, match="hammunition/2"):
        engine.ask_engine(cfg(tmp_path))


def test_an_error_document_carries_its_message(tmp_path: Path, fake_engine: FakeEngine) -> None:
    fake_engine.set_doc(
        {
            "schema": "hammunition/1",
            "kind": "error",
            "engine": "0.16.0",
            "command": "artifacts",
            "exit_code": 2,
            "message": "could not find the catalog",
        }
    )
    with pytest.raises(EngineError, match="could not find the catalog"):
        engine.ask_engine(cfg(tmp_path))


def test_a_missing_field_is_named(tmp_path: Path, fake_engine: FakeEngine) -> None:
    item = entry("country-files", "cty.dat", "https://p/cty.dat", "sha256", SHA, size=1)
    del item["checksum_url"]
    fake_engine.set_doc(artifacts_doc([item]))
    with pytest.raises(EngineError, match="checksum_url"):
        engine.ask_engine(cfg(tmp_path))


def test_a_wrong_type_is_named(tmp_path: Path, fake_engine: FakeEngine) -> None:
    item = entry("country-files", "cty.dat", "https://p/cty.dat", "sha256", SHA, size=1)
    item["size"] = "ten"
    fake_engine.set_doc(artifacts_doc([item]))
    with pytest.raises(EngineError, match="size"):
        engine.ask_engine(cfg(tmp_path))


def test_an_added_field_is_tolerated(tmp_path: Path, fake_engine: FakeEngine) -> None:
    """D-059: a field may be added within a major version."""
    item = entry("country-files", "cty.dat", "https://p/cty.dat", "sha256", SHA, size=1)
    item["mirror_hint"] = "anything"
    doc = artifacts_doc([item])
    doc["generated_by"] = "a later engine"
    fake_engine.set_doc(doc)
    assert len(engine.ask_engine(cfg(tmp_path)).artifacts) == 1


def test_an_unknown_check_defers_that_artifact(tmp_path: Path, fake_engine: FakeEngine) -> None:
    fake_engine.set_doc(
        artifacts_doc(
            [
                entry("a-unit", "one", "https://p/one", "blake3-publisher", "c" * 64, size=1),
                entry("a-unit", "two", "https://p/two", "sha256", SHA, size=1),
            ]
        )
    )
    listing = engine.ask_engine(cfg(tmp_path))
    assert [a.name for a in listing.artifacts] == ["two"]
    assert listing.deferred[0].name == "one"
    assert "blake3-publisher" in listing.deferred[0].reason


def test_command_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(EngineError, match="not found"):
        engine.ask_engine(cfg(tmp_path))


def test_timeout(tmp_path: Path, fake_engine: FakeEngine) -> None:
    fake_engine.script.write_text("#!/bin/sh\nexec sleep 30\n")
    with pytest.raises(EngineError, match="did not answer within"):
        engine.ask_engine(cfg(tmp_path, extra="[engine]\ntimeout = 0.5\n"))


def test_engine_version_parses(tmp_path: Path, fake_engine: FakeEngine) -> None:
    fake_engine.set_version("0.16.2")
    assert engine.engine_version(cfg(tmp_path)) == "0.16.2"


@pytest.mark.parametrize(
    ("version", "ok"),
    [("0.16.0", True), ("0.16.1", True), ("1.0.0", True), ("0.15.9", False), ("0.9.0", False)],
)
def test_meets_floor(version: str, ok: bool) -> None:
    assert engine.meets_floor(version) is ok


def test_a_name_listed_twice_with_different_bytes_is_deferred(
    tmp_path: Path, fake_engine: FakeEngine
) -> None:
    fake_engine.set_doc(
        artifacts_doc(
            [
                entry("u", "one", "https://p/a", "sha256", SHA, size=1),
                entry("u", "one", "https://p/b", "sha256", "c" * 64, size=1),
            ]
        )
    )
    listing = engine.ask_engine(cfg(tmp_path))
    assert [a.url for a in listing.artifacts] == ["https://p/a"]
    assert "listed twice" in listing.deferred[0].reason
