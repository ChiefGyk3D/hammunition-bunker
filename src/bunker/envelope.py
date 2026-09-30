# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The envelope every ``--json`` document shares, in Hammunition's shape (D-059).

Every document is ``{"schema": "bunker/1", "kind": ..., "engine": ...}``
followed by its own fields. ``engine`` names the version of the program
that wrote the document -- here the Bunker, exactly as a Hammunition
document names Hammunition -- so a reader of the engine's documents reads
these the same way, and refuses the ``bunker`` schema by name if it only
knows ``hammunition``. The Hammunition version a run asked is a field of
the documents that have one (``engine_version``).

Under ``--json`` the command's ``sys.stdout`` points at stderr, so anything
it prints is a diagnostic; the one document goes to the real stdout. A
command that ends without one gets an ``error`` document carrying its exit
code and everything it wrote to stderr, so stdout parses as exactly one
document on every path.
"""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable, Mapping
from typing import Any, TextIO

from bunker import __version__

__all__ = ["SCHEMA", "document", "dumps", "run_json"]

SCHEMA = "bunker/1"
_ENVELOPE = ("schema", "kind", "engine")


def document(kind: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """The envelope plus *body*."""
    clash = [k for k in _ENVELOPE if k in body]
    if clash:
        raise ValueError(f"a document body may not carry the envelope field {clash[0]!r}")
    return {"schema": SCHEMA, "kind": kind, "engine": __version__, **body}


def dumps(kind: str, body: Mapping[str, Any]) -> str:
    """One document as printed: indented, UTF-8, never ASCII-escaped."""
    return json.dumps(document(kind, body), indent=2, ensure_ascii=False)


class _Tee(io.TextIOBase):
    """The real stderr, recorded."""

    def __init__(self, stream: TextIO) -> None:
        super().__init__()
        self._stream = stream
        self._parts: list[str] = []

    def write(self, text: str) -> int:
        self._parts.append(text)
        return self._stream.write(text)

    def flush(self) -> None:
        self._stream.flush()

    def text(self) -> str:
        return "".join(self._parts)


def run_json(
    command: str,
    func: Callable[[Callable[[str, Mapping[str, Any]], None]], int],
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run *func* as a ``--json`` command and return its exit code.

    *func* is handed ``emit(kind, body)``, to be called at most once.
    """
    out = stdout if stdout is not None else sys.stdout
    tee = _Tee(stderr if stderr is not None else sys.stderr)
    emitted = False

    def emit(kind: str, body: Mapping[str, Any]) -> None:
        nonlocal emitted
        if emitted:
            raise RuntimeError("a --json run prints exactly one document")
        out.write(dumps(kind, body) + "\n")
        out.flush()
        emitted = True

    saved = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = tee  # type: ignore[assignment]
    code = 1
    try:
        code = func(emit)
        return code
    finally:
        sys.stdout, sys.stderr = saved
        if not emitted:
            emit("error", {"command": command, "exit_code": code, "message": tee.text()})
