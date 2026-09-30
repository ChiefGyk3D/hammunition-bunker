# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable, Mapping
from typing import Any

import pytest

import bunker
from bunker import envelope

Emit = Callable[[str, Mapping[str, Any]], None]


def test_envelope_shape_is_d059s() -> None:
    doc = envelope.document("status", {"a": 1})
    assert list(doc) == ["schema", "kind", "engine", "a"]
    assert doc["schema"] == "bunker/1"
    assert doc["kind"] == "status"
    assert doc["engine"] == bunker.__version__


def test_body_may_not_shadow_the_envelope() -> None:
    with pytest.raises(ValueError, match="kind"):
        envelope.document("status", {"kind": "x"})


def _run(func: Callable[[Emit], int]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = envelope.run_json("status", func, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_one_document_on_stdout_even_when_the_command_prints() -> None:
    def command(emit: Emit) -> int:
        print("a stray line of the text form")
        emit("status", {"ok": True})
        return 0

    code, out, err = _run(command)
    assert code == 0
    assert json.loads(out)["ok"] is True
    assert "stray line" in err


def test_no_document_means_an_error_document() -> None:
    def command(emit: Emit) -> int:
        print("error: the index is newer than this Bunker", file=sys.stderr)
        return 2

    code, out, _ = _run(command)
    doc = json.loads(out)
    assert code == 2
    assert doc["kind"] == "error"
    assert doc["command"] == "status"
    assert doc["exit_code"] == 2
    assert "newer than this Bunker" in doc["message"]


def test_an_exception_still_leaves_one_document() -> None:
    def command(emit: Emit) -> int:
        raise RuntimeError("boom")

    out = io.StringIO()
    with pytest.raises(RuntimeError):
        envelope.run_json("run", command, stdout=out, stderr=io.StringIO())
    assert json.loads(out.getvalue())["kind"] == "error"


def test_a_second_document_is_a_bug() -> None:
    def command(emit: Emit) -> int:
        emit("status", {})
        emit("status", {})
        return 0

    with pytest.raises(RuntimeError, match="exactly one"):
        _run(command)


def test_stdout_is_restored() -> None:
    before = sys.stdout
    _run(lambda emit: 0)
    assert sys.stdout is before
