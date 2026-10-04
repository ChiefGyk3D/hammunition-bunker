# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fuzz target: the engine's ``hammunition artifacts --json`` document.

``engine._parse`` is the Bunker's only source of what to mirror and is read
strictly: a bad answer raises ``EngineError`` and fails the run, loudly. Any
other exception is a bug, and an accepted listing must hold only entries whose
check this Bunker knows, with no name listed twice. Text in, nothing else: the
engine is never run. Half the inputs are a well-formed document with one
wrong field, so the per-entry checks are reached.
"""

import json
import sys
from typing import Any

import atheris

with atheris.instrument_imports():
    from bunker import engine

_CHECKS = (*engine.CHECKS, "sha256-file", "")


def _opt(fdp: atheris.FuzzedDataProvider, good: str) -> Any:
    pick = fdp.ConsumeIntInRange(0, 5)
    if pick == 0:
        return None
    if pick == 1:
        return fdp.ConsumeIntInRange(-3, 2**33)
    if pick == 2:
        return fdp.ConsumeBool()
    if pick == 3:
        return fdp.ConsumeUnicodeNoSurrogates(10)
    return good


def _item(fdp: atheris.FuzzedDataProvider) -> Any:
    if fdp.ConsumeIntInRange(0, 15) == 0:
        return fdp.ConsumeUnicodeNoSurrogates(4)
    item: dict[str, Any] = {
        "unit": _opt(fdp, "country-files"),
        "name": _opt(fdp, "vermont.pbf"),
        "url": _opt(fdp, "https://example.invalid/a"),
        "check": _CHECKS[fdp.ConsumeIntInRange(0, len(_CHECKS) - 1)]
        if fdp.ConsumeBool()
        else _opt(fdp, "sha256"),
        "digest": _opt(fdp, "0" * 64),
        "checksum_url": _opt(fdp, None),
        "size": _opt(fdp, 10),
        "licence": _opt(fdp, "CC0  1.0\n"),
        "deferred": None if fdp.ConsumeBool() else _opt(fdp, "no grid square"),
    }
    for key in list(item):
        if fdp.ConsumeIntInRange(0, 20) == 0:
            del item[key]
    return item


def _document(fdp: atheris.FuzzedDataProvider) -> str:
    doc: dict[str, Any] = {
        "schema": engine.SCHEMA_MAJOR
        if fdp.ConsumeIntInRange(0, 9)
        else fdp.ConsumeUnicodeNoSurrogates(8),
        "kind": "artifacts" if fdp.ConsumeIntInRange(0, 9) else fdp.ConsumeUnicodeNoSurrogates(8),
        "engine": _opt(fdp, "0.19.0"),
        "artifacts": [_item(fdp) for _ in range(fdp.ConsumeIntInRange(0, 5))],
    }
    if fdp.ConsumeIntInRange(0, 12) == 0:
        doc["artifacts"] = _opt(fdp, "x")
    return json.dumps(doc)


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    text = _document(fdp) if fdp.ConsumeBool() else fdp.ConsumeUnicodeNoSurrogates(4096)
    try:
        listing = engine._parse(text)
    except engine.EngineError:
        return  # the documented refusal
    seen = set()
    for a in listing.artifacts:
        assert a.check in engine.CHECKS and a.url and a.name
        assert (a.unit, a.name) not in seen
        seen.add((a.unit, a.name))
    for d in listing.deferred:
        assert d.reason
    note = engine.newer_engine_note(listing.engine_version)
    assert listing.warnings == ((note,) if note else ())
    try:
        engine.meets_floor(listing.engine_version)
    except ValueError:
        pass  # the documented refusal of a string that is not a version


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
