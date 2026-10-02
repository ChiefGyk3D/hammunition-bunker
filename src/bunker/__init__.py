# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hammunition Bunker: a verified LAN mirror of Hammunition's offline data.

The Bunker holds no catalog, no pins and no verifier of its own. It asks an
installed Hammunition engine what to keep (``hammunition artifacts --json``),
downloads through the engine's own verified fetch, and serves the result on
the LAN, where every consumer checks every byte again.
"""

__all__ = ["ENGINE_CONTRACT", "ENGINE_FLOOR", "__version__"]

__version__ = "0.1.0"

#: The oldest Hammunition release that has ``hammunition artifacts`` and the
#: LAN mirror (D-070). The pyproject pin and the image's ENGINE_VERSION say
#: the same; ``tests/test_repo_hygiene.py`` holds the three together.
ENGINE_FLOOR = "0.16.0"

#: The newest Hammunition release whose ``artifacts`` document this Bunker's
#: check table (``bunker.checks``) was written against: it knows every kind
#: that release can emit. An engine newer than this is named in the run and
#: by ``bunker doctor``, and any kind the Bunker does not know is refused by
#: name. This is not the pin: the image still installs ``ENGINE_FLOOR``'s
#: release until the pin is bumped, and the two kinds that need a newer
#: engine than the floor (``sha1-publisher``, ``unverified-zip``) say so
#: when they are met on one that lacks the method.
ENGINE_CONTRACT = "0.19.0"
