# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Builders for the canned documents the fake engine prints."""

from __future__ import annotations

from typing import Any

ENGINE_VERSION = "0.16.0"


def entry(
    unit: str,
    name: str | None,
    url: str | None = None,
    check: str | None = "sha256",
    digest: str | None = None,
    *,
    checksum_url: str | None = None,
    size: int | None = None,
    licence: str = "Public domain",
    deferred: str | None = None,
) -> dict[str, Any]:
    """One ``ArtifactEntry`` exactly as the engine's contract (D-070, as built)
    names its fields."""
    return {
        "unit": unit,
        "name": name,
        "url": url,
        "check": check,
        "digest": digest,
        "checksum_url": checksum_url,
        "size": size,
        "licence": licence,
        "deferred": deferred,
    }


def deferred(unit: str, reason: str, name: str | None = None) -> dict[str, Any]:
    return entry(unit, name, None, None, None, licence="ODbL 1.0", deferred=reason)


def artifacts_doc(
    entries: list[dict[str, Any]],
    *,
    regions: tuple[str, ...] = (),
    freshness: str = "yearly",
    engine: str = ENGINE_VERSION,
) -> dict[str, Any]:
    """An ``ArtifactsDocument`` in the D-059 envelope."""
    units = list(dict.fromkeys(e["unit"] for e in entries))
    return {
        "schema": "hammunition/1",
        "kind": "artifacts",
        "engine": engine,
        "map_regions": list(regions),
        "map_freshness": freshness,
        "units": units,
        "artifacts": entries,
    }


def config_text(root: str, *, extra: str = "", selection: str = "") -> str:
    """A bunker.toml for a temp volume; *extra* is appended verbatim."""
    return f'[storage]\nroot = "{root}"\n[selection]\n{selection or "map_regions = []"}\n{extra}'
