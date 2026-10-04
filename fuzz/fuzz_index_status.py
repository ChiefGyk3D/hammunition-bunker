# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fuzz target: ``index.json`` and the status page rendered from it.

``index.load`` reads the volume's own document, which a crash, a full disk or
an operator's editor can leave in any state. It must return an Index or raise
``IndexRefused`` (whose message tells the operator to move the file aside);
anything else is a traceback at startup. A loaded Index must then render to a
status page without raising, and the page has no script of its own, so any
``<script`` in the output is a value that was not escaped. The index is bytes
written to a temp directory the target made.
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import atheris

with atheris.instrument_imports():
    from bunker import index, statuspage

_TMP = tempfile.TemporaryDirectory(prefix="fuzz-bunker-index-")
_ROOT = Path(_TMP.name)
_PAYLOAD = "<script>x</script>"


def _val(fdp: atheris.FuzzedDataProvider, good: Any) -> Any:
    pick = fdp.ConsumeIntInRange(0, 9)
    if pick < 6:
        return good
    if pick == 6:
        return None
    if pick == 7:
        return fdp.ConsumeIntInRange(-3, 2**40)
    if pick == 8:
        return _PAYLOAD
    return fdp.ConsumeUnicodeNoSurrogates(8)


def _entry(fdp: atheris.FuzzedDataProvider) -> Any:
    if fdp.ConsumeIntInRange(0, 15) == 0:
        return fdp.ConsumeUnicodeNoSurrogates(4)
    entry: dict[str, Any] = {
        "unit": _val(fdp, "country-files"),
        "name": _val(fdp, "cty.dat"),
        "path": _val(fdp, "country-files/cty.dat"),
        "sha256": _val(fdp, "0" * 64),
        "size": _val(fdp, 12),
        "publisher_check": _val(fdp, "sha256"),
        "publisher_digest": _val(fdp, "0" * 64),
        "publisher_url": _val(fdp, "https://example.invalid/cty.dat"),
        "licence": _val(fdp, "CC0-1.0"),
        "fetched": _val(fdp, "2026-10-04T00:00:00Z"),
        "verified": _val(fdp, "2026-10-04T00:00:00Z"),
        "status": index.STATUSES[fdp.ConsumeIntInRange(0, 3)]
        if fdp.ConsumeIntInRange(0, 9)
        else _val(fdp, "x"),
        "reason": _val(fdp, None),
        "previous": _val(fdp, None),
    }
    for key in list(entry):
        if fdp.ConsumeIntInRange(0, 30) == 0:
            del entry[key]
    return entry


def _document(fdp: atheris.FuzzedDataProvider) -> bytes:
    version = index.INDEX_VERSION if fdp.ConsumeIntInRange(0, 3) else fdp.ConsumeIntInRange(0, 3)
    doc: dict[str, Any] = {
        "kind": index.KIND if fdp.ConsumeIntInRange(0, 15) else "other",
        "version": version if fdp.ConsumeIntInRange(0, 15) else _val(fdp, 2),
        "generated": _val(fdp, "2026-10-04T00:00:00Z"),
        "engine": _val(fdp, {"version": "0.19.0"}),
        "artifacts": [_entry(fdp) for _ in range(fdp.ConsumeIntInRange(0, 4))],
        "deferred": _val(fdp, [{"unit": "u", "name": None, "reason": "r"}]),
        "declined": _val(fdp, [{"unit": "u", "name": "n", "reason": "r"}]),
        "last_run": _val(fdp, {"started": "a", "finished": "b", "plain_http": ["http://x"]}),
    }
    if fdp.ConsumeIntInRange(0, 6) == 0:
        doc["deferred"] = [_val(fdp, {"unit": "u", "reason": _PAYLOAD}) for _ in range(2)]
    return json.dumps(doc).encode()


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    (_ROOT / "index.json").write_bytes(
        _document(fdp) if fdp.ConsumeBool() else fdp.ConsumeBytes(4096)
    )
    try:
        loaded = index.load(_ROOT)
    except index.IndexRefused:
        return  # the documented refusal
    html = statuspage.render(loaded, disk_used=0)
    assert "<script" not in html.lower(), "a value reached the status page unescaped"


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
