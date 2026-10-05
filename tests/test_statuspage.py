# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bunker import statuspage
from bunker.index import Entry, Index


def an_entry(**over: Any) -> Entry:
    fields: dict[str, Any] = {
        "unit": "osm-regions",
        "name": "north-america/us/vermont",
        "path": "osm-regions/north-america/us/vermont/vermont-260101.osm.pbf",
        "sha256": "a" * 64,
        "size": 2 * 1024**2,
        "publisher_check": "md5-publisher",
        "publisher_digest": "b" * 32,
        "publisher_url": "https://download.geofabrik.de/x.osm.pbf",
        "licence": "ODbL 1.0",
        "fetched": "2026-09-22T03:10:41Z",
        "verified": "2026-09-29T03:00:12Z",
        "status": "current",
        "reason": None,
        "previous": None,
    }
    fields.update(over)
    return Entry(**fields)


def page(**over: Any) -> str:
    idx = Index(
        engine_version="0.19.0",
        generated="2026-09-29T03:05:00Z",
        artifacts=[
            an_entry(),
            an_entry(
                name="north-america/us/delaware",
                status="failed",
                reason="HTTP 503 <script>alert(1)</script>",
            ),
            an_entry(
                unit="country-files",
                name="cty.dat",
                licence="Free for amateur use",
                status="stale",
                reason="refreshed monthly",
            ),
        ],
        deferred=[{"unit": "kiwix-library", "name": None, "reason": "no books selected"}],
        last_run={
            "started": "2026-09-29T03:00:00Z",
            "finished": "2026-09-29T03:05:00Z",
            "fetched": 1,
            "verified": 2,
            "failed": 1,
            "corrupted": 0,
            "stale": 1,
            "error": None,
        },
        **over,
    )
    return statuspage.render(idx, disk_used=3 * 1024**3)


def test_reasons_are_escaped() -> None:
    text = page()
    assert "<script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text


def test_it_shows_what_the_spec_lists() -> None:
    text = page()
    assert "2026-09-29T03:00:00Z" in text  # last run
    assert "north-america/us/delaware" in text and "HTTP 503" in text  # failures, with reasons
    assert "3.0 GiB" in text  # disk used
    assert "ODbL 1.0" in text and "Free for amateur use" in text  # every unit's licence
    assert "no books selected" in text  # deferred
    assert re.search(r"osm-regions</td>\s*<td>1</td>\s*<td>0</td>\s*<td>1</td>", text)
    assert "without authentication" in text  # the LAN notice
    assert "Declined by your configuration" not in text


def test_declined_has_its_own_section_after_engine_deferred() -> None:
    text = page(
        declined=[
            {
                "unit": "config-unit",
                "name": "disabled",
                "reason": "hold_unverified = false",
            }
        ]
    )
    deferred = text.split("<h2>Deferred by the engine</h2>", 1)[1].split("</ul>", 1)[0]
    assert "Declined by your configuration" in text
    assert "config-unit/disabled" not in deferred
    assert text.index("Deferred by the engine") < text.index("Declined by your configuration")
    assert "config-unit/disabled" in text and "hold_unverified = false" in text


def test_an_engine_error_is_shown() -> None:
    idx = Index(last_run={"started": "s", "finished": "f", "error": "engine exited 2"})
    assert "engine exited 2" in statuspage.render(idx, disk_used=0)


def test_no_external_resources() -> None:
    text = page()
    assert "<script" not in text and "<link" not in text and "src=" not in text
    assert "@import" not in text and "url(" not in text


def test_write_is_atomic(tmp_path: Path) -> None:
    statuspage.write(tmp_path, Index())
    assert [p.name for p in tmp_path.iterdir()] == ["status.html"]
    assert (tmp_path / "status.html").read_text().startswith("<!doctype html>")


def test_human_size() -> None:
    assert statuspage.human_size(0) == "0 B"
    assert statuspage.human_size(1536) == "1.5 KiB"
    assert statuspage.human_size(5 * 1024**4) == "5.0 TiB"


def test_the_lede_and_a_unit_row_read_as_one_piece_each() -> None:
    # Both are built from several string literals; a missing comma or space
    # would merge or glue them silently.
    html = page()
    assert (
        "It serves without authentication, over plain HTTP, because every machine "
        "that takes a file from it checks every byte against a digest it already "
        "holds. It belongs on your LAN only: never publish its port on an "
        "interface the internet can reach.</p>"
    ) in html
    assert (
        '<div class="wrap"><table><thead><tr><th>Unit</th><th>Current</th><th>Stale</th>'
        "<th>Failed</th><th>Corrupted</th><th>Size</th></tr></thead><tbody>"
    ) in html
    row = re.search(r"<tr><td>osm-regions</td>.*?</tr>", html, re.S)
    assert row is not None
    cells = re.findall(r"<td>(.*?)</td>", row.group(0))
    assert cells[0] == "osm-regions"
    assert len(cells) == 6
    assert cells[1:] == ["1", "0", "1", "0", "4.0 MiB"]
