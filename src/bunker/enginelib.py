# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The one place the Bunker imports the engine as a library.

The spec's rule is one verifier: every download goes through Hammunition's
own :class:`~hammunition.fetch.Fetcher`, at the pinned release, so the
Bunker never has a second opinion about what a good file is.

``hammunition.backends`` is imported first on purpose. In the engine,
``hammunition.fetch`` imports ``hammunition.backends.base``, whose package
``__init__`` imports ``apt_repo``, which imports ``hammunition.fetch`` back:
with ``fetch`` as the package's first import that cycle raises ImportError.
Importing the backends package first completes the cycle from the other
end. ``tests/test_volume.py`` imports this module in a fresh interpreter to
keep that true.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import hammunition.backends
from hammunition.backends.base import BackendError
from hammunition.fetch import (
    DEFAULT_MAX_BYTES,
    Fetcher,
    FetchResult,
    MirrorPath,
    Transport,
    UrllibTransport,
    safe_name,
)
from hammunition.manifest.schema import RemoteArtifact

# The import above must precede hammunition.fetch (see the module docstring). Read
# here, so the order is checked when this module loads and not only by a test.
if not hasattr(hammunition.backends, "base"):
    raise ImportError("hammunition.backends must load before hammunition.fetch")

__all__ = [
    "DEFAULT_MAX_BYTES",
    "BackendError",
    "FetchResult",
    "Fetcher",
    "MirrorPath",
    "RemoteArtifact",
    "Transport",
    "UrllibTransport",
    "acma",
    "safe_name",
]


def acma() -> ModuleType:
    """``hammunition.acma``, the engine's own reader and check for the ACMA
    register (D-074). Imported when needed: the pinned floor release does not
    have it, and a Bunker on that release must still start."""
    try:
        return importlib.import_module("hammunition.acma")
    except ImportError:
        raise BackendError(
            "the installed Hammunition has no hammunition.acma, which the "
            "unverified-zip check (the ACMA register, D-074) needs; install the "
            "Hammunition release that carries it"
        ) from None
