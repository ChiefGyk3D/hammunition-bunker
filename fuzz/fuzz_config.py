# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fuzz target: ``bunker.toml``, the one file the operator edits.

``config.load`` must return a Config whose every value passed its check, or
raise ``ConfigError`` naming the key; any other exception is a traceback shown
to an operator who made a typo. The input is raw bytes half the time and a
mostly valid document with one wrong value the other half, so the per-key
checks are reached. The file lives in a temp directory the target made.
"""

import sys
import tempfile
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from bunker import config

_TMP = tempfile.TemporaryDirectory(prefix="fuzz-bunker-config-")
_FILE = Path(_TMP.name) / "bunker.toml"

_TABLES = {
    "engine": ("command", "catalog", "timeout"),
    "selection": ("map_regions", "map_freshness", "reference_books", "units", "hold_unverified"),
    "storage": ("root", "keep_previous", "downloads", "max_rate"),
    "schedule": ("default", "run_at", "units"),
    "verify": ("default", "units"),
    "serve": ("bind", "port"),
}
_VALUES = (
    '"hammunition"',
    '"a b"',
    '"\\""',
    '["hammunition", "--x"]',
    "[]",
    "[1]",
    '""',
    "0",
    "1",
    "4",
    "5",
    "-1",
    "8080",
    "65536",
    "1.5",
    "1e400",
    "true",
    "false",
    '"weekly"',
    '"yearly"',
    '"every-run"',
    '"20M"',
    '"0"',
    '"03:00"',
    "03:00:00",
    "1979-05-27",
    '"vermont"',
    '["vermont", "delaware"]',
    '{ "kiwix-library" = "daily" }',
    '{ "Bad Unit" = "daily" }',
    "{ a = 1 }",
    '"/data"',
    '"../x"',
)


def _structured(fdp: atheris.FuzzedDataProvider) -> bytes:
    lines: list[str] = []
    for _ in range(fdp.ConsumeIntInRange(0, 6)):
        table = list(_TABLES)[fdp.ConsumeIntInRange(0, len(_TABLES) - 1)]
        lines.append(
            f"[{table}]"
            if fdp.ConsumeIntInRange(0, 9)
            else f"[{fdp.ConsumeUnicodeNoSurrogates(5)}]"
        )
        for _ in range(fdp.ConsumeIntInRange(0, 3)):
            keys = _TABLES[table]
            key = keys[fdp.ConsumeIntInRange(0, len(keys) - 1)]
            if fdp.ConsumeIntInRange(0, 9) == 0:
                key = fdp.ConsumeUnicodeNoSurrogates(5)
            value = _VALUES[fdp.ConsumeIntInRange(0, len(_VALUES) - 1)]
            if fdp.ConsumeIntInRange(0, 7) == 0:
                value = fdp.ConsumeUnicodeNoSurrogates(8)
            elif fdp.ConsumeIntInRange(0, 15) == 0:
                depth = fdp.ConsumeIntInRange(1, 700)  # tomllib recurses once per nested array
                value = "[" * depth + "]" * depth
            lines.append(f"{key} = {value}")
    return "\n".join(lines).encode("utf-8", errors="replace")


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    _FILE.write_bytes(_structured(fdp) if fdp.ConsumeBool() else fdp.ConsumeBytes(2048))
    try:
        cfg = config.load(_FILE)
    except config.ConfigError:
        return  # the documented refusal
    assert cfg.engine.command and all(cfg.engine.command)
    assert cfg.engine.timeout > 0
    assert 1 <= cfg.storage.downloads <= config.MAX_DOWNLOADS
    assert cfg.storage.max_rate is None or cfg.storage.max_rate > 0
    assert 1 <= cfg.serve.port <= 65535
    assert cfg.selection.map_freshness in config.FRESHNESS
    assert cfg.schedule.default in config.CADENCES
    assert cfg.schedule.verify_default in config.VERIFY_CADENCES
    assert all(c in config.CADENCES for c in cfg.schedule.units.values())
    assert all(c in config.VERIFY_CADENCES for c in cfg.schedule.verify_units.values())

    text = fdp.ConsumeUnicodeNoSurrogates(16)
    try:
        assert config.parse_rate(text) > 0
    except ValueError:
        pass  # the documented refusal of a rate


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
