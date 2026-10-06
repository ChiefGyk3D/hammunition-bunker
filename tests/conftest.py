# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Suite-wide guarantees, and the fixtures every test of a run shares.

**No test reaches the network.** The Bunker downloads things for a living,
and a test that quietly fell through to a real publisher would be slow,
flaky, and would stop testing what it names. Every socket to anywhere but
loopback is blocked for the whole suite, so a test that tries gets a clear
failure rather than a timeout. Loopback stays open: the publisher and the
Bunker's own server in these tests are real HTTP servers on 127.0.0.1.
(The pattern is Hammunition's own ``tests/conftest.py``.)
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

#: The `scene` fixture (tests/scene.py), shared by the run, verify, server and CLI tests.
pytest_plugins = ["tests.scene"]

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


class NetworkBlocked(RuntimeError):
    """A test tried to open a non-loopback connection."""


def _loopback(address: Any) -> bool:
    """Whether *address* is loopback, for the address families that have one."""
    if not isinstance(address, tuple) or not address:
        # AF_UNIX and friends: a filesystem path, not the network.
        return True
    host = address[0]
    if not isinstance(host, str):
        return False
    return host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127.")


@pytest.fixture(autouse=True, scope="session")
def _no_network() -> Any:
    def guard(self: socket.socket, address: Any) -> Any:
        if not _loopback(address):
            raise NetworkBlocked(
                f"the test suite blocked a connection to {address!r}. Tests must not "
                f"reach the network: serve the file from the loopback publisher fixture "
                f"instead of letting a fetch fall through to the real internet."
            )
        return _real_connect(self, address)

    def guard_ex(self: socket.socket, address: Any) -> Any:
        if not _loopback(address):
            raise NetworkBlocked(f"the test suite blocked a connection to {address!r}")
        return _real_connect_ex(self, address)

    socket.socket.connect = guard  # type: ignore[assignment,method-assign]
    socket.socket.connect_ex = guard_ex  # type: ignore[assignment,method-assign]
    try:
        yield
    finally:
        socket.socket.connect = _real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = _real_connect_ex  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# A fake `hammunition` on PATH.
# ---------------------------------------------------------------------------

_FAKE_ENGINE = '''#!{python}
"""A stand-in for `hammunition`: prints the document it was given."""
import json, os, sys
with open(os.environ["FAKE_ENGINE_ARGV"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if "--version" in sys.argv[1:]:
    print("hammunition " + os.environ.get("FAKE_ENGINE_VERSION", "0.21.0"))
    sys.exit(0)
sys.stderr.write(os.environ.get("FAKE_ENGINE_STDERR", ""))
with open(os.environ["FAKE_ENGINE_DOC"], encoding="utf-8") as doc:
    sys.stdout.write(doc.read())
sys.exit(int(os.environ.get("FAKE_ENGINE_EXIT", "0")))
'''


class FakeEngine:
    """Controls the fake engine: what it prints, how it exits, what it was asked."""

    def __init__(self, directory: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bin = directory / "bin"
        self.bin.mkdir(parents=True)
        self.script = self.bin / "hammunition"
        self.script.write_text(_FAKE_ENGINE.format(python=sys.executable), encoding="utf-8")
        self.script.chmod(0o755)
        self.doc_path = directory / "artifacts.json"
        self.argv_log = directory / "argv.jsonl"
        self.argv_log.write_text("")
        self._monkeypatch = monkeypatch
        monkeypatch.setenv("PATH", f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}")
        monkeypatch.setenv("FAKE_ENGINE_DOC", str(self.doc_path))
        monkeypatch.setenv("FAKE_ENGINE_ARGV", str(self.argv_log))
        self.set_doc({})

    def set_doc(self, doc: Any) -> None:
        text = doc if isinstance(doc, str) else json.dumps(doc)
        self.doc_path.write_text(text, encoding="utf-8")

    def set_exit(self, code: int, stderr: str = "") -> None:
        self._monkeypatch.setenv("FAKE_ENGINE_EXIT", str(code))
        self._monkeypatch.setenv("FAKE_ENGINE_STDERR", stderr)

    def set_version(self, version: str) -> None:
        self._monkeypatch.setenv("FAKE_ENGINE_VERSION", version)

    def calls(self) -> list[list[str]]:
        lines = self.argv_log.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line]


@pytest.fixture
def fake_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    return FakeEngine(tmp_path / "engine", monkeypatch)


# ---------------------------------------------------------------------------
# A publisher on loopback: serves bytes, their .md5, an ETag on HEAD.
# ---------------------------------------------------------------------------


class Publisher:
    """A real HTTP server on 127.0.0.1 standing in for Geofabrik, the
    Copernicus bucket and every other publisher. Files are set per path;
    requests are counted; an optional delay lets a test see concurrency."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.counts: dict[str, int] = {}
        self.delay = 0.0
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        publisher = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _serve(self, body: bool) -> None:
                path = self.path.split("?", 1)[0]
                with publisher._lock:
                    publisher.counts[path] = publisher.counts.get(path, 0) + 1
                    publisher.active += 1
                    publisher.max_active = max(publisher.max_active, publisher.active)
                try:
                    if publisher.delay:
                        time.sleep(publisher.delay)
                    data = publisher.files.get(path)
                    if data is None:
                        self.send_error(404)
                        return
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
                    self.send_header("ETag", f'"{md5}"')
                    self.end_headers()
                    if body:
                        self.wfile.write(data)
                finally:
                    with publisher._lock:
                        publisher.active -= 1

            def do_GET(self) -> None:
                self._serve(True)

            def do_HEAD(self) -> None:
                self._serve(False)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host!s}:{port}"

    def put(self, path: str, data: bytes) -> str:
        """Serve *data* at *path* (and its md5 at *path*.md5); return the URL."""
        self.files[path] = data
        md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
        self.files[path + ".md5"] = f"{md5}  {path.rsplit('/', 1)[-1]}\n".encode()
        return self.base + path

    def requests(self, path: str) -> int:
        return self.counts.get(path, 0)

    def total(self) -> int:
        return sum(n for p, n in self.counts.items() if not p.endswith(".md5"))

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def publisher() -> Any:
    pub = Publisher()
    try:
        yield pub
    finally:
        pub.close()
