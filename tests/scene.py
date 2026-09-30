# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""A volume, a fake engine and a loopback publisher, wired together: the
three artifacts every run test starts from, one per check the catalog uses."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bunker import config, index, run
from tests.conftest import FakeEngine, Publisher
from tests.helpers import artifacts_doc, config_text, entry

T0 = datetime(2026, 9, 29, 3, 0, 0, tzinfo=UTC)
REGION = "north-america/us/vermont"
TILE = "Copernicus_DSM_COG_10_N44_00_W073_00_DEM"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class Scene:
    """Three artifacts, one of each check the catalog uses today."""

    def __init__(self, tmp_path: Path, engine: FakeEngine, pub: Publisher) -> None:
        self.tmp = tmp_path
        self.engine = engine
        self.pub = pub
        self.root = tmp_path / "vol"
        self.clock = Clock()
        self.data = {
            "cty": b"country files " * 100,
            "region": b"osm region pbf " * 3000,
            "tile": b"elevation tile " * 2000,
        }
        self.extra = ""
        self.publish()

    def publish(self, **changes: bytes) -> None:
        self.data.update(changes)
        self.cty_url = self.pub.put("/cf/bigcty-20260906.zip", self.data["cty"])
        self.region_url = self.pub.put(
            "/geofabrik/north-america/us/vermont-260101.osm.pbf", self.data["region"]
        )
        self.tile_url = self.pub.put(f"/cop/{TILE}.tif", self.data["tile"])
        self.list()

    def entries(self) -> list[dict[str, Any]]:
        d = self.data
        return [
            entry(
                "country-files",
                "cty.dat",
                self.cty_url,
                "sha256",
                sha(d["cty"]),
                size=len(d["cty"]),
                licence="Free for amateur use",
            ),
            entry(
                "osm-regions",
                REGION,
                self.region_url,
                "md5-publisher",
                md5(d["region"]),
                checksum_url=self.region_url + ".md5",
                size=len(d["region"]),
                licence="ODbL 1.0",
            ),
            entry(
                "dem-copernicus",
                TILE,
                self.tile_url,
                "etag-md5",
                md5(d["tile"]),
                checksum_url=self.tile_url,
                size=len(d["tile"]),
                licence="Copernicus DEM licence",
            ),
        ]

    def list(self, entries: list[dict[str, Any]] | None = None) -> None:
        self.engine.set_doc(
            artifacts_doc(entries if entries is not None else self.entries(), regions=(REGION,))
        )

    def cfg(self) -> config.Config:
        path = self.tmp / "bunker.toml"
        path.write_text(
            config_text(
                str(self.root),
                selection=f'map_regions = ["{REGION}"]',
                extra='[schedule]\ndefault = "daily"\n' + self.extra,
            )
        )
        return config.load(path)

    def run(self, **kw: Any) -> run.RunReport:
        return run.run(self.cfg(), now=self.clock, **kw)

    def entry(self, unit: str, name: str) -> index.Entry:
        found = index.load(self.root).find(unit, name)
        assert found is not None
        return found

    def file(self, unit: str, name: str) -> Path:
        path = self.entry(unit, name).path
        assert path is not None
        return self.root / path


@pytest.fixture
def scene(tmp_path: Path, fake_engine: FakeEngine, publisher: Publisher) -> Scene:
    return Scene(tmp_path, fake_engine, publisher)
