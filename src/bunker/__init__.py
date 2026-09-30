# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hammunition Bunker: a verified LAN mirror of Hammunition's offline data.

The Bunker holds no catalog, no pins and no verifier of its own. It asks an
installed Hammunition engine what to keep (``hammunition artifacts --json``),
downloads through the engine's own verified fetch, and serves the result on
the LAN, where every consumer checks every byte again.
"""

__all__ = ["ENGINE_FLOOR", "__version__"]

__version__ = "0.1.0"

#: The oldest Hammunition release that has ``hammunition artifacts`` and the
#: LAN mirror (D-070). The pyproject pin and the image's ENGINE_VERSION say
#: the same; ``tests/test_repo_hygiene.py`` holds the three together.
ENGINE_FLOOR = "0.16.0"
