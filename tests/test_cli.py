# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The commands as an operator types them, and their --json documents
against goldens (tests/golden/). BUNKER_UPDATE_GOLDENS=1 rewrites them;
read the diff before committing one."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import bunker
from bunker import cli, index
from bunker.volume import RunLock
from tests.scene import REGION, Scene
from tests.test_doctor import free_port

GOLDEN = Path(__file__).parent / "golden"


def normalise(text: str, scene: Scene) -> Any:
    text = text.replace(scene.pub.base, "http://publisher.test")
    text = text.replace(str(scene.tmp), "<tmp>")
    doc = json.loads(text)
    assert doc["engine"] == bunker.__version__
    doc["engine"] = "<bunker version>"
    return doc


def assert_golden(name: str, doc: Any) -> None:
    path = GOLDEN / f"{name}.json"
    rendered = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("BUNKER_UPDATE_GOLDENS") == "1":
        path.write_text(rendered, encoding="utf-8")
    assert path.exists(), f"{path} is missing: run with BUNKER_UPDATE_GOLDENS=1 and read it"
    assert rendered == path.read_text(encoding="utf-8"), f"{name} differs from its golden"


@pytest.fixture
def invoke(
    scene: Scene, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Any:
    monkeypatch.setattr(cli, "CLOCK", scene.clock)
    cfg_path = scene.tmp / "bunker.toml"

    def call(*argv: str) -> tuple[int, str, str]:
        scene.cfg()  # writes the config file
        code = cli.main([*argv, "--config", str(cfg_path)])
        out, err = capsys.readouterr()
        return code, out, err

    return call


def test_run_prints_a_plain_summary(invoke: Any) -> None:
    code, out, _ = invoke("run")
    assert code == 0
    assert "3 fetched" in out and "0 failed" in out


def test_run_json_golden(invoke: Any, scene: Scene) -> None:
    code, out, _ = invoke("run", "--json")
    assert code == 0
    assert_golden("run", normalise(out, scene))


def test_run_locked_exits_125(invoke: Any, scene: Scene) -> None:
    scene.root.mkdir(parents=True)
    with RunLock(scene.root):
        code, out, err = invoke("run")
    assert code == 125
    assert "in progress" in err and out == ""


def test_run_locked_json_is_an_error_document(invoke: Any, scene: Scene) -> None:
    scene.root.mkdir(parents=True)
    with RunLock(scene.root):
        code, out, _ = invoke("run", "--json")
    doc = json.loads(out)
    assert code == 125 and doc["kind"] == "error" and doc["exit_code"] == 125


def test_run_with_failures_exits_1(invoke: Any, scene: Scene) -> None:
    entries = scene.entries()
    entries[0]["digest"] = "0" * 64
    scene.list(entries)
    code, out, _ = invoke("run")
    assert code == 1
    assert "failed: country-files/cty.dat" in out


def test_run_all_and_unit(invoke: Any, scene: Scene) -> None:
    invoke("run")
    code, out, _ = invoke("run", "--unit", "osm-regions", "--all")
    assert code == 0
    assert "0 fetched, 1 verified" in out  # --all makes a matching copy due, not re-downloaded


def test_status_json_golden(invoke: Any, scene: Scene) -> None:
    entries = scene.entries()
    entries[2]["digest"] = "0" * 32
    scene.list(entries)
    invoke("run")
    code, out, _ = invoke("status", "--json")
    assert code == 0
    assert_golden("status", normalise(out, scene))


def test_status_text_names_what_is_not_current(invoke: Any, scene: Scene) -> None:
    entries = scene.entries()
    entries[1]["digest"] = "0" * 32
    scene.list(entries)
    invoke("run")
    code, out, _ = invoke("status")
    assert code == 0
    assert f"failed: osm-regions/{REGION}" in out
    assert "Last run:" in out


def test_status_lists_declined_separately(invoke: Any, scene: Scene) -> None:
    scene.root.mkdir(parents=True)
    idx = index.Index(
        deferred=[{"unit": "engine-unit", "name": "later", "reason": "not listed"}],
        declined=[{"unit": "config-unit", "name": "disabled", "reason": "hold_unverified = false"}],
    )
    index.save(scene.root, idx, generated="2026-09-29T03:00:00Z")

    code, out, _ = invoke("status")
    assert code == 0
    assert "  deferred: engine-unit/later: not listed" in out
    assert "  declined: config-unit/disabled: hold_unverified = false" in out

    code, out, _ = invoke("status", "--json")
    doc = json.loads(out)
    assert code == 0
    assert doc["deferred"] == idx.deferred
    assert doc["declined"] == idx.declined


def test_status_before_any_run(invoke: Any) -> None:
    code, out, _ = invoke("status")
    assert code == 0 and "No run yet" in out


def test_verify_json_golden(invoke: Any, scene: Scene) -> None:
    invoke("run")
    path = scene.file("osm-regions", REGION)
    path.write_bytes(b"!" + path.read_bytes()[1:])
    code, out, _ = invoke("verify", "--json")
    assert code == 1
    assert_golden("verify", normalise(out, scene))


def test_doctor_json_golden(invoke: Any, scene: Scene, monkeypatch: pytest.MonkeyPatch) -> None:
    port = free_port()
    monkeypatch.setattr(scene, "extra", f'[serve]\nbind = "127.0.0.1"\nport = {port}\n')
    code, out, _ = invoke("doctor", "--json")
    doc = normalise(out.replace(f":{port}", ":<port>"), scene)
    assert_golden("doctor", doc)
    assert code == (0 if doc["ok"] else 1)


def test_serve_has_no_json_form(invoke: Any, scene: Scene) -> None:
    code, out, _ = invoke("serve", "--json")
    doc = normalise(out, scene)
    assert code == 2
    assert_golden("error", doc)


def test_a_bad_config_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bunker.toml"
    bad.write_text("[storage]\ndownloads = 9\n")
    assert cli.main(["run", "--config", str(bad)]) == 2
    assert "storage.downloads" in capsys.readouterr().err


def test_a_newer_index_exits_2(invoke: Any, scene: Scene) -> None:
    scene.root.mkdir(parents=True)
    (scene.root / "index.json").write_text('{"kind": "bunker-index", "version": 9}')
    for command in ("run", "status", "verify"):
        code, _, err = invoke(command)
        assert code == 2 and "newer" in err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"bunker {bunker.__version__}"


def test_no_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


def test_schedule_serves_runs_and_stops_on_sigterm(scene: Scene) -> None:
    """The container's entry point, as a real process: it serves at once,
    runs a pass, and a SIGTERM (docker stop) ends it cleanly."""
    import signal
    import subprocess
    import sys
    import time
    import urllib.request

    port = free_port()
    scene.extra = f'[serve]\nbind = "127.0.0.1"\nport = {port}\n'
    scene.cfg()
    proc = subprocess.Popen(
        [sys.executable, "-m", "bunker", "schedule", "--config", str(scene.tmp / "bunker.toml")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        fetched = False
        while time.monotonic() < deadline and not fetched:
            try:
                url = f"http://127.0.0.1:{port}/country-files/cty.dat"
                with urllib.request.urlopen(url, timeout=2) as response:
                    fetched = response.read() == scene.data["cty"]
            except OSError:
                time.sleep(0.1)
        assert fetched, "the scheduler never served the first pass's file"
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert proc.returncode == 0, err
    assert "3 fetched" in out


def test_signal_handler_does_not_deadlock_on_the_events_lock() -> None:
    """A signal that lands inside Event.wait() holds the Event's lock in the
    same thread; a handler calling set() inline would wait on it forever."""
    import signal
    import threading

    stop = threading.Event()
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    try:
        cli._stop_event_on_signals(stop)
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        with stop._cond:  # type: ignore[attr-defined] # held inside wait()
            handler(signal.SIGTERM, None)  # must return, not block
        assert stop.wait(5), "the handler never set the event"
    finally:
        signal.signal(signal.SIGTERM, before[0])
        signal.signal(signal.SIGINT, before[1])
