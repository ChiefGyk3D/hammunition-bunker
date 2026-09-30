<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contributing

Project context and standing rules are in [CLAUDE.md](CLAUDE.md), which is
also what Claude Code loads. Issues and pull requests are welcome; a pull
request is merged by the maintainer, never by its author.

## Run the checks before you push

```
make venv       # once
make check      # ruff, ruff format --check, mypy --strict, pytest
```

`make check` is what CI runs, minus the Python version matrix. The suite
blocks every socket that is not loopback: a test that needs a publisher uses
the loopback one in `tests/conftest.py`, never the internet.

### Developing against an unreleased engine

`pyproject.toml` pins the engine by git tag. Until that tag exists, or to
work against an engine branch, install a local checkout first and the
Bunker without dependencies:

```
python3 -m venv .venv
.venv/bin/pip install -e /path/to/Hammunition --config-settings editable_mode=compat
.venv/bin/pip install -e . --no-deps --config-settings editable_mode=compat
.venv/bin/pip install pytest mypy ruff
```

`editable_mode=compat` matters: mypy cannot follow setuptools' default
editable finder, and `mypy --strict` reads the engine's types.

## What the checks hold

| Check | Holds |
|---|---|
| `tests/test_repo_hygiene.py` | the suite really blocks the network; `.gitignore` is anchored; nothing tracked is ignored; the engine version agrees in three places |
| `tests/test_engine.py` | the engine's answer is read strictly, through a fake `hammunition` on PATH |
| `tests/test_run.py`, `tests/test_verify.py` | first run, second run, corruption, a failed fetch keeping the old copy, cadence, lock, concurrency |
| `tests/test_server.py` | byte ranges, hidden paths, and Hammunition's own fetch taking a file from the server |
| `tests/test_cli.py` | exit codes, the `--json` goldens, the scheduler as a real process |
| `tests/test_packaging.py` | pinned actions, the image's posture, compose and quadlet agreeing, the engine fetch refusing a wrong hash |
| `tests/test_docs.py` | links, cited paths, and that the reference names every key, command and document |

**A check must be falsifiable.** Before trusting a new one, break the thing
it watches and watch it go red with a message naming the fix. Every check
above was falsified once when it was written.

The `--json` goldens are in `tests/golden/`. After a deliberate change to a
document, `BUNKER_UPDATE_GOLDENS=1 make test` rewrites them; read the diff
before committing it.

## Cutting a release

1. The engine release the Bunker pins must exist. Its version is in three
   places, held together by a test: `bunker.ENGINE_FLOOR`, the pin in
   `pyproject.toml`, and `ENGINE_VERSION` in the `Dockerfile`.
2. Fill `ENGINE_SHA256` in the `Dockerfile` with the sha256 of the bytes at
   `ENGINE_URL`:

   ```
   curl -fLo engine.tar.gz https://github.com/ChiefGyk3D/Hammunition/archive/refs/tags/v0.16.0.tar.gz
   sha256sum engine.tar.gz
   ```

   Compare the tree inside with the tag before trusting it, and fill the
   digest only after that.
3. Bump `__version__` in `src/bunker/__init__.py`, the image tag in
   `compose.yaml` and `packaging/bunker.container`, and move the changelog's
   Unreleased entries under the new version.
4. `make check`, then `podman build .` (rootless) on a machine where building
   is fine, then tag. The release workflow builds, scans, signs and
   publishes the image.

Never pin an action or a reusable workflow from memory: resolve the tag with
`git ls-remote --tags` and pin the commit, with the version in a comment.

## Rules that are not style

- Never pipe remote content into a shell, in the image or anywhere else.
- Never add a dependency from a package index to the image; Debian's archive
  or a verified release archive only.
- Never write a real selection, position, callsign or grid square into the
  repository, an issue or a test. The examples use Vermont, New Hampshire
  and Delaware; station values, where one is ever needed, are `N0CALL` and
  `FN31pr`.
- Rootless Podman, never the docker group.

## You keep your copyright

There is no CLA. Contributions are under GPL-3.0-or-later, the project's
licence, and you keep the copyright on what you write.
