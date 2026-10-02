# Hammunition Bunker — Claude Code Context

A verified LAN mirror of [Hammunition](https://github.com/ChiefGyk3D/Hammunition)'s
offline data, for a NAS. A sibling of Hammunition under the separable-
components rule: its own repository, its own releases, the engine reached
only through its public interfaces.

Binary: `bunker`. Python package: `bunker`. Licence: GPL-3.0-or-later
(it imports the engine as a library). Copyright Renegade Penguin LLC.

## Authority

The spec, `docs/superpowers/specs/2026-09-29-bunker-design.md`, is
authoritative, including its "as built" notes on the engine side (D-070 in
Hammunition). `docs/reference.md` describes what exists; where the two
disagree, the reference is describing a recorded ruling or is a bug.

## Invariants

- **One verifier.** Every download goes through the engine's own
  `hammunition.fetch.Fetcher`, imported through `src/bunker/enginelib.py`
  (the only module that imports the engine library; it orders the imports
  around the engine's fetch/backends cycle). The Bunker never decides what a
  good file is.
- **One source of what to keep.** `hammunition artifacts --json`, run as a
  subprocess. The Bunker carries no catalog and no pins.
- **Nothing trusted.** Every unit and name from the engine is checked before
  it becomes a path (`volume.artifact_dir`); every path in `index.json` is
  checked again before the server opens it; the sidecar is re-hashed on a
  cadence.
- **The server serves an allow-list** built from the index. Never add a
  route that serves the volume by prefix.
- **Nothing downloaded is executed, unpacked or parsed** beyond hashing, bar
  the engine's own structure check of an `unverified-zip` (CRCs and headers,
  read in place; `bunker.checks` is the one table of kinds).
- **Deleting is for a person.** Entries the engine stops listing are dropped
  from the index; their files stay until someone removes them.

## Standing rules (from the parent project)

- CI and a real test suite are not optional; `make check` reproduces CI.
- A check must be falsifiable: break what it watches, see it go red, restore.
- The suite blocks every socket but loopback (`tests/conftest.py`).
- `mypy --strict` and ruff are gates.
- Measure before claiming; a claim about the NAS that nothing measured says so.
- Never pin an action from memory: `git ls-remote --tags`, pin the commit.
- Never `curl | sh`; hashes are mandatory for anything fetched.
- Rootless Podman, never the docker group.
- Docs are part of the deliverable; `tests/test_docs.py` holds the reference
  to the code.

## Privacy

The maintainer's regions, position, callsign and grid square never appear in
this repository, a test, an issue or a log excerpt. Examples use Vermont,
New Hampshire and Delaware; placeholders are `N0CALL` and `FN31pr`.

## Layout

```
src/bunker/        config, engine (subprocess), enginelib (the import),
                   volume, index, run, verify, statuspage, server,
                   schedule, doctor, envelope, cli
packaging/         fetch_engine.py (the image's verified engine fetch),
                   bunker.container (rootless Podman quadlet)
tests/             conftest (socket guard, fake engine, loopback publisher),
                   scene (the shared three-artifact volume), golden/
docs/              guide.md, reference.md, superpowers/ (spec and plan)
```
