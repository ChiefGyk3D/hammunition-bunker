<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

Notable changes, newest first. Versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
