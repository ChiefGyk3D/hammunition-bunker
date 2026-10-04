# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fuzz target: the ``--json`` envelope every Bunker document shares.

``envelope.document`` and ``run_json`` take a kind and a body from the commands
and must leave exactly one parseable document on stdout whatever a command
prints, returns or raises. The documented refusals are a body that shadows the
envelope (``ValueError``) and a second ``emit`` (``RuntimeError``); anything
else escaping is a bug. In-memory streams only: nothing touches a real stream.
"""

import io
import json
import sys
from typing import Any

import atheris

with atheris.instrument_imports():
    from bunker import envelope

_KEYS = ("schema", "kind", "engine", "a", "")


def _value(fdp: atheris.FuzzedDataProvider, depth: int = 0) -> Any:
    pick = fdp.ConsumeIntInRange(0, 6 if depth < 3 else 4)
    if pick == 0:
        return None
    if pick == 1:
        return fdp.ConsumeBool()
    if pick == 2:
        return fdp.ConsumeIntInRange(-(2**40), 2**40)
    if pick == 3:
        return fdp.ConsumeFloat()
    if pick == 4:
        return fdp.ConsumeUnicodeNoSurrogates(24)
    if pick == 5:
        return [_value(fdp, depth + 1) for _ in range(fdp.ConsumeIntInRange(0, 3))]
    return {
        fdp.ConsumeUnicodeNoSurrogates(6): _value(fdp, depth + 1)
        for _ in range(fdp.ConsumeIntInRange(0, 3))
    }


def _body(fdp: atheris.FuzzedDataProvider) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for _ in range(fdp.ConsumeIntInRange(0, 4)):
        key = (
            _KEYS[fdp.ConsumeIntInRange(0, len(_KEYS) - 1)]
            if fdp.ConsumeBool()
            else fdp.ConsumeUnicodeNoSurrogates(6)
        )
        body[key] = _value(fdp)
    return body


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    kind = fdp.ConsumeUnicodeNoSurrogates(12)
    body = _body(fdp)
    try:
        text = envelope.dumps(kind, body)
    except ValueError:
        assert any(k in body for k in ("schema", "kind", "engine"))
    else:
        doc = json.loads(text)
        assert list(doc)[:3] == ["schema", "kind", "engine"]
        assert doc["schema"] == envelope.SCHEMA and doc["kind"] == kind

    printed = fdp.ConsumeUnicodeNoSurrogates(40)
    code = fdp.ConsumeIntInRange(0, 255)
    emits = fdp.ConsumeIntInRange(0, 2)
    out, err = io.StringIO(), io.StringIO()

    def command(emit: Any) -> int:
        print(printed, end="")
        for _ in range(emits):
            emit(kind, body)
        return code

    try:
        got = envelope.run_json("fuzz", command, stdout=out, stderr=err)
    except (ValueError, RuntimeError):
        return  # a shadowing body, or a second document: the documented refusals
    assert got == code
    doc = json.loads(out.getvalue())  # exactly one document, even when the command emitted none
    if emits == 0:
        assert doc["kind"] == "error" and doc["exit_code"] == code and doc["message"] == printed
    assert printed in err.getvalue() or not printed


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
