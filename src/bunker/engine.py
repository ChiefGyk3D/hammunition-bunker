# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asking the engine what to keep: ``hammunition artifacts --json`` (D-070).

This is the Bunker's only source of what to mirror, so it is read strictly:
a non-zero exit, a document that is not JSON, a schema major this Bunker
does not know, an ``error`` document or an entry missing a field fails the
whole run, loudly, with what the engine said. A field the engine added
within its major is tolerated (D-059 allows that), and an entry whose
``check`` this Bunker does not know is deferred by name rather than
guessed at: nothing is downloaded that cannot be verified. That entry is
*refused* by name, with the engine's version, and fails the run's exit code:
a kind this Bunker does not know means the engine has outgrown it, and a
mirror that quietly stopped keeping something is the failure to avoid.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from bunker import ENGINE_CONTRACT, ENGINE_FLOOR
from bunker.checks import KINDS
from bunker.config import Config

__all__ = [
    "CHECKS",
    "Artifact",
    "Deferred",
    "EngineError",
    "Listing",
    "argv",
    "ask_engine",
    "engine_version",
    "meets_floor",
    "newer_engine_note",
]

#: The checks this Bunker knows how to verify, as the contract names them:
#: the keys of the table in :mod:`bunker.checks`.
CHECKS = tuple(KINDS)
SCHEMA_MAJOR = "hammunition/1"

_FIELDS: dict[str, tuple[type, ...]] = {
    "unit": (str,),
    "name": (str, type(None)),
    "url": (str, type(None)),
    "check": (str, type(None)),
    "digest": (str, type(None)),
    "checksum_url": (str, type(None)),
    "size": (int, type(None)),
    "licence": (str,),
    "deferred": (str, type(None)),
}
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class EngineError(Exception):
    """The engine could not be asked, or its answer cannot be used."""


@dataclass(frozen=True)
class Artifact:
    """One artifact the engine would fetch, as it listed it."""

    unit: str
    name: str
    url: str
    check: str
    digest: str | None
    checksum_url: str | None
    size: int | None
    licence: str


@dataclass(frozen=True)
class Deferred:
    """What the selection cannot list, and why."""

    unit: str
    name: str | None
    reason: str
    refused: bool = False
    """The Bunker refused it (a check kind it does not know), as opposed to the
    engine having deferred it."""


@dataclass(frozen=True)
class Listing:
    engine_version: str
    artifacts: tuple[Artifact, ...]
    deferred: tuple[Deferred, ...]
    licences: Mapping[str, str]
    """Each unit's licence line, as the plan prints it."""
    warnings: tuple[str, ...] = ()
    """Notes that are not failures: the engine is newer than this Bunker knows."""


def argv(cfg: Config) -> list[str]:
    """The command line the Bunker runs."""
    out = list(cfg.engine.command)
    if cfg.engine.catalog is not None:
        out += ["--catalog", str(cfg.engine.catalog)]
    out += ["artifacts", "--json", "--map-freshness", cfg.selection.map_freshness]
    if cfg.selection.map_regions:
        out += ["--map-regions", ",".join(cfg.selection.map_regions)]
    if cfg.selection.reference_books:
        out += ["--reference-books", ",".join(cfg.selection.reference_books)]
    if cfg.selection.units:
        out += ["--units", ",".join(cfg.selection.units)]
    return out


def _execute(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - the operator's own configured command
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        raise EngineError(
            f"the engine {command[0]!r} was not found. Set [engine] command to its path, "
            f"or install Hammunition {ENGINE_FLOOR} or later on this machine's PATH."
        ) from None
    except subprocess.TimeoutExpired:
        raise EngineError(
            f"`{' '.join(command)}` did not answer within {timeout:g} s ([engine] timeout)"
        ) from None
    except OSError as exc:
        raise EngineError(f"the engine {command[0]!r} could not be run: {exc}") from None


def _entry(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise EngineError(f"artifact {index} of the engine's document is not an object")
    for key, types in _FIELDS.items():
        if key not in item:
            raise EngineError(f"artifact {index} of the engine's document has no {key!r} field")
        value = item[key]
        if isinstance(value, bool) or not isinstance(value, types):
            raise EngineError(
                f"artifact {index} of the engine's document: {key!r} is {value!r}, "
                f"not {' or '.join(t.__name__ for t in types)}"
            )
    return item


def _key(version: str) -> tuple[int, ...] | None:
    match = _VERSION.match(version)
    return None if match is None else tuple(int(p) for p in match.groups())


def newer_engine_note(version: str) -> str | None:
    """A sentence when *version* is newer than the release this Bunker's check
    table was written against (:data:`bunker.ENGINE_CONTRACT`), else None."""
    got, known = _key(version), _key(ENGINE_CONTRACT)
    if got is None or known is None or got <= known:
        return None
    return (
        f"Hammunition {version} is newer than {ENGINE_CONTRACT}, the newest release whose "
        f"artifacts document this Bunker knows. Any check kind it does not know is refused "
        f"by name until you update the Bunker."
    )


def _parse(text: str) -> Listing:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EngineError(
            f"the engine's answer is not a JSON document ({exc}); it began: {text[:200]!r}"
        ) from None
    if not isinstance(doc, dict):
        raise EngineError("the engine's answer is not a JSON object")
    schema = doc.get("schema")
    if schema != SCHEMA_MAJOR:
        raise EngineError(
            f"the engine answered with schema {schema!r}; this Bunker reads {SCHEMA_MAJOR!r} "
            f"only. Pin the engine release this Bunker names ({ENGINE_FLOOR}), or update "
            f"the Bunker."
        )
    if doc.get("kind") == "error":
        raise EngineError(
            f"the engine refused (exit {doc.get('exit_code')}): "
            f"{str(doc.get('message', '')).strip()}"
        )
    if doc.get("kind") != "artifacts":
        raise EngineError(f"the engine answered with a {doc.get('kind')!r} document")
    items = doc.get("artifacts")
    if not isinstance(items, list):
        raise EngineError("the engine's document has no artifacts list")

    artifacts: list[Artifact] = []
    deferred: list[Deferred] = []
    licences: dict[str, str] = {}
    seen: dict[tuple[str, str], Artifact] = {}
    for index, raw in enumerate(items):
        item = _entry(raw, index)
        unit, name = item["unit"], item["name"]
        licences.setdefault(unit, " ".join(item["licence"].split()))
        if item["deferred"] is not None:
            deferred.append(Deferred(unit, name, item["deferred"]))
            continue
        if name is None or item["url"] is None or item["check"] is None:
            raise EngineError(f"artifact {index} ({unit}) is listed but has no name, url or check")
        if item["check"] not in CHECKS:
            deferred.append(
                Deferred(
                    unit,
                    name,
                    f"refused: its check {item['check']!r} is not one this Bunker knows "
                    f"({', '.join(CHECKS)}); the engine is Hammunition "
                    f"{doc.get('engine') or 'of an unknown version'}, this Bunker knows "
                    f"the artifacts document through {ENGINE_CONTRACT}. Nothing was "
                    f"downloaded for it; update the Bunker",
                    refused=True,
                )
            )
            continue
        artifact = Artifact(
            unit=unit,
            name=name,
            url=item["url"],
            check=item["check"],
            digest=item["digest"],
            checksum_url=item["checksum_url"],
            size=item["size"],
            licence=" ".join(item["licence"].split()),
        )
        first = seen.get((unit, name))
        if first is not None:
            # A region typed twice lists twice; two workers on one name
            # would race for one path. The same artifact again is dropped;
            # a different one under the same name is deferred, by name.
            if first != artifact:
                deferred.append(
                    Deferred(
                        unit,
                        name,
                        f"listed twice with different contents ({first.url} and "
                        f"{artifact.url}); a mirror serves one file per name",
                    )
                )
            continue
        seen[(unit, name)] = artifact
        artifacts.append(artifact)
    note = newer_engine_note(str(doc.get("engine", "")))
    return Listing(
        warnings=(note,) if note else (),
        engine_version=str(doc.get("engine", "")),
        artifacts=tuple(artifacts),
        deferred=tuple(deferred),
        licences=licences,
    )


def ask_engine(cfg: Config) -> Listing:
    """Run ``hammunition artifacts --json`` for the configured selection."""
    command = argv(cfg)
    done = _execute(command, cfg.engine.timeout)
    if done.returncode != 0:
        detail = done.stderr.strip() or done.stdout.strip()[:500]
        raise EngineError(f"`{' '.join(command)}` exited {done.returncode}: {detail}")
    return _parse(done.stdout)


def engine_version(cfg: Config) -> str:
    """What ``hammunition --version`` says, as ``X.Y.Z``."""
    done = _execute([*cfg.engine.command, "--version"], min(cfg.engine.timeout, 60.0))
    match = _VERSION.search(done.stdout)
    if done.returncode != 0 or match is None:
        raise EngineError(
            f"`{' '.join(cfg.engine.command)} --version` did not print a version "
            f"(exit {done.returncode}): {(done.stderr or done.stdout).strip()[:200]}"
        )
    return match.group(0)


def meets_floor(version: str, floor: str = ENGINE_FLOOR) -> bool:
    """Whether *version* is at least *floor*, both ``X.Y.Z``."""

    def key(v: str) -> tuple[int, ...]:
        match = _VERSION.match(v)
        if match is None:
            raise ValueError(f"{v!r} is not a version")
        return tuple(int(p) for p in match.groups())

    return key(version) >= key(floor)
