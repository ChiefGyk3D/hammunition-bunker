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

import socket
from typing import Any

import pytest

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
