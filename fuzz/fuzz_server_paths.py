# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fuzz target: what the mirror's HTTP server does with a request.

The server is the stdlib's, so the request line is not parsed here; what is the
Bunker's is the path it maps through ``index.json`` and the ``Range`` header it
reads. Three properties: ``parse_range`` returns a range that sits inside the
file or one of its two documented answers; ``_safe`` never returns a path
outside the volume or one that is hidden; and a request path that
``Routes.lookup`` resolves, however hostile the index, still goes through
``_safe`` to a path under the root. The index is bytes written to a temp
directory the target made; nothing is opened or served.
"""

import json
import sys
import tempfile
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from bunker import server

_TMP = tempfile.TemporaryDirectory(prefix="fuzz-bunker-server-")
_ROOT = Path(_TMP.name)
_ROUTES = server.Routes(_ROOT)
_ROUTES_LOCK_FILE = _ROOT / "index.json"


def _under_root(path: Path) -> bool:
    parts = path.relative_to(_ROOT).parts
    return all(p not in ("", ".", "..") and not p.startswith(".") for p in parts)


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)

    size = fdp.ConsumeIntInRange(0, 2**34)
    header = (
        fdp.ConsumeUnicodeNoSurrogates(24)
        if fdp.ConsumeBool()
        else f"bytes={fdp.ConsumeIntInRange(-5, 2**35)}-{fdp.ConsumeIntInRange(-5, 2**35) if fdp.ConsumeBool() else ''}"
    )
    wanted = server.parse_range(header, size)
    if isinstance(wanted, tuple):
        first, last = wanted
        assert 0 <= first <= last < size, (header, size, wanted)
    else:
        assert wanted is None or wanted == server.UNSATISFIABLE

    relative = fdp.ConsumeUnicodeNoSurrogates(40)
    safe = server._safe(_ROOT, relative)
    if safe is not None:
        assert safe.is_relative_to(_ROOT) and _under_root(safe), relative

    entries = [
        {
            "unit": fdp.ConsumeUnicodeNoSurrogates(8),
            "name": fdp.ConsumeUnicodeNoSurrogates(8),
            "path": fdp.ConsumeUnicodeNoSurrogates(16),
            "status": "corrupted" if fdp.ConsumeIntInRange(0, 5) == 0 else "current",
        }
        for _ in range(fdp.ConsumeIntInRange(0, 4))
    ]
    text = json.dumps({"artifacts": entries}) if fdp.ConsumeBool() else None
    if text is None:
        _ROUTES_LOCK_FILE.write_bytes(fdp.ConsumeBytes(1024))
    else:
        _ROUTES_LOCK_FILE.write_text(text, encoding="utf-8")
    _ROUTES._stamp = None  # force a rebuild: the same file name and size can repeat
    request = (
        (entries[0]["unit"] + "/" + entries[0]["name"])
        if entries and fdp.ConsumeBool()
        else fdp.ConsumeUnicodeNoSurrogates(24)
    )
    target = _ROUTES.lookup(request)
    if target is not None:
        resolved = server._safe(_ROOT, target.path)
        if resolved is not None:
            assert resolved.is_relative_to(_ROOT) and _under_root(resolved), target.path


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
