<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

Notable changes, newest first. Versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- The engine pin is Hammunition v0.19.0 (was v0.16.0): `ENGINE_FLOOR`,
  `pyproject.toml`, the Dockerfile (tag and the tag archive's sha256, measured
  twice) and the live workflow's ref. `Fetcher.fetch_sha1`,
  `Fetcher.fetch_checked` and `hammunition.acma` are all present, so the
  `sha1-publisher` and `unverified-zip` tests run on the pinned engine.

### Added

- Every check kind the engine's `artifacts` document can emit, in one table
  (`src/bunker/checks.py`, tested against the engine's own list and against
  the README and the reference): `sha256`, `sha256-publisher`,
  `md5-publisher`, `etag-md5`, `sha1-publisher` (CoMaps; `Fetcher.fetch_sha1`)
  and `unverified-zip` (the ACMA register; `Fetcher.fetch_checked` with the
  engine's own `hammunition.acma.check_register`). Before this, `sha1-publisher`
  and the register were deferred as unknown.
- Unverified artifacts, held by the maintainer's ruling of 2026-10-02 (D-070,
  D-074's ACMA amendment): the register is stored with its size and fetch
  date, fetched again on its unit's schedule, never marked stale, CRC-checked
  by the engine's check on every fetch and by `bunker verify`, and listed by
  `bunker status` (`unverified` in its document), the status page and `bunker
  doctor` under *Unverified, held by the maintainer's ruling*.
- `selection.hold_unverified` (default `true`): `false` declines every
  unverified artifact by name, never fetches it and withdraws a copy already
  held from the index. `bunker doctor` names the unverified artifacts held and
  the switch's setting (a new `unverified` check).
- `bunker.ENGINE_CONTRACT`: when the engine's `artifacts` document is newer
  than the release this Bunker's table was written against, the run
  (`warnings`) and `bunker doctor` say so.
- The `run` document gains `refused`, `declined` and `warnings`; the `status`
  document gains `unverified`.
- `selection.reference_books` in `bunker.toml`: Kiwix book ids, passed to
  the engine as `--reference-books` when non-empty (Hammunition #178). Each
  selected book is a plain `sha256` artifact (`unit: kiwix-library`) and
  needs nothing book-specific from the run path; none selected defers the
  unit as "no books selected" like any other deferral. Books are the
  largest artifacts a Bunker can hold, so the default stays empty. Needs
  the Hammunition release that carries #178 (the next release after
  v0.18.0, until it is tagged).

### Changed

- A check kind this Bunker does not know is **refused by name**, with the
  engine's version, and fails the run (exit 1). It was deferred quietly
  before; the rest of the listing is still mirrored.

## [0.1.0] — unreleased

The first cut, from the approved spec
(`docs/superpowers/specs/2026-09-29-bunker-design.md`). Waits on Hammunition
v0.16.0 (D-070: `hammunition artifacts` and the LAN mirror); the image's
engine digest is filled in when that release exists.

### Added

- `bunker run`, `status`, `verify`, `serve`, `schedule` and `doctor`, each
  with `--config`, and `--json` in Hammunition's envelope shape (D-059)
  where a document exists. Exit codes 0, 1, 2 and 125.
- `bunker.toml`: the selection, the volume, a refresh cadence and a verify
  cadence per unit, two downloads at a time (never more than four), an
  optional rate cap, the server's address. Unknown keys are refused by name.
- The run: the engine is asked with `hammunition artifacts --json`, every
  download goes through the engine's own verified fetch, every file gets a
  sha256 sidecar and one `.previous`, a failed fetch leaves the last good
  copy serving, corruption is re-fetched and reported, `.runs.jsonl` keeps
  one line per run.
- `index.json` version 1, and `status.html` with every unit's licence line.
- A read-only HTTP server with byte ranges that serves only what the index
  names, at the mirror path `<unit>/<name>` and at the volume path.
- A Debian 13 slim image that takes nothing from a package index, a
  `compose.yaml` for Synology Container Manager, a rootless Podman quadlet,
  and GYST CI, security and release workflows, plus a weekly live run.
- `docs/guide.md` and `docs/reference.md`.
