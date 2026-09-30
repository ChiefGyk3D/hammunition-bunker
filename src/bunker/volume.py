# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The volume: where each artifact lives, its sidecar, its one previous copy.

Layout, all under ``<root>``::

    <unit>/<name>/<file>              the current copy; <file> is the publisher
                                      URL's own name (vermont-260101.osm.pbf)
    <unit>/<name>/<file>.sha256       sidecar: sha256 of the bytes, whatever
                                      the publisher's check was
    <unit>/<name>/<old>.previous      the last good copy, and its .sha256
    .incoming/<unit>/                 downloads in flight (the engine's fetch)
    .lock  .runs.jsonl                the run lock and the run log
    index.json  status.html           what is served as navigation

One directory per artifact, so a name never collides with another's file
and the on-disk name (dated, ``-latest``, a tile name) never leaks into the
mirror contract, which is ``<unit>/<name>`` mapped through the index.

Every unit and name comes from the engine's document and is refused here if
it could step outside ``<root>`` or into a hidden path: nothing the engine
says is trusted to be a safe path.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import re
from collections.abc import Callable
from pathlib import Path
from types import TracebackType

from bunker.enginelib import safe_name

__all__ = [
    "HIDDEN",
    "RESERVED",
    "Locked",
    "RunLock",
    "UnsafeName",
    "artifact_dir",
    "disk_used",
    "file_name",
    "hash_file",
    "install",
    "read_sidecar",
    "sidecar",
    "write_atomic",
    "write_sidecar",
]

HIDDEN = (".incoming", ".lock", ".runs.jsonl")
RESERVED = ("index.json", "status.html")
PREVIOUS = ".previous"
SIDECAR = ".sha256"

_UNIT = re.compile(r"[a-z0-9][a-z0-9._-]*")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1024 * 1024


class UnsafeName(ValueError):
    """A unit or name that could leave the volume or reach a hidden path."""


class Locked(Exception):
    """Another run holds the volume's lock."""


def artifact_dir(root: Path, unit: str, name: str) -> Path:
    """``<root>/<unit>/<name>``, or UnsafeName."""
    if not _UNIT.fullmatch(unit) or unit in RESERVED:
        raise UnsafeName(f"unit {unit!r} is not a catalog unit name")
    segments = name.split("/")
    for segment in segments:
        if (
            not segment
            or segment.startswith(".")
            or "\\" in segment
            or "\x00" in segment
            or len(segment.encode()) > 200
        ):
            raise UnsafeName(
                f"{unit}/{name!r} has an empty, hidden, over-long or '..' segment; "
                f"refusing to store it"
            )
    return root.joinpath(unit, *segments)


def file_name(url: str) -> str:
    """The on-disk name of the current copy: the publisher URL's own file
    name, made safe as one path segment by the engine's own rule."""
    return safe_name(url)


def hash_file(path: Path) -> tuple[str, str]:
    """``(sha256, md5)`` of *path*, in one read."""
    sha = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def sidecar(path: Path) -> Path:
    return path.with_name(path.name + SIDECAR)


def write_atomic(path: Path, data: bytes) -> None:
    """Write *data* to *path* through a temporary and a rename."""
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_sidecar(path: Path, sha256: str) -> None:
    """``<sha256>  <name>``, the format ``sha256sum -c`` reads."""
    write_atomic(sidecar(path), f"{sha256}  {path.name}\n".encode())


def read_sidecar(path: Path) -> str | None:
    """The digest *path*'s sidecar claims, or None when absent or malformed."""
    try:
        text = sidecar(path).read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return None
    first = text.split(maxsplit=1)[0] if text.strip() else ""
    return first if _HEX64.fullmatch(first) else None


def _remove(path: Path) -> None:
    path.unlink(missing_ok=True)
    sidecar(path).unlink(missing_ok=True)


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def install(
    root: Path,
    unit: str,
    name: str,
    incoming: Path,
    basename: str,
    sha256: str,
    *,
    keep_previous: bool,
    current: str | None,
    commit: Callable[[str, str | None], None],
) -> tuple[str, str | None]:
    """Move a verified download into place; return ``(path, previous)``,
    both relative to *root*.

    Order is what keeps something servable throughout: the new file is
    moved in, its sidecar written, then *commit* (the index update) runs
    while the old copy is still where the index said it was, and only then
    does the old copy become ``.previous`` -- one kept, older ones deleted.
    When the new copy has the old one's name, the old bytes are hard-linked
    to ``.previous`` before the rename replaces them.
    """
    folder = artifact_dir(root, unit, name)
    folder.mkdir(parents=True, exist_ok=True)
    new = folder / basename
    old = root / current if current else None
    if old is not None and (old.parent != folder or not old.is_file()):
        old = None  # never touch a path the index names outside this artifact

    stale = [p for p in folder.iterdir() if p.name.endswith(PREVIOUS)]
    previous: Path | None = None
    if keep_previous and old is not None:
        previous = old.with_name(old.name + PREVIOUS)
        stale = [p for p in stale if p != previous]
        if old == new:
            _remove(previous)
            os.link(old, previous)
            claimed = read_sidecar(old)
            if claimed is not None:
                write_sidecar(previous, claimed)

    os.replace(incoming, new)
    write_sidecar(new, sha256)
    commit(_rel(root, new), _rel(root, previous) if previous is not None else None)

    if old is not None and old != new:
        if previous is not None:
            _remove(previous)
            os.replace(old, previous)
            claimed = read_sidecar(old)
            sidecar(old).unlink(missing_ok=True)
            if claimed is not None:
                write_sidecar(previous, claimed)
        else:
            _remove(old)
    for path in stale:
        _remove(path)
    return _rel(root, new), (_rel(root, previous) if previous is not None else None)


def disk_used(root: Path) -> int:
    """Bytes in every file under *root*."""
    total = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except FileNotFoundError:
                continue
    return total


class RunLock:
    """One run at a time on a volume: ``flock`` on ``<root>/.lock``."""

    def __init__(self, root: Path) -> None:
        self.path = root / ".lock"
        self._fd: int | None = None

    def __enter__(self) -> RunLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                raise Locked(f"a run is in progress ({self.path} is held)") from None
            raise
        self._fd = fd
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
