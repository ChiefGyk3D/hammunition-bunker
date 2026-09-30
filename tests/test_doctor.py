# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest

from bunker import config, doctor, server
from tests.conftest import FakeEngine
from tests.helpers import config_text


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def cfg(tmp_path: Path, port: int) -> config.Config:
    path = tmp_path / "bunker.toml"
    path.write_text(
        config_text(str(tmp_path / "vol"), extra=f'[serve]\nbind = "127.0.0.1"\nport = {port}\n')
    )
    return config.load(path)


def by_name(report: doctor.DoctorReport) -> dict[str, doctor.Check]:
    return {c.name: c for c in report.checks}


def test_all_good(tmp_path: Path, fake_engine: FakeEngine) -> None:
    report = doctor.doctor(cfg(tmp_path, free_port()))
    assert report.ok, report.checks
    assert set(by_name(report)) == {"config", "engine", "volume", "port"}
    assert "0.16.0" in by_name(report)["engine"].detail


def test_an_engine_below_the_floor(tmp_path: Path, fake_engine: FakeEngine) -> None:
    fake_engine.set_version("0.15.0")
    check = by_name(doctor.doctor(cfg(tmp_path, free_port())))["engine"]
    assert not check.ok and "0.16.0" in check.detail


def test_no_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    check = by_name(doctor.doctor(cfg(tmp_path, free_port())))["engine"]
    assert not check.ok and "not found" in check.detail


def test_a_volume_that_cannot_be_written(tmp_path: Path, fake_engine: FakeEngine) -> None:
    c = cfg(tmp_path, free_port())
    c.storage.root.parent.mkdir(exist_ok=True)
    c.storage.root.write_text("a file where the volume should be")
    check = by_name(doctor.doctor(c))["volume"]
    assert not check.ok


def test_a_port_in_use_by_something_else(tmp_path: Path, fake_engine: FakeEngine) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = busy.getsockname()[1]
        check = by_name(doctor.doctor(cfg(tmp_path, port)))["port"]
    assert not check.ok and "in use" in check.detail


def test_a_port_in_use_by_a_bunker(tmp_path: Path, fake_engine: FakeEngine) -> None:
    c = cfg(tmp_path, free_port())
    c.storage.root.mkdir(parents=True)
    from bunker import index

    index.ensure(c.storage.root, generated="g")
    httpd = server.make_server(c.storage.root, "127.0.0.1", c.serve.port, quiet=True)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    try:
        check = by_name(doctor.doctor(c))["port"]
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert check.ok and "already serving" in check.detail


def test_a_config_error_is_a_failed_check(tmp_path: Path) -> None:
    report = doctor.doctor_path(tmp_path / "missing.toml")
    assert not report.ok
    assert [c.name for c in report.checks] == ["config"]


def test_a_wildcard_bind_outside_a_container_is_flagged(
    tmp_path: Path, fake_engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doctor, "in_container", lambda: False)
    path = tmp_path / "bunker.toml"
    path.write_text(config_text(str(tmp_path / "vol"), extra=f"[serve]\nport = {free_port()}\n"))
    check = by_name(doctor.doctor(config.load(path)))["port"]
    assert "every interface" in check.detail
