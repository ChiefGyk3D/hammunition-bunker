# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fetch the Hammunition release the image pins, verify it, unpack it.

Run by the Dockerfile before anything else is installed, so it is stdlib
only. Usage::

    python3 fetch_engine.py URL SHA256 DEST

The archive is refused unless its sha256 equals SHA256, and SHA256 must be
64 lowercase hex characters: the Dockerfile's placeholder refuses the build
by name rather than letting an unverified engine in. Nothing reaches DEST
until the hash matched; members are unpacked with tarfile's ``data``
filter, which refuses absolute paths, ``..`` and links out of the tree, and
the archive's one top-level directory is stripped.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import warnings
from collections.abc import Sequence
from pathlib import Path

_HEX64 = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1024 * 1024
_LIMIT = 256 * 1024 * 1024


def _refuse(message: str) -> SystemExit:
    return SystemExit(f"fetch_engine: {message}")


def _extract_safely(tar: tarfile.TarFile, dest: Path) -> None:
    """Unpack with the ``data`` filter, or the same rules by hand where it does not exist.

    The filter arrived in Python 3.11.4. Debian 12 ships 3.11.2, so there the
    members are checked here before a plain extractall: every path must stay
    under ``dest``, a link must point inside it, and devices and FIFOs are
    refused. That is what the ``data`` filter refuses too.
    """
    try:
        tar.extractall(dest, filter="data")
        return
    except TypeError:
        pass  # no extraction filters on this interpreter
    root = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if target != root and root not in target.parents:
            raise tarfile.TarError(f"{member.name!r} escapes the destination")
        if member.isdev() or member.isfifo():
            raise tarfile.TarError(f"{member.name!r} is a device or FIFO")
        if member.issym() or member.islnk():
            link = (target.parent / member.linkname).resolve()
            if link != root and root not in link.parents:
                raise tarfile.TarError(f"{member.name!r} links outside the destination")
    with warnings.catch_warnings():
        # Newer interpreters warn that no filter was given; every member was
        # checked above, which is what the filter would have done.
        warnings.simplefilter("ignore", DeprecationWarning)
        tar.extractall(dest)  # noqa: S202


def main(argv: Sequence[str]) -> None:
    if len(argv) != 3:
        raise _refuse("usage: fetch_engine.py URL SHA256 DEST")
    url, expected, dest_text = argv
    if not _HEX64.fullmatch(expected):
        raise _refuse(
            f"ENGINE_SHA256 is {expected!r}, not a sha256. Fill it in the Dockerfile (or pass "
            f"--build-arg ENGINE_SHA256=...) with the sha256 of the engine release archive; "
            f"docs/guide.md says how to compute it. An unverified engine is never installed."
        )
    if urllib.parse.urlsplit(url).scheme not in ("https", "http"):
        raise _refuse(f"{url!r}: only https (or http, for a test) URLs are fetched")
    dest = Path(dest_text)
    if dest.exists():
        raise _refuse(f"{dest} already exists")

    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "engine.tar.gz"
        digest = hashlib.sha256()
        size = 0
        # The scheme was checked above. The opener has HTTP handlers only (the
        # engine's rule): a redirect to file:, ftp: or data: has nothing to
        # answer it.
        opener = urllib.request.OpenerDirector()
        for handler in (
            urllib.request.HTTPHandler(),
            urllib.request.HTTPSHandler(),
            urllib.request.HTTPRedirectHandler(),
            urllib.request.HTTPErrorProcessor(),
            urllib.request.HTTPDefaultErrorHandler(),
        ):
            opener.add_handler(handler)
        request = urllib.request.Request(  # noqa: S310 - scheme checked above
            url, headers={"User-Agent": "hammunition-bunker-build"}
        )
        response = opener.open(request, timeout=120)
        if response is None:
            raise _refuse(f"no handler would fetch {url!r}")
        with response, archive.open("wb") as out:
            while chunk := response.read(_CHUNK):
                size += len(chunk)
                if size > _LIMIT:
                    raise _refuse(f"{url} is over {_LIMIT} bytes; refusing")
                digest.update(chunk)
                out.write(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise _refuse(
                f"{url} does not match ENGINE_SHA256.\n  expected: {expected}\n"
                f"  actual:   {actual}\nNothing was installed."
            )
        unpacked = Path(scratch) / "tree"
        unpacked.mkdir()
        try:
            with tarfile.open(archive, "r:gz") as tar:
                _extract_safely(tar, unpacked)
        except (tarfile.TarError, OSError) as exc:
            raise _refuse(f"{url}: the archive could not be unpacked safely: {exc}") from None
        tops = list(unpacked.iterdir())
        if len(tops) != 1 or not tops[0].is_dir():
            raise _refuse(f"{url}: expected one top-level directory, found {len(tops)} entries")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tops[0]), dest)
    print(f"fetch_engine: {url} verified (sha256 {actual}) and unpacked to {dest}")


if __name__ == "__main__":
    main(sys.argv[1:])
