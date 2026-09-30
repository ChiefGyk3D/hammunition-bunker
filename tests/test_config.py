# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from bunker import config
from bunker.config import ConfigError

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "config.example.toml"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "bunker.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_example_loads() -> None:
    cfg = config.load(EXAMPLE)
    assert cfg.engine.command == ("hammunition",)
    assert cfg.selection.map_freshness == "yearly"
    assert cfg.storage.root == Path("/data")
    assert cfg.serve.port == 8080
    assert cfg.schedule.cadence("osm-regions") == "daily"
    assert cfg.schedule.cadence("anything-else") == cfg.schedule.default


def test_example_regions_are_public_examples_only() -> None:
    """The maintainer's real selection lives on the NAS, never here."""
    cfg = config.load(EXAMPLE)
    allowed = {
        "north-america/us/vermont",
        "north-america/us/new-hampshire",
        "north-america/us/delaware",
    }
    assert set(cfg.selection.map_regions) <= allowed


def test_defaults_are_the_specs(tmp_path: Path) -> None:
    cfg = config.load(write(tmp_path, ""))
    assert cfg.engine.command == ("hammunition",)
    assert cfg.engine.catalog is None
    assert cfg.selection.map_regions == ()
    assert cfg.selection.map_freshness == "yearly"
    assert cfg.selection.units == ()
    assert cfg.storage.root == Path("/data")
    assert cfg.storage.keep_previous is True
    assert cfg.storage.downloads == 2
    assert cfg.storage.max_rate is None
    assert cfg.schedule.default == "weekly"
    assert cfg.schedule.run_at == time(3, 0)
    assert cfg.schedule.verify_cadence("x") == "auto"
    assert cfg.serve.bind == "0.0.0.0"
    assert cfg.serve.port == 8080


def test_engine_command_as_a_list(tmp_path: Path) -> None:
    cfg = config.load(write(tmp_path, '[engine]\ncommand = ["/opt/h/bin/hammunition", "-q"]\n'))
    assert cfg.engine.command == ("/opt/h/bin/hammunition", "-q")


def test_relative_root_resolves_against_the_config(tmp_path: Path) -> None:
    cfg = config.load(write(tmp_path, '[storage]\nroot = "vol"\n'))
    assert cfg.storage.root == tmp_path / "vol"


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("[storage]\ndownloads = 5\n", "storage.downloads"),
        ("[storage]\ndownloads = 0\n", "storage.downloads"),
        ('[storage]\nmax_rate = "fast"\n', "storage.max_rate"),
        ('[schedule]\ndefault = "hourly"\n', "schedule.default"),
        ('[schedule.units]\nosm-regions = "sometimes"\n', "schedule.units.osm-regions"),
        ('[schedule]\nrun_at = "25:00"\n', "schedule.run_at"),
        ('[verify]\ndefault = "never"\n', "verify.default"),
        ("[serve]\nport = 0\n", "serve.port"),
        ("[serve]\nport = 70000\n", "serve.port"),
        ('[selection]\nmap_freshness = "daily"\n', "selection.map_freshness"),
        ('[selection]\nmap_regions = "north-america/us/vermont"\n', "selection.map_regions"),
        ("[selection]\nunits = [1]\n", "selection.units"),
        ("[storage]\nkeep_previous = 1\n", "storage.keep_previous"),
        ('[storage]\nroot = ""\n', "storage.root"),
        ('[engine]\ncommand = ""\n', "engine.command"),
        ("[engine]\ntimeout = -1\n", "engine.timeout"),
        ("[storage]\nroots = 1\n", "storage.roots"),
        ("[stoarge]\n", "stoarge"),
    ],
)
def test_invalid_values_name_the_key(tmp_path: Path, text: str, key: str) -> None:
    with pytest.raises(ConfigError, match=key.replace(".", r"\.")):
        config.load(write(tmp_path, text))


def test_unparseable_toml_names_the_file(tmp_path: Path) -> None:
    path = write(tmp_path, "[engine\n")
    with pytest.raises(ConfigError, match=str(path)):
        config.load(path)


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        config.load(tmp_path / "nope.toml")


def test_find_prefers_the_explicit_path(tmp_path: Path) -> None:
    explicit = tmp_path / "x.toml"
    assert config.find(explicit, candidates=(tmp_path / "a.toml",)) == explicit


def test_find_takes_the_first_candidate_that_exists(tmp_path: Path) -> None:
    second = tmp_path / "b.toml"
    second.write_text("")
    assert config.find(None, candidates=(tmp_path / "a.toml", second)) == second


def test_find_with_nothing_names_every_place(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"a\.toml.*b\.toml"):
        config.find(None, candidates=(tmp_path / "a.toml", tmp_path / "b.toml"))


def test_default_search_order() -> None:
    assert config.DEFAULT_PATHS == (Path("/etc/bunker/bunker.toml"), Path("bunker.toml"))


@pytest.mark.parametrize(
    ("text", "value"),
    [("512K", 512 * 1024), ("20M", 20 * 1024**2), ("1G", 1024**3), ("4096", 4096)],
)
def test_parse_rate(text: str, value: int) -> None:
    assert config.parse_rate(text) == value


@pytest.mark.parametrize("text", ["", "0", "0M", "-1M", "20MB", "fast"])
def test_parse_rate_refuses(text: str) -> None:
    with pytest.raises(ValueError):
        config.parse_rate(text)
