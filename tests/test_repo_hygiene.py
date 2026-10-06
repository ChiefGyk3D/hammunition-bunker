# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Properties of the repository and of the suite itself."""

from __future__ import annotations

import re
import socket
import subprocess
import tomllib
from pathlib import Path

import pytest

import bunker
from bunker import engine
from tests.conftest import NetworkBlocked

ROOT = Path(__file__).resolve().parent.parent

#: Patterns that must match at any depth, each with the reason. Everything
#: else in .gitignore is anchored to the repository root with a leading "/":
#: in the parent project an unanchored `reference/` silently excluded
#: `docs/reference/`, and a trailing slash anchors nothing.
UNANCHORED = {
    "__pycache__/": "Python writes one beside every package, at every depth",
    "*.py[cod]": "compiled files sit beside their sources, at every depth",
}


def test_non_loopback_connect_is_blocked() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkBlocked),
    ):
        # A short timeout so a guard that stopped guarding fails in two
        # seconds (TimeoutError, not NetworkBlocked) rather than hanging.
        sock.settimeout(2)
        sock.connect(("192.0.2.1", 9))  # TEST-NET-1: never routable anyway


def test_loopback_connect_is_allowed() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=5):
            pass


def _patterns() -> list[str]:
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def test_gitignore_patterns_are_anchored() -> None:
    loose = [p for p in _patterns() if not p.startswith(("/", "!")) and p not in UNANCHORED]
    assert not loose, (
        f"unanchored .gitignore patterns {loose}: anchor each with a leading '/', or add "
        f"it to UNANCHORED in {Path(__file__).name} with the reason it must match anywhere"
    )


def test_nothing_tracked_is_ignored() -> None:
    out = subprocess.run(
        ["git", "ls-files", "-ci", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert out == [], f"tracked files a .gitignore pattern also matches: {out}"


def test_engine_floor_agrees() -> None:
    """One engine release pinned, three places: the code's contract, the
    pyproject pin and the image's build argument. The floor is separate (the
    oldest engine the Bunker works with) and may not exceed the pin."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pins = [d for d in project["dependencies"] if d.startswith("hammunition")]
    assert pins == [
        f"hammunition @ git+https://github.com/Renegade-Penguin/Hammunition@v{bunker.ENGINE_CONTRACT}"
    ]
    dockerfile = ROOT / "Dockerfile"
    if dockerfile.exists():
        found = re.search(r"^ARG ENGINE_VERSION=(\S+)$", dockerfile.read_text(), re.M)
        assert found is not None, "the Dockerfile names no ENGINE_VERSION"
        assert found.group(1) == bunker.ENGINE_CONTRACT
    assert engine.meets_floor(bunker.ENGINE_CONTRACT, bunker.ENGINE_FLOOR), (
        "ENGINE_FLOOR is above ENGINE_CONTRACT: the pinned engine would fail bunker doctor"
    )


def test_version_is_single_sourced() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "version" not in project and project["dynamic"] == ["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", bunker.__version__)
