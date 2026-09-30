# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""``bunker doctor``: the config parses, the engine answers at or above the
floor, the volume is writable, the port binds (or a Bunker already serves
on it). Each check says what it found; none changes anything but a
temporary file it removes."""

from __future__ import annotations

import errno
import json
import os
import socket
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from bunker import ENGINE_FLOOR
from bunker.config import Config, ConfigError, load
from bunker.engine import EngineError, engine_version, meets_floor
from bunker.index import IndexRefused
from bunker.index import load as load_index

__all__ = ["Check", "DoctorReport", "doctor", "doctor_path"]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class DoctorReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": [asdict(c) for c in self.checks]}

    def lines(self) -> list[str]:
        return [f"{'ok  ' if c.ok else 'FAIL'}  {c.name}: {c.detail}" for c in self.checks]


def _engine(cfg: Config) -> Check:
    try:
        version = engine_version(cfg)
    except EngineError as exc:
        return Check("engine", False, str(exc))
    if not meets_floor(version):
        return Check(
            "engine",
            False,
            f"Hammunition {version} answers; this Bunker needs {ENGINE_FLOOR} or later "
            f"(hammunition artifacts and the LAN mirror, D-070)",
        )
    return Check("engine", True, f"Hammunition {version} answers (floor {ENGINE_FLOOR})")


def _volume(cfg: Config) -> Check:
    root = cfg.storage.root
    probe = root / f".doctor.{os.getpid()}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        return Check("volume", False, f"{root} is not writable: {exc.strerror or exc}")
    try:
        held = load_index(root)
    except IndexRefused as exc:
        return Check("volume", False, str(exc))
    return Check("volume", True, f"{root} is writable; its index lists {len(held.artifacts)}")


def _already_a_bunker(port: int) -> bool:
    url = f"http://127.0.0.1:{port}/index.json"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return bool(json.loads(response.read()).get("kind") == "bunker-index")
    except (OSError, ValueError):
        return False


def _port(cfg: Config) -> Check:
    bind, port = cfg.serve.bind, cfg.serve.port
    family = socket.AF_INET6 if ":" in bind else socket.AF_INET
    where = f"{bind}:{port}"
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((bind, port))
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            if _already_a_bunker(port):
                return Check("port", True, f"{where} is in use: a Bunker is already serving there")
            return Check("port", False, f"{where} is in use by something that is not a Bunker")
        return Check("port", False, f"{where} cannot be bound: {exc.strerror or exc}")
    return Check("port", True, f"{where} binds")


def doctor(cfg: Config) -> DoctorReport:
    report = DoctorReport([Check("config", True, f"{cfg.path} parses")])
    report.checks += [_engine(cfg), _volume(cfg), _port(cfg)]
    return report


def doctor_path(path: Path) -> DoctorReport:
    """:func:`doctor` from a config path; a config that fails is the one check."""
    try:
        cfg = load(path)
    except ConfigError as exc:
        return DoctorReport([Check("config", False, str(exc))])
    return doctor(cfg)
