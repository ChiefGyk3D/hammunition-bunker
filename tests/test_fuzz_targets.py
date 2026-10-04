# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Atheris targets under fuzz/ still run, so a target that rots is caught here.

GYST's python-fuzz.yml runs each target for a fixed time in CI; this is the
cheap half that runs on every ordinary test run. Each target's ``TestOneInput``
is called on a handful of seeds (empty, a valid document, a truncated one, 64 KiB
of random bytes) and must not raise.

Atheris publishes wheels for CPython 3.12 to 3.14 on x86_64 only, so elsewhere
the module skips. On a machine that *can* have it, a missing Atheris is a
failure: a skip that could hide on the one runner that matters is no check.
"""

from __future__ import annotations

import importlib
import importlib.util
import platform
import random
import sys
from pathlib import Path
from types import ModuleType

import pytest

FUZZ_DIR = Path(__file__).resolve().parent.parent / "fuzz"
TARGETS = sorted(FUZZ_DIR.glob("fuzz_*.py"))
CAN_HAVE_ATHERIS = platform.machine() == "x86_64" and (3, 12) <= sys.version_info[:2] <= (3, 14)

if importlib.util.find_spec("atheris") is None:
    if CAN_HAVE_ATHERIS:
        raise ImportError(
            "atheris is not installed, and this platform has a wheel: pip install -e '.[dev]'"
        )
    pytest.skip("atheris has no wheel for this platform", allow_module_level=True)

VALID = {
    "fuzz_envelope": b"\x01\x02ab\x03",
    "fuzz_config": b"\x01\x04\x01\x00\x01\x00",
    "fuzz_engine_document": b"\x01" + b"\x09" * 40,
    "fuzz_index_status": b"\x01" + b"\x09" * 60,
    "fuzz_server_paths": b"\x00" * 20 + b"\x01" + b"vermont/a.pbf",
}


def _seeds(name: str) -> list[bytes]:
    valid = VALID[name]
    rng = random.Random(0)  # noqa: S311 - a fixed seed for reproducible test input
    return [
        b"",
        valid,
        valid[: len(valid) // 2],
        bytes(rng.randrange(256) for _ in range(64 * 1024)),
    ]


def test_every_target_has_seeds() -> None:
    assert {t.stem for t in TARGETS} == set(VALID), "a target was added or removed: update VALID"


@pytest.mark.parametrize("target", TARGETS, ids=lambda p: p.stem)
def test_target_accepts_seeds(target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(FUZZ_DIR))
    sys.modules.pop(target.stem, None)
    module: ModuleType = importlib.import_module(target.stem)
    try:
        for seed in _seeds(target.stem):
            module.TestOneInput(seed)
    finally:
        sys.modules.pop(target.stem, None)
