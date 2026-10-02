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
from bunker.engine import EngineError, engine_version, meets_floor, newer_engine_note
from bunker.index import IndexRefused, held_unverified
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
    detail = f"Hammunition {version} answers (floor {ENGINE_FLOOR})"
    note = newer_engine_note(version)
    if note:
        detail += f"; note: {note}"
    return Check("engine", True, detail)


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


def _unverified(cfg: Config) -> Check:
    """Which artifacts with no digest are held (the ACMA register), and whether
    the switch that holds them is on. Read from the index: the engine is not asked."""
    try:
        held = held_unverified(load_index(cfg.storage.root))
    except (IndexRefused, OSError) as exc:
        return Check("unverified", False, f"the volume's index cannot be read: {exc}")
    names = ", ".join(f"{e.unit}/{e.name}" for e in held)
    if not cfg.selection.hold_unverified:
        left = (
            f"; on the volume until you delete them (the next run withdraws them from the index and from serving): {names}"
            if held
            else ""
        )
        return Check(
            "unverified",
            True,
            f"[selection] hold_unverified = false: artifacts with no digest are not held{left}",
        )
    if not held:
        return Check(
            "unverified",
            True,
            "[selection] hold_unverified = true (the default; the maintainer's ruling of "
            "2026-10-02): none held yet. The ACMA register is held when the engine lists it",
        )
    return Check(
        "unverified",
        True,
        f"[selection] hold_unverified = true (the maintainer's ruling of 2026-10-02): held "
        f"without any digest to check: {names}. The ACMA register includes licensees' names "
        f"and addresses; set hold_unverified = false to stop holding it (delete a copy already held yourself)",
    )


def _already_a_bunker(port: int) -> bool:
    url = f"http://127.0.0.1:{port}/index.json"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return bool(json.loads(response.read()).get("kind") == "bunker-index")
    except (OSError, ValueError):
        return False


def in_container() -> bool:
    """Whether this process runs in a Docker or Podman container."""
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


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
    note = ""
    if bind in ("0.0.0.0", "::") and not in_container():
        note = (
            "; note: that is every interface of this host, including any the internet "
            "reaches. Outside a container, set [serve] bind to this host's LAN address"
        )
    return Check("port", True, f"{where} binds{note}")


def doctor(cfg: Config) -> DoctorReport:
    report = DoctorReport([Check("config", True, f"{cfg.path} parses")])
    report.checks += [_engine(cfg), _volume(cfg), _unverified(cfg), _port(cfg)]
    return report


def doctor_path(path: Path) -> DoctorReport:
    """:func:`doctor` from a config path; a config that fails is the one check."""
    try:
        cfg = load(path)
    except ConfigError as exc:
        return DoctorReport([Check("config", False, str(exc))])
    return doctor(cfg)
