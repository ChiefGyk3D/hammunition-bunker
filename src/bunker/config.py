# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""``bunker.toml``: one file, bind-mounted read-only, every value checked.

A key this module does not know is refused by name rather than ignored: a
typo'd ``[schedule.units]`` entry that silently fell back to the default is
exactly the kind of wrong a mirror would carry for months.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import Any

__all__ = [
    "CADENCES",
    "DEFAULT_PATHS",
    "FRESHNESS",
    "MAX_DOWNLOADS",
    "VERIFY_CADENCES",
    "Config",
    "ConfigError",
    "EngineConfig",
    "Schedule",
    "Selection",
    "Serve",
    "Storage",
    "find",
    "load",
    "parse_rate",
]

#: How often a unit's artifacts are refreshed from their publishers.
CADENCES = ("never", "daily", "weekly", "monthly")
#: How often the bytes on disk are re-hashed. ``auto`` is the spec's default:
#: every run for a file under 1 GiB, monthly above.
VERIFY_CADENCES = ("auto", "every-run", "daily", "weekly", "monthly")
#: What ``hammunition artifacts --map-freshness`` accepts.
FRESHNESS = ("yearly", "monthly", "latest")
#: Downloads within one run never exceed this, whatever the config says.
MAX_DOWNLOADS = 4
DEFAULT_PATHS = (Path("/etc/bunker/bunker.toml"), Path("bunker.toml"))

_KNOWN: dict[str, tuple[str, ...]] = {
    "engine": ("command", "catalog", "timeout"),
    "selection": ("map_regions", "map_freshness", "reference_books", "units", "hold_unverified"),
    "storage": ("root", "keep_previous", "downloads", "max_rate"),
    "schedule": ("default", "run_at", "units"),
    "verify": ("default", "units"),
    "serve": ("bind", "port"),
}
_RATE = re.compile(r"([1-9][0-9]*)([KMG]?)")
_UNIT = re.compile(r"[a-z0-9][a-z0-9._-]*")


class ConfigError(Exception):
    """The configuration cannot be used. The message names the key."""


@dataclass(frozen=True)
class EngineConfig:
    command: tuple[str, ...] = ("hammunition",)
    """The engine executable and any leading arguments."""
    catalog: Path | None = None
    """Passed as ``--catalog``; None lets the engine (or HAMMUNITION_CATALOG) find it."""
    timeout: float = 600.0
    """Seconds ``hammunition artifacts`` may take; it asks publishers for checksums."""


@dataclass(frozen=True)
class Selection:
    map_regions: tuple[str, ...] = ()
    map_freshness: str = "yearly"
    reference_books: tuple[str, ...] = ()
    """Kiwix book ids (D-066). Empty defers ``kiwix-library`` as *no books
    selected*, unlike ``units``: a book is the largest kind of artifact a
    Bunker can hold, so none is fetched without being named."""
    units: tuple[str, ...] = ()
    """Empty: everything ``hammunition artifacts`` lists for the selection."""
    hold_unverified: bool = True
    """Keep the artifacts whose check names no digest (``unverified-zip``: the
    ACMA register, D-074; ``unverified-fetch``: the on-request repeater lists, D-078). True by the maintainer's ruling of 2026-10-02: the
    register's ``client.csv`` carries licensees' names and addresses, which its
    licence bars passing on in a derivative; the Bunker is for users to
    download things and have their repository set up, and the engine never
    opens ``client.csv``. False declines every such artifact by name and
    withdraws one already held."""


@dataclass(frozen=True)
class Storage:
    root: Path = Path("/data")
    keep_previous: bool = True
    downloads: int = 2
    max_rate: int | None = None
    """Bytes per second across every download of a run, or None for no cap."""


@dataclass(frozen=True)
class Schedule:
    default: str = "weekly"
    units: Mapping[str, str] = field(default_factory=dict)
    run_at: time = time(3, 0)
    """When ``bunker schedule`` runs each day (the container's clock, usually UTC)."""
    verify_default: str = "auto"
    verify_units: Mapping[str, str] = field(default_factory=dict)

    def cadence(self, unit: str) -> str:
        return self.units.get(unit, self.default)

    def verify_cadence(self, unit: str) -> str:
        return self.verify_units.get(unit, self.verify_default)


@dataclass(frozen=True)
class Serve:
    bind: str = "0.0.0.0"
    port: int = 8080


@dataclass(frozen=True)
class Config:
    engine: EngineConfig
    selection: Selection
    storage: Storage
    schedule: Schedule
    serve: Serve
    path: Path


def parse_rate(text: str) -> int:
    """``"20M"`` → bytes per second. K, M and G are powers of 1024; a bare
    number is bytes. Zero, negatives and anything else raise ValueError."""
    match = _RATE.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"{text!r} is not a rate: use a whole number with K, M or G (e.g. 20M)")
    scale = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[match.group(2)]
    return int(match.group(1)) * scale


def find(explicit: Path | None, candidates: Sequence[Path] = DEFAULT_PATHS) -> Path:
    """``--config`` when given, else the first of *candidates* that exists."""
    if explicit is not None:
        return explicit
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ConfigError(
        "no configuration: pass --config PATH, or put one at "
        + " or ".join(str(c) for c in candidates)
        + " (config.example.toml in the repository is the template)"
    )


def _table(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a table")
    unknown = sorted(set(value) - set(_KNOWN[name]))
    if unknown:
        raise ConfigError(f"unknown key {name}.{unknown[0]}; known: {', '.join(_KNOWN[name])}")
    return value


def _str(table: Mapping[str, Any], name: str, key: str, default: str) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name}.{key} must be a non-empty string")
    return value


def _choice(value: Any, key: str, choices: Sequence[str]) -> str:
    if value not in choices:
        raise ConfigError(f"{key} is {value!r}; it must be one of {', '.join(choices)}")
    return str(value)


def _strings(table: Mapping[str, Any], name: str, key: str) -> tuple[str, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"{name}.{key} must be a list of non-empty strings")
    return tuple(v.strip() for v in value)


def _boolean(table: Mapping[str, Any], name: str, key: str, default: bool) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{name}.{key} must be true or false")
    return value


def _cadences(value: Any, key: str, choices: Sequence[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a table of unit = cadence")
    out: dict[str, str] = {}
    for unit, cadence in value.items():
        if not _UNIT.fullmatch(unit):
            raise ConfigError(f"{key}.{unit} does not name a catalog unit")
        out[unit] = _choice(cadence, f"{key}.{unit}", choices)
    return out


def _engine(table: Mapping[str, Any], base: Path) -> EngineConfig:
    raw = table.get("command", "hammunition")
    if isinstance(raw, str):
        command = tuple(shlex.split(raw))
    elif isinstance(raw, list) and all(isinstance(p, str) for p in raw):
        command = tuple(raw)
    else:
        command = ()
    if not command or not all(command):
        raise ConfigError("engine.command must be a command line or a list of arguments")
    catalog = table.get("catalog")
    if catalog is not None and (not isinstance(catalog, str) or not catalog):
        raise ConfigError("engine.catalog must be a path")
    timeout = table.get("timeout", 600)
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
        raise ConfigError("engine.timeout must be a positive number of seconds")
    return EngineConfig(
        command=command,
        catalog=(base / catalog) if catalog else None,
        timeout=float(timeout),
    )


def _storage(table: Mapping[str, Any], base: Path) -> Storage:
    root = table.get("root", "/data")
    if not isinstance(root, str) or not root:
        raise ConfigError("storage.root must be a path")
    keep = table.get("keep_previous", True)
    if not isinstance(keep, bool):
        raise ConfigError("storage.keep_previous must be true or false")
    downloads = table.get("downloads", 2)
    if isinstance(downloads, bool) or not isinstance(downloads, int):
        raise ConfigError("storage.downloads must be a whole number")
    if not 1 <= downloads <= MAX_DOWNLOADS:
        raise ConfigError(f"storage.downloads is {downloads}; it must be 1 to {MAX_DOWNLOADS}")
    rate: int | None = None
    if "max_rate" in table:
        try:
            rate = parse_rate(str(table["max_rate"]))
        except ValueError as exc:
            raise ConfigError(f"storage.max_rate: {exc}") from None
    return Storage(root=base / root, keep_previous=keep, downloads=downloads, max_rate=rate)


def _run_at(value: Any) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        try:
            return time.fromisoformat(value)
        except ValueError:
            pass
    raise ConfigError(f'schedule.run_at is {value!r}; give a time of day such as "03:00"')


def load(path: Path) -> Config:
    """Read and check *path*. Relative paths in it resolve against its directory."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{path} does not exist") from None
    except OSError as exc:
        raise ConfigError(f"{path} cannot be read: {exc.strerror or exc}") from None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from None
    unknown = sorted(set(data) - set(_KNOWN))
    if unknown:
        raise ConfigError(f"unknown table {unknown[0]} in {path}; known: {', '.join(_KNOWN)}")
    base = path.parent

    selection = _table(data, "selection")
    sched = _table(data, "schedule")
    verify = _table(data, "verify")
    serve = _table(data, "serve")
    port = serve.get("port", 8080)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError(f"serve.port is {port!r}; it must be 1 to 65535")

    return Config(
        engine=_engine(_table(data, "engine"), base),
        selection=Selection(
            map_regions=_strings(selection, "selection", "map_regions"),
            map_freshness=_choice(
                selection.get("map_freshness", "yearly"), "selection.map_freshness", FRESHNESS
            ),
            reference_books=_strings(selection, "selection", "reference_books"),
            units=_strings(selection, "selection", "units"),
            hold_unverified=_boolean(selection, "selection", "hold_unverified", True),
        ),
        storage=_storage(_table(data, "storage"), base),
        schedule=Schedule(
            default=_choice(sched.get("default", "weekly"), "schedule.default", CADENCES),
            units=_cadences(sched.get("units", {}), "schedule.units", CADENCES),
            run_at=_run_at(sched.get("run_at", "03:00")),
            verify_default=_choice(
                verify.get("default", "auto"), "verify.default", VERIFY_CADENCES
            ),
            verify_units=_cadences(verify.get("units", {}), "verify.units", VERIFY_CADENCES),
        ),
        serve=Serve(bind=_str(serve, "serve", "bind", "0.0.0.0"), port=port),
        path=path,
    )
