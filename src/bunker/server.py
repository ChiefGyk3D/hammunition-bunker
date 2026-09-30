# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The read-only HTTP server: what the index names, and nothing else.

The mirror contract is ``<mirror>/<unit>/<name>`` (D-070); the server maps
that through ``index.json`` to the file on disk, so an on-disk name never
leaks into the contract. The same files are also reachable at their volume
path, with their ``.sha256`` sidecars, for verifying by hand. Anything not
named by the index -- ``.incoming``, ``.lock``, ``.runs.jsonl``, a
``.previous`` copy, a stray file, a directory -- is a 404, the same 404 a
name that does not exist gets. There are no directory listings; the index
and the status page are the only navigation.

A path the index names is checked again before it is opened: it must stay
inside the volume, have no hidden segment, and not be a symbolic link. The
index is data on a disk, and data on a disk can be edited.

GET and HEAD only. HEAD answers with the size, so the engine can check
before fetching. One ``Range: bytes=`` range is honoured (206); several are
answered with the whole file (200), which RFC 9110 allows.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import stat
import sys
import threading
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from bunker import __version__
from bunker.volume import SIDECAR

__all__ = ["Routes", "make_server", "parse_range"]

_CHUNK = 256 * 1024
UNSATISFIABLE: Literal["unsatisfiable"] = "unsatisfiable"
HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'"


@dataclass(frozen=True)
class Target:
    path: str
    """Relative to the volume root."""
    content_type: str


class Routes:
    """Request path -> file, rebuilt whenever ``index.json`` changes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._stamp: tuple[int, int, int] | None = None
        self._map: dict[str, Target] = {}

    def _build(self) -> dict[str, Target]:
        routes = {
            "": Target("status.html", "text/html; charset=utf-8"),
            "status.html": Target("status.html", "text/html; charset=utf-8"),
            "index.json": Target("index.json", "application/json"),
        }
        try:
            raw = json.loads((self.root / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return routes
        items = raw.get("artifacts") if isinstance(raw, dict) else None
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            unit, name, path = item.get("unit"), item.get("name"), item.get("path")
            if not (isinstance(unit, str) and isinstance(name, str) and isinstance(path, str)):
                continue
            if not (unit and name and path) or item.get("status") == "corrupted":
                continue  # a corrupted copy: the consumer would reject it; a 404 sends them on
            data = Target(path, "application/octet-stream")
            routes.setdefault(f"{unit}/{name}", data)
            routes.setdefault(path, data)
            routes.setdefault(path + SIDECAR, Target(path + SIDECAR, "text/plain; charset=utf-8"))
        return routes

    def lookup(self, request_path: str) -> Target | None:
        try:
            info = os.stat(self.root / "index.json")
            stamp: tuple[int, int, int] | None = (info.st_mtime_ns, info.st_size, info.st_ino)
        except OSError:
            stamp = None
        with self._lock:
            if stamp != self._stamp or not self._map:
                self._map = self._build()
                self._stamp = stamp
            return self._map.get(request_path)


def parse_range(header: str | None, size: int) -> tuple[int, int] | Literal["unsatisfiable"] | None:
    """One ``bytes=`` range as ``(first, last)`` inclusive; None to send the
    whole file (no header, several ranges, or syntax this does not read);
    ``"unsatisfiable"`` for a 416."""
    if not header:
        return None
    unit, _, spec = header.strip().partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        return None
    first_text, dash, last_text = spec.strip().partition("-")
    if not dash:
        return None
    try:
        if first_text == "":
            suffix = int(last_text)
            if suffix <= 0:
                return UNSATISFIABLE
            return (max(size - suffix, 0), size - 1) if size else UNSATISFIABLE
        first = int(first_text)
        last = int(last_text) if last_text else size - 1
    except ValueError:
        return None
    if first < 0:
        return None
    if first >= size:
        return UNSATISFIABLE
    if last < first:
        return None
    return first, min(last, size - 1)


def _safe(root: Path, relative: str) -> Path | None:
    """*relative* under *root*, or None if it could leave it or is hidden."""
    parts = relative.split("/")
    if relative.startswith("/") or any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        return None
    if parts[-1].endswith(".previous") or parts[-1].endswith(".previous" + SIDECAR):
        return None
    return root.joinpath(*parts)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "bunker/" + __version__
    sys_version = ""
    routes: Routes
    quiet = False

    def log_message(self, format: str, *args: Any) -> None:
        if not self.quiet:
            sys.stderr.write(f"{self.address_string()} {format % args}\n")

    def _plain(self, status: int, text: str, extra: dict[str, str] | None = None) -> None:
        body = (text + "\n").encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _serve(self) -> None:
        raw = urllib.parse.urlsplit(self.path).path
        try:
            decoded = urllib.parse.unquote(raw, errors="strict")
        except UnicodeDecodeError:
            self._plain(404, "not found")
            return
        target = None if "\x00" in decoded else self.routes.lookup(decoded.lstrip("/"))
        path = _safe(self.routes.root, target.path) if target is not None else None
        if target is None or path is None:
            self._plain(404, "not found")
            return
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError:
            self._plain(404, "not found")
            return
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):  # a regular file only
                self._plain(404, "not found")
                return
            size = info.st_size
            wanted = parse_range(self.headers.get("Range"), size)
            if wanted == UNSATISFIABLE:
                self._plain(416, "range not satisfiable", {"Content-Range": f"bytes */{size}"})
                return
            if isinstance(wanted, tuple):
                first, last = wanted
                status = 206
            else:
                first, last, status = 0, size - 1, 200
            length = max(last - first + 1, 0)
            self.send_response(status)
            self.send_header("Content-Type", target.content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("X-Content-Type-Options", "nosniff")
            if status == 206:
                self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
            if target.content_type.startswith("text/html"):
                self.send_header("Content-Security-Policy", HTML_CSP)
            if target.path in ("index.json", "status.html"):
                self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if self.command == "HEAD":
                return
            handle.seek(first)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self) -> None:
        self._serve()

    def do_HEAD(self) -> None:
        self._serve()

    def _refuse(self) -> None:
        self._plain(405, "read-only: GET and HEAD only", {"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


class _Server6(_Server):
    address_family = socket.AF_INET6


def make_server(
    root: Path, bind: str, port: int, *, quiet: bool = False
) -> http.server.ThreadingHTTPServer:
    """A server for *root* on *bind*:*port*, not yet serving."""
    handler = type("BunkerHandler", (Handler,), {"routes": Routes(root), "quiet": quiet})
    cls = _Server6 if ":" in bind else _Server
    return cls((bind, port), handler)
