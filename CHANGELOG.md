<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

Notable changes, newest first. Versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `docs/reference.md` said the on-request repeater lists are not listed by `hammunition artifacts`; the engine lists them as unit `repeater-snapshots` from v0.20.0 (D-078). The README names the latest engine release against the pinned one (#7).

### Added

- Keep the suite board current: a `project-sync` caller for GYST v1.12.0 (Hammunition #362) adds this repository's issues and pull requests to the Renegade-Penguin board, sets status and done date, and reconciles weekly.
- GYST callers to v1.12.0 (every input they pass exists in v1.12.0; v1.11.0 to v1.12.0 changed only `project-sync.yml`).
- Code scanning, second pass: the Units table header in the status page is one parenthesised literal with its rendered text pinned by a test, and `enginelib` reads `hammunition.backends` at import (an `ImportError` if the load order is wrong) instead of holding an unread module variable.
- The GYST callers move from v1.9.0 to v1.10.0 (a no-op for the called workflows: their inputs are identical).
- Fuzzing: Atheris targets under `fuzz/` for the `--json` envelope, `bunker.toml`,
  the engine's `artifacts` document, `index.json` with the status page, and the
  server's paths and ranges, run by GYST's `python-fuzz.yml` (v1.10.0) from
  `ci.yml` on pull requests and weekly; `tests/test_fuzz_targets.py` keeps them
  honest. See CONTRIBUTING.md.
- The `unverified-fetch` check kind (Hammunition D-078): the on-request repeater
  lists (ETCC, Brandmeister, hearham; unit `repeater-snapshots`) are held under
  `hold_unverified`, keeping size and fetch date only, with no zip structure
  check. `bunker verify` runs the engine's structure check on `unverified-zip`
  copies alone.

### Fixed

- Found by the fuzz targets: a `bunker.toml` that is not UTF-8, has an unclosed
  quotation in `engine.command`, or nests arrays about 500 deep is now a
  `ConfigError` naming the file or key, not a traceback. An `index.json` that
  is not UTF-8, or has a field of the wrong type (`deferred` a number, a size
  as text, `last_run` a list), is refused by name with the move-it-aside
  instruction, where it used to fail later in the status page or a run.

### Changed

- The project moved from the `ChiefGyk3D` user to the `Renegade-Penguin` organization (Hammunition #359, epic #357): every suite repository URL, badge and link now points at the organization.
- `index.json` is version 2, with a separate persisted `declined` list so
  status identifies artifacts declined by configuration rather than by the
  engine. Version-1 indexes upgrade without reclassifying their `deferred`
  entries.
- The engine pin is Hammunition v0.19.0 (was v0.16.0): `ENGINE_FLOOR`,
  `pyproject.toml`, the Dockerfile (tag and the tag archive's sha256, measured
  twice) and the live workflow's ref. `Fetcher.fetch_sha1`,
  `Fetcher.fetch_checked` and `hammunition.acma` are all present, so the
  `sha1-publisher` and `unverified-zip` tests run on the pinned engine.
- The reference documents the v0.19.0 floor, full engine argv and data the
  engine does not list for mirroring.
- The run lock `<root>/.lock` is created 0600 (was 0644): only the run that
  flocks it ever opens it. Adds `SECURITY.md`. Status-page strings, an unused
  import and a dead store are tidied (CodeQL sweep).

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
  largest artifacts a Bunker can hold, so the default stays empty.
  Requires Hammunition v0.19.0 or later (#178).

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
