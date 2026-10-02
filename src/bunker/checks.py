# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every check kind the engine's ``artifacts`` document can name, and what
this Bunker does for each (D-070; D-074, amended 2026-10-01 and 2026-10-02).

One table, read by the document parser, the run, ``bunker verify``,
``bunker status``, ``bunker doctor`` and the documentation test, so no
place decides for itself which kinds exist. A kind that is not in it is
refused by name with the engine's version (:mod:`bunker.engine`); a kind
that is in it is verified exactly as the engine verifies it, through the
engine's own :class:`~hammunition.fetch.Fetcher`.

The README's table and ``docs/reference.md`` are tested against this one.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "KINDS",
    "UNVERIFIED_LABEL",
    "CheckKind",
    "is_unverified",
    "kind_names",
]

#: How ``bunker status`` and the status page headline the artifacts whose
#: kind carries no digest of any kind.
UNVERIFIED_LABEL = "Unverified, held by the maintainer's ruling"


@dataclass(frozen=True)
class CheckKind:
    """One check kind and the Bunker's behaviour for it."""

    name: str
    method: str
    """The engine :class:`Fetcher` method that downloads and checks it."""
    algorithm: str | None
    """The digest ``digest`` carries (``sha256``, ``md5``, ``sha1``); None
    when the engine lists none."""
    needs_size: bool
    """A fetch without the listed size is refused by name."""
    needs_digest: bool
    summary: str
    """What is verified, for the documentation table."""

    @property
    def unverified(self) -> bool:
        """No digest of any kind exists: the engine checks structure only,
        and the Bunker holds the file under the maintainer's ruling."""
        return not self.needs_digest


KINDS: dict[str, CheckKind] = {
    k.name: k
    for k in (
        CheckKind(
            "sha256",
            "fetch",
            "sha256",
            False,
            True,
            "the sha256 Hammunition pins; the bytes are hashed as they arrive",
        ),
        CheckKind(
            "sha256-publisher",
            "fetch",
            "sha256",
            False,
            True,
            "a sha256 the publisher serves, as the engine read it while listing "
            "(no unit produces it today)",
        ),
        CheckKind(
            "md5-publisher",
            "fetch_md5",
            "md5",
            True,
            True,
            "Geofabrik's published MD5, and the exact size the engine listed",
        ),
        CheckKind(
            "etag-md5",
            "fetch_md5",
            "md5",
            True,
            True,
            "the Copernicus object's single-part ETag, which is its MD5, and the "
            "exact size the engine listed",
        ),
        CheckKind(
            "sha1-publisher",
            "fetch_sha1",
            "sha1",
            True,
            True,
            "the SHA-1 and size in CoMaps' own map index at the pinned commit; "
            "the engine says this is weaker than a pinned sha256",
        ),
        CheckKind(
            "unverified-zip",
            "fetch_checked",
            None,
            False,
            False,
            "no digest exists (the ACMA register changes daily and the ACMA publishes "
            "none): the zip's own CRC-32s and the tables the engine's reader needs, "
            "by the engine's own check",
        ),
    )
}


def kind_names() -> tuple[str, ...]:
    return tuple(KINDS)


def is_unverified(check: str) -> bool:
    """Whether *check* names a kind with no digest. An unknown kind is not."""
    kind = KINDS.get(check)
    return kind is not None and kind.unverified
