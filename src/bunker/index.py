# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""``index.json``: the Bunker's own document, versioned, one per volume.

It is what the server maps ``<unit>/<name>`` through, what ``status.html``
is rendered from, and what the next run reads to know what it holds. It is
never the proof of anything: every file it names has a sidecar, and the
bytes are re-hashed against the sidecar on a cadence.

Version 1 is the first. A later version adds an entry to :data:`UPGRADES`
(vN to vN+1); an older index is upgraded in place on load and written back,
and a newer one refuses, because a Bunker cannot know what fields it would
be dropping.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from bunker.volume import write_atomic

__all__ = [
    "INDEX_VERSION",
    "KIND",
    "STATUSES",
    "UPGRADES",
    "Entry",
    "Index",
    "IndexRefused",
    "ensure",
    "load",
    "save",
]

INDEX_VERSION = 1
KIND = "bunker-index"
FILE = "index.json"
#: ``current``: the copy matches what the engine lists. ``stale``: the
#: engine lists a newer version the schedule has not fetched yet.
#: ``failed``: the last fetch failed; the copy named (if any) is the last
#: good one. ``corrupted``: the bytes no longer match the sidecar.
STATUSES = ("current", "stale", "failed", "corrupted")

#: vN -> vN+1, applied in order by :func:`load`.
UPGRADES: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


class IndexRefused(Exception):
    """The index on the volume cannot be read by this Bunker."""


@dataclass
class Entry:
    """One artifact on the volume."""

    unit: str
    name: str
    path: str | None
    """The current copy, relative to the volume root; None when there is none."""
    sha256: str | None
    """sha256 of the current copy's bytes (the sidecar's claim when written)."""
    size: int | None
    publisher_check: str
    """How the engine verifies it: sha256, md5-publisher, etag-md5, sha256-publisher."""
    publisher_digest: str | None
    """The digest of that kind the current copy was verified against."""
    publisher_url: str
    licence: str
    fetched: str | None
    verified: str | None
    status: str
    reason: str | None
    """Why the status is not ``current``; None when it is."""
    previous: str | None


@dataclass
class Index:
    engine_version: str | None = None
    artifacts: list[Entry] = field(default_factory=list)
    deferred: list[dict[str, str | None]] = field(default_factory=list)
    last_run: dict[str, Any] | None = None
    generated: str | None = None

    def find(self, unit: str, name: str) -> Entry | None:
        for entry in self.artifacts:
            if entry.unit == unit and entry.name == name:
                return entry
        return None


_ENTRY_FIELDS = tuple(f.name for f in fields(Entry))


def _refuse(path: Path, detail: str) -> IndexRefused:
    return IndexRefused(
        f"{path} is not an index this Bunker can read ({detail}). Move it aside "
        f"(mv {path} {path}.bad): the next run re-hashes every file on the volume "
        f"against its sidecar and writes a new one."
    )


def _entry(path: Path, raw: Any, position: int) -> Entry:
    if not isinstance(raw, dict):
        raise _refuse(path, f"artifact {position} is not an object")
    missing = [k for k in _ENTRY_FIELDS if k not in raw]
    if missing:
        raise _refuse(path, f"artifact {position} has no {missing[0]!r}")
    if raw["status"] not in STATUSES:
        raise _refuse(path, f"artifact {position} has status {raw['status']!r}")
    return Entry(**{k: raw[k] for k in _ENTRY_FIELDS})


def load(root: Path) -> Index:
    """The volume's index: empty when absent, upgraded when older, refused
    when corrupt or newer."""
    path = root / FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Index()
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _refuse(path, f"not JSON: {exc}") from None
    if not isinstance(raw, dict) or raw.get("kind") != KIND:
        raise _refuse(path, f"its kind is not {KIND!r}")
    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _refuse(path, "it has no version")
    if version > INDEX_VERSION:
        raise IndexRefused(
            f"{path} is index version {version}, written by a newer Bunker; this one "
            f"reads version {INDEX_VERSION} and would drop what it does not know. "
            f"Run the newer release, or move the index aside."
        )
    upgraded = version < INDEX_VERSION
    while version < INDEX_VERSION:
        step = UPGRADES.get(version)
        if step is None:
            raise IndexRefused(
                f"{path} is index version {version} and this Bunker has no upgrade "
                f"from it; move it aside and the next run writes a new one."
            )
        raw = step(raw)
        version += 1
    artifacts = raw.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise _refuse(path, "its artifacts are not a list")
    engine = raw.get("engine")
    index = Index(
        engine_version=engine.get("version") if isinstance(engine, dict) else None,
        artifacts=[_entry(path, a, n) for n, a in enumerate(artifacts)],
        deferred=list(raw.get("deferred") or []),
        last_run=raw.get("last_run"),
        generated=raw.get("generated"),
    )
    if upgraded:
        save(root, index, generated=index.generated or "")
    return index


def save(root: Path, index: Index, *, generated: str) -> None:
    """Write the index atomically: a reader sees the old one or the new one."""
    index.generated = generated
    body = {
        "kind": KIND,
        "version": INDEX_VERSION,
        "generated": generated,
        "engine": {"version": index.engine_version},
        "artifacts": [asdict(e) for e in index.artifacts],
        "deferred": index.deferred,
        "last_run": index.last_run,
    }
    root.mkdir(parents=True, exist_ok=True)
    text = json.dumps(body, indent=2, ensure_ascii=False) + "\n"
    write_atomic(root / FILE, text.encode("utf-8"))


def ensure(root: Path, *, generated: str) -> None:
    """Write an empty index when there is none, so a fresh volume serves
    ``/index.json`` (the container's healthcheck) before its first run."""
    if not (root / FILE).exists():
        save(root, Index(), generated=generated)
