# Offline catalogue — Bunker (Plan B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Bunker that publishes a signed, versioned catalogue of everything it holds (`catalogue.json` v3 plus one `ssh-keygen -Y sign` signature per configured key), keeps the signing keys (file, FIDO2 security key, ssh-agent/PIV) under its own `bunker keys` commands, records the publisher facts and plan-time inputs the engine needs to plan with publishers unreachable, holds the remaining data kinds, payloads and git bundles, filters group-mode shares, exports the same layout to a drive, and proves the whole chain once in a network namespace where only the Bunker answers.

**Architecture:** The engine owns the reader and the shared rules (`hammunition.catalogue`, `hammunition.keystrength`, `hammunition.signers`); the Bunker imports them through `src/bunker/enginelib.py` and never re-implements them. The Bunker owns the writer. A run keeps its working state in `<root>/.state.json` (the v3 document, unsigned, written after every artifact) and publishes `catalogue.json` plus `catalogue.sig.d/<n>.sig` exactly once at the end of a run, through `src/bunker/publish.py` and `src/bunker/signing.py`, so the served pair is always one signed catalogue and a touch-required token is tapped once per change, not once per artifact. The server serves only what the published catalogue names.

**Tech Stack:** Python 3.11+, stdlib only (`subprocess` for `ssh-keygen`, `git`, `fido2-token`, `opensc-tool`; `http.server`), pytest, mypy --strict, ruff; the engine as a library from its pinned release.

**Spec:** `docs/superpowers/specs/2026-10-07-offline-bunker-catalogue-design.md` in Renegade-Penguin/Hammunition (checkout read while writing this plan: `/home/chiefgyk3d/src/Hammunition-offline-bunker/docs/superpowers/specs/2026-10-07-offline-bunker-catalogue-design.md`)

**Contract:** `docs/superpowers/plans/2026-10-07-offline-bunker-contract.md` in Renegade-Penguin/Hammunition (checkout: `/home/chiefgyk3d/src/Hammunition-offline-bunker/docs/superpowers/plans/2026-10-07-offline-bunker-contract.md`); binding, not edited here.

**Depends on:** Plan A release (the engine release that ships `hammunition.catalogue`, `hammunition.keystrength`, `hammunition.signers`, the expanded `artifacts --json` of Plan A task A10, `--offline` and `mirror enrol`). This plan assumes it is tagged `v0.22.0`; if it is another number, substitute it in Task 11. Tasks 1 to 10 are written and tested against a local checkout of the Plan A branch installed per CONTRIBUTING.md ("Developing against an unreleased engine"); tests that need a Plan A module go through `tests/plan_a.py` (skip until Task 11 turns the skip into a failure).

## Global Constraints

- Python floor: `requires-python = ">=3.11"`; ruff `target-version = "py311"`, `line-length = 100`; no syntax newer than 3.11.
- mypy: `strict = true`, `python_version = "3.11"`, `warn_unreachable = true`, `show_error_codes = true`, over `src`, `tests`, `packaging`; no new `# type: ignore` without an error code and a reason.
- ruff `select = ["E","F","W","I","UP","B","SIM","S","RUF"]`; a `subprocess` call in `src/` carries `# noqa: S603 - <reason>`; tests already ignore `S101`, `S603`, `S607`, `S108`.
- GYST pins untouched: every `uses: ChiefGyk3D/git-your-ship-together/...@fde2a491de5107c4edb953c8d24f04835c11cb0a # v1.13.0` line stays byte-identical; the only workflow edit in this plan is the `install-command` and `test-command` values of `ci.yml` in Task 10; `tests/test_packaging.py::test_gyst_pins_agree` stays green.
- No `shell=True` anywhere; every subprocess is an argv list with `check=False`, an explicit return-code branch and a timeout.
- No real hardware in CI: no test opens `/dev/hidraw*`, talks to `pcscd`, or needs a token; FIDO2 and PIV paths run against `tests/signing_fakes.py` or a stub runner, and file/agent keys are real `ssh-keygen` keys generated in `tmp_path`.
- New examples and fixtures use `europe/monaco` or `north-america/us/delaware` only; no callsign, grid square or real selection anywhere (placeholders `N0CALL`, `FN31pr`); existing tests keep the regions they already use.
- Every task ends green on `make check` (ruff, ruff format --check, mypy, pytest); run `make format` first, because the code blocks in this plan are not pre-formatted to ruff's style, then `make check; echo "exit=$?"` and read the exit code, never pipe the gate into `grep`.
- Commits are authored `ChiefGyk3D <19499446+ChiefGyk3D@users.noreply.github.com>` and end with the attribution line the session gives; the branch is pushed and merged by the maintainer, never by the implementer.
- A private signing key never leaves `<root>/.keys/` (0700, files 0600) and never appears in the catalogue, a log line, a `--json` document or a test assertion message.

## Review Focus

The spec implies five failure modes that none of its test bullets exercise and that would most likely bite a user. Each gets a test in the task that owns the code.

1. **A token unplugged (or never touched) in the middle of a refresh.** `ssh-keygen -Y sign` blocks on the touch or fails; a run must not publish a catalogue that lists a signer which did not sign, must not leave the old catalogue unservable, and must say which key skipped and why. Owner: Task 2 (`test_an_unplugged_key_is_dropped_and_the_others_sign`, `test_when_no_key_can_sign_the_served_pair_is_untouched`, `test_a_signer_that_times_out_is_unavailable_not_a_hang`).
2. **Disk full while writing the catalogue and its signatures.** A half-written pair is a catalogue every laptop refuses. All new files are staged first and renamed into place; an `ENOSPC` anywhere before the renames leaves the served pair byte-identical. Owner: Task 2 (`test_disk_full_while_staging_leaves_the_served_pair_untouched`); the same rule for a full drive in Task 8 (`test_a_full_drive_leaves_no_catalogue_behind`).
3. **A retired key still listed.** A retired key left in `signers`, or its `<n>.sig` left in `catalogue.sig.d/`, is a key the operator believes is dead still vouching. Owner: Task 2 (`test_a_retired_key_is_gone_from_signers_and_the_signature_directory`) and Task 3 (`test_retire_republishes_at_once_and_refuses_the_last_key`, `test_a_retire_that_could_not_publish_is_finished_by_the_next_publish`).
4. **Two things writing at once**: a second run, `bunker keys retire`, `bunker enrol remove` or `bunker export` landing while a run is publishing, and a laptop reading while a run is mid-way. Owner: Task 2 (`test_a_second_publish_is_refused_while_one_holds_the_lock`, `test_the_served_pair_does_not_change_until_the_run_publishes`), Task 3 (`test_keys_retire_during_a_run_is_locked_out_and_changes_nothing`), Task 8 (`test_export_is_locked_out_by_a_run`).
5. **The serial going backwards.** Laptops refuse a lower serial, so a Bunker that loses `catalogue.json` (a restore from backup, an operator moving it aside) and restarts at 1 locks the whole fleet out until each runs `hammunition mirror accept-older`. The serial is kept in its own high-water file. Owner: Task 1 (`test_the_serial_never_goes_backwards_when_the_catalogue_is_lost`).

---

### Task 1: Catalogue v3 — the index becomes `catalogue.json`

The index document gains `serial`, `bunker`, `signers`, `inputs` and, per artifact, `publisher_name`, `publisher_size` and `share`; `index.json` is renamed `catalogue.json`; a v2 `index.json` is still read and upgraded. A run no longer rewrites the served file after every artifact: it keeps its working state in `.state.json` and publishes `catalogue.json` once, at the end, through the new `bunker.publish` (unsigned until Task 2). The serial lives in its own `.serial` high-water file.

**Files:**
- Create: `src/bunker/publish.py`, `tests/plan_a.py`, `tests/test_publish.py`
- Modify: `src/bunker/index.py` (whole file, 1-262), `src/bunker/config.py` (`__all__` 22-38, `_KNOWN` 51-58, `Config` 128-135, `load` 284-320), `src/bunker/enginelib.py` (after 67), `src/bunker/run.py` (imports 36-52, `_finish` 651-670), `src/bunker/verify.py` (imports 20-27, 127-129), `src/bunker/cli.py` (imports 272-276, `cmd_serve` 175, `cmd_schedule` 190-191), `src/bunker/server.py` (docstring 1-22, `Routes` 55-99, 207), `src/bunker/volume.py` (docstring 15, `RESERVED` 58), `src/bunker/statuspage.py` (208-211), `fuzz/fuzz_index_status.py` (62-93), `fuzz/fuzz_server_paths.py` (29), `docs/reference.md` (The volume 156-174, The index 176-205, HTTP 207-222, Configuration table 49-78), `docs/guide.md` (212-213, 258, 305), `config.example.toml` (after the `[engine]` table), `CHANGELOG.md` (Unreleased, `### Added` at line 17)
- Test: `tests/test_index.py` (edits at lines 51, 55, 67, 83-84, 90, 104-106, 117-129, 139-144, 169), `tests/test_config.py`, `tests/test_publish.py`, `tests/test_run.py` (47-48), `tests/test_server.py` (169-194), `tests/test_kinds.py` (319), `tests/test_volume.py` (41), `tests/conftest.py`, `tests/helpers.py`

**Interfaces:**
- Consumes: `bunker.volume.write_atomic(path: Path, data: bytes) -> None`; `bunker.config` (`Config`, `ConfigError`, `_choice`); `hammunition.catalogue.parse(data: bytes)` in tests only (Plan A; the contract names `parse()` and does not give its argument type, so `tests/plan_a.py::parse_catalogue` is the one place that assumes `bytes`).
- Produces (all in `bunker.index` unless noted):
  - `INDEX_VERSION: int = 3`, `FILE = "catalogue.json"`, `LEGACY_FILE = "index.json"`, `STATE = ".state.json"`, `SERIAL_FILE = ".serial"`, `INPUT_KINDS: tuple[str, ...]`
  - `@dataclass(frozen=True) class Signer: id: str; public_key: str; algorithm: str; bits: int; hardware: bool; signature: str`
  - `@dataclass class Input: kind: str; region: str; name: str; path: str; sha256: str; size: int; fetched: str`
  - `Entry` gains `publisher_name: str | None = None`, `publisher_size: int | None = None`, `share: str = "all"`
  - `Index` gains `serial: int = 0`, `name: str = "bunker"`, `mode: str = "personal"`, `signers: list[dict[str, Any]]`, `inputs: list[Input]`
  - `body(idx: Index, *, serial: int, generated: str, signers: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]`
  - `render(idx: Index, *, serial: int, generated: str, signers: Sequence[Mapping[str, Any]] | None = None) -> bytes`
  - `save(root: Path, idx: Index, *, generated: str) -> None` (writes `.state.json`, unsigned, never served)
  - `next_serial(root: Path, published: int) -> int`
  - `load(root: Path) -> Index` (reads `.state.json`, else `catalogue.json`, else `index.json`)
  - `bunker.config.MODES: tuple[str, ...]`, `BunkerConfig(name: str, mode: str)`, `Config.bunker: BunkerConfig`
  - `bunker.publish.PublishResult(published: bool, serial: int, signed_by: tuple[str, ...] = (), skipped: tuple[tuple[str, str], ...] = ())`, `publish(cfg: Config, idx: Index, *, generated: str) -> PublishResult`, `ensure_published(cfg: Config, *, generated: str) -> None`
  - `bunker.enginelib.catalogue_module() -> ModuleType`, `bunker.enginelib.validate_catalogue(data: bytes) -> None`
  - `tests.plan_a.module(name) -> ModuleType`, `optional(name) -> ModuleType | None`, `parse_catalogue(data: bytes) -> Any`, `REQUIRE_PLAN_A: bool`
  - `tests.helpers.FAKE_PUBLIC`, `FAKE_ID`, `FAKE_SK_PUBLIC`, `FAKE_SK_ID`

- [ ] **Step 1: The Plan A access seam and the fixture keys (no behaviour yet)**

Create `tests/plan_a.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Access to the engine modules Plan A adds: ``hammunition.catalogue``,
``hammunition.keystrength`` and ``hammunition.signers``.

Until the pinned engine is the Plan A release (Task 11) a test that needs one
skips; ``REQUIRE_PLAN_A`` is then flipped and a missing module is a failure,
so a skip cannot outlive the pin that makes it unnecessary.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

import pytest

#: Task 11 sets this to True.
REQUIRE_PLAN_A = False


def optional(name: str) -> ModuleType | None:
    try:
        return importlib.import_module(name)
    except ImportError:
        if REQUIRE_PLAN_A:
            raise
        return None


def module(name: str) -> ModuleType:
    found = optional(name)
    if found is None:
        pytest.skip(f"{name} comes with the Plan A engine release; the installed engine lacks it")
    return found


def parse_catalogue(data: bytes) -> Any:
    """The engine's own reader. The contract says ``parse()`` and does not say
    what it takes; the bytes are what the signatures cover, so bytes."""
    return module("hammunition.catalogue").parse(data)
```

Append to `tests/helpers.py` (the fingerprints were measured with `ssh-keygen -l`; the keys are throw-away fixtures whose private halves were discarded, and the second is a hand-built `sk-ssh-ed25519` public blob, not a real token):

```python
#: A throw-away Ed25519 public key (private half discarded) and its fingerprint.
FAKE_PUBLIC = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAqh/Q/itrDvcGCOeDb7XBvHbd/MmzdymlTnnbWaq20x bunker-fixture"
)
FAKE_ID = "SHA256:Jo/yEkflbseRTafuq4t5y9mq83HUEfHmdaCIk/a4+NM"
#: A hand-built sk-ssh-ed25519 public key line: no token stands behind it.
FAKE_SK_PUBLIC = (
    "sk-ssh-ed25519@openssh.com "
    "AAAAGnNrLXNzaC1lZDI1NTE5QG9wZW5zc2guY29tAAAAIAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8gAAAAFnNzaDpoYW1tdW5pdGlvbi1idW5rZXI= "
    "bunker-fixture-sk"
)
FAKE_SK_ID = "SHA256:vJDshBNO+6Rtm/DfyLKDlqas9te1mfF+fLlwRb3ZC80"
```

Run: `.venv/bin/python -m pytest tests/test_index.py -q` — Expected: passes (nothing changed yet).

- [ ] **Step 2: Write the failing index tests**

In `tests/test_index.py` change the imports and add tests. Replace lines 10-13 with:

```python
import pytest

from bunker import index
from bunker.index import Entry, Index, IndexRefused, Input, Signer
from tests import plan_a
from tests.helpers import FAKE_ID, FAKE_PUBLIC
```

Add after `an_entry` (line 34):

```python
def an_input(**over: Any) -> Input:
    fields: dict[str, Any] = {
        "kind": "region-outline",
        "region": "europe/monaco",
        "name": "europe/monaco.poly",
        "path": "inputs/region-outline/europe/monaco.poly",
        "sha256": "c" * 64,
        "size": 2048,
        "fetched": "2026-10-06T03:00:00Z",
    }
    fields.update(over)
    return Input(**fields)


SIGNER = Signer(
    id=FAKE_ID,
    public_key=FAKE_PUBLIC,
    algorithm="ssh-ed25519",
    bits=256,
    hardware=False,
    signature="catalogue.sig.d/1.sig",
)


def v2_document() -> dict[str, Any]:
    entry = {
        k: v
        for k, v in asdict(an_entry()).items()
        if k not in ("publisher_name", "publisher_size", "share")
    }
    return {
        "kind": "bunker-index",
        "version": 2,
        "generated": "2026-10-04T00:00:00Z",
        "engine": {"version": "0.21.0"},
        "artifacts": [entry],
        "deferred": [],
        "declined": [],
        "last_run": None,
    }
```

and add `from dataclasses import asdict` to the imports. Apply these edits to the existing tests (the working file is now `.state.json`; `index.json` is only ever read for an upgrade):

| Line | Change |
|---|---|
| 51 | `(tmp_path / "index.json")` becomes `(tmp_path / index.STATE)` |
| 53 | `assert raw["version"] == 2` becomes `assert raw["version"] == 3` |
| 55 | `assert raw["engine"] == {"version": "0.21.0"}` becomes `assert raw["engine_version"] == "0.21.0" and "engine" not in raw` |
| 67 | `== ["index.json"]` becomes `== [index.STATE]` |
| 83-84 | both `"index.json"` become `index.STATE` |
| 90 | `"version": 3` becomes `"version": 4` (a legacy file newer than this Bunker still refuses) |
| 104-106 | the v0 chain: the last assertion reads `json.loads((tmp_path / index.STATE).read_text())["version"] == 3` |
| 117, 129 | `path = tmp_path / "index.json"` becomes `path = tmp_path / index.STATE`; `assert upgraded["version"] == 2 and upgraded["declined"] == []` becomes `== 3` |
| 141-144 | `ensure` moves to `publish.ensure_published` (Step 8); delete `test_ensure_writes_an_empty_index_only_when_absent` here |
| 169 | `"engine": {"version": "0.21.0"}` stays (a v3 file written before this change is read through the same fallback); add `"serial": 1, "signers": [], "inputs": []` to the dict |

Add the new tests at the end of the file:

```python
def test_round_trip_keeps_the_v3_fields(tmp_path: Path) -> None:
    idx = Index(
        engine_version="0.22.0",
        artifacts=[
            an_entry(
                publisher_name="monaco-260101.osm.pbf",
                publisher_size=123,
                share="owner:e-0123456789abcdef",
            )
        ],
        inputs=[an_input()],
        name="shack-1",
        mode="group",
        serial=7,
    )
    index.save(tmp_path, idx, generated="2026-10-07T12:00:00Z")
    raw = json.loads((tmp_path / index.STATE).read_text())
    assert raw["serial"] == 7 and raw["bunker"] == {"name": "shack-1", "mode": "group"}
    loaded = index.load(tmp_path)
    assert loaded.artifacts == idx.artifacts and loaded.inputs == idx.inputs
    assert (loaded.name, loaded.mode, loaded.serial) == ("shack-1", "group", 7)


def test_a_v2_index_json_is_read_and_upgraded_into_the_state_file(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text(json.dumps(v2_document()))
    loaded = index.load(tmp_path)
    assert loaded.engine_version == "0.21.0" and loaded.serial == 0 and loaded.inputs == []
    first = loaded.artifacts[0]
    assert (first.publisher_name, first.publisher_size, first.share) == (None, None, "all")
    assert (tmp_path / "index.json").exists(), "deleting is for a person"
    upgraded = json.loads((tmp_path / index.STATE).read_text())
    assert upgraded["version"] == 3 and upgraded["engine_version"] == "0.21.0"
    assert index.load(tmp_path).artifacts == loaded.artifacts


def test_the_state_file_wins_over_the_catalogue_which_wins_over_index_json(tmp_path: Path) -> None:
    for name, engine in (("index.json", "0.19.0"), (index.FILE, "0.20.0"), (index.STATE, "0.21.0")):
        doc = {**index_doc(), "engine_version": engine}
        (tmp_path / name).write_text(json.dumps(doc))
    assert index.load(tmp_path).engine_version == "0.21.0"
    (tmp_path / index.STATE).unlink()
    assert index.load(tmp_path).engine_version == "0.20.0"
    (tmp_path / index.FILE).unlink()
    assert index.load(tmp_path).engine_version == "0.19.0"


def index_doc(**over: Any) -> dict[str, Any]:
    doc = {
        "kind": index.KIND,
        "version": index.INDEX_VERSION,
        "serial": 1,
        "generated": "2026-10-04T00:00:00Z",
        "bunker": {"name": "bunker", "mode": "personal"},
        "signers": [],
        "engine_version": "0.22.0",
        "artifacts": [],
        "inputs": [],
        "deferred": [],
        "declined": [],
        "last_run": None,
    }
    doc.update(over)
    return doc


@pytest.mark.parametrize(
    ("what", "over"),
    [
        ("serial is text", {"serial": "7"}),
        ("serial is negative", {"serial": -1}),
        ("signers is a number", {"signers": 3}),
        ("inputs is an object", {"inputs": {}}),
        ("an input has an unknown kind", {"inputs": [asdict(an_input(kind="cheese"))]}),
        ("an input's size is text", {"inputs": [{**asdict(an_input()), "size": "2"}]}),
        ("a share is free text", {"artifacts": [{**asdict(an_entry()), "share": "anyone"}]}),
        ("a share names nobody", {"artifacts": [{**asdict(an_entry()), "share": "owner:"}]}),
        ("publisher_size is text", {"artifacts": [{**asdict(an_entry()), "publisher_size": "1"}]}),
    ],
)
def test_a_wrong_v3_field_is_refused_by_name(tmp_path: Path, what: str, over: dict[str, Any]) -> None:
    (tmp_path / index.FILE).write_text(json.dumps(index_doc(**over)), encoding="utf-8")
    with pytest.raises(IndexRefused, match="mv "):
        index.load(tmp_path)


def test_a_corrupt_catalogue_json_is_refused_naming_it(tmp_path: Path) -> None:
    (tmp_path / index.FILE).write_text("{not json")
    with pytest.raises(IndexRefused, match=r"catalogue\.json.*[Mm]ove it aside"):
        index.load(tmp_path)


def test_the_serial_never_goes_backwards_when_the_catalogue_is_lost(tmp_path: Path) -> None:
    """Laptops refuse a lower serial. A Bunker restored from a backup, or one whose
    operator moved the catalogue aside, must not start again at 1."""
    assert index.next_serial(tmp_path, 0) == 1
    assert index.next_serial(tmp_path, 1) == 2
    for name in (index.STATE, index.FILE):
        (tmp_path / name).unlink(missing_ok=True)
    assert index.next_serial(tmp_path, 0) == 3
    assert index.next_serial(tmp_path, 10) == 11  # a published serial above the file wins


def test_a_garbled_serial_file_does_not_lower_the_serial(tmp_path: Path) -> None:
    (tmp_path / index.SERIAL_FILE).write_text("not a number")
    assert index.next_serial(tmp_path, 5) == 6


@pytest.mark.parametrize("what", ["empty", "full", "group", "upgraded"])
def test_every_rendered_document_passes_the_engines_reader(tmp_path: Path, what: str) -> None:
    idx = Index(engine_version="0.22.0")
    if what == "full":
        idx.artifacts = [an_entry(publisher_name="x.osm.pbf", publisher_size=1)]
        idx.inputs = [an_input(), an_input(kind="tile-selection", name="europe/monaco.json")]
        idx.deferred = [{"unit": "kiwix-library", "name": None, "reason": "no books selected"}]
        idx.last_run = {"started": "s", "finished": "f", "fetched": 1, "failed": 0}
    if what == "group":
        idx.name, idx.mode = "club-nas", "group"
        idx.artifacts = [an_entry(share="owner:e-0123456789abcdef")]
    if what == "upgraded":
        (tmp_path / "index.json").write_text(json.dumps(v2_document()))
        idx = index.load(tmp_path)
    data = index.render(idx, serial=3, generated="2026-10-07T12:00:00Z", signers=[asdict(SIGNER)])
    plan_a.parse_catalogue(data)


def test_the_engines_reader_refuses_a_catalogue_with_no_signer(tmp_path: Path) -> None:
    """Falsification of the test above: the reader does reject a bad document."""
    data = index.render(Index(), serial=3, generated="2026-10-07T12:00:00Z", signers=[])
    with pytest.raises(Exception, match="signers"):
        plan_a.parse_catalogue(data)
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/bin/python -m pytest tests/test_index.py -q -x`
Expected: FAIL at import — `ImportError: cannot import name 'Input' from 'bunker.index'`.

- [ ] **Step 4: Write the failing `[bunker]` config tests**

Append to `tests/test_config.py`:

```python
def test_the_bunker_table_defaults_and_values(tmp_path: Path) -> None:
    assert config.load(write(tmp_path, "")).bunker == config.BunkerConfig("bunker", "personal")
    cfg = config.load(write(tmp_path, '[bunker]\nname = "shack-1"\nmode = "group"\n'))
    assert (cfg.bunker.name, cfg.bunker.mode) == ("shack-1", "group")


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ('[bunker]\nname = "Shack"\n', "bunker.name"),
        ('[bunker]\nname = ""\n', "bunker.name"),
        ('[bunker]\nname = "-x"\n', "bunker.name"),
        (f'[bunker]\nname = "{"a" * 64}"\n', "bunker.name"),
        ('[bunker]\nmode = "club"\n', "bunker.mode"),
        ("[bunker]\nport = 1\n", "unknown key bunker.port"),
    ],
)
def test_a_bad_bunker_table_is_refused_by_key(tmp_path: Path, text: str, needle: str) -> None:
    with pytest.raises(ConfigError, match=needle):
        config.load(write(tmp_path, text))
```

Run: `.venv/bin/python -m pytest tests/test_config.py -q -k bunker`
Expected: FAIL — `AttributeError: module 'bunker.config' has no attribute 'BunkerConfig'`.

- [ ] **Step 5: Add `[bunker]` to `src/bunker/config.py`**

Add `"MODES"`, `"BunkerConfig"` to `__all__` (keep it sorted). After line 49 (`DEFAULT_PATHS`) add:

```python
#: ``personal``: one operator's machines. ``group``: several operators, one admin;
#: the Bunker filters ``owner:`` entries by enrolment (docs/reference.md).
MODES = ("personal", "group")
```

In `_KNOWN` (line 51) add `"bunker": ("name", "mode"),` as the first entry. After `Serve` (line 126) add:

```python
@dataclass(frozen=True)
class BunkerConfig:
    name: str = "bunker"
    """The signing principal is ``bunker:<name>``: lowercase letters, digits and hyphens."""
    mode: str = "personal"


_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
```

Add `bunker: BunkerConfig` to `Config` (after `serve: Serve`, before `path: Path`), add this function above `load`:

```python
def _bunker(table: Mapping[str, Any]) -> BunkerConfig:
    name = table.get("name", "bunker")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ConfigError(
            f"bunker.name is {name!r}; use 1 to 63 lowercase letters, digits and hyphens, "
            f"starting with a letter or digit"
        )
    return BunkerConfig(name=name, mode=_choice(table.get("mode", "personal"), "bunker.mode", MODES))
```

and in `load`'s `return Config(` pass `bunker=_bunker(_table(data, "bunker")),` before `path=path`.

Run: `.venv/bin/python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 6: Replace `src/bunker/index.py`**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""``catalogue.json``: the Bunker's own document, versioned, one per volume.

Three files carry it. ``catalogue.json`` is the published one: it is what the
server maps ``<unit>/<name>`` through, what the signatures cover and what a
laptop reads, and it changes only when :mod:`bunker.publish` writes it.
``.state.json`` is the Bunker's working copy, the same document unsigned,
rewritten after every artifact so a killed run loses nothing; it is never
served. ``index.json`` is the version-2 name, still read for one release so a
volume written by an older Bunker upgrades in place, and never deleted:
deleting is for a person.

``serial`` only grows. It lives in ``.serial`` as well as in the document so a
volume restored without its catalogue does not start again at 1, which every
laptop would refuse.

The document is never the proof of anything: every file it names has a
sidecar, and the bytes are re-hashed against the sidecar on a cadence. An
older document is upgraded on load; a newer one refuses, because a Bunker
cannot know what fields it would be dropping.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from bunker.checks import is_unverified
from bunker.config import MODES
from bunker.volume import write_atomic

__all__ = [
    "FILE",
    "INDEX_VERSION",
    "INPUT_KINDS",
    "KIND",
    "LEGACY_FILE",
    "SERIAL_FILE",
    "STATE",
    "STATUSES",
    "UPGRADES",
    "Entry",
    "Index",
    "IndexRefused",
    "Input",
    "Signer",
    "body",
    "held_unverified",
    "load",
    "next_serial",
    "render",
    "save",
]

INDEX_VERSION = 3
KIND = "bunker-index"
FILE = "catalogue.json"
LEGACY_FILE = "index.json"
STATE = ".state.json"
SERIAL_FILE = ".serial"
#: ``current``: the copy matches what the engine lists. ``stale``: the
#: engine lists a newer version the schedule has not fetched yet.
#: ``failed``: the last fetch failed; the copy named (if any) is the last
#: good one. ``corrupted``: the bytes no longer match the sidecar.
STATUSES = ("current", "stale", "failed", "corrupted")
#: The plan-time inputs of the contract (``inputs[].kind``).
INPUT_KINDS = (
    "region-outline",
    "tile-selection",
    "sheet-selection",
    "dem3dep-selection",
    "fstopo-selection",
)
_SHARE = re.compile(r"all|owner:[A-Za-z0-9_-]{1,64}")
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def _v1_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """Add the separate configuration-declined list without reclassifying v1."""
    return {**raw, "version": 2, "declined": []}


def _v2_to_v3(raw: dict[str, Any]) -> dict[str, Any]:
    """``engine.version`` becomes ``engine_version``; serial 0 means never
    published; signers and inputs start empty; each artifact gains the three
    fields the engine plans offline with (``share`` is ``all``)."""
    engine = raw.get("engine")
    out = {k: v for k, v in raw.items() if k != "engine"}
    if "engine_version" not in out:
        out["engine_version"] = engine.get("version") if isinstance(engine, dict) else None
    out["version"] = 3
    out.setdefault("serial", 0)
    out.setdefault("signers", [])
    out.setdefault("inputs", [])
    artifacts = raw.get("artifacts")
    if isinstance(artifacts, list):
        out["artifacts"] = [
            {"publisher_name": None, "publisher_size": None, "share": "all", **a}
            if isinstance(a, dict)
            else a
            for a in artifacts
        ]
    return out


#: vN -> vN+1, applied in order by :func:`load`.
UPGRADES: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
}


class IndexRefused(Exception):
    """The index on the volume cannot be read by this Bunker."""


@dataclass(frozen=True)
class Signer:
    """One key that signed the published catalogue (the contract's ``signers[]``)."""

    id: str
    """The key's SHA256 fingerprint."""
    public_key: str
    algorithm: str
    bits: int
    hardware: bool
    signature: str
    """Relative path of its signature, ``catalogue.sig.d/<n>.sig``."""


@dataclass
class Input:
    """A plan-time input the engine needs but an operator does not install:
    a region outline, or a selection derived from one."""

    kind: str
    region: str
    name: str
    path: str
    sha256: str
    size: int
    fetched: str


@dataclass
class Entry:
    """One artifact on the volume."""

    unit: str
    name: str
    path: str | None
    """The current copy, relative to the volume root; None when there is none."""
    sha256: str | None
    """sha256 of the current copy's bytes (the sidecar's claim when written)."""
    size: int | None
    publisher_check: str
    """How the engine verifies it: a kind from the table in :mod:`bunker.checks`."""
    publisher_digest: str | None
    """The digest of that kind the current copy was verified against."""
    publisher_url: str
    licence: str
    fetched: str | None
    verified: str | None
    status: str
    reason: str | None
    """Why the status is not ``current``; None when it is."""
    previous: str | None
    publisher_name: str | None = None
    """The dated file name the publisher's answer resolved to; None for an
    artifact the repository pins by sha256 (the pin is the trust)."""
    publisher_size: int | None = None
    """The size the publisher reported when the Bunker fetched it."""
    share: str = "all"
    """``all`` or ``owner:<enrolment id>``; only a group Bunker reads it."""


@dataclass
class Index:
    engine_version: str | None = None
    artifacts: list[Entry] = field(default_factory=list)
    deferred: list[dict[str, str | None]] = field(default_factory=list)
    declined: list[dict[str, str | None]] = field(default_factory=list)
    last_run: dict[str, Any] | None = None
    generated: str | None = None
    serial: int = 0
    """The serial last published; 0 before the first publication."""
    name: str = "bunker"
    mode: str = "personal"
    signers: list[dict[str, Any]] = field(default_factory=list)
    """The signers of the last published catalogue (``bunker keys`` and the
    status page read them)."""
    inputs: list[Input] = field(default_factory=list)

    def find(self, unit: str, name: str) -> Entry | None:
        for entry in self.artifacts:
            if entry.unit == unit and entry.name == name:
                return entry
        return None


_ENTRY_FIELDS = tuple(f.name for f in fields(Entry))


def _refuse(path: Path, detail: str) -> IndexRefused:
    return IndexRefused(
        f"{path} is not an index this Bunker can read ({detail}). Move it aside "
        f"(mv {path} {path}.bad): the next run re-hashes every file on the volume "
        f"against its sidecar and writes a new one."
    )


#: The type each Entry field holds on disk. Everything downstream (the status
#: page, the server's routes, the run's arithmetic) trusts these, so a document
#: that breaks one is refused here, with the field named, not at the first use.
_ENTRY_TYPES: dict[str, tuple[type, ...]] = {
    "unit": (str,),
    "name": (str,),
    "path": (str, type(None)),
    "sha256": (str, type(None)),
    "size": (int, type(None)),
    "publisher_check": (str,),
    "publisher_digest": (str, type(None)),
    "publisher_url": (str,),
    "licence": (str,),
    "fetched": (str, type(None)),
    "verified": (str, type(None)),
    "status": (str,),
    "reason": (str, type(None)),
    "previous": (str, type(None)),
    "publisher_name": (str, type(None)),
    "publisher_size": (int, type(None)),
    "share": (str,),
}
_INPUT_TYPES: dict[str, tuple[type, ...]] = {
    "kind": (str,),
    "region": (str,),
    "name": (str,),
    "path": (str,),
    "sha256": (str,),
    "size": (int,),
    "fetched": (str,),
}


def _is(value: Any, types: tuple[type, ...]) -> bool:
    return isinstance(value, types) and not (isinstance(value, bool) and bool not in types)


def _entry(path: Path, raw: Any, position: int) -> Entry:
    if not isinstance(raw, dict):
        raise _refuse(path, f"artifact {position} is not an object")
    missing = [k for k in _ENTRY_FIELDS if k not in raw]
    if missing:
        raise _refuse(path, f"artifact {position} has no {missing[0]!r}")
    for key, types in _ENTRY_TYPES.items():
        if not _is(raw[key], types):
            raise _refuse(
                path,
                f"artifact {position}: {key!r} is {raw[key]!r}, not "
                + " or ".join(t.__name__ for t in types),
            )
    if raw["status"] not in STATUSES:
        raise _refuse(path, f"artifact {position} has status {raw['status']!r}")
    if not _SHARE.fullmatch(raw["share"]):
        raise _refuse(path, f"artifact {position}: share {raw['share']!r} is not all or owner:<id>")
    return Entry(**{k: raw[k] for k in _ENTRY_FIELDS})


def _input(path: Path, raw: Any, position: int) -> Input:
    if not isinstance(raw, dict):
        raise _refuse(path, f"input {position} is not an object")
    for key, types in _INPUT_TYPES.items():
        if key not in raw:
            raise _refuse(path, f"input {position} has no {key!r}")
        if not _is(raw[key], types):
            raise _refuse(
                path,
                f"input {position}: {key!r} is {raw[key]!r}, not "
                + " or ".join(t.__name__ for t in types),
            )
    if raw["kind"] not in INPUT_KINDS:
        raise _refuse(path, f"input {position} has kind {raw['kind']!r}")
    return Input(**{k: raw[k] for k in _INPUT_TYPES})


def _notes(path: Path, raw: dict[str, Any], key: str) -> list[dict[str, str | None]]:
    """``deferred`` or ``declined``: a list of objects whose values are text or null."""
    value = raw.get(key) or []
    if not isinstance(value, list) or not all(
        isinstance(row, dict) and all(isinstance(v, str | None) for v in row.values())
        for row in value
    ):
        raise _refuse(path, f"its {key} are not a list of objects of text")
    return list(value)


def _list_of_objects(path: Path, raw: dict[str, Any], key: str) -> list[Any]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise _refuse(path, f"its {key} are not a list")
    return value


def _last_run(path: Path, value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("plain_http", []), list):
        raise _refuse(path, "its last_run is not an object")
    return value


def _source(root: Path) -> Path | None:
    """The file :func:`load` reads: the working copy, else the published
    catalogue, else the version-2 name."""
    for name in (STATE, FILE, LEGACY_FILE):
        if (root / name).exists():
            return root / name
    return None


def load(root: Path) -> Index:
    """The volume's index: empty when absent, upgraded when older, refused
    when corrupt or newer."""
    path = _source(root)
    if path is None:
        return Index()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Index()
    except UnicodeDecodeError as exc:
        raise _refuse(path, f"not JSON: {exc}") from None
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _refuse(path, f"not JSON: {exc}") from None
    if not isinstance(raw, dict) or raw.get("kind") != KIND:
        raise _refuse(path, f"its kind is not {KIND!r}")
    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _refuse(path, "it has no version")
    if version > INDEX_VERSION:
        raise IndexRefused(
            f"{path} is index version {version}, written by a newer Bunker; this one "
            f"reads version {INDEX_VERSION} and would drop what it does not know. "
            f"Run the newer release, or move the index aside."
        )
    upgraded = version < INDEX_VERSION
    while version < INDEX_VERSION:
        step = UPGRADES.get(version)
        if step is None:
            raise IndexRefused(
                f"{path} is index version {version} and this Bunker has no upgrade "
                f"from it; move it aside and the next run writes a new one."
            )
        raw = step(raw)
        version += 1
    artifacts = raw.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise _refuse(path, "its artifacts are not a list")
    if "engine_version" in raw:
        engine_version = raw["engine_version"]
    else:  # a version-3 file written before engine_version, or a hand edit
        engine = raw.get("engine")
        engine_version = engine.get("version") if isinstance(engine, dict) else None
    generated = raw.get("generated")
    if not isinstance(engine_version, str | None) or not isinstance(generated, str | None):
        raise _refuse(path, "its engine version or generated time is not text")
    serial = raw.get("serial", 0)
    if isinstance(serial, bool) or not isinstance(serial, int) or serial < 0:
        raise _refuse(path, f"its serial is {serial!r}, not a whole number")
    signers = _list_of_objects(path, raw, "signers")
    if not all(isinstance(s, dict) for s in signers):
        raise _refuse(path, "its signers are not a list of objects")
    bunker = raw.get("bunker")
    name, mode = "bunker", "personal"
    if isinstance(bunker, dict):
        if isinstance(bunker.get("name"), str) and _NAME.fullmatch(bunker["name"]):
            name = bunker["name"]
        if bunker.get("mode") in MODES:
            mode = bunker["mode"]
    index = Index(
        engine_version=engine_version,
        artifacts=[_entry(path, a, n) for n, a in enumerate(artifacts)],
        deferred=_notes(path, raw, "deferred"),
        declined=_notes(path, raw, "declined"),
        last_run=_last_run(path, raw.get("last_run")),
        generated=generated,
        serial=serial,
        name=name,
        mode=mode,
        signers=[dict(s) for s in signers],
        inputs=[_input(path, i, n) for n, i in enumerate(_list_of_objects(path, raw, "inputs"))],
    )
    if upgraded:
        save(root, index, generated=index.generated or "")
    return index


def body(
    idx: Index,
    *,
    serial: int,
    generated: str,
    signers: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """The v3 document as a dict. *signers* defaults to the index's own."""
    return {
        "kind": KIND,
        "version": INDEX_VERSION,
        "serial": serial,
        "generated": generated,
        "bunker": {"name": idx.name, "mode": idx.mode},
        "signers": [dict(s) for s in (idx.signers if signers is None else signers)],
        "engine_version": idx.engine_version,
        "artifacts": [asdict(e) for e in idx.artifacts],
        "inputs": [asdict(i) for i in idx.inputs],
        "deferred": idx.deferred,
        "declined": idx.declined,
        "last_run": idx.last_run,
    }


def render(
    idx: Index,
    *,
    serial: int,
    generated: str,
    signers: Sequence[Mapping[str, Any]] | None = None,
) -> bytes:
    """The exact bytes that are signed and served."""
    text = json.dumps(
        body(idx, serial=serial, generated=generated, signers=signers),
        indent=2,
        ensure_ascii=False,
    )
    return (text + "\n").encode("utf-8")


def save(root: Path, index: Index, *, generated: str) -> None:
    """Write the working copy atomically: a reader sees the old one or the new one."""
    index.generated = generated
    root.mkdir(parents=True, exist_ok=True)
    write_atomic(root / STATE, render(index, serial=index.serial, generated=generated))


def next_serial(root: Path, published: int) -> int:
    """The serial for the next catalogue: one more than the highest this
    volume has ever used. Written before anything is published, so a publish
    that fails halfway still burns the number rather than reusing it."""
    try:
        high = int((root / SERIAL_FILE).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        high = 0
    serial = max(high, published, 0) + 1
    root.mkdir(parents=True, exist_ok=True)
    write_atomic(root / SERIAL_FILE, f"{serial}\n".encode("ascii"))
    return serial


def held_unverified(index: Index) -> list[Entry]:
    """The artifacts on the volume whose check names no digest (``unverified-zip``, ``unverified-fetch``),
    in index order: what ``status``, the status page and ``doctor`` list under
    the maintainer's ruling."""
    return [e for e in index.artifacts if e.path is not None and is_unverified(e.publisher_check)]
```

- [ ] **Step 7: Run the index and config tests**

Run: `.venv/bin/python -m pytest tests/test_index.py tests/test_config.py -q`
Expected: PASS. The two tests that call the engine's reader (`test_every_rendered_document_passes_the_engines_reader`, `test_the_engines_reader_refuses_a_catalogue_with_no_signer`) SKIP on an engine without `hammunition.catalogue` and PASS on the Plan A checkout.

- [ ] **Step 8: `bunker.publish` and the engine accessors**

Add to `src/bunker/enginelib.py` after line 67 (and add `"catalogue_module"`, `"validate_catalogue"` to `__all__`):

```python
def catalogue_module() -> ModuleType:
    """``hammunition.catalogue``, the engine's reader for the catalogue this
    Bunker writes (Plan A; the contract names ``parse()``)."""
    try:
        return importlib.import_module("hammunition.catalogue")
    except ImportError:
        raise BackendError(
            "the installed Hammunition has no hammunition.catalogue, which reads the "
            "catalogue this Bunker publishes; install the Hammunition release that carries it"
        ) from None


def validate_catalogue(data: bytes) -> None:
    """Raise unless the engine's own reader accepts *data*. Task 11 makes a
    missing module an error; until the pin moves, an engine without one is not
    asked (nothing can be published against it anyway)."""
    try:
        reader = catalogue_module()
    except BackendError:
        return
    reader.parse(data)
```

Create `src/bunker/publish.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publishing: the one place ``catalogue.json`` is written.

A run, ``bunker verify`` and the key and enrolment commands all end here, so
the served catalogue changes at most once per command and never between two
artifacts of a run. Until Task 2 the catalogue is written unsigned.
"""

from __future__ import annotations

from dataclasses import dataclass

from bunker import index
from bunker.config import Config
from bunker.index import Index
from bunker.volume import write_atomic

__all__ = ["PublishResult", "ensure_published", "publish"]


@dataclass(frozen=True)
class PublishResult:
    published: bool
    """False when nothing needed publishing (Task 2)."""
    serial: int
    signed_by: tuple[str, ...] = ()
    """Fingerprints of the keys whose signatures went out with it."""
    skipped: tuple[tuple[str, str], ...] = ()
    """``(fingerprint, reason)`` for each key that could not sign this time."""


def publish(cfg: Config, idx: Index, *, generated: str) -> PublishResult:
    """Write ``catalogue.json`` from *idx* and record the new serial."""
    root = cfg.storage.root
    idx.name, idx.mode = cfg.bunker.name, cfg.bunker.mode
    serial = index.next_serial(root, idx.serial)
    write_atomic(root / index.FILE, index.render(idx, serial=serial, generated=generated, signers=()))
    idx.serial = serial
    index.save(root, idx, generated=generated)
    return PublishResult(published=True, serial=serial)


def ensure_published(cfg: Config, *, generated: str) -> None:
    """A fresh volume serves a catalogue (the container's healthcheck asks for
    it) before its first run. A volume that has any state is left alone."""
    root = cfg.storage.root
    if any((root / n).exists() for n in (index.STATE, index.FILE, index.LEGACY_FILE)):
        return
    publish(cfg, index.load(root), generated=generated)
```

- [ ] **Step 9: Wire the run, verify and the CLI to `publish`**

`src/bunker/run.py`: change line 36 to `from bunker import publish, statuspage`. In `_finish` (lines 651-670) replace the `save_index(root, idx, generated=report.finished)` line with:

```python
    save_index(root, idx, generated=report.finished)
    publish.publish(cfg, idx, generated=report.finished)
```

(The first line stays: the working state is saved before anything can fail.)

`src/bunker/verify.py`: change line 20 to `from bunker import publish, statuspage` and replace lines 128-129 with:

```python
        save_index(root, idx, generated=report.finished)
        publish.publish(cfg, idx, generated=report.finished)
        statuspage.write(root, idx)
```

`src/bunker/cli.py`: change the import on line 272 to add `publish` (`from bunker import __version__, checks, config, envelope, index, publish, run, schedule, server, verify`). In `cmd_serve` and `cmd_schedule` replace `index.ensure(cfg.storage.root, generated=_now_iso())` and `index.ensure(root, generated=_now_iso())` with `publish.ensure_published(cfg, generated=_now_iso())` (keep the `index.load(...)` that follows each).

- [ ] **Step 10: The server reads `catalogue.json`, and answers `index.json` as an alias**

In `src/bunker/server.py` replace `Routes` (lines 55-99) with:

```python
CATALOGUE = "catalogue.json"
LEGACY = "index.json"


class Routes:
    """Request path -> file, rebuilt whenever the catalogue changes. The
    catalogue is ``catalogue.json``; ``index.json`` is its alias for one
    release (and the old document itself on a volume that was never published
    by a v3 Bunker)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._stamp: tuple[str, int, int, int] | None = None
        self._map: dict[str, Target] = {}

    def _document(self) -> Path | None:
        for name in (CATALOGUE, LEGACY):
            if (self.root / name).is_file():
                return self.root / name
        return None

    def _build(self, document: Path | None) -> dict[str, Target]:
        routes = {
            "": Target("status.html", "text/html; charset=utf-8"),
            "status.html": Target("status.html", "text/html; charset=utf-8"),
        }
        if document is None:
            return routes
        routes["index.json"] = Target(document.name, "application/json")
        if document.name == CATALOGUE:
            routes["catalogue.json"] = Target(CATALOGUE, "application/json")
        try:
            raw = json.loads(document.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return routes
        items = raw.get("artifacts") if isinstance(raw, dict) else None
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            unit, name, path = item.get("unit"), item.get("name"), item.get("path")
            if not (isinstance(unit, str) and isinstance(name, str) and isinstance(path, str)):
                continue
            if not (unit and name and path) or item.get("status") == "corrupted":
                continue  # a corrupted copy: the consumer would reject it; a 404 sends them on
            data = Target(path, "application/octet-stream")
            routes.setdefault(f"{unit}/{name}", data)
            routes.setdefault(path, data)
            routes.setdefault(path + SIDECAR, Target(path + SIDECAR, "text/plain; charset=utf-8"))
        return routes

    def lookup(self, request_path: str) -> Target | None:
        document = self._document()
        stamp: tuple[str, int, int, int] | None = None
        if document is not None:
            try:
                info = os.stat(document)
                stamp = (document.name, info.st_mtime_ns, info.st_size, info.st_ino)
            except OSError:
                document = None
        with self._lock:
            if stamp != self._stamp or not self._map:
                self._map = self._build(document)
                self._stamp = stamp
            return self._map.get(request_path)
```

Change line 207 to `if target.path in ("catalogue.json", "index.json", "status.html"):` and the module docstring's first paragraph (lines 6-8) to say "through ``catalogue.json``". In `src/bunker/volume.py` change line 58 to `RESERVED = ("index.json", "catalogue.json", "status.html")` and the docstring line 15 to `catalogue.json  status.html     what is served as navigation (index.json: the v2 name, read for one release)`. In `src/bunker/statuspage.py` lines 208-211 change `index.json` to `catalogue.json` (both the href and the text).

- [ ] **Step 11: Update the existing tests that name the file**

Apply with exact edits:

- `tests/test_run.py` lines 47-48 become:
  ```python
      raw = json.loads((scene.root / "catalogue.json").read_text())
      assert raw["engine_version"] == "0.21.0"
      assert raw["serial"] == 1 and raw["bunker"] == {"name": "bunker", "mode": "personal"}
  ```
- `tests/test_server.py` lines 169, 173, 183, 185, 192, 194: `scene.root / "index.json"` becomes `scene.root / "catalogue.json"` (six occurrences; `sed -i '169,194s#scene.root / "index.json"#scene.root / "catalogue.json"#' tests/test_server.py`). Lines 123, 144, 163, 201 keep `/index.json`: they test the alias.
- `tests/test_kinds.py` line 319: replace `(bench.root / "index.json").unlink()` with
  ```python
      for name in (FILE, STATE):  # the index moved aside: the published copy and the working copy
          (bench.root / name).unlink()
  ```
  and add `from bunker.index import FILE, STATE` beside line 31.
- `tests/test_volume.py` line 41: add `("catalogue.json", "x"),` under `("index.json", "x"),`.
- `fuzz/fuzz_server_paths.py` line 29: `_ROOT / "index.json"` becomes `_ROOT / "catalogue.json"`. `fuzz/fuzz_index_status.py`: in `_entry` add after `"previous": _val(fdp, None),` the three lines `"publisher_name": _val(fdp, None), "publisher_size": _val(fdp, None), "share": _val(fdp, "all"),`; in `_document` replace the `"engine": ...` line with `"engine_version": _val(fdp, "0.22.0"),` and add `"serial": _val(fdp, 1), "bunker": _val(fdp, {"name": "bunker", "mode": "personal"}), "signers": _val(fdp, []), "inputs": _val(fdp, []),`; change `version = index.INDEX_VERSION if ...` unchanged; line 90 `_ROOT / "index.json"` becomes `_ROOT / index.FILE`.

- [ ] **Step 12: The publish tests and the every-publication guard**

Create `tests/test_publish.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""``bunker.publish``: the one place the served catalogue is written."""

from __future__ import annotations

import json
from pathlib import Path

from bunker import config, index, publish
from bunker.index import Index
from tests.helpers import config_text


def cfg_for(tmp_path: Path) -> config.Config:
    path = tmp_path / "bunker.toml"
    path.write_text(config_text(str(tmp_path / "vol")))
    return config.load(path)


def test_ensure_publishes_an_empty_catalogue_only_on_a_fresh_volume(tmp_path: Path) -> None:
    cfg = cfg_for(tmp_path)
    publish.ensure_published(cfg, generated="g1")
    published = json.loads((cfg.storage.root / index.FILE).read_text())
    assert published["artifacts"] == [] and published["serial"] == 1
    publish.ensure_published(cfg, generated="g2")
    assert json.loads((cfg.storage.root / index.FILE).read_text())["generated"] == "g1"


def test_a_volume_with_only_a_v2_index_json_is_left_alone(tmp_path: Path) -> None:
    cfg = cfg_for(tmp_path)
    cfg.storage.root.mkdir()
    (cfg.storage.root / "index.json").write_text("{}")
    publish.ensure_published(cfg, generated="g")
    assert not (cfg.storage.root / index.FILE).exists()


def test_publish_takes_name_and_mode_from_the_config_and_bumps_the_serial(tmp_path: Path) -> None:
    cfg = cfg_for(tmp_path)
    idx = Index()
    first = publish.publish(cfg, idx, generated="2026-10-07T12:00:00Z")
    second = publish.publish(cfg, idx, generated="2026-10-07T13:00:00Z")
    assert (first.serial, second.serial) == (1, 2) and idx.serial == 2
    document = json.loads((cfg.storage.root / index.FILE).read_text())
    assert document["serial"] == 2 and document["bunker"] == {"name": "bunker", "mode": "personal"}
    assert index.load(cfg.storage.root).serial == 2
```

Add to `tests/conftest.py` (after the imports, before the network guard) — and `import json` is already there:

```python
#: Task 2 sets this to False: from then on every published catalogue has a signer,
#: and the guard below parses every one with the engine's reader.
UNSIGNED_OK = True


@pytest.fixture(autouse=True)
def _every_publication_passes_the_engines_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every catalogue the Bunker publishes, in any test, must pass
    ``hammunition.catalogue.parse()`` of the pinned engine. Until the engine has
    the module this checks nothing (``tests/plan_a.py``); once it does, it
    cannot be forgotten."""
    from bunker import publish
    from tests import plan_a

    real = publish.publish

    def checked(cfg: Any, idx: Any, *, generated: str) -> Any:
        result = real(cfg, idx, generated=generated)
        reader = plan_a.optional("hammunition.catalogue")
        if result.published and reader is not None:
            data = (cfg.storage.root / "catalogue.json").read_bytes()
            if not UNSIGNED_OK or json.loads(data)["signers"]:
                reader.parse(data)
        return result

    monkeypatch.setattr(publish, "publish", checked)
```

- [ ] **Step 13: Run the whole suite**

Run: `.venv/bin/python -m pytest -q -W error::DeprecationWarning; echo "exit=$?"`
Expected: `exit=0`. If `tests/test_cli.py::test_*golden` fails on a changed document, the cause is a real change (read the diff); `status.json`/`run.json` do not change in this task.

- [ ] **Step 14: Docs, changelog, falsification, `make check`, commit**

`docs/reference.md`: in the Configuration table add after the `engine.timeout` row:

```
| `bunker.name` | `"bunker"` | the name this Bunker signs as: the signing principal is `bunker:<name>`. 1 to 63 lowercase letters, digits and hyphens |
| `bunker.mode` | `"personal"` | `personal` (one operator's machines) or `group` (several operators, one admin; Task 6's `share` filter) |
```

Replace the `## The volume` tree (lines 158-168) with one that lists `catalogue.json` (the published catalogue), `.state.json` (the working copy), `.serial` (the highest serial ever used) and `index.json` (the v2 name, read once and never deleted); replace `## The index` (lines 176-205) with `## The catalogue`: "`catalogue.json`, version 3", a field table with `kind`, `version` (3; an index of version 1 or 2 is upgraded in place on load, a newer one refused), `serial`, `generated`, `bunker.name`, `bunker.mode`, `signers`, `engine_version`, `artifacts`, `inputs`, `deferred`, `declined`, `last_run`, the artifact table of the old section plus `publisher_name`, `publisher_size` and `share`, and a paragraph: "Three files carry it. `catalogue.json` is published once at the end of a run, a `verify`, a key or enrolment change; `.state.json` is the working copy a run rewrites after every artifact and nobody is served; `index.json` is the old name, answered as an alias for one release." In the HTTP table add `/catalogue.json` and change `/index.json` to "the catalogue (alias of `/catalogue.json`, for one release)". In `docs/guide.md` change the three `index.json` mentions (lines 212, 258, 305) to `catalogue.json` and the link anchor to `reference.md#the-catalogue`. `CHANGELOG.md`, first `### Added` under Unreleased: "- Catalogue version 3: `index.json` becomes `catalogue.json` with `serial`, `bunker`, `signers`, `inputs` and per-artifact `publisher_name`, `publisher_size` and `share`; a version-2 `index.json` upgrades in place; the working copy is `.state.json`, published once per run through `bunker.publish`; `[bunker]` config (`name`, `mode`). The serial is kept in `.serial` so a lost catalogue cannot lower it."

Falsify once: in `index.next_serial` temporarily change `max(high, published, 0) + 1` to `max(published, 0) + 1`, run `.venv/bin/python -m pytest tests/test_index.py -q -k serial` — Expected: `test_the_serial_never_goes_backwards_when_the_catalogue_is_lost` FAILS (`assert 1 == 3`); restore it.

Run: `make check; echo "exit=$?"` — Expected: `exit=0`.

```bash
git add src/bunker/index.py src/bunker/publish.py src/bunker/config.py src/bunker/enginelib.py src/bunker/run.py src/bunker/verify.py src/bunker/cli.py src/bunker/server.py src/bunker/volume.py src/bunker/statuspage.py fuzz/fuzz_index_status.py fuzz/fuzz_server_paths.py tests/plan_a.py tests/helpers.py tests/conftest.py tests/test_index.py tests/test_config.py tests/test_publish.py tests/test_run.py tests/test_server.py tests/test_kinds.py tests/test_volume.py docs/reference.md docs/guide.md CHANGELOG.md
git commit -m "Catalogue v3: index.json becomes catalogue.json, published once per run

serial, bunker {name, mode}, signers, inputs and per-artifact publisher_name,
publisher_size and share; a v2 index.json upgrades in place; the working copy is
.state.json; the serial has its own high-water file so a lost catalogue cannot
lower it; [bunker] config."
```

### Task 2: Signing — backends, one signature per key, atomic publication

`bunker.signing` signs the exact bytes of `catalogue.json` with `ssh-keygen -Y sign -n hammunition-bunker-catalogue`, once per configured key, for three backends (`file`, `security-key`, `agent`) that differ only in what `-f` points at and what the process can reach. `publish_signed` is the one place the served pair (`catalogue.json`, `catalogue.sig.d/<n>.sig`) changes: stage everything, verify every signature locally, validate with the engine's reader, then rename into place. A fake-backend seam lets every other test publish without a token or `ssh-keygen`; tests that exercise the real thing generate real file keys with `ssh-keygen` in `tmp_path` and are marked `real_signing`.

**Files:**
- Create: `src/bunker/signing.py`, `tests/signing_fakes.py`, `tests/realkeys.py`, `tests/test_signing.py`
- Modify: `src/bunker/publish.py` (whole body, 1-52 as written in Task 1), `src/bunker/index.py` (add `parse_stamp`; imports 31-36), `src/bunker/volume.py` (`RunLock.__init__` 548-553), `src/bunker/run.py` (`_parse` 93-99, `RunReport` 137-217, `_finish` 651-670), `src/bunker/verify.py` (`VerifyReport` 41-65, tail 127-130), `src/bunker/cli.py` (`_dispatch` 529-540), `tests/conftest.py`, `tests/test_publish.py`, `tests/test_cli.py` (`test_schedule_serves_runs_and_stops_on_sigterm` 202-238), `tests/test_run.py`, `pyproject.toml` (`[tool.pytest.ini_options]`), `docs/reference.md`, `CHANGELOG.md`
- Test: `tests/test_signing.py` (real `ssh-keygen`, real `ssh-agent`), `tests/test_publish.py` (fake backend), `tests/test_run.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `bunker.index` (`Index`, `Signer`, `body`, `render`, `save`, `next_serial`, `FILE`), `bunker.volume` (`RunLock`, `Locked`, `write_atomic`), `bunker.enginelib.validate_catalogue`.
- Produces (`bunker.signing`):
  - `NAMESPACE = "hammunition-bunker-catalogue"`, `SIG_DIR = "catalogue.sig.d"`, `KEYS_DIR = ".keys"`, `REGISTRY = "keys.json"`, `STAGING = ".publish.tmp"`, `PUBLISH_LOCK = ".publish.lock"`, `SIGN_TIMEOUT: float = 60.0`, `REFRESH: timedelta = timedelta(days=7)`, `BACKEND_NAMES = ("file", "security-key", "agent")`
  - `class SigningError(Exception)`; `SignerUnavailable(SigningError)`; `SignatureInvalid(SigningError)`; `PublishFailed(SigningError)`
  - `@dataclass(frozen=True) class KeySpec: id: str; backend: str; public_key: str; algorithm: str; bits: int; hardware: bool; path: str; no_touch: bool = False; retired: str | None = None; added: str = ""`
  - `Runner = Callable[[Sequence[str], bytes, float, Mapping[str, str] | None], subprocess.CompletedProcess[bytes]]`; `run_command(argv: Sequence[str], stdin: bytes, timeout: float, env: Mapping[str, str] | None) -> subprocess.CompletedProcess[bytes]`
  - `class Backend(Protocol): sign(self, spec: KeySpec, data: bytes, *, timeout: float) -> bytes; verify(self, spec: KeySpec, data: bytes, signature: bytes, *, principal: str) -> None`
  - `class SshKeygenBackend(command: Sequence[str] = ("ssh-keygen",), *, agent_socket: str | None = None, run: Runner = run_command)`; `BACKENDS: dict[str, Backend]`
  - `fingerprint(public_key: str) -> str`, `clean_public_key(line: str) -> str`, `allowed_signers_line(principal: str, public_key: str) -> str`
  - `keys_dir(root: Path) -> Path`, `load_registry(root: Path) -> list[KeySpec]`, `save_registry(root: Path, keys: Sequence[KeySpec]) -> None`, `load_signed(root: Path) -> dict[str, str]`, `record_signed(root: Path, ids: Sequence[str], when: str) -> None`
  - `stable_digest(doc: Mapping[str, Any]) -> str`
  - `@dataclass(frozen=True) class PublishResult(published: bool, serial: int, signed_by: tuple[str, ...] = (), skipped: tuple[tuple[str, str], ...] = ())` (moved from `bunker.publish`, which re-exports it)
  - `publish_signed(root: Path, idx: Index, *, generated: str, keys: Sequence[KeySpec], backends: Mapping[str, Backend], refresh: timedelta = REFRESH, timeout: float = SIGN_TIMEOUT, validate: Callable[[bytes], None] | None = None) -> PublishResult`
  - `bunker.index.parse_stamp(text: str | None) -> datetime | None`; `bunker.volume.RunLock(root: Path, name: str = ".lock")`
  - `tests.signing_fakes.FakeBackend` (`fail: dict[str, str]`, `broken: set[str]`, `calls: list[str]`, `signature(spec, data) -> bytes`), `fake_key(...) -> KeySpec`, `install_fake_backends(monkeypatch) -> FakeBackend`; `tests.realkeys.make_file_key(root: Path, kind: str = "ed25519") -> KeySpec`; the `real_signing` pytest marker and the autouse `_fake_signing` fixture.

- [ ] **Step 1: The fake backend, the real-key helper, the marker and the fixture**

Create `tests/signing_fakes.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""A signer that needs no token and no ssh-keygen, for every test that is not
about the real thing. It signs a digest of the bytes it is given, so a
catalogue changed after signing fails its verify exactly as a real one would."""

from __future__ import annotations

import hashlib

import pytest

from bunker import signing
from bunker.signing import KeySpec, SignatureInvalid, SignerUnavailable
from tests.helpers import FAKE_ID, FAKE_PUBLIC


class FakeBackend:
    def __init__(self) -> None:
        self.fail: dict[str, str] = {}
        """Key id -> why it cannot sign right now (an unplugged token)."""
        self.broken: set[str] = set()
        """Key ids whose signature does not verify."""
        self.calls: list[str] = []
        """Key ids, in the order they signed."""

    @staticmethod
    def signature(spec: KeySpec, data: bytes) -> bytes:
        digest = hashlib.sha256(data).hexdigest().encode()
        return b"FAKE-SIGNATURE " + spec.id.encode() + b" " + digest + b"\n"

    def sign(self, spec: KeySpec, data: bytes, *, timeout: float) -> bytes:
        if spec.id in self.fail:
            raise SignerUnavailable(self.fail[spec.id])
        self.calls.append(spec.id)
        return self.signature(spec, data)

    def verify(self, spec: KeySpec, data: bytes, signature: bytes, *, principal: str) -> None:
        if spec.id in self.broken or signature != self.signature(spec, data):
            raise SignatureInvalid(f"the signature of {spec.id} does not verify")


def fake_key(
    *,
    backend: str = "file",
    public: str = FAKE_PUBLIC,
    key_id: str = FAKE_ID,
    algorithm: str = "ssh-ed25519",
    bits: int = 256,
    hardware: bool = False,
    no_touch: bool = False,
) -> KeySpec:
    return KeySpec(
        id=key_id,
        backend=backend,
        public_key=public,
        algorithm=algorithm,
        bits=bits,
        hardware=hardware,
        path="/nonexistent/fake-key",
        no_touch=no_touch,
        added="2026-10-07T00:00:00Z",
    )


def install_fake_backends(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    backend = FakeBackend()
    for name in signing.BACKEND_NAMES:
        monkeypatch.setitem(signing.BACKENDS, name, backend)
    return backend
```

Create `tests/realkeys.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real keys from the real ``ssh-keygen``, generated in a temp directory: the
tests that sign for real use these, never a token."""

from __future__ import annotations

import subprocess
from pathlib import Path

from bunker import signing
from bunker.signing import KeySpec

_KINDS = {
    "ed25519": ["-t", "ed25519"],
    "ecdsa": ["-t", "ecdsa", "-b", "384"],
    "rsa3072": ["-t", "rsa", "-b", "3072"],
    "rsa2048": ["-t", "rsa", "-b", "2048"],
}


def make_file_key(root: Path, kind: str = "ed25519", *, register: bool = True) -> KeySpec:
    """A real passphrase-less key under ``<root>/.keys``, registered unless told not to."""
    folder = signing.keys_dir(root)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = folder / f"test-{kind}-{len(list(folder.glob('test-*.pub')))}"
    subprocess.run(
        ["ssh-keygen", "-q", *_KINDS[kind], "-N", "", "-C", "bunker-test", "-f", str(target)],
        check=True,
        capture_output=True,
    )
    public = target.with_name(target.name + ".pub").read_text(encoding="utf-8").strip()
    listing = subprocess.run(
        ["ssh-keygen", "-l", "-f", str(target) + ".pub"], check=True, capture_output=True, text=True
    ).stdout.split()
    spec = KeySpec(
        id=signing.fingerprint(public),
        backend="file",
        public_key=public,
        algorithm=public.split()[0],
        bits=int(listing[0]),
        hardware=False,
        path=str(target),
        added="2026-10-07T00:00:00Z",
    )
    if register:
        signing.save_registry(root, [*signing.load_registry(root), spec])
    return spec
```

Add to `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
markers = [
    "real_signing: signs with the real ssh-keygen and the real key registry (no fake backend); skipped where ssh-keygen is missing",
]
```

In `tests/conftest.py` change `UNSIGNED_OK = True` to `UNSIGNED_OK = False` (every publication now has a signer), add the imports `from bunker import signing`, `from bunker.signing import KeySpec`, `import shutil` and `from tests.signing_fakes import FakeBackend, fake_key, install_fake_backends`, and append:

```python
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if shutil.which("ssh-keygen") is not None:
        return
    skip = pytest.mark.skip(reason="ssh-keygen (openssh-client) is not installed here")
    for item in items:
        if item.get_closest_marker("real_signing") is not None:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _fake_signing(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> FakeBackend | None:
    """Every test that is not marked ``real_signing`` signs with the fake backend,
    and every volume without a key registry has the one fake key. No test needs
    a token, ``ssh-keygen`` or an agent unless it says so."""
    if request.node.get_closest_marker("real_signing") is not None:
        return None
    backend = install_fake_backends(monkeypatch)
    real_registry = signing.load_registry

    def registry(root: Path) -> list[KeySpec]:
        return real_registry(root) or [fake_key()]

    monkeypatch.setattr(signing, "load_registry", registry)
    return backend


@pytest.fixture
def fake_backend(_fake_signing: FakeBackend | None) -> FakeBackend:
    assert _fake_signing is not None, "a real_signing test asked for the fake backend"
    return _fake_signing
```

- [ ] **Step 2: Write the failing publish tests (fake backend)**

Rewrite `tests/test_publish.py`: keep the three Task 1 tests, with these edits (a stamp is required now: `ensure_published(cfg, generated="2026-10-07T12:00:00Z")` and `"2026-10-07T13:00:00Z"` replace `"g1"` and `"g2"`, and the assertion on `generated` follows; in `test_publish_takes_name_and_mode_from_the_config_and_bumps_the_serial` the second publish uses `generated="2026-10-15T12:00:00Z"`, eight days on, because an unchanged catalogue under a week old is no longer signed again); put this import block at the top, replacing the old one:

```python
from __future__ import annotations

import dataclasses
import errno
import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from bunker import config, index, publish, signing
from bunker.index import Index
from bunker.signing import KeySpec, PublishFailed
from bunker.volume import RunLock
from tests import plan_a
from tests.helpers import FAKE_SK_ID, FAKE_SK_PUBLIC, config_text
from tests.signing_fakes import FakeBackend, fake_key
from tests.test_index import an_entry
```

and append:

```python
GEN = "2026-10-07T12:00:00Z"
LATER = "2026-10-08T12:00:00Z"
EIGHT_DAYS = "2026-10-15T12:00:00Z"

A = fake_key()  # a file key
B = fake_key(  # a security key that needs a touch
    backend="security-key",
    public=FAKE_SK_PUBLIC,
    key_id=FAKE_SK_ID,
    algorithm="sk-ssh-ed25519@openssh.com",
    hardware=True,
)


def idx() -> Index:
    return Index(name="shack-1", engine_version="0.22.0", artifacts=[an_entry()])


def changed() -> Index:
    other = idx()
    other.artifacts[0].status = "failed"
    return other


def served(root: Path) -> dict[str, bytes]:
    signatures = sorted(p.relative_to(root).as_posix() for p in (root / signing.SIG_DIR).glob("*.sig"))
    return {n: (root / n).read_bytes() for n in [index.FILE, *signatures] if (root / n).exists()}


def go(
    root: Path,
    index_: Index,
    keys: list[KeySpec],
    *,
    generated: str = GEN,
    refresh: timedelta = signing.REFRESH,
    validate: Callable[[bytes], None] | None = None,
) -> signing.PublishResult:
    return signing.publish_signed(
        root,
        index_,
        generated=generated,
        keys=keys,
        backends=signing.BACKENDS,
        refresh=refresh,
        validate=validate,
    )


def test_one_signature_per_key_and_the_catalogue_names_them(
    tmp_path: Path, fake_backend: FakeBackend
) -> None:
    result = go(tmp_path, idx(), [B, A])
    assert result.published and result.serial == 1 and result.skipped == ()
    assert result.signed_by == (A.id, B.id), "unattended keys sign first, touch-required last"
    data = (tmp_path / index.FILE).read_bytes()
    document = json.loads(data)
    assert [s["id"] for s in document["signers"]] == [A.id, B.id]
    assert [s["signature"] for s in document["signers"]] == [
        "catalogue.sig.d/1.sig",
        "catalogue.sig.d/2.sig",
    ]
    assert document["signers"][1]["hardware"] is True
    for n, key in enumerate([A, B], 1):
        assert (tmp_path / f"catalogue.sig.d/{n}.sig").read_bytes() == FakeBackend.signature(key, data)
    plan_a.parse_catalogue(data)


def test_an_unplugged_key_is_dropped_and_the_others_sign(
    tmp_path: Path, fake_backend: FakeBackend
) -> None:
    """A token pulled out mid-refresh: the catalogue lists only the keys that
    signed, the signature of the one that did is over the bytes as published,
    and the skip is reported with its reason."""
    fake_backend.fail[B.id] = "no authenticator found"
    result = go(tmp_path, idx(), [A, B])
    assert result.signed_by == (A.id,)
    assert result.skipped == ((B.id, "no authenticator found"),)
    data = (tmp_path / index.FILE).read_bytes()
    assert [s["id"] for s in json.loads(data)["signers"]] == [A.id]
    assert sorted(p.name for p in (tmp_path / signing.SIG_DIR).iterdir()) == ["1.sig"]
    assert (tmp_path / "catalogue.sig.d/1.sig").read_bytes() == FakeBackend.signature(A, data)


def test_a_key_that_failed_last_time_is_tried_again_on_unchanged_content(
    tmp_path: Path, fake_backend: FakeBackend
) -> None:
    fake_backend.fail[B.id] = "no authenticator found"
    first = go(tmp_path, idx(), [A, B])
    fake_backend.fail.clear()
    second = go(tmp_path, idx(), [A, B], generated=LATER)
    assert first.signed_by == (A.id,) and second.published
    assert second.signed_by == (A.id, B.id) and second.serial == first.serial + 1


def test_when_no_key_can_sign_the_served_pair_is_untouched(
    tmp_path: Path, fake_backend: FakeBackend
) -> None:
    go(tmp_path, idx(), [A, B])
    before = served(tmp_path)
    fake_backend.fail.update({A.id: "agent has no key", B.id: "no authenticator found"})
    with pytest.raises(PublishFailed, match="no key could sign.*agent has no key"):
        go(tmp_path, changed(), [A, B], generated=LATER)
    assert served(tmp_path) == before
    assert not (tmp_path / signing.STAGING).exists()


def test_a_signature_that_does_not_verify_is_not_published(
    tmp_path: Path, fake_backend: FakeBackend
) -> None:
    go(tmp_path, idx(), [A])
    before = served(tmp_path)
    fake_backend.broken.add(A.id)
    with pytest.raises(PublishFailed, match="no key could sign"):
        go(tmp_path, changed(), [A], generated=LATER)
    assert served(tmp_path) == before


def test_disk_full_while_staging_leaves_the_served_pair_untouched(
    tmp_path: Path, fake_backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    go(tmp_path, idx(), [A, B])
    before = served(tmp_path)
    real = signing._write_staged
    writes: list[Path] = []

    def full(path: Path, data: bytes) -> None:
        writes.append(path)
        if len(writes) == 2:  # the first signature is down; the second write finds no space
            raise OSError(errno.ENOSPC, "No space left on device")
        real(path, data)

    monkeypatch.setattr(signing, "_write_staged", full)
    with pytest.raises(PublishFailed, match="No space left on device.*still being served"):
        go(tmp_path, changed(), [A, B], generated=LATER)
    assert len(writes) == 2
    assert served(tmp_path) == before
    assert not (tmp_path / signing.STAGING).exists()


def test_a_retired_key_is_gone_from_signers_and_the_signature_directory(
    tmp_path: Path, fake_backend: FakeBackend
) -> None:
    go(tmp_path, idx(), [A, B])
    assert (tmp_path / "catalogue.sig.d/2.sig").exists()
    retired = dataclasses.replace(B, retired=GEN)
    result = go(tmp_path, idx(), [A, retired], generated=LATER)
    assert result.published and result.signed_by == (A.id,)
    document = json.loads((tmp_path / index.FILE).read_text())
    assert [s["id"] for s in document["signers"]] == [A.id]
    assert sorted(p.name for p in (tmp_path / signing.SIG_DIR).iterdir()) == ["1.sig"]


def test_no_active_key_refuses_and_changes_nothing(tmp_path: Path, fake_backend: FakeBackend) -> None:
    with pytest.raises(PublishFailed, match="no signing key"):
        go(tmp_path, idx(), [dataclasses.replace(A, retired=GEN)])
    assert served(tmp_path) == {}


def test_a_second_publish_is_refused_while_one_holds_the_lock(
    tmp_path: Path, fake_backend: FakeBackend
) -> None:
    go(tmp_path, idx(), [A])
    before = served(tmp_path)
    with (
        RunLock(tmp_path, signing.PUBLISH_LOCK),
        pytest.raises(PublishFailed, match="another publish is in progress"),
    ):
        go(tmp_path, changed(), [A], generated=LATER)
    assert served(tmp_path) == before


def test_unchanged_content_is_not_signed_again_until_the_catalogue_is_a_week_old(
    tmp_path: Path, fake_backend: FakeBackend
) -> None:
    go(tmp_path, idx(), [A])
    before, signed = served(tmp_path), len(fake_backend.calls)
    again = idx()
    again.artifacts[0].verified = "2026-10-08T03:00:00Z"  # re-hashed since: not a change
    again.last_run = {"started": "s", "finished": "f"}
    quiet = go(tmp_path, again, [A], generated=LATER)
    assert not quiet.published and quiet.serial == 1
    assert served(tmp_path) == before and len(fake_backend.calls) == signed
    stale = go(tmp_path, again, [A], generated=EIGHT_DAYS)
    assert stale.published and stale.serial == 2
    assert json.loads((tmp_path / index.FILE).read_text())["generated"] == EIGHT_DAYS


def test_a_change_publishes_with_a_higher_serial(tmp_path: Path, fake_backend: FakeBackend) -> None:
    go(tmp_path, idx(), [A])
    other = idx()
    other.artifacts[0].sha256 = "d" * 64
    result = go(tmp_path, other, [A], generated=LATER)
    assert result.published and result.serial == 2
    assert index.load(tmp_path).serial == 2


def test_the_engines_reader_refusing_the_document_stops_the_publication(
    tmp_path: Path, fake_backend: FakeBackend
) -> None:
    def refuse(data: bytes) -> None:
        raise ValueError("signers[0].bits: not a number")

    with pytest.raises(PublishFailed, match=r"would not pass the engine's reader.*signers\[0\]"):
        go(tmp_path, idx(), [A], validate=refuse)
    assert served(tmp_path) == {}


def test_a_timestamp_that_is_not_utc_is_refused(tmp_path: Path, fake_backend: FakeBackend) -> None:
    with pytest.raises(PublishFailed, match="generated"):
        go(tmp_path, idx(), [A], generated="yesterday")


def test_the_refresh_interval_is_a_parameter(tmp_path: Path, fake_backend: FakeBackend) -> None:
    go(tmp_path, idx(), [A])
    soon = go(tmp_path, idx(), [A], generated=LATER, refresh=timedelta(hours=1))
    assert soon.published
```

- [ ] **Step 3: Write the failing real-signing tests**

Create `tests/test_signing.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The real thing: ``ssh-keygen -Y sign`` and ``-Y verify`` over real keys
generated in a temp directory, and a real ``ssh-agent``. No token anywhere."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from bunker import config, index, publish, signing
from bunker.index import Index
from bunker.signing import SignatureInvalid, SignerUnavailable, SshKeygenBackend
from tests import plan_a, realkeys
from tests.helpers import FAKE_ID, FAKE_PUBLIC, config_text
from tests.signing_fakes import fake_key
from tests.test_index import an_entry

pytestmark = pytest.mark.real_signing

DATA = b'{"kind": "bunker-index", "serial": 1}\n'
PRINCIPAL = "bunker:shack-1"


@pytest.mark.parametrize("kind", ["ed25519", "ecdsa", "rsa2048"])
def test_the_fingerprint_is_the_one_ssh_keygen_prints(tmp_path: Path, kind: str) -> None:
    spec = realkeys.make_file_key(tmp_path, kind, register=False)
    printed = subprocess.run(
        ["ssh-keygen", "-l", "-f", spec.path + ".pub"], check=True, capture_output=True, text=True
    ).stdout.split()[1]
    assert signing.fingerprint(spec.public_key) == printed == spec.id
    assert signing.fingerprint(FAKE_PUBLIC) == FAKE_ID


@pytest.mark.parametrize("line", ["", "ssh-ed25519", "ssh-ed25519 not*base64", "a b\nc d", "x y\x00"])
def test_a_public_key_line_that_is_not_one_line_of_a_key_is_refused(line: str) -> None:
    with pytest.raises(signing.SigningError):
        signing.clean_public_key(line)


@pytest.mark.parametrize("kind", ["ed25519", "ecdsa", "rsa3072"])
def test_a_file_key_signs_and_its_signature_verifies(tmp_path: Path, kind: str) -> None:
    spec = realkeys.make_file_key(tmp_path, kind, register=False)
    backend = SshKeygenBackend()
    signature = backend.sign(spec, DATA, timeout=30)
    assert signature.startswith(b"-----BEGIN SSH SIGNATURE-----")
    backend.verify(spec, DATA, signature, principal=PRINCIPAL)
    with pytest.raises(SignatureInvalid):
        backend.verify(spec, DATA + b" ", signature, principal=PRINCIPAL)


def test_a_signature_by_another_key_does_not_verify_for_this_one(tmp_path: Path) -> None:
    one = realkeys.make_file_key(tmp_path, "ed25519", register=False)
    two = realkeys.make_file_key(tmp_path, "ed25519", register=False)
    backend = SshKeygenBackend()
    with pytest.raises(SignatureInvalid):
        backend.verify(one, DATA, backend.sign(two, DATA, timeout=30), principal=PRINCIPAL)


def test_the_signature_is_checked_in_the_contracts_namespace(tmp_path: Path) -> None:
    """What a laptop runs, by hand, as the contract spells it."""
    spec = realkeys.make_file_key(tmp_path, "ed25519", register=False)
    signature = SshKeygenBackend().sign(spec, DATA, timeout=30)
    allowed, sig = tmp_path / "allowed", tmp_path / "sig"
    allowed.write_text(signing.allowed_signers_line(PRINCIPAL, spec.public_key) + "\n")
    sig.write_bytes(signature)
    base = ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", PRINCIPAL, "-s", str(sig)]
    good = subprocess.run([*base, "-n", signing.NAMESPACE], input=DATA, capture_output=True)
    assert good.returncode == 0, good.stderr
    wrong = subprocess.run([*base, "-n", "something-else"], input=DATA, capture_output=True)
    assert wrong.returncode != 0


def test_a_missing_ssh_keygen_is_named() -> None:
    backend = SshKeygenBackend(("ssh-keygen-that-is-not-installed",))
    with pytest.raises(signing.SigningError, match="not found.*openssh-client"):
        backend.sign(fake_key(), DATA, timeout=5)


def test_a_signer_that_times_out_is_unavailable_not_a_hang() -> None:
    started = time.monotonic()
    with pytest.raises(SignerUnavailable, match="did not finish within"):
        signing.run_command(["sleep", "5"], b"", 0.2, None)
    assert time.monotonic() - started < 3


def test_a_failing_ssh_keygen_is_unavailable_with_its_message(tmp_path: Path) -> None:
    spec = dataclasses.replace(realkeys.make_file_key(tmp_path, register=False), path=str(tmp_path / "gone"))
    with pytest.raises(SignerUnavailable, match=r"file key SHA256:.*exited"):
        SshKeygenBackend().sign(spec, DATA, timeout=10)


@pytest.fixture
def agent(tmp_path: Path) -> Iterator[tuple[Path, subprocess.Popen[bytes]]]:
    sock = tmp_path / "a.sock"  # a unix socket path is limited to about 100 bytes
    proc = subprocess.Popen(
        ["ssh-agent", "-D", "-a", str(sock)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        for _ in range(100):
            if sock.exists():
                break
            time.sleep(0.05)
        else:
            raise AssertionError("ssh-agent never created its socket")
        yield sock, proc
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_the_agent_backend_signs_with_the_agents_key_not_a_file(
    tmp_path: Path, agent: tuple[Path, subprocess.Popen[bytes]]
) -> None:
    sock, proc = agent
    key = realkeys.make_file_key(tmp_path, "rsa3072", register=False)
    subprocess.run(
        ["ssh-add", key.path],
        env={**os.environ, "SSH_AUTH_SOCK": str(sock)},
        check=True,
        capture_output=True,
    )
    alone = tmp_path / "pub-only"  # no private key beside it: ssh-keygen must ask the agent
    alone.mkdir()
    (alone / "agent.pub").write_text(key.public_key + "\n")
    spec = dataclasses.replace(key, backend="agent", path=str(alone / "agent.pub"))
    backend = SshKeygenBackend(agent_socket=str(sock))
    signature = backend.sign(spec, DATA, timeout=30)
    backend.verify(spec, DATA, signature, principal=PRINCIPAL)
    proc.terminate()  # falsify: with the agent gone the same call must fail
    proc.wait(timeout=5)
    with pytest.raises(SignerUnavailable):
        backend.sign(spec, DATA, timeout=10)


def test_the_registry_round_trips_and_a_damaged_one_is_named(tmp_path: Path) -> None:
    spec = realkeys.make_file_key(tmp_path, "ed25519")
    assert signing.load_registry(tmp_path) == [spec]
    path = signing.keys_dir(tmp_path) / signing.REGISTRY
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(signing.keys_dir(tmp_path).stat().st_mode & 0o777) == "0o700"
    path.write_text("{not json")
    with pytest.raises(signing.SigningError, match="keys.json"):
        signing.load_registry(tmp_path)
    path.write_text(json.dumps({"keys": [{"id": "x"}]}))
    with pytest.raises(signing.SigningError, match="key 0 is malformed"):
        signing.load_registry(tmp_path)


def test_an_end_to_end_publication_with_two_real_keys_verifies_like_a_laptop(tmp_path: Path) -> None:
    root = tmp_path / "vol"
    first = realkeys.make_file_key(root, "ed25519")
    second = realkeys.make_file_key(root, "ecdsa")
    path = tmp_path / "bunker.toml"
    path.write_text(config_text(str(root), extra='[bunker]\nname = "shack-1"\n'))
    cfg = config.load(path)
    idx = Index(engine_version="0.22.0", artifacts=[an_entry()])
    result = publish.publish(cfg, idx, generated="2026-10-07T12:00:00Z")
    assert result.signed_by == (first.id, second.id), "registry order"
    data = (root / index.FILE).read_bytes()
    plan_a.parse_catalogue(data)
    by_id = {first.id: first, second.id: second}
    for n, signer in enumerate(json.loads(data)["signers"], 1):
        allowed = tmp_path / f"allowed{n}"
        allowed.write_text(signing.allowed_signers_line(PRINCIPAL, by_id[signer["id"]].public_key) + "\n")
        done = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", PRINCIPAL,
             "-n", signing.NAMESPACE, "-s", str(root / f"catalogue.sig.d/{n}.sig")],
            input=data, capture_output=True,
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
    tampered = tmp_path / "tampered"
    tampered.write_bytes(data.replace(b'"serial": 1', b'"serial": 9'))
    allowed = tmp_path / "allowed1"
    done = subprocess.run(
        ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", PRINCIPAL,
         "-n", signing.NAMESPACE, "-s", str(root / "catalogue.sig.d/1.sig")],
        input=tampered.read_bytes(), capture_output=True,
    )  # fmt: skip
    assert done.returncode != 0, "a changed catalogue must fail its signature"
```

Note `tests/test_signing.py` uses `config_text(str(root), extra='[bunker]\nname = "shack-1"\n')`: `config_text` appends *extra* after `[selection]`, so the `[bunker]` table is legal there.

- [ ] **Step 4: Run them to see them fail**

Run: `.venv/bin/python -m pytest tests/test_publish.py tests/test_signing.py -q -x`
Expected: FAIL at collection — `ImportError: cannot import name 'signing' from 'bunker'`.

- [ ] **Step 5: Write `src/bunker/signing.py`**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Signing the catalogue.

``catalogue.json`` is signed as the exact bytes served, with
``ssh-keygen -Y sign -n hammunition-bunker-catalogue``, once per configured
key. The three backends differ only in what ``-f`` names and what the process
can reach: ``file`` (a private key in ``<root>/.keys``), ``security-key`` (the
key handle of a FIDO2 ``-sk`` key; the token must be attached and, unless the
key was made ``no-touch-required``, touched) and ``agent`` (a public key file
with no private key beside it: ``ssh-keygen`` then asks ``ssh-agent``, which is
how PIV and other PKCS#11 tokens sign).

:func:`publish_signed` is the only place the served pair changes. It stages
every file first, so a full disk or a pulled token before the renames leaves
the previous catalogue and its signatures exactly as they were. Every
signature is verified locally before anything is published, and the engine's
own reader must accept the document: the Bunker never publishes what a laptop
would refuse.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from bunker import index
from bunker.index import Index
from bunker.volume import Locked, RunLock, write_atomic

__all__ = [
    "BACKENDS",
    "BACKEND_NAMES",
    "KEYS_DIR",
    "NAMESPACE",
    "PUBLISH_LOCK",
    "REFRESH",
    "REGISTRY",
    "SIGN_TIMEOUT",
    "SIG_DIR",
    "STAGING",
    "Backend",
    "KeySpec",
    "PublishFailed",
    "PublishResult",
    "Runner",
    "SignatureInvalid",
    "SignerUnavailable",
    "SigningError",
    "SshKeygenBackend",
    "allowed_signers_line",
    "clean_public_key",
    "fingerprint",
    "keys_dir",
    "load_registry",
    "load_signed",
    "publish_signed",
    "record_signed",
    "run_command",
    "save_registry",
    "stable_digest",
]

NAMESPACE = "hammunition-bunker-catalogue"
SIG_DIR = "catalogue.sig.d"
KEYS_DIR = ".keys"
REGISTRY = "keys.json"
SIGNED_FILE = "signed.json"
STAGING = ".publish.tmp"
PUBLISH_LOCK = ".publish.lock"
#: How long one ``ssh-keygen -Y sign`` may take, a touch included.
SIGN_TIMEOUT = 60.0
#: A catalogue older than this is signed again even if nothing changed, so a
#: quiet Bunker never trips the engine's 30-day staleness warning.
REFRESH = timedelta(days=7)
BACKEND_NAMES = ("file", "security-key", "agent")
_SIGNATURE_HEAD = b"-----BEGIN SSH SIGNATURE-----"
_PUBLIC_KEY = re.compile(r"[a-z0-9@.-]+ [A-Za-z0-9+/]+={0,3}( [^\x00-\x1f\x7f]*)?")
#: Fields of the document that change without the catalogue's meaning changing.
_VOLATILE = ("serial", "generated", "last_run", "signers")


class SigningError(Exception):
    """A key cannot be used, or a signature cannot be made or checked."""


class SignerUnavailable(SigningError):
    """The key cannot sign right now: a token not attached or not touched in
    time, an agent without the key, a missing key file."""


class SignatureInvalid(SigningError):
    """A signature does not verify for the key and bytes it claims."""


class PublishFailed(SigningError):
    """Nothing was published; the previous catalogue is still being served."""


@dataclass(frozen=True)
class KeySpec:
    """One signing key as ``<root>/.keys/keys.json`` records it."""

    id: str
    """SHA256 fingerprint of the public key."""
    backend: str
    public_key: str
    algorithm: str
    bits: int
    hardware: bool
    path: str
    """``file``: the private key; ``security-key``: the key handle file;
    ``agent``: a public key file with no private key beside it."""
    no_touch: bool = False
    retired: str | None = None
    """When it was retired; a retired key never signs and is never listed."""
    added: str = ""


@dataclass(frozen=True)
class PublishResult:
    published: bool
    """False when nothing needed publishing."""
    serial: int
    signed_by: tuple[str, ...] = ()
    """Fingerprints of the keys whose signatures went out with the catalogue."""
    skipped: tuple[tuple[str, str], ...] = ()
    """``(fingerprint, reason)`` for each key that could not sign this time."""


Runner = Callable[
    [Sequence[str], bytes, float, Mapping[str, str] | None], "subprocess.CompletedProcess[bytes]"
]


def run_command(
    argv: Sequence[str], stdin: bytes, timeout: float, env: Mapping[str, str] | None
) -> subprocess.CompletedProcess[bytes]:
    """Run *argv* (never a shell), capturing its output; a missing program is a
    :class:`SigningError`, a program that outlasts *timeout* is killed and is
    :class:`SignerUnavailable`."""
    try:
        return subprocess.run(  # noqa: S603 - an argv list built here, never a shell
            list(argv),
            input=stdin,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=None if env is None else {**os.environ, **env},
        )
    except FileNotFoundError:
        raise SigningError(
            f"{argv[0]!r} was not found; install openssh-client (the image has it)"
        ) from None
    except subprocess.TimeoutExpired:
        raise SignerUnavailable(
            f"{' '.join(argv[:3])} did not finish within {timeout:g} s"
            f" (a security key waits for a touch)"
        ) from None


def _tail(stderr: bytes) -> str:
    return stderr.decode("utf-8", "replace").strip().replace("\n", " ")[-300:]


def clean_public_key(line: str) -> str:
    """*line* as one public-key line (``type base64 [comment]``), or a SigningError."""
    text = line.strip()
    if not _PUBLIC_KEY.fullmatch(text):
        raise SigningError("that is not one line of an OpenSSH public key (type, base64, comment)")
    return text


def fingerprint(public_key: str) -> str:
    """``SHA256:...`` exactly as ``ssh-keygen -l`` prints it."""
    parts = clean_public_key(public_key).split()
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except ValueError:
        raise SigningError("the public key's second field is not base64") from None
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


def allowed_signers_line(principal: str, public_key: str) -> str:
    """One OpenSSH allowed-signers line limiting the key to this namespace.
    (OpenSSH's file takes ``namespaces``, ``cert-authority`` and the validity
    options only: a ``no-touch-required`` option here is rejected as a bad
    option by OpenSSH 10.3, so none is ever written.)"""
    key_type, blob = clean_public_key(public_key).split()[:2]
    return f'{principal} namespaces="{NAMESPACE}" {key_type} {blob}'


class Backend(Protocol):
    def sign(self, spec: KeySpec, data: bytes, *, timeout: float) -> bytes: ...

    def verify(
        self, spec: KeySpec, data: bytes, signature: bytes, *, principal: str
    ) -> None: ...


class SshKeygenBackend:
    """``ssh-keygen -Y sign`` / ``-Y verify``, for all three key backends."""

    def __init__(
        self,
        command: Sequence[str] = ("ssh-keygen",),
        *,
        agent_socket: str | None = None,
        run: Runner = run_command,
    ) -> None:
        self.command = tuple(command)
        self.agent_socket = agent_socket
        self.run = run

    def _env(self, spec: KeySpec) -> dict[str, str] | None:
        if spec.backend == "agent" and self.agent_socket:
            return {"SSH_AUTH_SOCK": self.agent_socket}
        return None

    def sign(self, spec: KeySpec, data: bytes, *, timeout: float) -> bytes:
        argv = [*self.command, "-Y", "sign", "-n", NAMESPACE, "-f", spec.path]
        done = self.run(argv, data, timeout, self._env(spec))
        if done.returncode != 0 or not done.stdout.startswith(_SIGNATURE_HEAD):
            raise SignerUnavailable(
                f"{spec.backend} key {spec.id}: ssh-keygen exited {done.returncode}: "
                f"{_tail(done.stderr)}"
            )
        return done.stdout

    def verify(self, spec: KeySpec, data: bytes, signature: bytes, *, principal: str) -> None:
        with tempfile.TemporaryDirectory(prefix="bunker-verify-") as tmp:
            allowed, sig = Path(tmp) / "allowed", Path(tmp) / "sig"
            allowed.write_text(allowed_signers_line(principal, spec.public_key) + "\n")
            sig.write_bytes(signature)
            argv = [
                *self.command, "-Y", "verify", "-f", str(allowed), "-I", principal,
                "-n", NAMESPACE, "-s", str(sig),
            ]  # fmt: skip
            done = self.run(argv, data, 30.0, None)
        if done.returncode != 0:
            raise SignatureInvalid(
                f"the signature of {spec.id} does not verify: {_tail(done.stderr)}"
            )


#: The real backends. Tests replace entries with a fake (``tests/signing_fakes.py``).
BACKENDS: dict[str, Backend] = {name: SshKeygenBackend() for name in BACKEND_NAMES}


# --- the key registry -------------------------------------------------------

_SPEC_TYPES: dict[str, tuple[type, ...]] = {
    "id": (str,),
    "backend": (str,),
    "public_key": (str,),
    "algorithm": (str,),
    "bits": (int,),
    "hardware": (bool,),
    "path": (str,),
    "no_touch": (bool,),
    "retired": (str, type(None)),
    "added": (str,),
}


def keys_dir(root: Path) -> Path:
    return root / KEYS_DIR


def _typed(value: Any, types: tuple[type, ...]) -> bool:
    return isinstance(value, types) and not (isinstance(value, bool) and bool not in types)


def load_registry(root: Path) -> list[KeySpec]:
    """The keys this volume signs with, in the order they were added."""
    path = keys_dir(root) / REGISTRY
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise SigningError(f"{path} cannot be read: {exc}") from None
    try:
        raw = json.loads(text)
    except ValueError:
        raise SigningError(
            f"{path} is not JSON; move it aside (the key files beside it stay) and add the "
            f"keys again with `bunker keys add`"
        ) from None
    items = raw.get("keys") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise SigningError(f"{path} has no list of keys")
    keys: list[KeySpec] = []
    for n, item in enumerate(items):
        if (
            not isinstance(item, dict)
            or any(k not in item or not _typed(item[k], t) for k, t in _SPEC_TYPES.items())
            or item["backend"] not in BACKEND_NAMES
        ):
            raise SigningError(f"{path}: key {n} is malformed")
        keys.append(KeySpec(**{k: item[k] for k in _SPEC_TYPES}))
    return keys


def save_registry(root: Path, keys: Sequence[KeySpec]) -> None:
    folder = keys_dir(root)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    text = json.dumps({"version": 1, "keys": [asdict(k) for k in keys]}, indent=2) + "\n"
    target = folder / REGISTRY
    write_atomic(target, text.encode("utf-8"))
    os.chmod(target, 0o600)


def load_signed(root: Path) -> dict[str, str]:
    """Fingerprint -> when it last signed a published catalogue."""
    try:
        raw = json.loads((keys_dir(root) / SIGNED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


def record_signed(root: Path, ids: Sequence[str], when: str) -> None:
    folder = keys_dir(root)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    merged = {**load_signed(root), **dict.fromkeys(ids, when)}
    write_atomic(folder / SIGNED_FILE, (json.dumps(merged, indent=2) + "\n").encode("utf-8"))


# --- publication ------------------------------------------------------------


def stable_digest(doc: Mapping[str, Any]) -> str:
    """A digest of what a catalogue *means*: the document without its serial,
    time, last-run summary, signers and per-artifact re-hash times. Two
    catalogues with the same digest need not be signed twice."""
    kept = {k: v for k, v in doc.items() if k not in _VOLATILE}
    artifacts = doc.get("artifacts")
    if isinstance(artifacts, list):
        kept["artifacts"] = [
            {k: v for k, v in a.items() if k != "verified"} if isinstance(a, dict) else a
            for a in artifacts
        ]
    return hashlib.sha256(
        json.dumps(kept, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _write_staged(path: Path, data: bytes) -> None:
    """Write *data* to *path* and force it to disk. Tests make this fail."""
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _exclusive(root: Path) -> Iterator[None]:
    try:
        with RunLock(root, PUBLISH_LOCK):
            yield
    except Locked:
        raise PublishFailed(
            "another publish is in progress on this volume; nothing was changed"
        ) from None


def _published(root: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads((root / index.FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def publish_signed(
    root: Path,
    idx: Index,
    *,
    generated: str,
    keys: Sequence[KeySpec],
    backends: Mapping[str, Backend],
    refresh: timedelta = REFRESH,
    timeout: float = SIGN_TIMEOUT,
    validate: Callable[[bytes], None] | None = None,
) -> PublishResult:
    """Sign and publish *idx* if it changed, a key was added or retired, a key
    that missed last time is available again, or the published catalogue is
    older than *refresh*. Raises :class:`PublishFailed` with the previous
    catalogue still being served."""
    active = [k for k in keys if k.retired is None]
    if not active:
        raise PublishFailed(
            "no signing key is configured (`bunker keys add`); nothing was published"
        )
    now = index.parse_stamp(generated)
    if now is None:
        raise PublishFailed(f"generated {generated!r} is not a UTC time like 2026-10-07T12:00:00Z")
    root.mkdir(parents=True, exist_ok=True)
    with _exclusive(root):
        try:
            return _publish(root, idx, now, generated, active, backends, refresh, timeout, validate)
        except OSError as exc:
            raise PublishFailed(
                f"could not write the catalogue and its signatures ({exc.strerror or exc}); "
                f"the previous catalogue is still being served"
            ) from None


def _signer(key: KeySpec, n: int) -> index.Signer:
    return index.Signer(
        id=key.id,
        public_key=key.public_key,
        algorithm=key.algorithm,
        bits=key.bits,
        hardware=key.hardware,
        signature=f"{SIG_DIR}/{n}.sig",
    )


def _publish(
    root: Path,
    idx: Index,
    now: datetime,
    generated: str,
    active: Sequence[KeySpec],
    backends: Mapping[str, Backend],
    refresh: timedelta,
    timeout: float,
    validate: Callable[[bytes], None] | None,
) -> PublishResult:
    current = _published(root)
    published_serial = 0
    if current is not None:
        serial_value = current.get("serial")
        published_serial = serial_value if isinstance(serial_value, int) else 0
        stamp = index.parse_stamp(current.get("generated"))
        listed = current.get("signers")
        published_ids = sorted(
            str(s["id"])
            for s in (listed if isinstance(listed, list) else [])
            if isinstance(s, dict) and "id" in s
        )
        unchanged = stable_digest(current) == stable_digest(
            index.body(idx, serial=0, generated="", signers=[])
        )
        if (
            unchanged
            and stamp is not None
            and now - stamp < refresh
            and published_ids == sorted(k.id for k in active)
        ):
            idx.serial = published_serial
            return PublishResult(False, published_serial, tuple(published_ids))

    principal = f"bunker:{idx.name}"
    # Keys that sign unattended go first (the sort is stable, so registry order
    # otherwise holds): a token that needs a touch is tapped last, once the rest
    # are known to have worked.
    chosen = sorted(active, key=lambda k: k.backend == "security-key" and not k.no_touch)
    serial = index.next_serial(root, max(idx.serial, published_serial))
    skipped: dict[str, str] = {}
    while True:
        signers = [_signer(k, n) for n, k in enumerate(chosen, 1)]
        data = index.render(idx, serial=serial, generated=generated, signers=[asdict(s) for s in signers])
        signatures: dict[str, bytes] = {}
        failed: dict[str, str] = {}
        for key in chosen:
            backend = backends.get(key.backend)
            if backend is None:
                failed[key.id] = f"no {key.backend} backend is available"
                continue
            try:
                signature = backend.sign(key, data, timeout=timeout)
                backend.verify(key, data, signature, principal=principal)
            except SigningError as exc:
                failed[key.id] = str(exc)
                continue
            signatures[key.id] = signature
        if not failed:
            break
        # The signers are part of the signed bytes, so a key that dropped out
        # means rendering again and signing again with the keys that remain.
        skipped.update(failed)
        chosen = [k for k in chosen if k.id not in failed]
        if not chosen:
            raise PublishFailed(
                "no key could sign: "
                + "; ".join(f"{kid}: {why}" for kid, why in skipped.items())
                + ". The previous catalogue is still being served."
            )

    if validate is not None:
        try:
            validate(data)
        except Exception as exc:
            raise PublishFailed(
                f"the document would not pass the engine's reader, so it was not published: {exc}"
            ) from None

    staging = root / STAGING
    shutil.rmtree(staging, ignore_errors=True)
    served = root / SIG_DIR
    try:
        (staging / SIG_DIR).mkdir(parents=True)
        for n, key in enumerate(chosen, 1):
            _write_staged(staging / SIG_DIR / f"{n}.sig", signatures[key.id])
        _write_staged(staging / index.FILE, data)
        served.mkdir(exist_ok=True)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    # Signatures first, the catalogue last, then the signatures of keys no longer
    # listed: a laptop never sees a catalogue whose signature file is missing.
    names = {f"{n}.sig" for n in range(1, len(chosen) + 1)}
    for name in sorted(names):
        os.replace(staging / SIG_DIR / name, served / name)
    os.replace(staging / index.FILE, root / index.FILE)
    for old in served.glob("*.sig"):
        if old.name not in names:
            old.unlink(missing_ok=True)
    shutil.rmtree(staging, ignore_errors=True)

    idx.serial = serial
    idx.signers = [asdict(s) for s in signers]
    try:
        index.save(root, idx, generated=generated)
        record_signed(root, [k.id for k in chosen], generated)
    except OSError as exc:
        raise PublishFailed(
            f"the catalogue was published (serial {serial}) but its working state could not "
            f"be saved: {exc.strerror or exc}"
        ) from None
    return PublishResult(
        True, serial, tuple(k.id for k in chosen), tuple(skipped.items())
    )

```

In `src/bunker/index.py` add `from datetime import UTC, datetime` to the imports, `"parse_stamp"` to `__all__` (sorted), and:

```python
def parse_stamp(text: str | None) -> datetime | None:
    """``2026-10-07T12:00:00Z`` as an aware UTC time; None for anything else."""
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
```

In `src/bunker/volume.py` change `RunLock.__init__` (lines 551-553) to:

```python
    def __init__(self, root: Path, name: str = ".lock") -> None:
        self.path = root / name
        self._fd: int | None = None
```

- [ ] **Step 6: Wire `bunker.publish`, the run and `verify` to signing**

Replace `src/bunker/publish.py` with:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publishing: the one place ``catalogue.json`` and its signatures are written.

A run, ``bunker verify`` and the key and enrolment commands all end here, so
the served catalogue changes at most once per command and never between two
artifacts of a run (a touch-required token is tapped once per change).
"""

from __future__ import annotations

from bunker import enginelib, index, signing
from bunker.config import Config
from bunker.index import Index
from bunker.signing import PublishResult

__all__ = ["PublishResult", "ensure_published", "publish"]


def publish(cfg: Config, idx: Index, *, generated: str) -> PublishResult:
    """Sign and publish *idx* when :func:`bunker.signing.publish_signed` says
    it needs publishing. Raises :class:`bunker.signing.PublishFailed`."""
    root = cfg.storage.root
    idx.name, idx.mode = cfg.bunker.name, cfg.bunker.mode
    return signing.publish_signed(
        root,
        idx,
        generated=generated,
        keys=signing.load_registry(root),
        backends=signing.BACKENDS,
        validate=enginelib.validate_catalogue,
    )


def ensure_published(cfg: Config, *, generated: str) -> None:
    """A fresh volume serves a catalogue (the container's healthcheck asks for
    it) before its first run. A volume that has any state is left alone."""
    root = cfg.storage.root
    if any((root / n).exists() for n in (index.STATE, index.FILE, index.LEGACY_FILE)):
        return
    publish(cfg, index.load(root), generated=generated)
```

`src/bunker/run.py`: add `from bunker import publish, signing, statuspage` (line 36), replace the `_parse` function (lines 93-99) with `from bunker.index import parse_stamp as _parse` in the import block, add to `RunReport` (after `warnings`) `catalogue: dict[str, Any] | None = None` with docstring `"""Serial, whether it was published, and the keys that signed it."""`, add `"catalogue": self.catalogue,` to `as_dict` (before `"exit_code"`), and replace `_finish` with:

```python
def _finish(cfg: Config, idx: Index, report: RunReport, clock: Clock) -> RunReport:
    root = cfg.storage.root
    report.finished = iso(clock())
    counts = report.counts()
    last_run: dict[str, Any] = {
        "started": report.started,
        "finished": report.finished,
        "fetched": counts["fetched"],
        "verified": counts["verified"],
        "failed": counts["failed"],
        "corrupted": counts["corrupted"],
        "stale": counts["stale"],
        "error": report.error,
        "plain_http": report.plain_http,
    }
    idx.last_run = last_run
    save_index(root, idx, generated=report.finished)
    try:
        result = publish.publish(cfg, idx, generated=report.finished)
    except signing.PublishFailed as exc:
        message = f"catalogue not published: {exc}"
        report.error = f"{report.error}; {message}" if report.error else message
        last_run["error"] = report.error
        save_index(root, idx, generated=report.finished)
    else:
        report.catalogue = {
            "serial": result.serial,
            "published": result.published,
            "signed_by": list(result.signed_by),
        }
        report.warnings += [f"signing key {kid} did not sign: {why}" for kid, why in result.skipped]
    statuspage.write(root, idx)
    with (root / ".runs.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(report.as_dict(), ensure_ascii=False) + "\n")
    return report
```

`src/bunker/verify.py`: import `signing` (`from bunker import publish, signing, statuspage`); in `VerifyReport` add `error: str | None = None`, make `exit_code` return `0 if all(r.ok for r in self.results) and self.error is None else 1`, add `"error": self.error,` to `as_dict` (before `"exit_code"`) and, in `summary_lines`, `if self.error: lines.append(f"  error: {self.error}")` after the header line. Replace the publish call from Task 1 with:

```python
        save_index(root, idx, generated=report.finished)
        try:
            publish.publish(cfg, idx, generated=report.finished)
        except signing.PublishFailed as exc:
            report.error = f"catalogue not published: {exc}"
        statuspage.write(root, idx)
```

`src/bunker/cli.py`: `from bunker import ... signing, ...` and in `_dispatch` add

```python
    except signing.PublishFailed as exc:
        _err(str(exc))
        return EXIT_REFUSED
```

`tests/test_cli.py::test_schedule_serves_runs_and_stops_on_sigterm`: the scheduler is a separate process the fake backend cannot reach, so give it a real key: add `@pytest.mark.real_signing` above the test and, after `scene.cfg()`, `realkeys.make_file_key(scene.root, "ed25519")` (import `from tests import realkeys`). Update the goldens (`BUNKER_UPDATE_GOLDENS=1 .venv/bin/python -m pytest tests/test_cli.py -q`) and read the diff: only `run.json` gains `"catalogue"` and `verify.json` gains `"error": null`.

`tests/test_run.py`: add (and use `from bunker import signing`, `from bunker import run as run_module` as needed):

```python
def test_the_served_pair_does_not_change_until_the_run_publishes(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A laptop reading while a run is mid-way sees one signed catalogue, not a
    half-written one: the signature it fetches still matches the catalogue."""
    scene.run()
    catalogue = scene.root / "catalogue.json"
    signature = scene.root / "catalogue.sig.d" / "1.sig"
    before = (catalogue.read_bytes(), signature.read_bytes())
    scene.publish(region=b"a newer region extract " * 3000)
    scene.clock.advance(days=1)
    seen: list[tuple[bytes, bytes]] = []
    real = run_module._download

    def spy(root: Path, artifact: Any, transport: Any) -> Any:
        seen.append((catalogue.read_bytes(), signature.read_bytes()))
        return real(root, artifact, transport)

    monkeypatch.setattr(run_module, "_download", spy)
    scene.run(units=("osm-regions",))
    assert seen and all(pair == before for pair in seen)
    assert (catalogue.read_bytes(), signature.read_bytes()) != before


def test_a_run_whose_catalogue_could_not_be_signed_says_so_and_exits_1(
    scene: Scene, fake_backend: FakeBackend
) -> None:
    fake_backend.fail.update({FAKE_ID: "agent has no key"})
    report = scene.run()
    assert report.exit_code == 1
    assert report.error is not None and "catalogue not published" in report.error
    assert not (scene.root / "catalogue.json").exists()
    assert scene.entry("osm-regions", REGION).status == "current", "the state is kept"
```

(imports: `from pathlib import Path`, `from typing import Any`, `import pytest`, `from bunker import run as run_module`, `from tests.helpers import FAKE_ID`, `from tests.signing_fakes import FakeBackend`; the file's existing imports cover the rest.)

- [ ] **Step 7: Run everything**

Run: `.venv/bin/python -m pytest -q -W error::DeprecationWarning; echo "exit=$?"`
Expected: `exit=0` (Plan A parse tests skip without the Plan A checkout). If `test_a_run_whose_catalogue_could_not_be_signed...` fails with `catalogue.json` existing, the first-run `ensure` is publishing: it is not called by `run`, so check `publish.publish` is the only writer.

- [ ] **Step 8: Docs, falsification, changelog, commit**

`docs/reference.md`: in *The volume* tree add `catalogue.sig.d/<n>.sig` (one signature per key that signed, numbered from 1 in `signers` order), `.keys/` (0700: `keys.json` the registry, the key files, `signed.json` when each key last signed), `.serial`, `.publish.lock`; add a `## Signing` section: the namespace, the principal `bunker:<name>`, "the signed bytes are exactly `catalogue.json` as served", how to check by hand:

```
ssh-keygen -Y verify -f allowed_signers -I bunker:<name> -n hammunition-bunker-catalogue \
    -s catalogue.sig.d/1.sig < catalogue.json
```

the three backends, "a key that cannot sign (a token not attached, not touched within 60 s) is left out of `signers` for that publication and named in the run's warnings; if none can sign, nothing is published and the previous catalogue keeps serving", "a run signs once, at its end; a catalogue is signed again only when its content changed, a key was added or retired, or it is seven days old", and "an `allowed_signers` line takes `namespaces`, never `no-touch-required` (OpenSSH 10.3 rejects it); user presence is a property of the key's creation, not of the verifying line". Add `catalogue` to the `run` document's field list and `error` to the `verify` document's. `CHANGELOG.md` first `### Added`: "- Signing: `bunker.signing` signs `catalogue.json` with `ssh-keygen -Y sign` (namespace `hammunition-bunker-catalogue`) once per key into `catalogue.sig.d/<n>.sig`, for file, security-key and agent keys; staged, verified locally and renamed into place, so a pulled token or a full disk leaves the previous pair serving."

Falsify twice. (1) In `publish_signed` swap the two `os.replace` blocks' arguments so the catalogue is replaced before the signatures are, run `.venv/bin/python -m pytest tests/test_publish.py -q` and see `test_one_signature_per_key_and_the_catalogue_names_them` still pass (order is not asserted by content) — then instead delete the `shutil.rmtree(staging, ignore_errors=True)` in the `except OSError` branch and see `test_disk_full_while_staging_leaves_the_served_pair_untouched` FAIL on `assert not (tmp_path / signing.STAGING).exists()`; restore. (2) Change `names = {f"{n}.sig" ...}` cleanup to skip the stale-removal loop and see `test_a_retired_key_is_gone_from_signers_and_the_signature_directory` FAIL (`['1.sig', '2.sig'] != ['1.sig']`); restore.

Run: `make check; echo "exit=$?"` — Expected: `exit=0`.

```bash
git add src/bunker/signing.py src/bunker/publish.py src/bunker/index.py src/bunker/volume.py src/bunker/run.py src/bunker/verify.py src/bunker/cli.py tests/signing_fakes.py tests/realkeys.py tests/test_signing.py tests/test_publish.py tests/test_run.py tests/test_cli.py tests/conftest.py tests/golden pyproject.toml docs/reference.md CHANGELOG.md
git commit -m "Sign the catalogue: ssh-keygen -Y sign per key, staged and renamed into place

File, security-key and agent backends behind one seam; a key that cannot sign is
left out and named, not retried in a hang; a full disk or a pulled token leaves
the previous catalogue and signatures serving; a catalogue is signed only when
it changed, a key changed, or it is a week old."
```

### Task 3: Key management — `[signing]`, `bunker keys`, first-run setup, key strength

`bunker keys list|add|retire` manage the registry Task 2 reads; a first start with no keys detects a FIDO2 token (`fido2-token -L`) and a PIV card (`opensc-tool --list-readers`, through `pcscd`), offers hardware as the recommended default, and otherwise explains why a hardware key is worth having and makes a file key. Generation order is Ed25519, ECDSA, RSA 4096, RSA 3072, RSA 2048; every key is classified by the engine's `hammunition.keystrength` and RSA of 2048 bits or fewer is warned wherever it is shown. Adding or retiring a key republishes the catalogue at once.

**Files:**
- Create: `src/bunker/keys.py`, `tests/test_keys.py`, `tests/golden/keys.json` (written by the golden helper)
- Modify: `src/bunker/config.py` (`__all__` 22-38, `_KNOWN` 51-58, `_engine` 210-233, `Config` 128-135, `load` 284-320), `src/bunker/enginelib.py` (after `validate_catalogue`), `src/bunker/signing.py` (`PublishFailed`'s base stays; no change), `src/bunker/publish.py`, `src/bunker/cli.py` (imports 272-276, `_now_iso` 415-416, `cmd_run` 296-303, `cmd_serve` 419-431, `cmd_schedule` 434-474, `COMMANDS` 477-485, `parser` 488-526, `_dispatch` 529-540), `src/bunker/doctor.py` (imports 20-24, `doctor` 158-161), `Dockerfile` (apt list 34-38), `config.example.toml`, `docs/reference.md`, `docs/guide.md`, `CLAUDE.md` (Layout), `CHANGELOG.md`, `tests/test_config.py`, `tests/test_doctor.py` (36-39), `tests/test_cli.py`, `tests/test_packaging.py`, `tests/realkeys.py` (unchanged), `tests/golden/doctor.json`
- Test: `tests/test_keys.py` (real `ssh-keygen`, stub runners for tokens), `tests/test_config.py`, `tests/test_doctor.py`, `tests/test_cli.py`, `tests/test_packaging.py`

**Interfaces:**
- Consumes: `bunker.signing` (`KeySpec`, `load_registry`, `save_registry`, `load_signed`, `keys_dir`, `fingerprint`, `clean_public_key`, `run_command`, `Runner`, `SigningError`, `PublishFailed`, `BACKEND_NAMES`), `bunker.publish.publish`, `bunker.volume.RunLock`, `hammunition.keystrength.classify(public_key_line)` returning an object with `algorithm`, `bits`, `hardware_by_type`, `rank`, `weak`, `warning` (the contract; how it refuses DSA is not specified, so `describe` turns any exception into `KeyManagementError`).
- Produces:
  - `bunker.config.SigningConfig(refresh_days: int = 7, sign_timeout: float = 60.0, ssh_keygen: tuple[str, ...] = ("ssh-keygen",), agent_socket: str | None = None)`, `Config.signing`
  - `bunker.enginelib.keystrength_module() -> ModuleType`
  - `bunker.keys`: `class KeyManagementError(SigningError)`; `ORDER: tuple[str, ...]`; `@dataclass(frozen=True) class Described(algorithm: str, bits: int, hardware_by_type: bool, rank: int, weak: bool, warning: str | None)`; `describe(public_key: str) -> Described`; `@dataclass(frozen=True) class Tokens(fido2: tuple[str, ...] = (), piv: tuple[str, ...] = ())`; `detect_tokens(*, runner: Runner = run_command) -> Tokens`; `TtyRunner = Callable[[Sequence[str], float], int]`; `run_tty(argv: Sequence[str], timeout: float) -> int`; `generate_file_key(root: Path, *, name: str, now: str, choice: str | None = None, runner: Runner = run_command, command: Sequence[str] = ("ssh-keygen",)) -> KeySpec`; `generate_security_key(root: Path, *, name: str, no_touch: bool, now: str, runner: TtyRunner = run_tty, command: Sequence[str] = ("ssh-keygen",)) -> KeySpec`; `register_agent_key(root: Path, public_key: str, *, hardware: bool, now: str) -> KeySpec`; `add(root: Path, spec: KeySpec) -> KeySpec`; `retire(root: Path, ref: str, now: str) -> KeySpec`; `@dataclass(frozen=True) class KeyView(id, backend, algorithm, bits, hardware, retired, added, last_signed, in_catalogue, warning)`; `views(keys: Sequence[KeySpec], signed: Mapping[str, str], published: Collection[str]) -> list[KeyView]`; `ensure_keys(root: Path, *, name: str, interactive: bool, ask: Callable[[str], str], say: Callable[[str], None], now: str, runner: Runner = run_command, tty: TtyRunner = run_tty, command: Sequence[str] = ("ssh-keygen",)) -> list[KeySpec]`; `NO_HARDWARE: str`
  - CLI: `bunker keys list [--json]`, `bunker keys add [--backend {file,security-key,agent}] [--algorithm ALG] [--no-touch] [--public-key PATH] [--hardware]`, `bunker keys retire REF`; the `keys` document (`serial`, `hardware_key`, `keys[]`); `bunker.doctor.which` seam; a `signing` doctor check.

- [ ] **Step 1: Write the failing config tests**

Append to `tests/test_config.py`:

```python
def test_the_signing_table_defaults_and_values(tmp_path: Path) -> None:
    assert config.load(write(tmp_path, "")).signing == config.SigningConfig()
    cfg = config.load(
        write(
            tmp_path,
            '[signing]\nrefresh_days = 14\nsign_timeout = 120\nssh_keygen = "/opt/ssh/ssh-keygen"\n'
            'agent_socket = "/run/agent.sock"\n',
        )
    )
    assert cfg.signing == config.SigningConfig(14, 120.0, ("/opt/ssh/ssh-keygen",), "/run/agent.sock")


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("[signing]\nrefresh_days = 0\n", "signing.refresh_days"),
        ("[signing]\nrefresh_days = 91\n", "signing.refresh_days"),
        ('[signing]\nrefresh_days = "7"\n', "signing.refresh_days"),
        ("[signing]\nsign_timeout = 0\n", "signing.sign_timeout"),
        ("[signing]\nsign_timeout = 601\n", "signing.sign_timeout"),
        ('[signing]\nssh_keygen = ""\n', "signing.ssh_keygen"),
        ("[signing]\nagent_socket = 5\n", "signing.agent_socket"),
        ("[signing]\nkey = 1\n", "unknown key signing.key"),
    ],
)
def test_a_bad_signing_table_is_refused_by_key(tmp_path: Path, text: str, needle: str) -> None:
    with pytest.raises(ConfigError, match=needle):
        config.load(write(tmp_path, text))
```

Run: `.venv/bin/python -m pytest tests/test_config.py -q -k signing` — Expected: FAIL, `AttributeError: module 'bunker.config' has no attribute 'SigningConfig'`.

- [ ] **Step 2: Add `[signing]` to `src/bunker/config.py`**

Add `"SigningConfig"` to `__all__` (isort order). In `_KNOWN` add `"signing": ("refresh_days", "sign_timeout", "ssh_keygen", "agent_socket"),` after `"serve"`. Add after `BunkerConfig`:

```python
@dataclass(frozen=True)
class SigningConfig:
    refresh_days: int = 7
    """A catalogue this old is signed again even if nothing changed."""
    sign_timeout: float = 60.0
    """Seconds one signature may take: a security key waits this long for a touch."""
    ssh_keygen: tuple[str, ...] = ("ssh-keygen",)
    agent_socket: str | None = None
    """``SSH_AUTH_SOCK`` for ``agent`` keys; unset uses the process's own."""
```

Add `signing: SigningConfig` to `Config` (after `bunker`). Replace the command parsing at the top of `_engine` (lines 211-222) by a shared helper and use it in both:

```python
def _command(raw: Any, key: str) -> tuple[str, ...]:
    if isinstance(raw, str):
        try:
            command = tuple(shlex.split(raw))
        except ValueError:  # an unclosed quotation
            command = ()
    elif isinstance(raw, list) and all(isinstance(p, str) for p in raw):
        command = tuple(raw)
    else:
        command = ()
    if not command or not all(command):
        raise ConfigError(f"{key} must be a command line or a list of arguments")
    return command


def _signing(table: Mapping[str, Any]) -> SigningConfig:
    days = table.get("refresh_days", 7)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 90:
        raise ConfigError(f"signing.refresh_days is {days!r}; it must be a whole number 1 to 90")
    timeout = table.get("sign_timeout", 60)
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or not 0 < timeout <= 600:
        raise ConfigError(f"signing.sign_timeout is {timeout!r}; it must be 1 to 600 seconds")
    socket = table.get("agent_socket")
    if socket is not None and (not isinstance(socket, str) or not socket):
        raise ConfigError("signing.agent_socket must be a path")
    return SigningConfig(
        refresh_days=days,
        sign_timeout=float(timeout),
        ssh_keygen=_command(table.get("ssh_keygen", "ssh-keygen"), "signing.ssh_keygen"),
        agent_socket=socket,
    )
```

In `_engine`, replace the `raw = ...` through `raise ConfigError("engine.command must be ...")` block with `command = _command(table.get("command", "hammunition"), "engine.command")`. In `load`'s `return Config(` add `signing=_signing(_table(data, "signing")),`.

Run: `.venv/bin/python -m pytest tests/test_config.py -q` — Expected: PASS (the existing `engine.command` tests still match "engine.command").

- [ ] **Step 3: Write the failing key tests**

Create `tests/test_keys.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Key generation, setup and the registry. File keys are real ``ssh-keygen``
keys in ``tmp_path``; a FIDO2 token, a PIV card and the terminal are stubs."""

from __future__ import annotations

import base64
import dataclasses
import json
import os
import struct
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from bunker import config, index, keys, publish, signing
from bunker.signing import KeySpec
from tests import plan_a, realkeys
from tests.helpers import FAKE_SK_PUBLIC, config_text

pytestmark = pytest.mark.real_signing

NOW = "2026-10-07T12:00:00Z"


def bits_by_ssh_keygen(public: Path) -> int:
    listing = subprocess.run(["ssh-keygen", "-l", "-f", str(public)], check=True, capture_output=True, text=True)
    return int(listing.stdout.split()[0])


def done(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], code, out.encode(), err.encode())


def fake_sk_ecdsa_public() -> str:
    """A hand-built sk-ecdsa public key line: the blob is well formed, no token stands behind it."""

    def s(b: bytes) -> bytes:
        return struct.pack(">I", len(b)) + b

    blob = s(b"sk-ecdsa-sha2-nistp256@openssh.com") + s(b"nistp256") + s(b"\x04" + bytes(range(64))) + s(b"ssh:")
    return "sk-ecdsa-sha2-nistp256@openssh.com " + base64.b64encode(blob).decode() + " bunker-fixture-sk-ecdsa"


class TtyStub:
    """Stands in for ``ssh-keygen -t ed25519-sk``: writes the two files a token
    would have made, or fails for the key types it is told to."""

    def __init__(self, fail: tuple[str, ...] = ()) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str], timeout: float) -> int:
        self.calls.append(list(argv))
        kind = argv[argv.index("-t") + 1]
        if kind in self.fail:
            return 1
        target = Path(argv[argv.index("-f") + 1])
        target.write_text("sk key handle\n")
        public = FAKE_SK_PUBLIC if kind == "ed25519-sk" else fake_sk_ecdsa_public()
        target.with_name(target.name + ".pub").write_text(public + "\n")
        return 0


def scripted(*answers: str) -> tuple[Callable[[str], str], list[str]]:
    queue, prompts = list(answers), []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return queue.pop(0)

    return ask, prompts


def no_tokens(argv: Sequence[str], stdin: bytes, timeout: float, env: object) -> subprocess.CompletedProcess[bytes]:
    """No token tools installed; the real ssh-keygen still makes file keys."""
    if argv[0].endswith("ssh-keygen"):
        return signing.run_command(argv, stdin, timeout, None)
    raise signing.SigningError(f"{argv[0]!r} was not found")


def with_fido2(argv: Sequence[str], stdin: bytes, timeout: float, env: object) -> subprocess.CompletedProcess[bytes]:
    if argv[0] == "fido2-token":
        return done(0, "/dev/hidraw3: vendor=0x1050, product=0x0407 (Yubico YubiKey OTP+FIDO+CCID)\n")
    return no_tokens(argv, stdin, timeout, env)


# --- strength ---------------------------------------------------------------


@pytest.mark.parametrize("kind", ["ed25519", "ecdsa", "rsa3072", "rsa2048"])
def test_describe_agrees_with_ssh_keygen_on_the_bits(tmp_path: Path, kind: str) -> None:
    plan_a.module("hammunition.keystrength")
    spec = realkeys.make_file_key(tmp_path, kind, register=False)
    assert keys.describe(spec.public_key).bits == bits_by_ssh_keygen(Path(spec.path + ".pub"))


def test_rsa_2048_is_accepted_and_warned_and_ed25519_is_not(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    weak = keys.describe(realkeys.make_file_key(tmp_path, "rsa2048", register=False).public_key)
    assert weak.weak and weak.warning is not None and "2048" in weak.warning
    assert weak.warning.endswith("replace with Ed25519, ECDSA or RSA 3072+")
    strong = keys.describe(realkeys.make_file_key(tmp_path, "ed25519", register=False).public_key)
    assert not strong.weak and strong.warning is None and strong.rank == 1


def test_a_key_the_engine_refuses_is_a_key_management_error() -> None:
    plan_a.module("hammunition.keystrength")
    with pytest.raises(keys.KeyManagementError):
        keys.describe("ssh-dss AAAAB3NzaC1kc3MAAAAB bunker-fixture-dsa")


# --- generation -------------------------------------------------------------


def test_the_default_key_is_ed25519_in_a_private_directory(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    spec = keys.generate_file_key(tmp_path, name="shack-1", now=NOW)
    assert spec.algorithm == "ssh-ed25519" and spec.bits == 256 and spec.backend == "file"
    assert spec.hardware is False and spec.no_touch is False and spec.added == NOW
    private = Path(spec.path)
    assert oct(private.stat().st_mode & 0o777) == "0o600"
    assert oct(signing.keys_dir(tmp_path).stat().st_mode & 0o777) == "0o700"
    assert private.with_name(private.name + ".pub").read_text().strip() == spec.public_key
    assert spec.public_key.endswith(" bunker:shack-1")
    assert list(signing.keys_dir(tmp_path).glob("new-*")) == [], "no half-made key is left behind"


def test_a_named_algorithm_is_made_and_never_downgraded(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    assert keys.generate_file_key(tmp_path, name="s", now=NOW, choice="rsa-3072").bits == 3072
    attempts: list[str] = []

    def refuse_everything(argv: Sequence[str], stdin: bytes, timeout: float, env: object) -> subprocess.CompletedProcess[bytes]:
        attempts.append(" ".join(argv))
        return done(255, err="no")

    with pytest.raises(keys.KeyManagementError, match="rsa-4096: no"):
        keys.generate_file_key(tmp_path, name="s", now=NOW, choice="rsa-4096", runner=refuse_everything)
    assert len(attempts) == 1, "a named choice is tried once, not silently replaced by a weaker one"


def test_the_default_falls_down_ed25519_ecdsa_rsa_4096_rsa_3072(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    tried: list[tuple[str, str | None]] = []

    def runner(argv: Sequence[str], stdin: bytes, timeout: float, env: object) -> subprocess.CompletedProcess[bytes]:
        kind = argv[argv.index("-t") + 1]
        bits = argv[argv.index("-b") + 1] if "-b" in argv else None
        tried.append((kind, bits))
        if kind in ("ed25519", "ecdsa") or bits == "4096":
            return done(255, err="unsupported here")
        return signing.run_command(argv, stdin, timeout, None)

    spec = keys.generate_file_key(tmp_path, name="s", now=NOW, runner=runner)
    assert spec.bits == 3072
    assert tried == [("ed25519", None), ("ecdsa", "384"), ("rsa", "4096"), ("rsa", "3072")]


def test_when_every_algorithm_fails_each_failure_is_named(tmp_path: Path) -> None:
    def runner(argv: Sequence[str], stdin: bytes, timeout: float, env: object) -> subprocess.CompletedProcess[bytes]:
        return done(255, err="no entropy")

    with pytest.raises(keys.KeyManagementError) as caught:
        keys.generate_file_key(tmp_path, name="s", now=NOW, runner=runner)
    for algorithm in keys.ORDER:
        assert f"{algorithm}: no entropy" in str(caught.value)


def test_rsa_2048_can_be_chosen_and_comes_back_weak(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    spec = keys.generate_file_key(tmp_path, name="s", now=NOW, choice="rsa-2048")
    assert spec.bits == 2048
    assert keys.describe(spec.public_key).weak


def test_a_security_key_is_resident_and_asks_for_touch_unless_told_not_to(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    stub = TtyStub()
    spec = keys.generate_security_key(tmp_path, name="shack-1", no_touch=False, now=NOW, runner=stub)
    argv = stub.calls[0]
    assert argv[argv.index("-t") + 1] == "ed25519-sk"
    assert ["-O", "resident"] == argv[argv.index("-O") : argv.index("-O") + 2]
    assert "application=ssh:hammunition-bunker-shack-1" in argv and "no-touch-required" not in argv
    assert spec.backend == "security-key" and spec.hardware is True and spec.no_touch is False
    quiet = keys.generate_security_key(tmp_path, name="shack-1", no_touch=True, now=NOW, runner=TtyStub())
    assert quiet.no_touch is True


def test_a_token_without_ed25519_gets_an_ecdsa_sk_key(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    stub = TtyStub(fail=("ed25519-sk",))
    spec = keys.generate_security_key(tmp_path, name="s", now=NOW, no_touch=False, runner=stub)
    assert [c[c.index("-t") + 1] for c in stub.calls] == ["ed25519-sk", "ecdsa-sk"]
    assert spec.algorithm == "sk-ecdsa-sha2-nistp256@openssh.com" and spec.hardware is True


def test_no_security_key_when_the_token_refuses_both(tmp_path: Path) -> None:
    with pytest.raises(keys.KeyManagementError, match="ed25519-sk.*ecdsa-sk"):
        keys.generate_security_key(
            tmp_path, name="s", now=NOW, no_touch=False, runner=TtyStub(fail=("ed25519-sk", "ecdsa-sk"))
        )


# --- detection and setup ----------------------------------------------------


def test_tokens_are_read_from_fido2_token_and_opensc(tmp_path: Path) -> None:
    def runner(argv: Sequence[str], stdin: bytes, timeout: float, env: object) -> subprocess.CompletedProcess[bytes]:
        if argv[0] == "fido2-token":
            return done(0, "/dev/hidraw3: vendor=0x1050, product=0x0407 (Yubico YubiKey)\n")
        return done(
            0,
            "# Detected readers (pcsc)\nNr.  Card  Features  Name\n"
            "0    Yes             Yubico YubiKey OTP+FIDO+CCID 00 00\n"
            "1    No              Empty reader\n",
        )

    found = keys.detect_tokens(runner=runner)
    assert found.fido2 == ("/dev/hidraw3: vendor=0x1050, product=0x0407 (Yubico YubiKey)",)
    assert found.piv == ("0    Yes             Yubico YubiKey OTP+FIDO+CCID 00 00",)
    assert keys.detect_tokens(runner=no_tokens) == keys.Tokens()


def test_setup_with_a_token_offers_hardware_first_and_a_file_key_beside_it(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    ask, prompts = scripted("", "y", "")  # hardware: yes; touch each time: yes; also a file key: yes
    said: list[str] = []
    made = keys.ensure_keys(
        tmp_path, name="shack-1", interactive=True, ask=ask, say=said.append, now=NOW,
        runner=with_fido2, tty=TtyStub(),
    )  # fmt: skip
    assert [k.backend for k in made] == ["security-key", "file"]
    assert made[0].hardware and not made[0].no_touch
    assert signing.load_registry(tmp_path) == made
    assert "recommended" in prompts[0] and "Y/n" in prompts[0], "hardware is the default answer"
    assert any("FIDO2" in line for line in said)


def test_setup_with_a_token_can_decline_the_touch_and_skip_the_file_key(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    ask, _ = scripted("y", "n", "n")
    made = keys.ensure_keys(
        tmp_path, name="s", interactive=True, ask=ask, say=lambda _: None, now=NOW,
        runner=with_fido2, tty=TtyStub(),
    )  # fmt: skip
    assert [k.backend for k in made] == ["security-key"] and made[0].no_touch is True


def test_setup_without_a_token_explains_and_makes_a_file_key(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    said: list[str] = []
    made = keys.ensure_keys(
        tmp_path, name="s", interactive=False, ask=lambda _: pytest.fail("asked without a terminal"),
        say=said.append, now=NOW, runner=no_tokens,
    )  # fmt: skip
    assert [k.backend for k in made] == ["file"]
    assert any(keys.NO_HARDWARE in line for line in said)
    assert "recommended, never required" in keys.NO_HARDWARE


def test_setup_with_a_token_but_nobody_at_the_terminal_does_not_guess(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    said: list[str] = []
    made = keys.ensure_keys(
        tmp_path, name="s", interactive=False, ask=lambda _: pytest.fail("asked without a terminal"),
        say=said.append, now=NOW, runner=with_fido2, tty=lambda *_: pytest.fail("touched a token unasked"),
    )  # fmt: skip
    assert [k.backend for k in made] == ["file"]
    assert any("bunker keys add --backend security-key" in line for line in said)


def test_setup_does_nothing_when_a_key_exists(tmp_path: Path) -> None:
    existing = realkeys.make_file_key(tmp_path)
    assert keys.ensure_keys(
        tmp_path, name="s", interactive=True, ask=lambda _: pytest.fail("asked"), say=lambda _: None,
        now=NOW, runner=no_tokens,
    ) == [existing]  # fmt: skip


# --- the registry -----------------------------------------------------------


def test_add_refuses_a_key_that_is_already_signing(tmp_path: Path) -> None:
    spec = realkeys.make_file_key(tmp_path)
    with pytest.raises(keys.KeyManagementError, match="already a signing key"):
        keys.add(tmp_path, spec)


def test_an_agent_key_is_a_public_key_file_with_no_private_key_beside_it(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    donor = realkeys.make_file_key(tmp_path / "other", "rsa3072", register=False)
    spec = keys.register_agent_key(tmp_path, donor.public_key, hardware=True, now=NOW)
    assert spec.backend == "agent" and spec.hardware is True and spec.bits == 3072
    pub = Path(spec.path)
    assert pub.suffix == ".pub" and not pub.with_suffix("").exists()


def test_retire_matches_an_id_or_a_unique_prefix_and_keeps_the_files(tmp_path: Path) -> None:
    first = realkeys.make_file_key(tmp_path)
    second = realkeys.make_file_key(tmp_path)
    retired = keys.retire(tmp_path, first.id.removeprefix("SHA256:")[:10], NOW)
    assert retired.id == first.id and retired.retired == NOW
    assert Path(first.path).exists(), "deleting is for a person"
    assert [(k.id, k.retired) for k in signing.load_registry(tmp_path)] == [(first.id, NOW), (second.id, None)]
    with pytest.raises(keys.KeyManagementError, match="only signing key"):
        keys.retire(tmp_path, second.id, NOW)
    with pytest.raises(keys.KeyManagementError, match="no active key matches"):
        keys.retire(tmp_path, "SHA256:nope", NOW)


def test_views_mark_weak_unpublished_and_retired_keys(tmp_path: Path) -> None:
    plan_a.module("hammunition.keystrength")
    weak = realkeys.make_file_key(tmp_path, "rsa2048")
    gone = dataclasses.replace(realkeys.make_file_key(tmp_path), retired=NOW)
    shown = keys.views([weak, gone], {weak.id: NOW}, {weak.id})
    assert shown[0].in_catalogue and shown[0].last_signed == NOW
    assert shown[0].warning is not None and "weak" in shown[0].warning
    assert shown[1].retired == NOW and not shown[1].in_catalogue and shown[1].last_signed is None


# --- the commands -----------------------------------------------------------


@pytest.fixture
def volume(tmp_path: Path) -> config.Config:
    path = tmp_path / "bunker.toml"
    path.write_text(config_text(str(tmp_path / "vol"), extra='[bunker]\nname = "shack-1"\n'))
    return config.load(path)


def cli(volume: config.Config, *argv: str) -> int:
    from bunker import cli as cli_module

    return cli_module.main([*argv, "--config", str(volume.path)])


def test_the_first_start_makes_a_key_and_publishes_a_signed_empty_catalogue(volume: config.Config) -> None:
    plan_a.module("hammunition.keystrength")
    from bunker import cli as cli_module

    cli_module._prepare(volume, publish_empty=True)
    document = json.loads((volume.storage.root / index.FILE).read_text())
    assert len(document["signers"]) == 1 and document["serial"] == 1
    assert (volume.storage.root / "catalogue.sig.d" / "1.sig").exists()
    cli_module._prepare(volume, publish_empty=True)  # a second start changes nothing
    assert json.loads((volume.storage.root / index.FILE).read_text())["serial"] == 1


def test_keys_add_publishes_at_once_and_the_new_key_signs(volume: config.Config, capsys: pytest.CaptureFixture[str]) -> None:
    plan_a.module("hammunition.keystrength")
    first = realkeys.make_file_key(volume.storage.root)
    publish.publish(volume, index.Index(), generated=NOW)
    assert cli(volume, "keys", "add", "--backend", "file", "--algorithm", "ecdsa-384") == 0
    ids = [s["id"] for s in index.load(volume.storage.root).signers]
    assert len(ids) == 2 and ids[0] == first.id
    assert "ecdsa" in capsys.readouterr().out.lower()


def test_keys_add_rsa_2048_prints_the_weak_key_warning(volume: config.Config, capsys: pytest.CaptureFixture[str]) -> None:
    plan_a.module("hammunition.keystrength")
    realkeys.make_file_key(volume.storage.root)
    assert cli(volume, "keys", "add", "--backend", "file", "--algorithm", "rsa-2048") == 0
    assert "RSA 2048-bit is weak" in capsys.readouterr().out


def test_retire_republishes_at_once_and_refuses_the_last_key(volume: config.Config, capsys: pytest.CaptureFixture[str]) -> None:
    plan_a.module("hammunition.keystrength")
    first = realkeys.make_file_key(volume.storage.root)
    second = realkeys.make_file_key(volume.storage.root)
    publish.publish(volume, index.Index(), generated=NOW)
    assert {s["id"] for s in index.load(volume.storage.root).signers} == {first.id, second.id}
    assert cli(volume, "keys", "retire", first.id) == 0
    assert [s["id"] for s in index.load(volume.storage.root).signers] == [second.id]
    assert [p.name for p in (volume.storage.root / "catalogue.sig.d").iterdir()] == ["1.sig"]
    capsys.readouterr()
    assert cli(volume, "keys", "retire", second.id) == 2
    assert "only signing key" in capsys.readouterr().err


def test_a_retire_that_could_not_publish_is_finished_by_the_next_publish(volume: config.Config, capsys: pytest.CaptureFixture[str]) -> None:
    plan_a.module("hammunition.keystrength")
    first = realkeys.make_file_key(volume.storage.root)
    second = realkeys.make_file_key(volume.storage.root)
    publish.publish(volume, index.Index(), generated=NOW)
    hidden = Path(second.path + ".hidden")
    os.replace(second.path, hidden)  # the remaining key cannot sign right now
    assert cli(volume, "keys", "retire", first.id) == 1
    assert "not republished" in capsys.readouterr().err
    assert first.id in {s["id"] for s in index.load(volume.storage.root).signers}, "still listed until a publish succeeds"
    os.replace(hidden, second.path)
    publish.publish(volume, index.load(volume.storage.root), generated="2026-10-07T13:00:00Z")
    assert [s["id"] for s in index.load(volume.storage.root).signers] == [second.id]


def test_keys_retire_during_a_run_is_locked_out_and_changes_nothing(volume: config.Config, capsys: pytest.CaptureFixture[str]) -> None:
    from bunker.volume import RunLock

    first = realkeys.make_file_key(volume.storage.root)
    realkeys.make_file_key(volume.storage.root)
    before = signing.load_registry(volume.storage.root)
    with RunLock(volume.storage.root):
        assert cli(volume, "keys", "retire", first.id) == 125
    assert signing.load_registry(volume.storage.root) == before
    assert "a run is in progress" in capsys.readouterr().err


def test_keys_add_security_key_needs_a_terminal(volume: config.Config, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(volume, "keys", "add", "--backend", "security-key") == 2
    assert "terminal" in capsys.readouterr().err


def test_keys_add_agent_needs_a_public_key_file(volume: config.Config, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(volume, "keys", "add", "--backend", "agent") == 2
    assert "--public-key" in capsys.readouterr().err
```

Run: `.venv/bin/python -m pytest tests/test_keys.py -q -x` — Expected: FAIL at import, `ImportError: cannot import name 'keys' from 'bunker'`.

- [ ] **Step 4: Write `src/bunker/keys.py`**

First add to `src/bunker/enginelib.py` (and to `__all__`: `"keystrength_module"`):

```python
def keystrength_module() -> ModuleType:
    """``hammunition.keystrength``: the suite's one rule for how strong a key is
    and what to say about a weak one (Plan A; the Bunker does not re-implement it)."""
    try:
        return importlib.import_module("hammunition.keystrength")
    except ImportError:
        raise BackendError(
            "the installed Hammunition has no hammunition.keystrength, which classifies "
            "signing keys; install the Hammunition release that carries it"
        ) from None
```

Create `src/bunker/keys.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Signing keys: making them, listing them, retiring them, and the first-run
setup that offers a hardware key.

Hardware is recommended and never required. Generation order is Ed25519,
ECDSA (P-384), RSA 4096, RSA 3072, RSA 2048: a default request walks down it
when ``ssh-keygen`` cannot make one, a named request is never replaced by a
weaker one. How strong a key is, and the warning for a weak one, are the
engine's (``hammunition.keystrength``): RSA of 2048 bits or fewer is accepted
and warned wherever the key is shown.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import subprocess
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from bunker import enginelib, signing
from bunker.signing import KeySpec, Runner, SigningError, run_command

__all__ = [
    "NO_HARDWARE",
    "ORDER",
    "Described",
    "KeyManagementError",
    "KeyView",
    "Tokens",
    "TtyRunner",
    "add",
    "describe",
    "detect_tokens",
    "ensure_keys",
    "generate_file_key",
    "generate_security_key",
    "register_agent_key",
    "retire",
    "run_tty",
    "views",
]

#: The #389 order, strongest first. ``rsa-2048`` is the last resort.
ORDER = ("ed25519", "ecdsa-384", "rsa-4096", "rsa-3072", "rsa-2048")
_KEYGEN: dict[str, tuple[str, ...]] = {
    "ed25519": ("-t", "ed25519"),
    "ecdsa-384": ("-t", "ecdsa", "-b", "384"),
    "rsa-4096": ("-t", "rsa", "-b", "4096"),
    "rsa-3072": ("-t", "rsa", "-b", "3072"),
    "rsa-2048": ("-t", "rsa", "-b", "2048"),
}
NO_HARDWARE = (
    "No hardware key was found. A hardware key (any FIDO2 token: YubiKey, Immurok, "
    "SoloKey, Nitrokey, Token2, Feitian; or a PIV smart card) keeps the signing key off "
    "this disk, so a copy of the volume or a backup cannot sign for you. It is "
    "recommended, never required. This Bunker signs with a file key for now; add a "
    "hardware key whenever you like with `bunker keys add`."
)
_READER_WITH_CARD = re.compile(r"^\d+\s+Yes\b")


class KeyManagementError(SigningError):
    """A key cannot be made, added or retired."""


@dataclass(frozen=True)
class Described:
    """What the engine's ``classify`` says about a public key."""

    algorithm: str
    bits: int
    hardware_by_type: bool
    rank: int
    weak: bool
    warning: str | None


def describe(public_key: str) -> Described:
    """Classify *public_key* with ``hammunition.keystrength``."""
    try:
        found = enginelib.keystrength_module().classify(signing.clean_public_key(public_key))
        return Described(
            algorithm=str(found.algorithm),
            bits=int(found.bits),
            hardware_by_type=bool(found.hardware_by_type),
            rank=int(found.rank),
            weak=bool(found.weak),
            warning=str(found.warning) if found.warning else None,
        )
    except Exception as exc:  # the engine's refusals (DSA, malformed) have no common base
        raise KeyManagementError(f"this key cannot be used: {exc}") from None


@dataclass(frozen=True)
class Tokens:
    fido2: tuple[str, ...] = ()
    """One line of ``fido2-token -L`` per attached FIDO2 authenticator."""
    piv: tuple[str, ...] = ()
    """One line of ``opensc-tool --list-readers`` per reader with a card in it."""


TtyRunner = Callable[[Sequence[str], float], int]


def run_tty(argv: Sequence[str], timeout: float) -> int:
    """Run *argv* on the operator's terminal (a PIN prompt, a touch request)."""
    try:
        return subprocess.run(list(argv), timeout=timeout, check=False).returncode  # noqa: S603 - argv list, no shell
    except FileNotFoundError:
        raise SigningError(f"{argv[0]!r} was not found; install openssh-client") from None
    except subprocess.TimeoutExpired:
        raise KeyManagementError(f"{argv[0]} did not finish within {timeout:g} s") from None


def detect_tokens(*, runner: Runner = run_command) -> Tokens:
    """Whether a FIDO2 token (``fido2-token -L``) or a PIV card (through
    ``pcscd``, read by ``opensc-tool``) is attached. A missing tool is no token."""

    def lines(argv: Sequence[str]) -> list[str]:
        try:
            done = runner(argv, b"", 10.0, None)
        except SigningError:
            return []
        if done.returncode != 0:
            return []
        return [x.strip() for x in done.stdout.decode("utf-8", "replace").splitlines() if x.strip()]

    return Tokens(
        fido2=tuple(lines(["fido2-token", "-L"])),
        piv=tuple(x for x in lines(["opensc-tool", "--list-readers"]) if _READER_WITH_CARD.match(x)),
    )


def _slug(public_key: str) -> str:
    return hashlib.sha256(signing.fingerprint(public_key).encode()).hexdigest()[:12]


def _discard(path: Path) -> None:
    path.unlink(missing_ok=True)
    path.with_name(path.name + ".pub").unlink(missing_ok=True)


def _install_pair(temp: Path, public: str) -> Path:
    """Move a freshly made key pair to its final name, which carries no secret."""
    final = temp.with_name(f"key-{_slug(public)}")
    os.replace(temp, final)
    os.replace(temp.with_name(temp.name + ".pub"), final.with_name(final.name + ".pub"))
    return final


def _spec(
    public_key: str, *, backend: str, path: Path, no_touch: bool, hardware: bool, now: str
) -> KeySpec:
    line = signing.clean_public_key(public_key)
    info = describe(line)
    return KeySpec(
        id=signing.fingerprint(line),
        backend=backend,
        public_key=line,
        algorithm=info.algorithm,
        bits=info.bits,
        hardware=hardware or info.hardware_by_type,
        path=str(path),
        no_touch=no_touch,
        retired=None,
        added=now,
    )


def generate_file_key(
    root: Path,
    *,
    name: str,
    now: str,
    choice: str | None = None,
    runner: Runner = run_command,
    command: Sequence[str] = ("ssh-keygen",),
) -> KeySpec:
    """A passphrase-less key under ``<root>/.keys`` (it must sign unattended).
    *choice* None walks :data:`ORDER`; a name from it makes exactly that."""
    if choice is not None and choice not in _KEYGEN:
        raise KeyManagementError(f"unknown algorithm {choice!r}; choose one of {', '.join(ORDER)}")
    folder = signing.keys_dir(root)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    failures: list[str] = []
    for algorithm in ORDER if choice is None else (choice,):
        temp = folder / f"new-{os.getpid()}"
        _discard(temp)
        argv = [*command, "-q", *_KEYGEN[algorithm], "-N", "", "-C", f"bunker:{name}", "-f", str(temp)]
        done = runner(argv, b"", 120.0, None)
        if done.returncode != 0:
            failures.append(f"{algorithm}: {done.stderr.decode('utf-8', 'replace').strip()[-200:]}")
            _discard(temp)
            continue
        public = temp.with_name(temp.name + ".pub").read_text(encoding="utf-8").strip()
        final = _install_pair(temp, public)
        return _spec(public, backend="file", path=final, no_touch=False, hardware=False, now=now)
    raise KeyManagementError("no key could be generated: " + "; ".join(failures))


def generate_security_key(
    root: Path,
    *,
    name: str,
    no_touch: bool,
    now: str,
    runner: TtyRunner = run_tty,
    command: Sequence[str] = ("ssh-keygen",),
) -> KeySpec:
    """A resident FIDO2 key on the attached token: ``ed25519-sk``, or
    ``ecdsa-sk`` when the token cannot do Ed25519. With *no_touch* the key is
    made ``no-touch-required`` so scheduled refreshes sign unattended. Runs on
    the terminal: the token asks for its PIN and a touch."""
    folder = signing.keys_dir(root)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    tried: list[str] = []
    for kind in ("ed25519-sk", "ecdsa-sk"):
        temp = folder / f"new-sk-{os.getpid()}"
        _discard(temp)
        argv = [*command, "-t", kind, "-O", "resident", "-O", f"application=ssh:hammunition-bunker-{name}"]
        if no_touch:
            argv += ["-O", "no-touch-required"]
        argv += ["-N", "", "-C", f"bunker:{name}", "-f", str(temp)]
        if runner(argv, 120.0) == 0:
            public = temp.with_name(temp.name + ".pub").read_text(encoding="utf-8").strip()
            final = _install_pair(temp, public)
            return _spec(public, backend="security-key", path=final, no_touch=no_touch, hardware=True, now=now)
        tried.append(kind)
        _discard(temp)
    raise KeyManagementError(
        f"the token would not make a key ({' and '.join(tried)} both failed): is it attached, "
        f"is its PIN set, and was it touched in time? FIDO2 has no RSA."
    )


def register_agent_key(root: Path, public_key: str, *, hardware: bool, now: str) -> KeySpec:
    """A key ``ssh-agent`` holds (a PIV card through PKCS#11, or any key added
    with ``ssh-add``): only its public half is stored, in a file with no
    private key beside it, so ``ssh-keygen`` must ask the agent."""
    line = signing.clean_public_key(public_key)
    folder = signing.keys_dir(root)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / f"agent-{_slug(line)}.pub"
    path.write_text(line + "\n", encoding="utf-8")
    return _spec(line, backend="agent", path=path, no_touch=False, hardware=hardware, now=now)


def add(root: Path, spec: KeySpec) -> KeySpec:
    existing = signing.load_registry(root)
    if any(k.id == spec.id and k.retired is None for k in existing):
        raise KeyManagementError(f"{spec.id} is already a signing key")
    signing.save_registry(root, [*existing, spec])
    return spec


def retire(root: Path, ref: str, now: str) -> KeySpec:
    """Stop signing with a key (its files stay: deleting is for a person).
    *ref* is a fingerprint or any unique prefix of at least six characters."""
    registry = signing.load_registry(root)
    active = [k for k in registry if k.retired is None]
    wanted = ref.removeprefix("SHA256:")
    matches = [
        k
        for k in active
        if k.id == ref or (len(wanted) >= 6 and k.id.removeprefix("SHA256:").startswith(wanted))
    ]
    if not matches:
        raise KeyManagementError(f"no active key matches {ref!r}; `bunker keys list` shows them")
    if len(matches) > 1:
        raise KeyManagementError(f"{ref!r} matches {len(matches)} keys; give more of the fingerprint")
    if len(active) == 1:
        raise KeyManagementError(
            "that is the only signing key; add another first, or the catalogue could not be signed"
        )
    gone = dataclasses.replace(matches[0], retired=now)
    signing.save_registry(root, [gone if k is matches[0] else k for k in registry])
    return gone


@dataclass(frozen=True)
class KeyView:
    id: str
    backend: str
    algorithm: str
    bits: int
    hardware: bool
    retired: str | None
    added: str
    last_signed: str | None
    in_catalogue: bool
    warning: str | None
    """The engine's weak-key text, or why strength could not be checked."""


def views(
    registry: Sequence[KeySpec], signed: Mapping[str, str], published: Collection[str]
) -> list[KeyView]:
    out: list[KeyView] = []
    for key in registry:
        try:
            warning = describe(key.public_key).warning
        except KeyManagementError as exc:
            warning = f"strength not checked: {exc}"
        out.append(
            KeyView(
                id=key.id,
                backend=key.backend,
                algorithm=key.algorithm,
                bits=key.bits,
                hardware=key.hardware,
                retired=key.retired,
                added=key.added,
                last_signed=signed.get(key.id),
                in_catalogue=key.id in published,
                warning=warning,
            )
        )
    return out


def _yes(answer: str, *, default: bool) -> bool:
    text = answer.strip().lower()
    return default if not text else text.startswith("y")


def ensure_keys(
    root: Path,
    *,
    name: str,
    interactive: bool,
    ask: Callable[[str], str],
    say: Callable[[str], None],
    now: str,
    runner: Runner = run_command,
    tty: TtyRunner = run_tty,
    command: Sequence[str] = ("ssh-keygen",),
) -> list[KeySpec]:
    """The keys this volume signs with, making them on a first start.

    With a FIDO2 token attached and a person at the terminal, a hardware key is
    offered as the default answer, with a file key beside it for the scheduled
    refreshes that nobody is there to touch. Without one, a paragraph says why a
    hardware key is worth having and a file key is made. Nothing is asked when
    nobody can answer (a container's first start): a file key is made, the
    registry says so, and the status page keeps a line about it."""
    existing = [k for k in signing.load_registry(root) if k.retired is None]
    if existing:
        return existing
    tokens = detect_tokens(runner=runner)
    made: list[KeySpec] = []
    if tokens.fido2 and interactive:
        say(f"A FIDO2 token is attached: {tokens.fido2[0]}")
        if _yes(ask("Create a hardware signing key on it? (recommended) [Y/n] "), default=True):
            touch = _yes(
                ask(
                    "Require a touch for every signature? More secure; scheduled refreshes "
                    "then wait for someone to tap. [y/N] "
                ),
                default=False,
            )
            made.append(
                add(root, generate_security_key(root, name=name, no_touch=not touch, now=now, runner=tty, command=command))
            )
    elif tokens.fido2:
        say(
            "A FIDO2 token is attached, but nobody is at a terminal to confirm. Make a hardware "
            "key with `bunker keys add --backend security-key` (run it with a terminal)."
        )
    if tokens.piv and not made:
        say(
            "A PIV smart card is attached. To sign with it, load it into ssh-agent "
            "(`ssh-add -s <pkcs11 module>`) and register it with "
            "`bunker keys add --backend agent --public-key FILE --hardware`."
        )
    if not made and not tokens.fido2 and not tokens.piv:
        say(NO_HARDWARE)
    need_file = not made
    if made and interactive:
        need_file = _yes(
            ask("Also create a file key, so scheduled refreshes sign unattended? [Y/n] "), default=True
        )
    if need_file:
        spec = add(root, generate_file_key(root, name=name, now=now, command=command, runner=runner))
        made.append(spec)
        say(f"Created file key {spec.id} ({spec.algorithm}, {spec.bits}-bit).")
        warning = describe(spec.public_key).warning
        if warning:
            say(f"warning: {warning}")
    return made
```

- [ ] **Step 5: Wire the commands**

`src/bunker/cli.py`:

Imports (line 272): `from bunker import __version__, checks, config, envelope, index, keys, publish, run, schedule, server, signing, verify`, and `from dataclasses import asdict` plus `from bunker.volume import Locked, RunLock`.

Replace `_now_iso` (415-416):

```python
def _now_iso() -> str:
    return run.iso(CLOCK() if CLOCK is not None else datetime.now(UTC))
```

Add after `_now_iso`:

```python
def _prepare(cfg: Config, *, publish_empty: bool) -> None:
    """Keys exist before anything is signed: a first start makes them (asking, on
    a terminal; otherwise a file key). A server also publishes an empty signed
    catalogue so the healthcheck and a laptop have something to read at once."""
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    keys.ensure_keys(
        cfg.storage.root,
        name=cfg.bunker.name,
        interactive=interactive,
        ask=input,
        say=print,
        now=_now_iso(),
        command=cfg.signing.ssh_keygen,
    )
    if publish_empty:
        publish.ensure_published(cfg, generated=_now_iso())
```

In `cmd_run` add `_prepare(cfg, publish_empty=False)` after `cfg = _config(args)`. In `cmd_serve` and `cmd_schedule` replace the `publish.ensure_published(cfg, generated=_now_iso())` line from Task 1 with `_prepare(cfg, publish_empty=True)`.

Add the command (above `COMMANDS`):

```python
def _keys_body(cfg: Config) -> dict[str, Any]:
    root = cfg.storage.root
    idx = index.load(root)
    shown = keys.views(
        signing.load_registry(root),
        signing.load_signed(root),
        {str(s.get("id")) for s in idx.signers},
    )
    return {
        "serial": idx.serial or None,
        "hardware_key": any(v.hardware and v.retired is None for v in shown),
        "keys": [asdict(v) for v in shown],
    }


def _print_keys(body: Mapping[str, Any]) -> None:
    print(f"Signing keys (catalogue serial {body['serial'] or 'none yet'}):")
    for k in body["keys"]:
        state = "retired " + k["retired"] if k["retired"] else ("in the catalogue" if k["in_catalogue"] else "not yet in the catalogue")
        kind = "hardware" if k["hardware"] else k["backend"]
        print(f"  {k['id']}  {kind:<8} {k['algorithm']} {k['bits']}-bit  last signed {k['last_signed'] or 'never'}  [{state}]")
        if k["warning"]:
            print(f"    warning: {k['warning']}")
    if not body["hardware_key"]:
        print("No hardware key configured. Add one with `bunker keys add --backend security-key`.")


def _keys_add(cfg: Config, args: argparse.Namespace, now: str) -> signing.KeySpec:
    root = cfg.storage.root
    terminal = sys.stdin.isatty() and sys.stdout.isatty()
    backend = args.backend
    if backend is None:
        found = keys.detect_tokens() if terminal else keys.Tokens()
        backend = "security-key" if found.fido2 else "file"
    if backend != "file" and args.algorithm:
        raise keys.KeyManagementError("--algorithm applies to file keys only")
    if backend == "file":
        spec = keys.generate_file_key(
            root, name=cfg.bunker.name, now=now, choice=args.algorithm, command=cfg.signing.ssh_keygen
        )
    elif backend == "security-key":
        if not terminal:
            raise keys.KeyManagementError(
                "a security key asks for its PIN and a touch: run this with a terminal "
                "(`podman exec -it <container> bunker keys add --backend security-key`)"
            )
        spec = keys.generate_security_key(
            root, name=cfg.bunker.name, no_touch=args.no_touch, now=now, command=cfg.signing.ssh_keygen
        )
    else:
        if args.public_key is None:
            raise keys.KeyManagementError("an agent key needs --public-key FILE (the key ssh-add -L shows)")
        try:
            text = args.public_key.read_text(encoding="utf-8")
        except OSError as exc:
            raise keys.KeyManagementError(f"{args.public_key}: {exc.strerror or exc}") from None
        spec = keys.register_agent_key(root, text, hardware=args.hardware, now=now)
    keys.add(root, spec)
    warning = keys.describe(spec.public_key).warning
    print(f"Added {spec.backend} key {spec.id} ({spec.algorithm}, {spec.bits}-bit).")
    if warning:
        print(f"warning: {warning}")
    return spec


def cmd_keys(args: argparse.Namespace, emit: Emit | None) -> int:
    cfg = _config(args)
    root = cfg.storage.root
    code = EXIT_OK
    if args.keys_command != "list":
        now = _now_iso()
        root.mkdir(parents=True, exist_ok=True)
        with RunLock(root):  # a run in progress is publishing: wait for it (exit 125)
            try:
                if args.keys_command == "add":
                    _keys_add(cfg, args, now)
                else:
                    gone = keys.retire(root, args.ref, now)
                    print(f"Retired {gone.id}; its files stay in {signing.keys_dir(root)}.")
            except signing.SigningError as exc:
                _err(str(exc))
                return EXIT_REFUSED
            try:
                publish.publish(cfg, index.load(root), generated=now)
            except signing.PublishFailed as exc:
                _err(f"the key list changed but the catalogue was not republished: {exc}")
                code = EXIT_FAILED
    body = _keys_body(cfg)
    if emit is not None:
        emit("keys", body)
    elif args.keys_command == "list":
        _print_keys(body)
    return code
```

Add `"keys": cmd_keys,` to `COMMANDS`. In `parser()` add (before `return top`):

```python
    p_keys = sub.add_parser("keys", help="the keys the catalogue is signed with")
    keys_sub = p_keys.add_subparsers(dest="keys_command", required=True, metavar="ACTION")
    keys_sub.add_parser("list", parents=[common], help="every key, its strength and when it last signed")
    p_add = keys_sub.add_parser("add", parents=[common], help="make or register a signing key")
    p_add.add_argument("--backend", choices=signing.BACKEND_NAMES, default=None, help="file (default without a token), security-key (default with a FIDO2 token), or agent")
    p_add.add_argument("--algorithm", choices=keys.ORDER, default=None, help="file keys only; default ed25519")
    p_add.add_argument("--no-touch", action="store_true", help="security keys: make it no-touch-required, so scheduled refreshes sign unattended")
    p_add.add_argument("--public-key", type=Path, default=None, metavar="FILE", help="agent keys: the public key file")
    p_add.add_argument("--hardware", action="store_true", help="agent keys: affirm the key lives on a token")
    p_retire = keys_sub.add_parser("retire", parents=[common], help="stop signing with a key")
    p_retire.add_argument("ref", metavar="FINGERPRINT", help="a fingerprint, or any unique prefix of six or more characters")
```

In `_dispatch` replace the Task 2 `except signing.PublishFailed` with `except signing.SigningError as exc:` (same body).

`src/bunker/publish.py`: replace the `publish` body with

```python
def publish(cfg: Config, idx: Index, *, generated: str) -> PublishResult:
    """Sign and publish *idx* when :func:`bunker.signing.publish_signed` says
    it needs publishing. Raises :class:`bunker.signing.PublishFailed`."""
    root = cfg.storage.root
    idx.name, idx.mode = cfg.bunker.name, cfg.bunker.mode
    return signing.publish_signed(
        root,
        idx,
        generated=generated,
        keys=signing.load_registry(root),
        backends=_backends(cfg),
        refresh=timedelta(days=cfg.signing.refresh_days),
        timeout=cfg.signing.sign_timeout,
        validate=enginelib.validate_catalogue,
    )


def _backends(cfg: Config) -> Mapping[str, signing.Backend]:
    if cfg.signing.ssh_keygen == ("ssh-keygen",) and cfg.signing.agent_socket is None:
        return signing.BACKENDS
    real = signing.SshKeygenBackend(cfg.signing.ssh_keygen, agent_socket=cfg.signing.agent_socket)
    return {name: real for name in signing.BACKEND_NAMES}
```

with `from collections.abc import Mapping` and `from datetime import timedelta`.

`src/bunker/doctor.py`: add `import shutil`, `from collections.abc import Callable`, `from bunker import ENGINE_FLOOR, keys, signing`, a seam and a check:

```python
#: ``shutil.which``; tests replace it so the suite does not depend on openssh-client.
which: Callable[[str], str | None] = shutil.which


def _signing(cfg: Config) -> Check:
    program = cfg.signing.ssh_keygen[0]
    if which(program) is None:
        return Check(
            "signing",
            False,
            f"{program!r} was not found: install openssh-client (the image has it); "
            f"the catalogue cannot be signed without it",
        )
    try:
        active = [k for k in signing.load_registry(cfg.storage.root) if k.retired is None]
    except signing.SigningError as exc:
        return Check("signing", False, str(exc))
    if not active:
        return Check("signing", False, "no signing key is configured: `bunker keys add` (a first start makes a file key)")
    detail = f"{len(active)} active key(s): " + ", ".join(f"{k.backend} {k.algorithm} {k.bits}-bit" for k in active)
    if not any(k.hardware for k in active):
        detail += "; no hardware key configured (recommended: `bunker keys add --backend security-key`)"
    for key in active:
        try:
            warning = keys.describe(key.public_key).warning
        except keys.KeyManagementError:
            warning = None
        if warning:
            detail += f"; {key.id}: {warning}"
    return Check("signing", True, detail)
```

and in `doctor()`: `report.checks += [_engine(cfg), _volume(cfg), _signing(cfg), _unverified(cfg), _port(cfg)]`.

Tests: in `tests/test_doctor.py` add an autouse fixture `monkeypatch.setattr(doctor, "which", lambda name: f"/usr/bin/{name}")` (module-level `@pytest.fixture(autouse=True) def _openssh(monkeypatch)`), change the check-name set on line 38 to include `"signing"`, and add `test_a_missing_ssh_keygen_fails_the_signing_check` (`monkeypatch.setattr(doctor, "which", lambda name: None)`; assert the check `not ok and "openssh-client" in detail`). In `tests/test_cli.py` add the same autouse `which` patch to the `invoke` fixture (`monkeypatch.setattr(doctor, "which", lambda name: "/usr/bin/" + name)`; `from bunker import doctor`), and:

```python
def test_keys_list_json_golden(invoke: Any, scene: Scene) -> None:
    plan_a.module("hammunition.keystrength")
    invoke("run")
    code, out, _ = invoke("keys", "list", "--json")
    assert code == 0
    assert_golden("keys", normalise(out, scene))
```

(`from tests import plan_a`). Regenerate: `BUNKER_UPDATE_GOLDENS=1 .venv/bin/python -m pytest tests/test_cli.py -q`, read the diff of `doctor.json` (gains a `signing` check) and `keys.json` (the fake key, `in_catalogue: true`, `last_signed` the scene clock).

`Dockerfile`: change the apt list (lines 34-38) to add `openssh-client fido2-tools opensc libpcsclite1` and add `tests/test_packaging.py::test_the_image_has_the_signing_tools`:

```python
def test_the_image_has_the_signing_tools() -> None:
    text = (ROOT / "Dockerfile").read_text()
    for package in ("openssh-client", "fido2-tools", "opensc", "libpcsclite1"):
        assert re.search(rf"^\s+.*\b{package}\b", text, re.M), f"the image lacks {package}"
```

`config.example.toml`: add after `[bunker]`:

```toml
[signing]
refresh_days = 7           # sign again at this age even if nothing changed (1 to 90)
sign_timeout = 60          # seconds one signature may take; a security key waits for a touch (1 to 600)
ssh_keygen = "ssh-keygen"  # the program that signs
# agent_socket = "/run/agent.sock"   # SSH_AUTH_SOCK for agent (PIV) keys
```

- [ ] **Step 6: Run the suite**

Run: `.venv/bin/python -m pytest -q -W error::DeprecationWarning; echo "exit=$?"`
Expected: `exit=0`. The `plan_a`-gated tests skip without the Plan A checkout installed; on it they must all pass, so run the suite there before committing.

- [ ] **Step 7: Docs, falsification, `make check`, commit**

`docs/reference.md`: commands table rows for `bunker keys list`, `bunker keys add [--backend B] [--algorithm A] [--no-touch] [--public-key FILE] [--hardware]` and `bunker keys retire FINGERPRINT` (JSON kind `keys`); configuration rows for `signing.refresh_days`, `signing.sign_timeout`, `signing.ssh_keygen`, `signing.agent_socket`; a `keys` row in the `--json` documents table (`serial`, `hardware_key`, `keys` with `id`, `backend`, `algorithm`, `bits`, `hardware`, `retired`, `added`, `last_signed`, `in_catalogue`, `warning`); exit codes: `bunker keys add|retire` exits 2 when refused, 1 when the key list changed but the republish failed, 125 while a run holds the volume. `docs/guide.md`: a section "Signing keys" before "Security posture": what is signed and why (a laptop that enrols this Bunker accepts a catalogue only if one of the keys it was shown signed it), the first-start behaviour in a container (no terminal: a file key; `podman exec -it ... bunker keys add` to add a hardware key later), key order and the RSA-2048 warning, that `<root>/.keys` holds the private file keys (a copy of the volume is a copy of the key; a hardware key avoids that), and `bunker keys retire`. `CLAUDE.md` layout block: add `index, publish, signing, keys` to the `src/bunker/` list. `CHANGELOG.md`: "- Keys: `[signing]` config, `bunker keys list|add|retire`, a first-start setup that detects a FIDO2 token or PIV card and offers hardware as the default, file keys generated Ed25519, ECDSA, RSA 4096, RSA 3072, RSA 2048 with the engine's weak-key warning, a `signing` doctor check, and `openssh-client`, `fido2-tools`, `opensc` and `libpcsclite1` in the image."

Falsify: in `keys.retire` change `if len(active) == 1:` to `if len(active) == 0:`; run `.venv/bin/python -m pytest tests/test_keys.py -q -k retire` — Expected: `test_retire_matches_an_id_or_a_unique_prefix_and_keeps_the_files` FAILS (the last key is retired); restore. In `generate_file_key` swap `choice` handling so a named choice walks `ORDER`; `test_a_named_algorithm_is_made_and_never_downgraded` FAILS on `len(attempts) == 1`; restore.

Run: `make check; echo "exit=$?"` — Expected: `exit=0`.

```bash
git add src/bunker/keys.py src/bunker/config.py src/bunker/enginelib.py src/bunker/publish.py src/bunker/cli.py src/bunker/doctor.py Dockerfile config.example.toml CLAUDE.md docs/reference.md docs/guide.md CHANGELOG.md tests/test_keys.py tests/test_config.py tests/test_doctor.py tests/test_cli.py tests/test_packaging.py tests/golden
git commit -m "Key management: [signing], bunker keys, first-start setup, strength warnings

list/add/retire republish the catalogue at once and refuse to retire the last
key; a first start detects a FIDO2 token or PIV card and offers hardware, else
explains and makes a file key; generation walks Ed25519, ECDSA, RSA 4096/3072,
RSA 2048 and RSA of 2048 bits or fewer is warned using the engine's rule."
```

### Task 4: Record publisher facts and plan-time inputs during the run

A run records, per artifact the repository does not pin by sha256, what the publisher said when the Bunker fetched it (`publisher_name`, `publisher_size`), and holds the plan-time **inputs** the engine's expanded `artifacts --json` lists: region outlines (fetched, sha256 recorded: Geofabrik publishes no digest for a `.poly`) and the derived tile, sheet, 3DEP and FSTopo selections (written from the document, sha256 recorded). Both land in the catalogue.

> **Assumption, from Plan A task A10, which this plan could not read:** the contract fixes the *catalogue's* field names, not the expanded `artifacts --json`. This task assumes each artifact entry may carry `publisher_name` and `publisher_size`, and the document may carry a top-level `inputs` list of `{"kind", "region", "name", "url", "content"}` with exactly one of `url` and `content` set. All of it is optional, so the pinned v0.21.0 document still parses. If A10 spells them differently, `engine._parse` and `tests/helpers.py` are the only two places to change.

**Files:**
- Create: `src/bunker/inputs.py`
- Modify: `src/bunker/engine.py` (`__all__` 31-42, `Artifact` 67-78, `Listing` 93-101, `_parse` 197-258), `src/bunker/run.py` (`RunReport` 137-217, `_Pass.__init__` 336-354, matched branch 477-488, `commit` 530-538, `run()` 720-726), `src/bunker/volume.py` (`artifact_dir` 395-412, `RESERVED` 58, `__all__` 359-375), `fuzz/fuzz_engine_document.py` (28-55, 68-74), `tests/helpers.py` (`entry` 234-258, `artifacts_doc` 265-282), `tests/scene.py` (`Scene.list` 391-394), `tests/test_engine.py`, `tests/test_run.py`, `tests/test_volume.py` (41), `docs/reference.md`, `CHANGELOG.md`
- Test: `tests/test_engine.py`, `tests/test_run.py`, `tests/test_volume.py`

**Interfaces:**
- Consumes: `bunker.index.Input`, `bunker.index.INPUT_KINDS`, `bunker.run._download(root, artifact, transport)` (the `unverified-fetch` branch: size and date only), `bunker.volume.write_atomic`, `write_sidecar`.
- Produces:
  - `bunker.engine.Artifact` gains `publisher_name: str | None = None`, `publisher_size: int | None = None`
  - `bunker.engine.InputSpec(kind: str, region: str, name: str, url: str | None, content: Any | None)`; `Listing.inputs: tuple[InputSpec, ...] = ()`
  - `bunker.volume.Downloaded` (Protocol: read-only `path: Path`, `sha256: str`, `size: int`); `bunker.volume.input_path(root: Path, kind: str, name: str) -> Path`; `RESERVED` gains `catalogue.sig.d` and `inputs`
  - `bunker.inputs.InputOutcome(kind: str, region: str, name: str, action: str, reason: str | None = None)`; `fetch_inputs(root: Path, idx: Index, wanted: Sequence[InputSpec], *, download: Callable[[Artifact], Downloaded], stamp: str, refresh: Callable[[str | None], bool]) -> list[InputOutcome]`
  - `bunker.run._publisher_facts(artifact: Artifact) -> tuple[str | None, int | None]`; `RunReport.inputs: list[InputOutcome]`

- [ ] **Step 1: Write the failing tests**

`tests/helpers.py`: change `entry(...)` to take `**extra: Any` after `deferred` and return `{..., "deferred": deferred, **extra}`; change `artifacts_doc(...)` to take `inputs: list[dict[str, Any]] | None = None` and add `if inputs is not None: doc["inputs"] = inputs` (build the dict in a variable first). Add:

```python
def input_item(
    kind: str,
    region: str,
    name: str,
    *,
    url: str | None = None,
    content: Any = None,
) -> dict[str, Any]:
    return {"kind": kind, "region": region, "name": name, "url": url, "content": content}
```

`tests/scene.py` `Scene.list` becomes:

```python
    def list(
        self, entries: list[dict[str, Any]] | None = None, inputs: list[dict[str, Any]] | None = None
    ) -> None:
        self.engine.set_doc(
            artifacts_doc(
                entries if entries is not None else self.entries(), regions=(REGION,), inputs=inputs
            )
        )
```

Append to `tests/test_engine.py` (use the file's existing `parse`/`doc` helpers if it has them; this version is self-contained via `engine._parse`):

```python
def _doc_with(**over: Any) -> str:
    import json

    from tests.helpers import artifacts_doc, entry

    doc = artifacts_doc([entry("osm-regions", "europe/monaco", "https://p/m.pbf", "sha256", "a" * 64)])
    doc.update(over)
    return json.dumps(doc)


def test_publisher_name_and_size_are_read_when_listed_and_none_when_not() -> None:
    import json

    from tests.helpers import artifacts_doc, entry

    listed = entry(
        "osm-regions", "europe/monaco", "https://p/monaco-latest.osm.pbf", "md5-publisher", "b" * 32,
        size=7, publisher_name="monaco-260101.osm.pbf", publisher_size=7,
    )  # fmt: skip
    plain = entry("country-files", "cty.dat", "https://p/cty.zip", "sha256", "a" * 64)
    got = engine._parse(json.dumps(artifacts_doc([listed, plain])))
    assert (got.artifacts[0].publisher_name, got.artifacts[0].publisher_size) == ("monaco-260101.osm.pbf", 7)
    assert (got.artifacts[1].publisher_name, got.artifacts[1].publisher_size) == (None, None)


@pytest.mark.parametrize("field", ["publisher_name", "publisher_size"])
def test_a_wrong_typed_publisher_field_is_refused_by_name(field: str) -> None:
    import json

    from tests.helpers import artifacts_doc, entry

    bad = entry("u", "n", "https://p/x", "sha256", "a" * 64, **{field: ["x"]})
    with pytest.raises(engine.EngineError, match=field):
        engine._parse(json.dumps(artifacts_doc([bad])))


def test_inputs_are_read_with_exactly_one_of_url_and_content() -> None:
    from tests.helpers import input_item

    got = engine._parse(
        _doc_with(
            inputs=[
                input_item("region-outline", "europe/monaco", "europe/monaco.poly", url="https://p/monaco.poly"),
                input_item("tile-selection", "europe/monaco", "europe/monaco.json", content=["N43E007"]),
                input_item("region-outline", "europe/monaco", "europe/monaco.poly", url="https://p/monaco.poly"),
            ]
        )
    )
    assert [(i.kind, i.url, i.content) for i in got.inputs] == [
        ("region-outline", "https://p/monaco.poly", None),
        ("tile-selection", None, ["N43E007"]),
    ], "the same input listed twice is held once"


@pytest.mark.parametrize(
    "item",
    [
        {"kind": "region-outline", "region": "r", "name": "n", "url": "https://p/x", "content": [1]},
        {"kind": "region-outline", "region": "r", "name": "n", "url": None, "content": None},
        {"kind": "region-outline", "region": "", "name": "n", "url": "https://p/x", "content": None},
        {"kind": "region-outline", "region": "r", "name": "n", "url": 5, "content": None},
        "not an object",
    ],
)
def test_a_malformed_input_fails_the_listing_by_index(item: Any) -> None:
    with pytest.raises(engine.EngineError, match="input 0"):
        engine._parse(_doc_with(inputs=[item]))


def test_an_unknown_input_kind_is_refused_by_name_with_the_engine_version() -> None:
    from tests.helpers import input_item

    got = engine._parse(_doc_with(inputs=[input_item("cheese-selection", "europe/monaco", "x", content=[])]))
    assert got.inputs == ()
    [refused] = [d for d in got.deferred if d.refused and d.unit == "inputs"]
    assert "cheese-selection" in refused.reason and "0.21.0" in refused.reason
```

(`import pytest`, `Any` are already imported by the file; add if not.)

Append to `tests/test_run.py`:

```python
def test_publisher_facts_are_recorded_for_publisher_digest_kinds_only(scene: Scene) -> None:
    entries = scene.entries()
    entries[0].update(publisher_name="bigcty-20260906.zip", publisher_size=len(scene.data["cty"]))
    entries[1].update(publisher_name="vermont-260101.osm.pbf", publisher_size=len(scene.data["region"]))
    entries[2].update(publisher_name=None, publisher_size=None)  # an etag-md5 tile: size falls back to the listed one
    scene.list(entries)
    scene.run()
    pinned = scene.entry("country-files", "cty.dat")
    assert (pinned.publisher_name, pinned.publisher_size) == (None, None), "the repository's pin is the trust"
    region = scene.entry("osm-regions", REGION)
    assert (region.publisher_name, region.publisher_size) == ("vermont-260101.osm.pbf", len(scene.data["region"]))
    tile = scene.entry("dem-copernicus", TILE)
    assert (tile.publisher_name, tile.publisher_size) == (None, len(scene.data["tile"]))
    document = json.loads((scene.root / "catalogue.json").read_text())
    by_name = {a["name"]: a for a in document["artifacts"]}
    assert by_name[REGION]["publisher_name"] == "vermont-260101.osm.pbf"


def test_publisher_facts_follow_a_copy_that_is_kept(scene: Scene) -> None:
    scene.run()
    entries = scene.entries()
    entries[1].update(publisher_name="vermont-260101.osm.pbf", publisher_size=len(scene.data["region"]))
    scene.list(entries)
    scene.clock.advance(hours=1)
    scene.run()  # nothing is fetched; the record still learns the name
    assert scene.entry("osm-regions", REGION).publisher_name == "vermont-260101.osm.pbf"


def _monaco_inputs(scene: Scene, outline: bytes = b"monaco 1\n1.0 2.0\nEND\nEND\n") -> list[dict[str, Any]]:
    url = scene.pub.put("/geofabrik/europe/monaco.poly", outline)
    return [
        input_item("region-outline", "europe/monaco", "europe/monaco.poly", url=url),
        input_item("tile-selection", "europe/monaco", "europe/monaco.json", content=["N43E007"]),
    ]


def test_inputs_are_fetched_recorded_and_written_beside_the_artifacts(scene: Scene) -> None:
    scene.list(inputs=_monaco_inputs(scene))
    report = scene.run()
    assert report.exit_code == 0 and [o.action for o in report.inputs] == ["fetched", "fetched"]
    held = {(i.kind, i.name): i for i in index.load(scene.root).inputs}
    outline = held["region-outline", "europe/monaco.poly"]
    body = (scene.root / outline.path).read_bytes()
    assert outline.path == "inputs/region-outline/europe/monaco.poly"
    assert outline.sha256 == sha(body) == volume.read_sidecar(scene.root / outline.path)
    assert outline.size == len(body) and outline.region == "europe/monaco"
    selection = held["tile-selection", "europe/monaco.json"]
    assert (scene.root / selection.path).read_bytes() == b'["N43E007"]\n'
    document = json.loads((scene.root / "catalogue.json").read_text())
    assert {i["kind"] for i in document["inputs"]} == {"region-outline", "tile-selection"}


def test_a_second_run_does_not_fetch_a_held_outline_again(scene: Scene) -> None:
    scene.list(inputs=_monaco_inputs(scene))
    scene.run()
    before = scene.pub.requests("/geofabrik/europe/monaco.poly")
    scene.clock.advance(hours=1)
    report = scene.run()
    assert [o.action for o in report.inputs] == ["unchanged", "unchanged"]
    assert scene.pub.requests("/geofabrik/europe/monaco.poly") == before


def test_a_changed_selection_is_rewritten_and_a_dropped_input_leaves_the_index_not_the_disk(scene: Scene) -> None:
    scene.list(inputs=_monaco_inputs(scene))
    scene.run()
    scene.list(inputs=[input_item("tile-selection", "europe/monaco", "europe/monaco.json", content=["N43E007", "N43E008"])])
    scene.clock.advance(hours=1)
    scene.run()
    held = index.load(scene.root).inputs
    assert [(i.kind, i.sha256) for i in held] == [("tile-selection", sha(b'["N43E007","N43E008"]\n'))]
    assert (scene.root / "inputs/region-outline/europe/monaco.poly").exists(), "deleting is for a person"


def test_a_failed_outline_fetch_keeps_the_previous_copy_and_fails_the_run(scene: Scene) -> None:
    scene.list(inputs=_monaco_inputs(scene))
    scene.run()
    scene.pub.files.pop("/geofabrik/europe/monaco.poly")
    scene.clock.advance(days=2)  # the daily cadence is due
    report = scene.run()
    assert report.exit_code == 1 and report.inputs[0].action == "failed"
    kept = [i for i in index.load(scene.root).inputs if i.kind == "region-outline"]
    assert len(kept) == 1 and (scene.root / kept[0].path).exists()


def test_an_unsafe_input_name_fails_that_input_alone(scene: Scene) -> None:
    scene.list(inputs=[
        input_item("tile-selection", "europe/monaco", "../../etc/passwd", content=[]),
        input_item("tile-selection", "europe/monaco", "europe/monaco.json", content=["N43E007"]),
    ])  # fmt: skip
    report = scene.run()
    assert [o.action for o in report.inputs] == ["failed", "fetched"]
    assert not (scene.root.parent / "etc").exists()


def test_a_unit_filtered_run_leaves_the_inputs_alone(scene: Scene) -> None:
    scene.list(inputs=_monaco_inputs(scene))
    scene.run(units=("osm-regions",))
    assert index.load(scene.root).inputs == []
```

(imports for this file: `from bunker import index, volume`, `from tests.helpers import input_item`, `from tests.scene import TILE, sha`, `from typing import Any` — add what is missing; `REGION` and `json` are already imported.)

`tests/test_volume.py` line 41 neighbourhood: add `("catalogue.sig.d", "x"),` and `("inputs", "x"),` to the unsafe-names parameters, and:

```python
def test_input_paths_share_the_segment_rules(tmp_path: Path) -> None:
    assert volume.input_path(tmp_path, "region-outline", "europe/monaco.poly") == (
        tmp_path / "inputs" / "region-outline" / "europe" / "monaco.poly"
    )
    for name in ("../x", "a//b", ".hidden", "a\\b", ""):
        with pytest.raises(UnsafeName):
            volume.input_path(tmp_path, "region-outline", name)
    with pytest.raises(UnsafeName):
        volume.input_path(tmp_path, "../x", "monaco.poly")
```

Run: `.venv/bin/python -m pytest tests/test_engine.py tests/test_run.py tests/test_volume.py -q -x` — Expected: FAIL (`TypeError: entry() got an unexpected keyword argument` is fixed by the helper edit; the first real failure is `AttributeError: 'Artifact' object has no attribute 'publisher_name'`).

- [ ] **Step 2: The engine document**

`src/bunker/engine.py`: add `"InputSpec"` to `__all__`. Give `Artifact` (after `licence`) `publisher_name: str | None = None` and `publisher_size: int | None = None`, with docstrings ("what the publisher said the file is called / how big it is, when the engine lists it"). Add:

```python
@dataclass(frozen=True)
class InputSpec:
    """A plan-time input the engine's planning needs: a region outline to fetch
    (``url``), or a selection derived from one (``content``)."""

    kind: str
    region: str
    name: str
    url: str | None
    content: Any | None
```

Give `Listing` `inputs: tuple[InputSpec, ...] = ()` after `warnings`. In `_parse`, replace the `artifact = Artifact(...)` construction's keyword list by adding `publisher_name=_optional(item, index, "publisher_name", str), publisher_size=_optional(item, index, "publisher_size", int),` and add:

```python
def _optional(item: dict[str, Any], index: int, key: str, kind: type) -> Any:
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, kind):
        raise EngineError(
            f"artifact {index} of the engine's document: {key!r} is {value!r}, not {kind.__name__}"
        )
    return value


def _inputs(doc: dict[str, Any]) -> tuple[tuple[InputSpec, ...], list[Deferred]]:
    raw = doc.get("inputs", [])
    if not isinstance(raw, list):
        raise EngineError("the engine's document has an inputs entry that is not a list")
    specs: list[InputSpec] = []
    refused: list[Deferred] = []
    seen: set[tuple[str, str, str]] = set()
    for n, item in enumerate(raw):
        words = ("kind", "region", "name")
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k] for k in words):
            raise EngineError(f"input {n} of the engine's document lacks a kind, region or name")
        url, content = item.get("url"), item.get("content")
        if not isinstance(url, str | None) or (url is None) == (content is None):
            raise EngineError(
                f"input {n} ({item['kind']} {item['region']}) must carry exactly one of url and content"
            )
        key = (item["kind"], item["region"], item["name"])
        if item["kind"] not in INPUT_KINDS:
            refused.append(
                Deferred(
                    "inputs",
                    f"{item['kind']}:{item['region']}",
                    f"refused: input kind {item['kind']!r} is not one this Bunker knows "
                    f"({', '.join(INPUT_KINDS)}); the engine is Hammunition "
                    f"{doc.get('engine') or 'of an unknown version'}. Nothing was held for it; "
                    f"update the Bunker",
                    refused=True,
                )
            )
        elif key not in seen:
            seen.add(key)
            specs.append(InputSpec(*key, url=url, content=content))
    return tuple(specs), refused
```

(import `from bunker.index import INPUT_KINDS`), and at the end of `_parse` call `inputs, refused_inputs = _inputs(doc)` and pass `inputs=inputs` and `deferred=tuple(deferred) + tuple(refused_inputs)` to `Listing`.

`fuzz/fuzz_engine_document.py`: in `_item` add `"publisher_name": _opt(fdp, "x.osm.pbf"), "publisher_size": _opt(fdp, "5")` (an int or a string, both are fuzz); in `_document` add `"inputs": [{"kind": _opt(fdp, "region-outline"), "region": _opt(fdp, "europe/monaco"), "name": _opt(fdp, "m.poly"), "url": _opt(fdp, "https://x"), "content": _opt(fdp, "[]")} for _ in range(fdp.ConsumeIntInRange(0, 3))]` and in `TestOneInput` after the deferred loop: `for spec in listing.inputs: assert (spec.url is None) != (spec.content is None)`.

Run: `.venv/bin/python -m pytest tests/test_engine.py -q` — Expected: PASS.

- [ ] **Step 3: Volume helpers**

In `src/bunker/volume.py` add `"Downloaded"` and `"input_path"` to `__all__`, `from typing import Protocol`, set `RESERVED = ("index.json", "catalogue.json", "catalogue.sig.d", "status.html", "inputs")`, and replace `artifact_dir` (395-412):

```python
INPUTS = "inputs"


def _segments(label: str, name: str) -> list[str]:
    segments = name.split("/")
    for segment in segments:
        if (
            not segment
            or segment.startswith(".")
            or "\\" in segment
            or "\x00" in segment
            or len(segment.encode()) > 200
        ):
            raise UnsafeName(
                f"{label}/{name!r} has an empty, hidden, over-long or '..' segment; "
                f"refusing to store it"
            )
    return segments


def artifact_dir(root: Path, unit: str, name: str) -> Path:
    """``<root>/<unit>/<name>``, or UnsafeName."""
    if not _UNIT.fullmatch(unit) or unit in RESERVED:
        raise UnsafeName(f"unit {unit!r} is not a catalog unit name")
    return root.joinpath(unit, *_segments(unit, name))


def input_path(root: Path, kind: str, name: str) -> Path:
    """``<root>/inputs/<kind>/<name>`` under the same rules, or UnsafeName."""
    if not _UNIT.fullmatch(kind):
        raise UnsafeName(f"input kind {kind!r} is not a name")
    return root.joinpath(INPUTS, kind, *_segments(f"{INPUTS}/{kind}", name))


class Downloaded(Protocol):
    """A verified download waiting in ``.incoming``: what :func:`install` needs."""

    @property
    def path(self) -> Path: ...

    @property
    def sha256(self) -> str: ...

    @property
    def size(self) -> int: ...
```

- [ ] **Step 4: `bunker.inputs`**

Create `src/bunker/inputs.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Plan-time inputs: what the engine needs to plan with its publishers
unreachable, held beside the artifacts under ``<root>/inputs/<kind>/<name>``.

A region outline (``.poly``) is fetched through the engine's own fetch with no
digest to check, so the Bunker records the sha256 of what arrived: the
catalogue's signature then says "this Bunker saw these bytes", never more. A
selection (the terrain tiles, topo sheets, 3DEP or FSTopo files an outline
needs) arrives inside the engine's document and is written from it. Nothing
here is opened or parsed beyond hashing.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from bunker.engine import Artifact, InputSpec
from bunker.enginelib import BackendError
from bunker.index import Index, Input
from bunker.volume import Downloaded, UnsafeName, input_path, write_atomic, write_sidecar

__all__ = ["InputOutcome", "fetch_inputs"]


@dataclass
class InputOutcome:
    kind: str
    region: str
    name: str
    action: str
    """``fetched``, ``unchanged`` or ``failed``."""
    reason: str | None = None


def _one(
    root: Path,
    spec: InputSpec,
    held: Input | None,
    download: Callable[[Artifact], Downloaded],
    stamp: str,
    refresh: Callable[[str | None], bool],
) -> tuple[InputOutcome, Input | None]:
    who = {"kind": spec.kind, "region": spec.region, "name": spec.name}
    try:
        target = input_path(root, spec.kind, spec.name)
    except UnsafeName as exc:
        return InputOutcome(**who, action="failed", reason=str(exc)), None
    try:
        if spec.content is not None:
            text = json.dumps(spec.content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            data = (text + "\n").encode("utf-8")
            digest, size = hashlib.sha256(data).hexdigest(), len(data)
            if held is not None and held.sha256 == digest and target.is_file():
                return InputOutcome(**who, action="unchanged"), held
            target.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(target, data)
        else:
            if held is not None and target.is_file() and not refresh(held.fetched):
                return InputOutcome(**who, action="unchanged"), held
            got = download(
                Artifact(
                    unit="inputs",
                    name=f"{spec.kind}/{spec.name}",
                    url=spec.url or "",
                    check="unverified-fetch",
                    digest=None,
                    checksum_url=None,
                    size=None,
                    licence="",
                )
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(got.path, target)
            digest, size = got.sha256, got.size
        write_sidecar(target, digest)
    except (BackendError, OSError, ValueError) as exc:
        return InputOutcome(**who, action="failed", reason=str(exc).strip()), held
    record = Input(
        kind=spec.kind,
        region=spec.region,
        name=spec.name,
        path=target.relative_to(root).as_posix(),
        sha256=digest,
        size=size,
        fetched=stamp,
    )
    return InputOutcome(**who, action="fetched"), record


def fetch_inputs(
    root: Path,
    idx: Index,
    wanted: Sequence[InputSpec],
    *,
    download: Callable[[Artifact], Downloaded],
    stamp: str,
    refresh: Callable[[str | None], bool],
) -> list[InputOutcome]:
    """Hold every input in *wanted*; the index afterwards lists exactly those
    (an input the engine stopped listing leaves the index, never the disk). A
    failed fetch keeps the previous copy and its record."""
    current = {(i.kind, i.region, i.name): i for i in idx.inputs}
    outcomes: list[InputOutcome] = []
    kept: list[Input] = []
    for spec in wanted:
        held = current.get((spec.kind, spec.region, spec.name))
        outcome, record = _one(root, spec, held, download, stamp, refresh)
        outcomes.append(outcome)
        if record is not None:
            kept.append(record)
    idx.inputs = kept
    return outcomes
```

- [ ] **Step 5: The run records them**

`src/bunker/run.py`:

1. Imports: `from bunker import inputs, publish, signing, statuspage` and `from bunker.inputs import InputOutcome`.
2. After `Outcome` (line 135) add:

```python
def _publisher_facts(artifact: Artifact) -> tuple[str | None, int | None]:
    """What the publisher said, kept only for artifacts the repository does not
    pin by sha256 (for a pinned one the pin is the trust and the copy here only
    says "here"). The size falls back to the one the engine listed."""
    if artifact.check == "sha256":
        return None, None
    size = artifact.publisher_size if artifact.publisher_size is not None else artifact.size
    return artifact.publisher_name, size
```

3. In the matched branch (lines 482-484) and in `commit` (533-535), after `entry.publisher_url = artifact.url` add `entry.publisher_name, entry.publisher_size = _publisher_facts(artifact)`.
4. `RunReport`: add `inputs: list[InputOutcome] = field(default_factory=list)`; `exit_code` becomes `1 if self.error or self.refused or counts["failed"] or counts["corrupted"] or any(o.action == "failed" for o in self.inputs) else 0`; `as_dict` adds `"inputs": [asdict(o) for o in self.inputs],` before `"deferred"`; `summary_lines` appends, before the plain-HTTP block, `for o in self.inputs: if o.action == "failed": lines.append(f"  failed input: {o.kind} {o.region}/{o.name}: {o.reason}")`.
5. `_Pass`: add

```python
    def input_due(self, fetched: str | None) -> bool:
        if self.all or "inputs" in self.named:
            return True
        return due(self.cfg.schedule.cadence("inputs"), _parse(fetched), self.now)
```

6. In `run()`, after the `ThreadPoolExecutor` block and before `_drop`:

```python
        if not units or "inputs" in units:
            report.inputs = inputs.fetch_inputs(
                root,
                idx,
                got.inputs,
                download=lambda artifact: _download(root, artifact, state.transport),
                stamp=state.stamp,
                refresh=state.input_due,
            )
```

Also in `run()` the `known` set for `--unit` validation: add `known.add("inputs")` so `--unit inputs` is legal.

- [ ] **Step 6: Run the suite**

Run: `.venv/bin/python -m pytest -q -W error::DeprecationWarning; echo "exit=$?"`
Expected: `exit=0`. Goldens: `BUNKER_UPDATE_GOLDENS=1 .venv/bin/python -m pytest tests/test_cli.py -q`; `run.json` gains `"inputs": []`. Read the diff.

- [ ] **Step 7: Docs, falsification, commit**

`docs/reference.md`: the volume tree gains `inputs/<kind>/<name>` (+ `.sha256`), the catalogue artifact table gains `publisher_name` ("the dated file name the publisher resolved to; null for an artifact the repository pins by sha256"), `publisher_size`, and a catalogue `inputs` table (`kind` one of `region-outline`, `tile-selection`, `sheet-selection`, `dem3dep-selection`, `fstopo-selection`; `region`; `name`; `path`; `sha256`; `size`; `fetched`); "What the Bunker asks the engine" notes that artifact entries may carry `publisher_name` and `publisher_size`, and the document an `inputs` list; the `run` document row gains `inputs` (`kind`, `region`, `name`, `action`, `reason`). `CHANGELOG.md`: "- Publisher facts and inputs: a run records `publisher_name` and `publisher_size` for artifacts the repository does not pin by sha256, and holds the region outlines and derived selections the engine lists under `inputs/<kind>/<name>`, with their sha256, in the catalogue."

Falsify: in `_publisher_facts` delete the `if artifact.check == "sha256": return None, None` guard; `test_publisher_facts_are_recorded_for_publisher_digest_kinds_only` FAILS on the pinned `cty.dat`; restore.

Run: `make check; echo "exit=$?"` — Expected: `exit=0`.

```bash
git add src/bunker/inputs.py src/bunker/engine.py src/bunker/run.py src/bunker/volume.py fuzz/fuzz_engine_document.py tests/helpers.py tests/scene.py tests/test_engine.py tests/test_run.py tests/test_volume.py tests/golden docs/reference.md CHANGELOG.md
git commit -m "Record publisher facts and plan-time inputs in the catalogue

publisher_name and publisher_size for artifacts the repository does not pin by
sha256; region outlines fetched and selections written under inputs/<kind>/<name>
with their sha256, kept when a refetch fails, dropped from the index (not the
disk) when the engine stops listing them."
```

### Task 5: New fetch kinds — sheets, payloads, git bundles

Three additions to what a Bunker holds. **Topo and FSTopo sheets** (US Topo, 3DEP and FSTopo, which the engine will take from a mirror after Plan A) arrive as two new check kinds: `etag` (the repository carries the object's ETag and size; an ETag is not always an MD5, so nothing here recomputes it) and `sized` (FSTopo files with no digest anywhere: size only, held under `hold_unverified` like the other unverified kinds). **Software payloads** (source tarballs, prebuilt binaries, venv wheels, the Node tarball, the mapsforge converter tool) are ordinary `sha256` artifacts under new unit and name shapes: no new kind, but their names carry `+`, `@` and nested paths, so a test pins that they survive the engine's percent-quoting and the server. **Git bundles** are built by the Bunker, not downloaded: `git clone --no-checkout` of the pinned repository, a check that the pinned commit is really there, `git bundle create --all`, and the same for each submodule, under the contract's names.

> **Assumptions, for the same reason as Task 4:** the check names `etag`, `sized` and `git-commit`, and the call shapes `Fetcher.fetch_etag(url, etag, expected_size=...)` and `Fetcher.fetch_sized(url, expected_size=...)` (the spec names the two methods, not their signatures), are this plan's. Step 3 settles the names against the installed Plan A engine: `tests/test_kinds.py::test_the_table_covers_every_kind_the_installed_engine_can_emit` imports `hammunition.interface.artifacts.CHECKS` and fails on a kind the table lacks; rename here to match. How the engine lists git pins is also unread: this task assumes one artifact per pinned repository, `unit` `git-bundles`, `name` `<unit>@<commit>`, `url` the repository, `check` `git-commit`, `digest` the 40-hex commit id; the Bunker discovers submodules itself, and holds a submodule the engine also lists once.

**Files:**
- Create: `src/bunker/gitbundle.py`, `tests/test_gitbundle.py`, `tests/test_payloads.py`
- Modify: `src/bunker/checks.py` (docstring 1-14, `KINDS` 420-489), `src/bunker/run.py` (`_download` 274-330, `_matches` 393-422, `sweep_incoming` 570-586, `_drop` 628-648, `_order` 673-674, `RunReport` 137-217, `run()` 720-726), `src/bunker/statuspage.py` (150-170), `Dockerfile` (apt list), `CLAUDE.md` (invariants), `README.md` (73-79, 124-126), `docs/reference.md` (102-111), `docs/guide.md` (295), `tests/test_kinds.py` (141-174), `tests/test_packaging.py`, `CHANGELOG.md`
- Test: `tests/test_kinds.py`, `tests/test_gitbundle.py`, `tests/test_payloads.py`, `tests/test_statuspage.py`, `tests/test_packaging.py`

**Interfaces:**
- Consumes: `bunker.volume.install(...)`, `artifact_dir`, `Downloaded`, `hash_file`, `read_sidecar`; `bunker.index.Entry`; `bunker.enginelib.BackendError`; `Fetcher.fetch_etag` and `Fetcher.fetch_sized` (Plan A).
- Produces:
  - `bunker.checks.KINDS` gains `etag` (method `fetch_etag`, no algorithm, needs size and digest), `sized` (method `fetch_sized`, needs size, no digest: `unverified`), `git-commit` (method `git_bundle`, built by `bunker.gitbundle`, needs a digest: the commit id)
  - `bunker.gitbundle.UNIT = "git-bundles"`, `ALLOWED_PROTOCOLS = "https"`, `MAX_DEPTH = 4`; `Pin(name: str, url: str, commit: str, licence: str = "")`; `Built(path: Path, sha256: str, size: int, submodules: tuple[Pin, ...])`; `GitRunner = Callable[[Sequence[str], Path | None, Mapping[str, str], float], subprocess.CompletedProcess[str]]`; `run_git(argv, cwd, env, timeout) -> CompletedProcess[str]`; `build(pin: Pin, workdir: Path, *, run: GitRunner = run_git, allowed: str | None = None) -> Built`; `BundleOutcome(name: str, action: str, reason: str | None = None)`; `hold_bundles(root: Path, idx: Index, pins: Sequence[Pin], *, stamp: str, run: GitRunner = run_git, allowed: str | None = None) -> list[BundleOutcome]`
  - `RunReport.bundles: list[BundleOutcome]`

- [ ] **Step 1: Write the failing kind tests**

In `tests/test_kinds.py` replace `test_the_engine_contract_kinds_are_listed_literally` and `test_the_table_is_complete_and_consistent` (lines 141-174) so they list the three new kinds:

```python
ALL_KINDS = {
    "sha256",
    "sha256-publisher",
    "md5-publisher",
    "etag-md5",
    "sha1-publisher",
    "unverified-zip",
    "unverified-fetch",
    "etag",
    "sized",
    "git-commit",
}


def test_the_engine_contract_kinds_are_listed_literally() -> None:
    assert ALL_KINDS == set(KINDS)


def test_the_table_is_complete_and_consistent() -> None:
    assert set(KINDS) == ALL_KINDS
    for name, kind in KINDS.items():
        assert kind.name == name
        assert kind.method in {
            "fetch", "fetch_md5", "fetch_sha1", "fetch_checked", "fetch_etag", "fetch_sized", "git_bundle",
        }  # fmt: skip
        assert kind.algorithm in {"sha256", "md5", "sha1"} or kind.algorithm is None
        assert kind.summary
    assert [n for n, k in KINDS.items() if k.unverified] == ["unverified-zip", "unverified-fetch", "sized"]
    assert [n for n, k in KINDS.items() if k.zip_structure] == ["unverified-zip"]
    assert [n for n, k in KINDS.items() if k.algorithm is None and k.needs_digest] == ["etag", "git-commit"]
    assert checks.is_unverified("sized") and not checks.is_unverified("etag")
    assert not checks.is_unverified("git-commit")
```

Add `held_unverified` to the file's `from bunker.index import load as load_index` import (`from bunker.index import held_unverified, load as load_index` splits into two lines under ruff's isort), and, near the other `needs_*` markers at the top of the file:

```python
needs_sheets = pytest.mark.skipif(
    not (hasattr(Fetcher, "fetch_etag") and hasattr(Fetcher, "fetch_sized")),
    reason="Fetcher.fetch_etag / fetch_sized come with the Plan A engine release",
)
```

and the behaviour tests (the loopback `Publisher` answers every path with `ETag: "<md5>"`):

```python
def etag_entry(bench: Bench, data: bytes = b"a us topo sheet " * 500) -> dict[str, Any]:
    url = bench.pub.put("/ustopo/DE_Dover_20240101.pdf", data)
    return entry("ustopo", "DE_Dover_20240101.pdf", url, "etag", md5(data), size=len(data))


@needs_sheets
def test_an_etag_sheet_is_fetched_recorded_and_not_recomputed(bench: Bench) -> None:
    listed = etag_entry(bench)
    bench.list([listed])
    assert bench.run().exit_code == 0
    stored = load_index(bench.root).find("ustopo", "DE_Dover_20240101.pdf")
    assert stored is not None and stored.publisher_check == "etag"
    assert stored.publisher_digest == listed["digest"] and stored.size == listed["size"]
    before = bench.pub.total()
    bench.clock.advance(hours=1)
    again = bench.run()
    assert [o.action for o in again.outcomes] == ["unchanged"] and bench.pub.total() == before


@needs_sheets
def test_an_etag_sheet_with_the_wrong_etag_keeps_nothing(bench: Bench) -> None:
    listed = etag_entry(bench)
    listed["digest"] = "0" * 32
    bench.list([listed])
    report = bench.run()
    assert report.exit_code == 1 and not list(bench.root.glob("ustopo/**/*.pdf"))


@needs_sheets
def test_a_sized_fstopo_file_is_held_under_the_unverified_ruling(bench: Bench) -> None:
    data = b"fstopo geopdf " * 300
    url = bench.pub.put("/fstopo/OR_Mt_Hood.pdf", data)
    bench.list([entry("fstopo", "OR_Mt_Hood.pdf", url, "sized", None, size=len(data))])
    assert bench.run().exit_code == 0
    stored = load_index(bench.root).find("fstopo", "OR_Mt_Hood.pdf")
    assert stored is not None and stored.size == len(data) and stored.publisher_digest is None
    assert [e.name for e in held_unverified(load_index(bench.root))] == ["OR_Mt_Hood.pdf"]


@needs_sheets
def test_a_sized_fstopo_file_is_declined_when_unverified_files_are_switched_off(bench: Bench) -> None:
    data = b"fstopo geopdf " * 300
    url = bench.pub.put("/fstopo/OR_Mt_Hood.pdf", data)
    bench.list([entry("fstopo", "OR_Mt_Hood.pdf", url, "sized", None, size=len(data))])
    path = bench.tmp / "off.toml"
    path.write_text(config_text(str(bench.root), selection="map_regions = []\nhold_unverified = false"))
    report = run.run(config.load(path), now=bench.clock)
    assert [d["name"] for d in report.declined] == ["OR_Mt_Hood.pdf"]
    assert not (bench.root / "fstopo").exists()


def test_a_sized_file_with_no_listed_size_is_refused_by_name(bench: Bench) -> None:
    bench.list([entry("fstopo", "x.pdf", "https://p/x.pdf", "sized", None, size=None)])
    report = bench.run()
    assert report.exit_code == 1 and "no size" in (report.outcomes[0].reason or "")


def test_an_engine_without_fetch_etag_is_named_not_guessed(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(Fetcher, "fetch_etag", raising=False)
    bench.list([etag_entry(bench)])
    report = bench.run()
    assert report.exit_code == 1 and "no Fetcher.fetch_etag" in (report.outcomes[0].reason or "")
```

Run: `.venv/bin/python -m pytest tests/test_kinds.py -q -x` — Expected: FAIL — `assert {...} == set(KINDS)` (the table lacks `etag`, `sized`, `git-commit`).

- [ ] **Step 2: Add the kinds**

In `src/bunker/checks.py` append to the `KINDS` tuple, after `unverified-fetch`, in this order (the order is asserted):

```python
        CheckKind(
            "sized",
            "fetch_sized",
            None,
            True,
            False,
            "no digest exists (FSTopo files the repository does not pin): the exact size the "
            "engine listed and nothing else; held under hold_unverified, with the engine's own "
            "fetch",
        ),
        CheckKind(
            "etag",
            "fetch_etag",
            None,
            True,
            True,
            "the object's ETag as the repository carries it (US Topo, 3DEP) and the exact size; "
            "an ETag is not always an MD5, so it is compared and never recomputed here",
        ),
        CheckKind(
            "git-commit",
            "git_bundle",
            None,
            False,
            True,
            "the commit id the repository pins; the Bunker clones the repository without "
            "checking anything out, confirms the commit is in it, and bundles it "
            "(bunker.gitbundle); the engine checks the commit again when it clones the bundle",
        ),
```

(the file keeps `unverified-fetch` before `sized`; the asserted order is `unverified-zip`, `unverified-fetch`, `sized`.) Update the module docstring's last paragraph to mention that `etag`, `sized` and `git-commit` arrive with Plan A's engine.

- [ ] **Step 3: Settle the names against the installed Plan A engine**

Run: `.venv/bin/python -c "import hammunition.interface.artifacts as a; print(a.CHECKS)"` on the Plan A checkout.
Expected: a tuple containing every kind in `ALL_KINDS`. If the engine spells a kind differently (for example `etag-sized`), rename it in `checks.py`, `ALL_KINDS`, the tests and the docs rows of Step 9 and re-run `.venv/bin/python -m pytest tests/test_kinds.py -q -k "covers_every_kind or listed_literally or complete"` — Expected: PASS. On the pinned v0.21.0 engine that import has no new kinds and the test passes trivially; that is why it is run here.

- [ ] **Step 4: The run downloads them**

`src/bunker/run.py`, `_download` (after the two `needs_digest` / `needs_size` guards, before `fetcher = Fetcher(...)`):

```python
    if kind.method == "git_bundle":
        raise BackendError(
            f"{artifact.unit}/{artifact.name}: a git-commit artifact is built by bunker.gitbundle, "
            f"never downloaded"
        )
```

and in the `if kind.method == "fetch" and digest is not None:` chain, add before the final `elif digest is not None and artifact.size is not None:`:

```python
    elif kind.method == "fetch_sized" and artifact.size is not None:
        result = method(artifact.url, expected_size=artifact.size)
```

(`fetch_etag` takes the same shape as `fetch_md5` and `fetch_sha1` and falls into that last branch.)

`_matches` (lines 393-422): replace the `if algorithm is None:  # pragma: no cover ...` block with

```python
        rel = held.relative_to(self.root).as_posix()
        if algorithm is None:
            # `etag`: an ETag cannot be recomputed from the bytes, so the record is
            # the only evidence. A copy is current when the record says it was
            # verified against this same ETag and its sidecar still matches.
            return (
                claimed is not None
                and entry.path == rel
                and entry.publisher_check == artifact.check
                and entry.publisher_digest == artifact.digest
            ), False
```

and delete the later duplicate `rel = held.relative_to(self.root).as_posix()` line.

`_order` (673-674): `return [a for a in listing.artifacts if a.check != "git-commit" and (not named or a.unit in named)]`.

Run: `.venv/bin/python -m pytest tests/test_kinds.py -q` — Expected: PASS on the Plan A checkout; the `needs_sheets` tests SKIP on v0.21.0.

- [ ] **Step 5: Write the failing payload tests**

Create `tests/test_payloads.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Software payloads (source tarballs, prebuilt binaries, venv wheels, the Node
tarball, the mapsforge converter tool) are ordinary sha256 artifacts. Nothing
new fetches them; what these tests pin is that their names, which carry ``+``,
``@`` and nested paths, survive the engine's percent-quoting and the server."""

from __future__ import annotations

import urllib.parse

import pytest

from bunker import index
from tests.helpers import entry
from tests.scene import Scene, sha
from tests.test_server import Served

PAYLOADS = [
    ("a2d", "source/a2d-1.2.3.tar.gz", "/src/a2d-1.2.3.tar.gz"),
    ("a2d", "binary/linux-amd64/a2d", "/bin/a2d"),
    ("meshtastic-cli", "venv/wheels/meshtastic-2.5.0+cpu-py3-none-any.whl", "/whl/meshtastic.whl"),
    ("nodejs", "node/node-v22.11.0-linux-x64.tar.xz", "/node/node-v22.11.0-linux-x64.tar.xz"),
    ("mapsforge-tools", "tools/mapsforge-map-writer-0.21.0-jar-with-dependencies.jar", "/jars/w.jar"),
    ("wheelhouse", "pkg@1.0/whl", "/whl/pkg-1.0.whl"),
]


@pytest.fixture
def payloads(scene: Scene) -> dict[tuple[str, str], bytes]:
    data = {(unit, name): f"payload {unit} {name} ".encode() * 40 for unit, name, _ in PAYLOADS}
    listed = scene.entries()
    for unit, name, path in PAYLOADS:
        body = data[unit, name]
        listed.append(entry(unit, name, scene.pub.put(path, body), "sha256", sha(body), size=len(body)))
    scene.list(listed)
    return data


def quoted(unit: str, name: str) -> str:
    """The engine's mirror path: each segment percent-quoted (hammunition.fetch.mirror_url)."""
    return "/" + "/".join(urllib.parse.quote(s, safe="") for s in [unit, *name.split("/")])


def test_every_payload_is_fetched_and_recorded_without_publisher_facts(
    scene: Scene, payloads: dict[tuple[str, str], bytes]
) -> None:
    report = scene.run()
    assert report.exit_code == 0 and report.counts()["fetched"] == 3 + len(PAYLOADS)
    for (unit, name), body in payloads.items():
        stored = scene.entry(unit, name)
        assert stored.sha256 == sha(body) and stored.size == len(body) and stored.status == "current"
        assert (stored.publisher_name, stored.publisher_size, stored.share) == (None, None, "all")
        assert (scene.root / (stored.path or "")).read_bytes() == body


def test_every_payload_is_served_at_its_quoted_mirror_path(
    scene: Scene, payloads: dict[tuple[str, str], bytes]
) -> None:
    scene.run()
    served = Served(scene.root)
    try:
        for (unit, name), body in payloads.items():
            status, _, got = served.request(quoted(unit, name))
            assert (status, got) == (200, body), f"{unit}/{name}"
            assert served.request(quoted(unit, name), "HEAD")[1]["Content-Length"] == str(len(body))
    finally:
        served.httpd.shutdown()
        served.httpd.server_close()


def test_a_payload_that_moves_to_a_new_pin_keeps_one_previous_copy(
    scene: Scene, payloads: dict[tuple[str, str], bytes]
) -> None:
    scene.run()
    unit, name, path = PAYLOADS[0]
    body = b"the next source release " * 50
    listed = [e for e in scene.entries()] + [
        entry(unit, name, scene.pub.put("/src/a2d-1.2.4.tar.gz", body), "sha256", sha(body), size=len(body))
    ]
    scene.list(listed)
    scene.clock.advance(days=2)
    assert scene.run().exit_code == 0
    stored = index.load(scene.root).find(unit, name)
    assert stored is not None and stored.previous is not None and stored.sha256 == sha(body)
```

Run: `.venv/bin/python -m pytest tests/test_payloads.py -q` — Expected: PASS already (no code change is needed for payloads; this task's test pins it). If `test_every_payload_is_served_at_its_quoted_mirror_path` fails on the `+` or `@` name, the server's `unquote` or the route table is wrong: fix there.

- [ ] **Step 6: Write the failing git bundle tests**

Create `tests/test_gitbundle.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Git bundles, built from real repositories in ``tmp_path`` with the real
``git``. The repositories are reached over ``file://``, which the Bunker never
allows by default (only ``https``): the tests name it, as a parameter."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from bunker import gitbundle, index
from bunker.enginelib import BackendError
from bunker.gitbundle import Pin
from tests.helpers import entry
from tests.scene import Scene

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed here")

ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "protocol.file.allow=always", *args],
        cwd=cwd, env=ENV, check=True, capture_output=True, text=True,
    )  # fmt: skip
    return done.stdout.strip()


class Repos:
    def __init__(self, tmp: Path) -> None:
        self.sub = tmp / "sub"
        self.top = tmp / "top"
        for path in (self.sub, self.top):
            path.mkdir()
            git(path, "init", "-q")
        (self.sub / "s.txt").write_text("sub\n")
        git(self.sub, "add", ".")
        git(self.sub, "commit", "-qm", "sub")
        self.sub_commit = git(self.sub, "rev-parse", "HEAD")
        (self.top / "t.txt").write_text("top\n")
        git(self.top, "add", ".")
        git(self.top, "submodule", "add", "-q", "../sub", "libs/sub")
        git(self.top, "commit", "-qm", "top")
        self.top_commit = git(self.top, "rev-parse", "HEAD")

    @property
    def url(self) -> str:
        return self.top.as_uri()


@pytest.fixture
def repos(tmp_path: Path) -> Repos:
    return Repos(tmp_path / "repos")


def pin(repos: Repos, commit: str | None = None) -> Pin:
    commit = commit or repos.top_commit
    return Pin(name=f"toolx@{commit}", url=repos.url, commit=commit, licence="GPL-3.0-or-later")


def test_a_bundle_holds_the_pinned_commit_and_verifies(repos: Repos, tmp_path: Path) -> None:
    built = gitbundle.build(pin(repos), tmp_path / "work", allowed="file")
    assert built.size == built.path.stat().st_size and len(built.sha256) == 64
    clone = tmp_path / "from-bundle"
    git(tmp_path, "clone", "-q", "--no-checkout", str(built.path), str(clone))
    git(clone, "bundle", "verify", str(built.path))
    assert git(clone, "cat-file", "-t", repos.top_commit) == "commit"


def test_submodules_are_found_and_named_under_the_contract(repos: Repos, tmp_path: Path) -> None:
    built = gitbundle.build(pin(repos), tmp_path / "work", allowed="file")
    assert [(s.name, s.commit) for s in built.submodules] == [
        (f"toolx@{repos.top_commit}/libs/sub@{repos.sub_commit}", repos.sub_commit)
    ]
    assert built.submodules[0].url == repos.sub.as_uri()


def test_a_commit_the_repository_does_not_have_is_refused(repos: Repos, tmp_path: Path) -> None:
    with pytest.raises(BackendError, match="does not contain"):
        gitbundle.build(pin(repos, "0" * 40), tmp_path / "work", allowed="file")


@pytest.mark.parametrize("commit", ["main", "abc123", "A" * 40, "0" * 39, "--upload-pack=x"])
def test_only_a_full_commit_id_is_accepted(repos: Repos, tmp_path: Path, commit: str) -> None:
    with pytest.raises(BackendError, match="40-hex"):
        gitbundle.build(pin(repos, commit), tmp_path / "work", allowed="file")


def test_https_is_the_only_protocol_by_default(repos: Repos, tmp_path: Path) -> None:
    with pytest.raises(BackendError, match="not allowed"):
        gitbundle.build(pin(repos), tmp_path / "work")  # the default: https only


def test_an_option_in_the_place_of_a_url_is_refused(tmp_path: Path) -> None:
    hostile = Pin(name="x@" + "a" * 40, url="--upload-pack=touch /tmp/pwned", commit="a" * 40)
    with pytest.raises(BackendError, match="not allowed"):
        gitbundle.build(hostile, tmp_path / "work", allowed="file")
    assert not Path("/tmp/pwned").exists()


def test_git_runs_in_a_clean_environment_with_no_prompt_and_never_checks_out(repos: Repos, tmp_path: Path) -> None:
    seen: list[tuple[list[str], dict[str, str]]] = []

    def spy(argv: Sequence[str], cwd: Path | None, env: Mapping[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
        seen.append((list(argv), dict(env)))
        return gitbundle.run_git(argv, cwd, env, timeout)

    gitbundle.build(pin(repos), tmp_path / "work", run=spy, allowed="file")
    assert seen and all(env["GIT_ALLOW_PROTOCOL"] == "file" for _, env in seen)
    assert all(env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_CONFIG_GLOBAL"] == "/dev/null" for _, env in seen)
    clone = next(a for a, _ in seen if a[0] == "clone")
    assert clone[:3] == ["clone", "--quiet", "--no-checkout"] and "--" in clone, "a URL is never an option"
    assert not any(a[0] == "checkout" for a, _ in seen), "nothing is ever checked out"


def test_run_git_always_points_the_hooks_at_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    def fake(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(gitbundle.subprocess, "run", fake)
    gitbundle.run_git(["status"], None, {}, 5.0)
    assert captured == [["git", "-c", "core.hooksPath=/dev/null", "status"]]


def test_a_missing_git_is_named(repos: Repos, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitbundle, "GIT", "git-that-is-not-installed")
    with pytest.raises(BackendError, match="git was not found"):
        gitbundle.build(pin(repos), tmp_path / "work", allowed="file")


# --- through a run ------------------------------------------------------------


@pytest.fixture
def listed(scene: Scene, repos: Repos, monkeypatch: pytest.MonkeyPatch) -> Repos:
    monkeypatch.setattr(gitbundle, "ALLOWED_PROTOCOLS", "file")
    scene.list(
        [
            *scene.entries(),
            entry(
                "git-bundles", f"toolx@{repos.top_commit}", repos.url, "git-commit", repos.top_commit,
                licence="GPL-3.0-or-later",
            ),  # fmt: skip
        ]
    )
    return repos


def test_a_run_holds_the_bundle_and_its_submodule_and_does_not_rebuild_them(
    scene: Scene, listed: Repos, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = scene.run()
    assert report.exit_code == 0
    assert sorted(o.action for o in report.bundles) == ["fetched", "fetched"]
    top = scene.entry("git-bundles", f"toolx@{listed.top_commit}")
    sub = scene.entry("git-bundles", f"toolx@{listed.top_commit}/libs/sub@{listed.sub_commit}")
    assert (top.publisher_check, top.publisher_digest) == ("git-commit", listed.top_commit)
    assert (sub.publisher_check, sub.publisher_digest) == ("git-commit", listed.sub_commit)
    assert top.licence == sub.licence == "GPL-3.0-or-later"
    for held in (top, sub):
        assert (scene.root / (held.path or "")).stat().st_size == held.size
    calls: list[str] = []
    real = gitbundle.run_git
    monkeypatch.setattr(gitbundle, "run_git", lambda *a, **k: calls.append(a[0][0]) or real(*a, **k))
    scene.clock.advance(hours=1)
    again = scene.run()
    assert [o.action for o in again.bundles] == ["unchanged"] and calls == []


def test_a_bundle_verify_found_damaged_is_rebuilt(scene: Scene, listed: Repos) -> None:
    scene.run()
    held = scene.entry("git-bundles", f"toolx@{listed.top_commit}")
    path = scene.root / (held.path or "")
    path.write_bytes(b"damaged")
    from bunker import verify

    assert verify.verify(scene.cfg(), now=scene.clock).exit_code == 1
    scene.clock.advance(hours=1)
    rebuilt = scene.run()
    assert "fetched" in [o.action for o in rebuilt.bundles]
    assert index.load(scene.root).find("git-bundles", held.name) is not None
    assert path.read_bytes() != b"damaged"


def test_a_pin_the_engine_stops_listing_takes_its_submodules_out_of_the_index(scene: Scene, listed: Repos) -> None:
    scene.run()
    scene.list(scene.entries())
    scene.clock.advance(hours=1)
    report = scene.run()
    assert {d["name"] for d in report.dropped} == {
        f"toolx@{listed.top_commit}",
        f"toolx@{listed.top_commit}/libs/sub@{listed.sub_commit}",
    }
    assert [e for e in index.load(scene.root).artifacts if e.unit == "git-bundles"] == []


def test_a_failing_clone_fails_that_pin_alone_and_the_run_exits_1(scene: Scene, listed: Repos) -> None:
    scene.list(
        [
            *scene.entries(),
            entry("git-bundles", "gone@" + "a" * 40, "file:///nonexistent/repo", "git-commit", "a" * 40),
        ]
    )
    report = scene.run()
    assert report.exit_code == 1 and report.bundles[0].action == "failed"
    assert report.counts()["fetched"] == 3


def test_bundle_names_that_would_leave_the_volume_are_refused(scene: Scene, listed: Repos) -> None:
    scene.list([entry("git-bundles", f"../../etc@{listed.top_commit}", listed.url, "git-commit", listed.top_commit)])
    report = scene.run()
    assert report.bundles[0].action == "failed" and "refusing to store" in (report.bundles[0].reason or "")
    assert not (scene.root.parent / "etc@").exists()
```

Run: `.venv/bin/python -m pytest tests/test_gitbundle.py -q -x` — Expected: FAIL at collection, `ImportError: cannot import name 'gitbundle' from 'bunker'`.

- [ ] **Step 7: Write `src/bunker/gitbundle.py`**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Git pins as bundles.

The one place the Bunker runs a program on something it fetched, so it is as
narrow as git allows: ``git clone --no-checkout`` (no working tree, so no
filter, hook or LFS smudge can run), hooks pointed at ``/dev/null``, no global
or system config, no credential prompt, only the transports named in
``GIT_ALLOW_PROTOCOL`` (``https``), and a URL that is not a transport git would
take as an option. A commit id is the verification: git's object model makes the
bundle hold exactly the pinned commit or the build fails. The engine checks the
commit again when it clones the bundle, and a submodule's gitlink against its own
pin.

Names follow the contract: ``<unit>@<commit>`` and, for each submodule,
``<unit>@<commit>/<path>@<commit>``. A bundle of a pinned commit never changes,
so a held one is rebuilt only if it is missing or ``bunker verify`` marked it
corrupted.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bunker.enginelib import BackendError
from bunker.index import Entry, Index
from bunker.index import save as save_index
from bunker.volume import UnsafeName, artifact_dir, hash_file, install

__all__ = [
    "ALLOWED_PROTOCOLS",
    "MAX_DEPTH",
    "UNIT",
    "Built",
    "BundleOutcome",
    "GitRunner",
    "Pin",
    "build",
    "hold_bundles",
    "run_git",
]

UNIT = "git-bundles"
GIT = "git"
#: The transports git may use for the clone: ``GIT_ALLOW_PROTOCOL``.
ALLOWED_PROTOCOLS = "https"
#: Submodules inside submodules, no deeper than this.
MAX_DEPTH = 4
#: A large repository over a slow link.
GIT_TIMEOUT = 3600.0
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SUBMODULE_KEY = re.compile(r"submodule\.(.+)\.(path|url)")

GitRunner = Callable[
    [Sequence[str], Path | None, Mapping[str, str], float], "subprocess.CompletedProcess[str]"
]


@dataclass(frozen=True)
class Pin:
    name: str
    url: str
    commit: str
    licence: str = ""


@dataclass(frozen=True)
class Built:
    path: Path
    sha256: str
    size: int
    submodules: tuple[Pin, ...]


@dataclass
class BundleOutcome:
    name: str
    action: str
    """``fetched``, ``unchanged`` or ``failed``."""
    reason: str | None = None


def _env(allowed: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/tmp",  # noqa: S108 - git wants one; the config files are switched off below
        "LC_ALL": "C",
        "GIT_ALLOW_PROTOCOL": allowed,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
    }


def run_git(
    argv: Sequence[str], cwd: Path | None, env: Mapping[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - an argv list; git is looked up on the image's PATH
            [GIT, "-c", "core.hooksPath=/dev/null", *argv],
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise BackendError("git was not found; install git (the image has it)") from None
    except subprocess.TimeoutExpired:
        raise BackendError(f"git {argv[0]} did not finish within {timeout:g} s") from None


def _ok(done: subprocess.CompletedProcess[str], what: str) -> str:
    if done.returncode != 0:
        raise BackendError(f"{what} failed (git exit {done.returncode}): {done.stderr.strip()[-300:]}")
    return done.stdout


def _resolve(parent: str, url: str) -> str:
    """A submodule URL as git reads it: relative ones are against the parent's."""
    if url.startswith(("./", "../")):
        return urljoin(parent.rstrip("/") + "/", url)
    return url


def _submodules(pin: Pin, clone: Path, run: GitRunner, env: Mapping[str, str]) -> tuple[Pin, ...]:
    tree = _ok(run(["ls-tree", "-r", "-z", pin.commit], clone, env, 120.0), "ls-tree")
    links: list[tuple[str, str]] = []
    for record in tree.split("\0"):
        meta, _, path = record.partition("\t")
        fields = meta.split(" ")
        if len(fields) == 3 and fields[0] == "160000":
            links.append((path, fields[2]))
    if not links:
        return ()
    declared = _ok(
        run(
            ["config", "-z", "--blob", f"{pin.commit}:.gitmodules", "--get-regexp",
             r"^submodule\..*\.(path|url)$"],
            clone, env, 60.0,
        ),
        f"reading .gitmodules at {pin.commit}",
    )  # fmt: skip
    by_name: dict[str, dict[str, str]] = {}
    for item in declared.split("\0"):
        key, _, value = item.partition("\n")
        found = _SUBMODULE_KEY.fullmatch(key)
        if found:
            by_name.setdefault(found.group(1), {})[found.group(2)] = value
    urls = {v["path"]: v["url"] for v in by_name.values() if "path" in v and "url" in v}
    out: list[Pin] = []
    for path, sha in links:
        if path not in urls:
            raise BackendError(f"{pin.name}: the submodule at {path} has no url in .gitmodules")
        name = f"{pin.name}/{path}@{sha}"
        try:
            artifact_dir(Path("/"), UNIT, name)
        except UnsafeName as exc:
            raise BackendError(str(exc)) from None
        out.append(Pin(name, _resolve(pin.url, urls[path]), sha, pin.licence))
    return tuple(out)


def build(
    pin: Pin, workdir: Path, *, run: GitRunner = run_git, allowed: str | None = None
) -> Built:
    """Clone *pin* without a checkout, confirm the commit, and bundle it."""
    protocols = ALLOWED_PROTOCOLS if allowed is None else allowed
    if not _COMMIT.fullmatch(pin.commit):
        raise BackendError(f"{pin.name}: {pin.commit!r} is not a full 40-hex commit id")
    if urlsplit(pin.url).scheme not in protocols.split(":") or pin.url.startswith("-"):
        raise BackendError(
            f"{pin.name}: {pin.url!r} uses a transport that is not allowed here (only {protocols})"
        )
    env = _env(protocols)
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    clone, out = workdir / "clone", workdir / "out.bundle"
    _ok(
        run(["clone", "--quiet", "--no-checkout", "--no-tags", "--", pin.url, str(clone)], None, env, GIT_TIMEOUT),
        f"cloning {pin.url}",
    )
    found = _ok(run(["rev-parse", "--verify", f"{pin.commit}^{{commit}}"], clone, env, 60.0), "rev-parse")
    if found.strip() != pin.commit:
        raise BackendError(f"{pin.url} does not contain commit {pin.commit}")
    _ok(run(["update-ref", "refs/bunker/pin", pin.commit], clone, env, 60.0), "update-ref")
    _ok(run(["bundle", "create", str(out), "--all"], clone, env, GIT_TIMEOUT), "git bundle create")
    _ok(run(["bundle", "verify", str(out)], clone, env, 600.0), "git bundle verify")
    digest, _ = hash_file(out)
    return Built(out, digest, out.stat().st_size, _submodules(pin, clone, run, env))


def _record(idx: Index, pin: Pin, built: Built, stamp: str, path: str) -> Entry:
    entry = idx.find(UNIT, pin.name)
    if entry is None:
        entry = Entry(
            unit=UNIT, name=pin.name, path=None, sha256=None, size=None, publisher_check="git-commit",
            publisher_digest=None, publisher_url=pin.url, licence=pin.licence, fetched=None,
            verified=None, status="failed", reason="not built yet", previous=None,
        )  # fmt: skip
        idx.artifacts.append(entry)
    entry.path, entry.sha256, entry.size = path, built.sha256, built.size
    entry.publisher_digest, entry.publisher_url, entry.licence = pin.commit, pin.url, pin.licence
    entry.fetched = entry.verified = stamp
    entry.status, entry.reason, entry.previous = "current", None, None
    return entry


def _fail(idx: Index, pin: Pin, reason: str) -> None:
    entry = idx.find(UNIT, pin.name)
    if entry is None:
        idx.artifacts.append(
            Entry(
                unit=UNIT, name=pin.name, path=None, sha256=None, size=None, publisher_check="git-commit",
                publisher_digest=None, publisher_url=pin.url, licence=pin.licence, fetched=None,
                verified=None, status="failed", reason=reason, previous=None,
            )  # fmt: skip
        )
    else:
        entry.status, entry.reason = "failed", reason


def _hold(
    root: Path, idx: Index, pin: Pin, stamp: str, run: GitRunner, allowed: str | None, depth: int
) -> list[BundleOutcome]:
    entry = idx.find(UNIT, pin.name)
    if (
        entry is not None
        and entry.path
        and (root / entry.path).is_file()
        and entry.status != "corrupted"
        and entry.publisher_digest == pin.commit
    ):
        return [BundleOutcome(pin.name, "unchanged")]
    work = root / ".incoming" / UNIT / f"{os.getpid()}-{depth}"
    try:
        built = build(pin, work, run=run, allowed=allowed)

        def commit(path: str, previous: str | None) -> None:
            _record(idx, pin, built, stamp, path)

        install(
            root, UNIT, pin.name, built.path, f"{pin.name.rsplit('/', 1)[-1]}.bundle", built.sha256,
            keep_previous=False, current=entry.path if entry else None, commit=commit,
        )  # fmt: skip
        save_index(root, idx, generated=stamp)
    except (BackendError, OSError, UnsafeName) as exc:
        shutil.rmtree(work, ignore_errors=True)
        reason = str(exc).strip()
        _fail(idx, pin, reason)
        return [BundleOutcome(pin.name, "failed", reason)]
    shutil.rmtree(work, ignore_errors=True)
    outcomes = [BundleOutcome(pin.name, "fetched")]
    for sub in built.submodules:
        if depth + 1 > MAX_DEPTH:
            outcomes.append(BundleOutcome(sub.name, "failed", f"submodules nested deeper than {MAX_DEPTH}"))
        else:
            outcomes += _hold(root, idx, replace(sub, licence=pin.licence), stamp, run, allowed, depth + 1)
    return outcomes


def hold_bundles(
    root: Path,
    idx: Index,
    pins: Sequence[Pin],
    *,
    stamp: str,
    run: GitRunner | None = None,
    allowed: str | None = None,
) -> list[BundleOutcome]:
    """Hold a bundle for every pin and for each of its submodules. A pin that
    fails fails alone: its previous bundle, if any, keeps serving."""
    runner = run if run is not None else run_git
    outcomes: list[BundleOutcome] = []
    for pin in pins:
        outcomes += _hold(root, idx, pin, stamp, runner, allowed, 0)
    return outcomes
```

Two details the code above relies on: `hold_bundles` reads `run_git` at call time (the `run or run_git` form), which is what lets the "does not rebuild" test replace `gitbundle.run_git`; and `hash_file` returns `(sha256, md5)`.

- [ ] **Step 8: Hold bundles in the run**

`src/bunker/run.py`: `from bunker import gitbundle, inputs, publish, signing, statuspage` and `from bunker.gitbundle import BundleOutcome`. `RunReport`: add `bundles: list[BundleOutcome] = field(default_factory=list)`; `exit_code` adds `or any(o.action == "failed" for o in self.bundles)`; `as_dict` adds `"bundles": [asdict(o) for o in self.bundles],`; `summary_lines` adds `for o in self.bundles: if o.action == "failed": lines.append(f"  failed bundle: {o.name}: {o.reason}")`. In `run()`, after the inputs block:

```python
        if not units or gitbundle.UNIT in units:
            pins = [
                gitbundle.Pin(a.name, a.url, a.digest or "", a.licence)
                for a in got.artifacts
                if a.check == "git-commit"
            ]
            report.bundles = gitbundle.hold_bundles(root, idx, pins, stamp=state.stamp)
```

and add `known.add(gitbundle.UNIT)` next to the `inputs` line from Task 4. `_drop` (628-648): add before the `kept` list

```python
    bundles = {a.name for a in listing.artifacts if a.check == "git-commit"}
```

and extend the keep condition with `or (e.unit == gitbundle.UNIT and e.name.split("/", 1)[0] in bundles)`. `sweep_incoming` (570-586): before `return removed` add `shutil.rmtree(incoming / gitbundle.UNIT, ignore_errors=True)  # a killed build's scratch clones` (and `import shutil`).

`Dockerfile`: add `git` to the apt list. `tests/test_packaging.py::test_the_image_has_the_signing_tools` gains `"git"` in its tuple (rename it `test_the_image_has_the_tools_it_runs`).

- [ ] **Step 9: Status page, docs and the invariant**

`src/bunker/statuspage.py` lines 150-170: replace the `zipped`/`fetched` flags and their two sentences with

```python
        zipped = any(KINDS[e.publisher_check].zip_structure for e in unverified)
        snapshots = any(e.publisher_check == "unverified-fetch" for e in unverified)
        sheets = any(e.publisher_check == "sized" for e in unverified)
        ...
        if snapshots:
            parts.append("For the repeater lists, only the size and the date fetched are kept. ")
        if sheets:
            parts.append("For the FSTopo sheets, only the size the publisher listed was checked. ")
```

and add to `tests/test_statuspage.py` a case with one `sized` entry asserting `"FSTopo sheets"` is in the page and `"repeater lists"` is not. `README.md` table (73-79) and `docs/reference.md` table (102-111): add rows `| \`sized\` | ... | \`Fetcher.fetch_sized\` |`, `| \`etag\` | ... | \`Fetcher.fetch_etag\` |`, `| \`git-commit\` | the commit id the repository pins; built by the Bunker with git, not downloaded | \`bunker.gitbundle\` |` (the docs test requires a row for each kind: ``| `kind` |`` at the start of a line). In `docs/reference.md` add a short section after *Check kinds*: "Git bundles": the names, that the Bunker runs `git clone --no-checkout --no-tags`, `git bundle create --all` and `git bundle verify` with hooks off, no config, no prompt and only `https`; that a submodule is found from the gitlinks and `.gitmodules` at the pinned commit and held as `<unit>@<commit>/<path>@<commit>`; that a held bundle is rebuilt only if missing or marked corrupted. `CLAUDE.md` invariant 5 becomes: "**Nothing downloaded is executed, unpacked or parsed** beyond hashing, bar the engine's own structure check of an `unverified-zip` ... and git pins: the Bunker runs `git clone --no-checkout` and `git bundle` on a pinned repository, with hooks off, no config files, no prompt and `https` only, and never checks anything out (`bunker.gitbundle`)." Make the same change to `README.md` lines 124-126 and `docs/guide.md` line 295. `CHANGELOG.md`: "- Sheets, payloads and git bundles: check kinds `etag` and `sized` (US Topo, 3DEP, FSTopo), software payloads pinned like any sha256 artifact (names with `+`, `@` and nested paths tested through the server), and git pins held as bundles built with `git clone --no-checkout` and `git bundle create --all`, submodules included, under `git-bundles/<unit>@<commit>`."

- [ ] **Step 10: Run, falsify, commit**

Run: `.venv/bin/python -m pytest -q -W error::DeprecationWarning; echo "exit=$?"` — Expected: `exit=0` (the `needs_sheets` tests skip on an engine without `fetch_etag`, and everything in `test_gitbundle.py` skips where `git` is missing). Regenerate goldens (`run.json` gains `"bundles": []`) with `BUNKER_UPDATE_GOLDENS=1 .venv/bin/python -m pytest tests/test_cli.py -q` and read the diff.

Falsify: in `build`, delete the `urlsplit(...).scheme not in protocols.split(":") or ...` clause and run `.venv/bin/python -m pytest tests/test_gitbundle.py -q -k "option_in_the_place or https_is_the_only"` — Expected: both FAIL (git is handed the text and fails with its own message, not "not allowed"); restore it. Delete `"--"` from the clone argv and run `-k clean_environment` — Expected: FAILS on `"--" in clone`; restore.

Run: `make check; echo "exit=$?"` — Expected: `exit=0`.

```bash
git add src/bunker/gitbundle.py src/bunker/checks.py src/bunker/run.py src/bunker/statuspage.py Dockerfile CLAUDE.md README.md docs/reference.md docs/guide.md CHANGELOG.md tests/test_gitbundle.py tests/test_payloads.py tests/test_kinds.py tests/test_statuspage.py tests/test_packaging.py tests/golden
git commit -m "New fetch kinds: etag and sized sheets, payload names, git bundles

etag and sized check kinds for US Topo, 3DEP and FSTopo; payload names with +,
@ and nested paths pinned through the server; git pins held as bundles built
with git clone --no-checkout and git bundle create, submodules included, with
hooks off, no config, no prompt and https only."
```

### Task 6: Server routes and group mode

The server learns the catalogue's other files: `/catalogue.json` (and `/index.json` as its alias), `/catalogue.sig.d/<n>.sig`, `/inputs/<kind>/<name>`. In `group` mode, `bunker enrol add|list|remove` keeps a list of enrolments on the volume and the server hands the bytes of an `owner:<id>` artifact only to a request whose `X-Hammunition-Enrolment` header is that id and a current enrolment; everyone else gets the same 404 as for a file that does not exist. Bring-your-own kinds (anything under `hold_unverified`) default to `owner:<id>` of the enrolment named by `bunker.byo_owner`, and to an owner nobody can be (`owner:admin`) when none is named. This is a sharing filter, not access control, and the docs say so.

**Files:**
- Create: `src/bunker/enrol.py`, `tests/test_enrol.py`
- Modify: `src/bunker/config.py` (`BunkerConfig`, `_bunker`, `_KNOWN`), `src/bunker/server.py` (`Target` 48-52, `Routes._build` as rewritten in Task 1, `Handler._serve` 165-219), `src/bunker/publish.py`, `src/bunker/cli.py` (`COMMANDS`, `parser`), `docs/reference.md` (Commands, Configuration, HTTP 207-222), `docs/guide.md`, `config.example.toml`, `CHANGELOG.md`
- Test: `tests/test_server.py`, `tests/test_enrol.py`, `tests/test_config.py`, `tests/test_publish.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `bunker.checks.is_unverified(check: str) -> bool`, `bunker.index.Index`, `bunker.volume.RunLock`, `bunker.publish.publish`.
- Produces:
  - `bunker.config.BunkerConfig(name: str = "bunker", mode: str = "personal", byo_owner: str | None = None)`
  - `bunker.enrol`: `FILE = ".enrolments.json"`, `ADMIN_OWNER = "owner:admin"`, `class EnrolError(Exception)`, `@dataclass(frozen=True) class Enrolment(id: str, label: str, added: str)`, `load(root: Path) -> list[Enrolment]` (strict), `load_lenient(root: Path) -> list[Enrolment]` (empty on any error: fail closed), `add(root: Path, label: str, now: str) -> Enrolment`, `remove(root: Path, ref: str) -> Enrolment`, `default_share(mode: str, check: str, owner_label: str | None, enrolments: Sequence[Enrolment]) -> str`
  - `bunker.server.ENROLMENT_HEADER = "X-Hammunition-Enrolment"`; `Target(path: str, content_type: str, owner: str | None = None)`; `Routes.may_read(owner: str, header: str | None) -> bool`
  - CLI: `bunker enrol add LABEL`, `bunker enrol list`, `bunker enrol remove REF`; the `enrol` document (`action`, `enrolment`, `enrolments`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_enrol.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bunker import cli, config, enrol, index, publish
from bunker.enrol import Enrolment
from bunker.index import Index
from tests.helpers import config_text
from tests.test_index import an_entry

NOW = "2026-10-07T12:00:00Z"


def test_an_enrolment_gets_a_random_id_and_the_file_is_private(tmp_path: Path) -> None:
    one = enrol.add(tmp_path, "alice-laptop", NOW)
    two = enrol.add(tmp_path, "bob-laptop", NOW)
    assert one.id != two.id and one.id.startswith("e-") and len(one.id) == 18
    assert enrol.load(tmp_path) == [one, two]
    assert oct((tmp_path / enrol.FILE).stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("label", ["", " ", "a" * 65, "line\nbreak", "tab\t", "<script>", "../x"])
def test_a_label_that_is_not_plain_text_is_refused(tmp_path: Path, label: str) -> None:
    with pytest.raises(enrol.EnrolError, match="label"):
        enrol.add(tmp_path, label, NOW)


def test_a_label_is_unique(tmp_path: Path) -> None:
    enrol.add(tmp_path, "alice-laptop", NOW)
    with pytest.raises(enrol.EnrolError, match="already"):
        enrol.add(tmp_path, "alice-laptop", NOW)


def test_remove_takes_an_id_or_a_label_and_names_what_it_did_not_find(tmp_path: Path) -> None:
    one = enrol.add(tmp_path, "alice-laptop", NOW)
    two = enrol.add(tmp_path, "bob-laptop", NOW)
    assert enrol.remove(tmp_path, one.id) == one
    assert enrol.remove(tmp_path, "bob-laptop") == two
    with pytest.raises(enrol.EnrolError, match="no enrolment"):
        enrol.remove(tmp_path, "bob-laptop")


def test_a_damaged_file_is_an_error_strictly_and_nobody_leniently(tmp_path: Path) -> None:
    (tmp_path / enrol.FILE).write_text("{not json")
    with pytest.raises(enrol.EnrolError, match=r"\.enrolments\.json"):
        enrol.load(tmp_path)
    assert enrol.load_lenient(tmp_path) == []


@pytest.mark.parametrize(
    ("mode", "check", "owner", "expected"),
    [
        ("personal", "unverified-fetch", "alice", "all"),
        ("group", "sha256", "alice", "all"),
        ("group", "md5-publisher", "alice", "all"),
        ("group", "unverified-fetch", "alice", "owner:e-aaaaaaaaaaaaaaaa"),
        ("group", "unverified-zip", "alice", "owner:e-aaaaaaaaaaaaaaaa"),
        ("group", "sized", "alice", "owner:e-aaaaaaaaaaaaaaaa"),
        ("group", "unverified-fetch", None, "owner:admin"),
        ("group", "unverified-fetch", "nobody-by-that-name", "owner:admin"),
    ],
)
def test_the_default_share(mode: str, check: str, owner: str | None, expected: str) -> None:
    people = [Enrolment("e-aaaaaaaaaaaaaaaa", "alice", NOW)]
    assert enrol.default_share(mode, check, owner, people) == expected


def cfg_for(tmp_path: Path, bunker_table: str) -> config.Config:
    path = tmp_path / "bunker.toml"
    path.write_text(config_text(str(tmp_path / "vol"), extra=bunker_table))
    return config.load(path)


def held_snapshot() -> Index:
    snapshot = an_entry(unit="repeater-snapshots", name="etcc.csv", publisher_check="unverified-fetch", publisher_digest=None)
    return Index(engine_version="0.22.0", artifacts=[an_entry(), snapshot])


def test_publish_applies_the_default_share_and_a_removed_owner_falls_back_to_admin(tmp_path: Path) -> None:
    cfg = cfg_for(tmp_path, '[bunker]\nmode = "group"\nbyo_owner = "alice"\n')
    alice = enrol.add(cfg.storage.root, "alice", NOW)
    idx = held_snapshot()
    publish.publish(cfg, idx, generated=NOW)
    shares = {e.name: e.share for e in index.load(cfg.storage.root).artifacts}
    assert shares == {"north-america/us/vermont": "all", "etcc.csv": f"owner:{alice.id}"}
    assert json.loads((cfg.storage.root / index.FILE).read_text())["bunker"]["mode"] == "group"
    enrol.remove(cfg.storage.root, "alice")
    publish.publish(cfg, idx, generated="2026-10-08T12:00:00Z")
    assert {e.name: e.share for e in index.load(cfg.storage.root).artifacts}["etcc.csv"] == "owner:admin"


def test_a_personal_bunker_shares_everything_whatever_an_old_index_said(tmp_path: Path) -> None:
    cfg = cfg_for(tmp_path, "")
    idx = held_snapshot()
    idx.artifacts[1].share = "owner:e-0123456789abcdef"
    publish.publish(cfg, idx, generated=NOW)
    assert {e.share for e in index.load(cfg.storage.root).artifacts} == {"all"}


# --- the command ------------------------------------------------------------


def run_cli(cfg: config.Config, *argv: str) -> int:
    return cli.main([*argv, "--config", str(cfg.path)])


def test_enrol_add_prints_the_id_and_list_shows_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = cfg_for(tmp_path, '[bunker]\nmode = "group"\n')
    assert run_cli(cfg, "enrol", "add", "alice-laptop") == 0
    [only] = enrol.load(cfg.storage.root)
    assert only.id in capsys.readouterr().out
    assert run_cli(cfg, "enrol", "list") == 0
    assert "alice-laptop" in capsys.readouterr().out
    assert run_cli(cfg, "enrol", "list", "--json") == 0
    document = json.loads(capsys.readouterr().out)
    assert document["kind"] == "enrol" and document["enrolments"][0]["label"] == "alice-laptop"


def test_enrol_is_refused_on_a_personal_bunker(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = cfg_for(tmp_path, "")
    assert run_cli(cfg, "enrol", "add", "alice-laptop") == 2
    assert "personal" in capsys.readouterr().err and enrol.load(cfg.storage.root) == []


def test_enrol_remove_republishes_and_is_locked_out_by_a_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from bunker.volume import RunLock

    cfg = cfg_for(tmp_path, '[bunker]\nmode = "group"\n')
    run_cli(cfg, "enrol", "add", "alice-laptop")
    with RunLock(cfg.storage.root):
        assert run_cli(cfg, "enrol", "remove", "alice-laptop") == 125
    assert len(enrol.load(cfg.storage.root)) == 1, "nothing changed while a run held the volume"
    assert run_cli(cfg, "enrol", "remove", "alice-laptop") == 0
    assert enrol.load(cfg.storage.root) == []
```

(`from tests.test_index import an_entry` is imported at the top; `an_entry` already builds `north-america/us/vermont`.)

Append to `tests/test_config.py`:

```python
def test_byo_owner_is_a_label_or_unset(tmp_path: Path) -> None:
    assert config.load(write(tmp_path, '[bunker]\nbyo_owner = "alice-laptop"\n')).bunker.byo_owner == "alice-laptop"
    assert config.load(write(tmp_path, "")).bunker.byo_owner is None
    with pytest.raises(ConfigError, match="bunker.byo_owner"):
        config.load(write(tmp_path, '[bunker]\nbyo_owner = ""\n'))
```

Append to `tests/test_server.py`:

```python
from bunker import enrol
from bunker.server import ENROLMENT_HEADER

SNAPSHOT = b"callsign,frequency\n" * 20


def group_scene(scene: Scene) -> tuple[Served, str, str]:
    """A group Bunker holding one owned repeater snapshot and the public data."""
    scene.extra += '[bunker]\nmode = "group"\nbyo_owner = "alice"\n'
    scene.root.mkdir(parents=True, exist_ok=True)
    alice = enrol.add(scene.root, "alice", "2026-09-29T00:00:00Z")
    enrol.add(scene.root, "bob", "2026-09-29T00:00:00Z")
    url = scene.pub.put("/snap/etcc.csv", SNAPSHOT)
    scene.list([*scene.entries(), entry("repeater-snapshots", "etcc.csv", url, "unverified-fetch", None, size=len(SNAPSHOT))])
    assert scene.run().exit_code == 0
    return Served(scene.root), alice.id, enrol.load(scene.root)[1].id


def test_owned_bytes_need_the_matching_enrolment_in_group_mode(scene: Scene) -> None:
    served, alice, bob = group_scene(scene)
    try:
        path = "/repeater-snapshots/etcc.csv"
        assert served.request(path)[0] == 404
        assert served.request(path, headers={ENROLMENT_HEADER: bob})[0] == 404
        assert served.request(path, headers={ENROLMENT_HEADER: "e-ffffffffffffffff"})[0] == 404
        assert served.request(path, headers={ENROLMENT_HEADER: alice + " "})[0] == 404
        status, _, body = served.request(path, headers={ENROLMENT_HEADER: alice})
        assert (status, body) == (200, SNAPSHOT)
        assert served.request(path, "HEAD", {ENROLMENT_HEADER: alice})[0] == 200
        assert served.request(path, "HEAD")[0] == 404
        # the public data does not care
        assert served.request(f"/osm-regions/{REGION}")[0] == 200
    finally:
        served.httpd.shutdown()
        served.httpd.server_close()


def test_the_volume_path_and_the_sidecar_of_owned_bytes_are_gated_too(scene: Scene) -> None:
    served, alice, _ = group_scene(scene)
    try:
        held = scene.entry("repeater-snapshots", "etcc.csv")
        assert held.path is not None
        for path in ("/" + held.path, "/" + held.path + ".sha256"):
            assert served.request(path)[0] == 404, path
            assert served.request(path, headers={ENROLMENT_HEADER: alice})[0] == 200, path
    finally:
        served.httpd.shutdown()
        served.httpd.server_close()


def test_a_removed_enrolment_loses_the_bytes_at_once(scene: Scene) -> None:
    served, alice, _ = group_scene(scene)
    try:
        path = "/repeater-snapshots/etcc.csv"
        assert served.request(path, headers={ENROLMENT_HEADER: alice})[0] == 200
        enrol.remove(scene.root, "alice")
        assert served.request(path, headers={ENROLMENT_HEADER: alice})[0] == 404
    finally:
        served.httpd.shutdown()
        served.httpd.server_close()


def test_a_personal_bunker_ignores_share(scene: Scene, served: Served) -> None:
    raw = json.loads((scene.root / "catalogue.json").read_text())
    raw["artifacts"][0]["share"] = "owner:e-0123456789abcdef"
    (scene.root / "catalogue.json").write_text(json.dumps(raw))
    assert served.request("/country-files/cty.dat")[0] == 200


def test_the_catalogue_its_signatures_and_the_inputs_are_served(scene: Scene) -> None:
    url = scene.pub.put("/geofabrik/europe/monaco.poly", b"monaco\n1\n2 3\nEND\nEND\n")
    scene.list(inputs=[input_item("region-outline", "europe/monaco", "europe/monaco.poly", url=url)])
    scene.run()
    served = Served(scene.root)
    try:
        catalogue = (scene.root / "catalogue.json").read_bytes()
        assert served.request("/catalogue.json")[2] == catalogue == served.request("/index.json")[2]
        assert served.request("/catalogue.sig.d/1.sig")[2] == (scene.root / "catalogue.sig.d/1.sig").read_bytes()
        assert served.request("/inputs/region-outline/europe/monaco.poly")[2] == b"monaco\n1\n2 3\nEND\nEND\n"
        assert served.request("/inputs/region-outline/europe/monaco.poly.sha256")[0] == 200
        assert served.request("/catalogue.json")[1]["Cache-Control"] == "no-cache"
    finally:
        served.httpd.shutdown()
        served.httpd.server_close()


@pytest.mark.parametrize(
    "path",
    [
        "/.keys/keys.json",
        "/.keys/",
        "/.state.json",
        "/.enrolments.json",
        "/.serial",
        "/.publish.lock",
        "/.publish.tmp/catalogue.json",
        "/catalogue.sig.d/",
        "/catalogue.sig.d/9.sig",
        "/catalogue.sig.d/../.keys/keys.json",
        "/inputs/",
        "/inputs/region-outline/europe/not-listed.poly",
    ],
)
def test_nothing_the_catalogue_does_not_name_is_served(scene: Scene, served: Served, path: str) -> None:
    signing_dir = scene.root / "catalogue.sig.d"
    (signing_dir / "9.sig").write_bytes(b"a stray signature file")
    (scene.root / ".enrolments.json").write_text("{}")
    (scene.root / "inputs/region-outline/europe").mkdir(parents=True, exist_ok=True)
    (scene.root / "inputs/region-outline/europe/not-listed.poly").write_bytes(b"stray")
    assert served.request(path)[0] == 404
```

(`input_item` from `tests.helpers`, `entry` already imported by the file or add it.)

Run: `.venv/bin/python -m pytest tests/test_enrol.py tests/test_server.py tests/test_config.py -q -x` — Expected: FAIL at collection, `ImportError: cannot import name 'enrol' from 'bunker'`.

- [ ] **Step 2: `byo_owner` in the config**

`src/bunker/config.py`: `"bunker": ("name", "mode", "byo_owner"),` in `_KNOWN`; `BunkerConfig` gains `byo_owner: str | None = None` with the docstring "The enrolment label that owns what a group Bunker holds on behalf of nobody in particular (anything under ``hold_unverified``); unset or unknown, those artifacts belong to no one (``owner:admin``)"; `_bunker` ends with:

```python
    owner = table.get("byo_owner")
    if owner is not None and (not isinstance(owner, str) or not owner.strip()):
        raise ConfigError("bunker.byo_owner must be the label of an enrolment (`bunker enrol list`)")
    return BunkerConfig(name=name, mode=_choice(table.get("mode", "personal"), "bunker.mode", MODES), byo_owner=owner)
```

- [ ] **Step 3: `bunker.enrol`**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enrolments: who a group Bunker shares ``owner:`` artifacts with.

An enrolment is an id the Bunker hands to a laptop's operator (``bunker enrol
add LABEL``); the laptop sends it as ``X-Hammunition-Enrolment`` and the server
answers an ``owner:<id>`` artifact only to that id. **This is a sharing filter,
not access control.** The id travels in clear over plain HTTP, anyone on the
LAN who learns it can send it, and the Bunker holds public data and its
operators' own downloads: nothing secret belongs on it.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from bunker.checks import is_unverified
from bunker.volume import write_atomic

__all__ = [
    "ADMIN_OWNER",
    "FILE",
    "EnrolError",
    "Enrolment",
    "add",
    "default_share",
    "load",
    "load_lenient",
    "remove",
]

FILE = ".enrolments.json"
#: Owner of what a group Bunker holds on behalf of nobody in particular and
#: has no enrolment to give it to. No laptop can hold this id (theirs are ``e-<hex>``).
ADMIN_OWNER = "owner:admin"
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")


class EnrolError(Exception):
    """An enrolment cannot be added, removed or read."""


@dataclass(frozen=True)
class Enrolment:
    id: str
    label: str
    added: str


def load(root: Path) -> list[Enrolment]:
    path = root / FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise EnrolError(f"{path} cannot be read ({exc}); move it aside to start the list again") from None
    items = raw.get("enrolments") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not all(
        isinstance(i, dict) and all(isinstance(i.get(k), str) for k in ("id", "label", "added")) for i in items
    ):
        raise EnrolError(f"{path} is not a list of enrolments; move it aside to start the list again")
    return [Enrolment(i["id"], i["label"], i["added"]) for i in items]


def load_lenient(root: Path) -> list[Enrolment]:
    """The enrolments, or none at all if the file cannot be read: the server and
    the share rule fail closed rather than guess."""
    try:
        return load(root)
    except EnrolError:
        return []


def _save(root: Path, enrolments: Sequence[Enrolment]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"version": 1, "enrolments": [asdict(e) for e in enrolments]}, indent=2) + "\n"
    write_atomic(root / FILE, text.encode("utf-8"))
    os.chmod(root / FILE, 0o600)


def add(root: Path, label: str, now: str) -> Enrolment:
    if not _LABEL.fullmatch(label) or label != label.strip():
        raise EnrolError(
            "an enrolment label is 1 to 64 letters, digits, spaces, dots, dashes or underscores, "
            "starting with a letter or digit (the label is for you; the id is what the laptop sends)"
        )
    existing = load(root)
    if any(e.label == label for e in existing):
        raise EnrolError(f"{label!r} is already enrolled; remove it first, or pick another label")
    enrolment = Enrolment(f"e-{secrets.token_hex(8)}", label, now)
    _save(root, [*existing, enrolment])
    return enrolment


def remove(root: Path, ref: str) -> Enrolment:
    existing = load(root)
    found = next((e for e in existing if ref in (e.id, e.label)), None)
    if found is None:
        raise EnrolError(f"no enrolment has the id or label {ref!r} (`bunker enrol list`)")
    _save(root, [e for e in existing if e is not found])
    return found


def default_share(
    mode: str, check: str, owner_label: str | None, enrolments: Sequence[Enrolment]
) -> str:
    """What a group Bunker shares by default. Public data is ``all``; what the
    Bunker holds on nobody's behalf in particular (anything under
    ``hold_unverified``: the register, the repeater lists, a bring-your-own
    export) goes to the owner named in the config, and to no one if that name
    is unset or no longer enrolled. A personal Bunker shares everything."""
    if mode != "group" or not is_unverified(check):
        return "all"
    owner = next((e for e in enrolments if e.label == owner_label), None) if owner_label else None
    return f"owner:{owner.id}" if owner is not None else ADMIN_OWNER
```

- [ ] **Step 4: Apply the shares when publishing**

`src/bunker/publish.py`: `from bunker import enginelib, enrol, index, signing`, and in `publish` after `idx.name, idx.mode = ...`:

```python
    enrolments = enrol.load_lenient(root)
    for entry in idx.artifacts:
        entry.share = enrol.default_share(
            cfg.bunker.mode, entry.publisher_check, cfg.bunker.byo_owner, enrolments
        )
```

- [ ] **Step 5: The server**

`src/bunker/server.py`: `import hmac`, `import re`, `from bunker import enrol`, then

```python
ENROLMENT_HEADER = "X-Hammunition-Enrolment"
_SIGNATURE = re.compile(r"catalogue\.sig\.d/[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.sig")


@dataclass(frozen=True)
class Target:
    path: str
    """Relative to the volume root."""
    content_type: str
    owner: str | None = None
    """An enrolment id: only a request that sends it is answered."""
```

In `Routes.__init__` add `self._enrol_stamp: tuple[int, int, int] | None = None` and `self._enrolled: frozenset[str] = frozenset()`. In `_build`, after the artifacts loop (inside, replace the three `Target` constructions) use:

```python
        group = isinstance(raw, dict) and isinstance(raw.get("bunker"), dict) and raw["bunker"].get("mode") == "group"
        ...
            share = item.get("share")
            owner = share[len("owner:") :] if group and isinstance(share, str) and share.startswith("owner:") else None
            data = Target(path, "application/octet-stream", owner)
            routes.setdefault(f"{unit}/{name}", data)
            routes.setdefault(path, data)
            routes.setdefault(path + SIDECAR, Target(path + SIDECAR, "text/plain; charset=utf-8", owner))
```

and after the loop:

```python
        signers = raw.get("signers") if isinstance(raw, dict) else None
        for signer in signers if isinstance(signers, list) else []:
            signature = signer.get("signature") if isinstance(signer, dict) else None
            if isinstance(signature, str) and _SIGNATURE.fullmatch(signature):
                routes.setdefault(signature, Target(signature, "application/octet-stream"))
        held = raw.get("inputs") if isinstance(raw, dict) else None
        for item in held if isinstance(held, list) else []:
            if not isinstance(item, dict):
                continue
            kind, name, path = item.get("kind"), item.get("name"), item.get("path")
            if isinstance(kind, str) and isinstance(name, str) and isinstance(path, str) and kind and name and path:
                routes.setdefault(f"inputs/{kind}/{name}", Target(path, "application/octet-stream"))
                routes.setdefault(path, Target(path, "application/octet-stream"))
                routes.setdefault(path + SIDECAR, Target(path + SIDECAR, "text/plain; charset=utf-8"))
```

Add to `Routes`:

```python
    def may_read(self, owner: str, header: str | None) -> bool:
        """Whether a request carrying *header* may have bytes owned by *owner*:
        the header is exactly that id, and that id is a current enrolment."""
        if not header or not header.isascii() or not owner.isascii():
            return False
        if not hmac.compare_digest(header.encode(), owner.encode()):
            return False
        try:
            info = os.stat(self.root / enrol.FILE)
            stamp: tuple[int, int, int] | None = (info.st_mtime_ns, info.st_size, info.st_ino)
        except OSError:
            stamp = None
        with self._lock:
            if stamp != self._enrol_stamp:
                self._enrolled = frozenset(e.id for e in enrol.load_lenient(self.root))
                self._enrol_stamp = stamp
            return header in self._enrolled
```

In `Handler._serve`, after `if target is None or path is None:` block:

```python
        if target.owner is not None and not self.routes.may_read(
            target.owner, self.headers.get(ENROLMENT_HEADER)
        ):
            self._plain(404, "not found")  # the same answer as a file that is not there
            return
```

and change the no-cache condition to `if target.path in ("catalogue.json", "index.json", "status.html") or target.path.startswith("catalogue.sig.d/"):`. Update the module docstring: the allow-list now also names the signatures and inputs the catalogue lists, and gates `owner:` bytes in group mode.

- [ ] **Step 6: The `enrol` command**

`src/bunker/cli.py`: `from bunker import ... enrol ...`, and

```python
def _enrol_body(root: Path, *, enrolment: enrol.Enrolment | None = None) -> dict[str, Any]:
    return {
        "enrolment": asdict(enrolment) if enrolment else None,
        "enrolments": [asdict(e) for e in enrol.load_lenient(root)],
    }


def cmd_enrol(args: argparse.Namespace, emit: Emit | None) -> int:
    cfg = _config(args)
    root = cfg.storage.root
    code, changed = EXIT_OK, None
    if args.enrol_command != "list":
        if cfg.bunker.mode != "group":
            _err("this Bunker is in personal mode: enrolments filter what a group Bunker shares "
                 "([bunker] mode = \"group\"); in personal mode every artifact is shared")
            return EXIT_REFUSED
        now = _now_iso()
        root.mkdir(parents=True, exist_ok=True)
        with RunLock(root):
            try:
                changed = (
                    enrol.add(root, args.label, now)
                    if args.enrol_command == "add"
                    else enrol.remove(root, args.ref)
                )
            except enrol.EnrolError as exc:
                _err(str(exc))
                return EXIT_REFUSED
            try:
                publish.publish(cfg, index.load(root), generated=now)
            except signing.PublishFailed as exc:
                _err(f"the enrolments changed but the catalogue was not republished: {exc}")
                code = EXIT_FAILED
    body = _enrol_body(root, enrolment=changed)
    if emit is not None:
        emit("enrol", body)
        return code
    if args.enrol_command == "add" and changed is not None:
        print(
            f"Enrolled {changed.label!r} as {changed.id}. Give that id to the laptop's operator "
            f"(`hammunition mirror enrol`); it is sent as {server.ENROLMENT_HEADER}. It filters "
            f"what is shared; it is not access control."
        )
    elif args.enrol_command == "remove" and changed is not None:
        print(f"Removed {changed.label!r} ({changed.id}); its owned artifacts are no longer served to it.")
    else:
        for e in body["enrolments"]:
            print(f"  {e['id']}  {e['label']}  (added {e['added']})")
        if not body["enrolments"]:
            print("No enrolments.")
    return code
```

Add `"enrol": cmd_enrol,` to `COMMANDS` and to `parser()`:

```python
    p_enrol = sub.add_parser("enrol", help="who a group Bunker shares owned artifacts with")
    enrol_sub = p_enrol.add_subparsers(dest="enrol_command", required=True, metavar="ACTION")
    p_e_add = enrol_sub.add_parser("add", parents=[common], help="enrol a laptop; prints its id")
    p_e_add.add_argument("label", help="a name for you to recognise it by")
    enrol_sub.add_parser("list", parents=[common], help="the enrolments")
    p_e_remove = enrol_sub.add_parser("remove", parents=[common], help="remove an enrolment")
    p_e_remove.add_argument("ref", metavar="ID_OR_LABEL")
```

- [ ] **Step 7: Run, docs, falsify, commit**

Run: `.venv/bin/python -m pytest -q -W error::DeprecationWarning; echo "exit=$?"` — Expected: `exit=0`.

`docs/reference.md`: Commands rows `bunker enrol add LABEL`, `bunker enrol list`, `bunker enrol remove ID_OR_LABEL` (JSON kind `enrol`); config row `bunker.byo_owner`; HTTP table rows for `/catalogue.json`, `/index.json` (alias), `/catalogue.sig.d/<n>.sig`, `/inputs/<kind>/<name>` (+ `.sha256`); a `## Group mode` section: how `share` is set (public data `all`; anything under `hold_unverified` goes to the `byo_owner` enrolment, or `owner:admin`, which nobody can read, when none is set); that the server answers an `owner:<id>` artifact (its `<unit>/<name>`, its volume path and its sidecar) only to a request whose `X-Hammunition-Enrolment` is that id and a current enrolment, with the same 404 as a missing file; that a removed enrolment loses access at once but the catalogue lists the artifact regardless (the engine skips what is not shared with it); and, in bold, **this is a sharing filter, not access control: the id is sent in clear over plain HTTP, any host on the LAN that learns it can send it, and nothing secret belongs on a Bunker**. `docs/guide.md`: a short "Group mode" section with the same warning and the enrol-then-`hammunition mirror enrol` flow. `config.example.toml` `[bunker]`: add `# byo_owner = "alice-laptop"   # group mode: who owns what is held under hold_unverified`. `CHANGELOG.md`: "- Group mode: `bunker enrol add|list|remove`, enrolments in `.enrolments.json`, `X-Hammunition-Enrolment` gating of `owner:<id>` artifacts (404 otherwise), `bunker.byo_owner` for what is held under `hold_unverified`; the server also serves `/catalogue.sig.d/<n>.sig` and `/inputs/<kind>/<name>`."

Falsify: in `Routes._build` give the sidecar `Target` no owner (revert to `Target(path + SIDECAR, "text/plain; charset=utf-8")`); `test_the_volume_path_and_the_sidecar_of_owned_bytes_are_gated_too` FAILS (200 without the header); restore. Delete the `enrol.load_lenient` re-read (cache forever) and `test_a_removed_enrolment_loses_the_bytes_at_once` FAILS; restore.

Run: `make check; echo "exit=$?"` — Expected: `exit=0`.

```bash
git add src/bunker/enrol.py src/bunker/config.py src/bunker/server.py src/bunker/publish.py src/bunker/cli.py config.example.toml docs/reference.md docs/guide.md CHANGELOG.md tests/test_enrol.py tests/test_server.py tests/test_config.py
git commit -m "Server routes for the catalogue files; group-mode enrolments

/catalogue.json, /index.json alias, /catalogue.sig.d/<n>.sig, /inputs/<kind>/<name>;
bunker enrol add|list|remove; owner:<id> artifacts are answered only to a
matching X-Hammunition-Enrolment (404 otherwise); BYO kinds default to the
byo_owner enrolment. A sharing filter, not access control, and the docs say so."
```

### Task 7: The status page and `bunker status` show the keys

A new *Signing* section lists every key with its algorithm, size and whether it is hardware, when it last signed and whether it is in the published catalogue, repeats the engine's weak-key warning for any key it applies to, and says plainly when no hardware key is configured. `bunker status` and its `--json` document carry the same facts (without the warning text, which depends on the installed engine; `bunker keys list` has it).

**Files:**
- Modify: `src/bunker/statuspage.py` (imports 15-22, `render` 79-214, `write` 217-220), `src/bunker/cli.py` (`_status_body` 306-333, `cmd_status` 336-373), `tests/test_statuspage.py`, `tests/test_cli.py`, `tests/golden/status.json`, `docs/reference.md` (`--json` documents table, status row), `docs/guide.md` (section 5, 189-215), `CHANGELOG.md`
- Test: `tests/test_statuspage.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `bunker.keys.KeyView`, `bunker.keys.views`, `bunker.keys.describe`, `bunker.signing.load_registry`, `bunker.signing.load_signed`, `Index.signers`, `Index.serial`.
- Produces: `statuspage.render(index: Index, *, disk_used: int, keys: Sequence[KeyView] = ()) -> str`; `statuspage.key_views(root: Path, index: Index) -> list[KeyView]`; `cli._status_body(root: Path, idx: Index) -> dict[str, Any]` gains `serial`, `hardware_key`, `keys`, `weak_keys`.

- [ ] **Step 1: Write the failing page tests**

Append to `tests/test_statuspage.py`:

```python
from bunker.keys import KeyView


def key_view(**over: Any) -> KeyView:
    fields: dict[str, Any] = {
        "id": "SHA256:Jo/yEkflbseRTafuq4t5y9mq83HUEfHmdaCIk/a4+NM",
        "backend": "file",
        "algorithm": "ssh-ed25519",
        "bits": 256,
        "hardware": False,
        "retired": None,
        "added": "2026-10-07T00:00:00Z",
        "last_signed": "2026-10-07T12:00:00Z",
        "in_catalogue": True,
        "warning": None,
    }
    fields.update(over)
    return KeyView(**fields)


def signing_page(keys: list[KeyView], **index_over: Any) -> str:
    idx = Index(engine_version="0.22.0", generated="2026-10-07T12:00:00Z", serial=7, **index_over)
    return statuspage.render(idx, disk_used=0, keys=keys)


def test_the_page_lists_each_key_with_algorithm_size_kind_and_last_signature() -> None:
    page = signing_page([key_view(), key_view(id="SHA256:two", backend="security-key", hardware=True,
                                              algorithm="sk-ssh-ed25519@openssh.com")])  # fmt: skip
    assert "<h2>Signing</h2>" in page and "serial 7" in page
    assert "ssh-ed25519" in page and "256-bit" in page
    assert "hardware" in page and "2026-10-07T12:00:00Z" in page
    assert "No hardware key configured" not in page


def test_it_says_so_when_no_hardware_key_is_configured() -> None:
    page = signing_page([key_view()])
    assert "No hardware key configured" in page and "bunker keys add --backend security-key" in page


def test_a_retired_hardware_key_is_not_a_hardware_key() -> None:
    page = signing_page([key_view(), key_view(id="SHA256:old", hardware=True, retired="2026-10-01T00:00:00Z")])
    assert "No hardware key configured" in page and "retired 2026-10-01T00:00:00Z" in page


def test_a_weak_key_carries_the_engines_warning_and_is_marked() -> None:
    warning = "RSA 2048-bit is weak: replace with Ed25519, ECDSA or RSA 3072+"
    page = signing_page([key_view(algorithm="ssh-rsa", bits=2048, warning=warning)])
    assert warning in page and 'class="bad"' in page
    assert "1 weak key" in page


def test_a_key_the_engine_could_not_classify_is_a_note_not_an_alarm() -> None:
    page = signing_page([key_view(warning="strength not checked: no hammunition.keystrength")])
    assert "strength not checked" in page and "weak key" not in page


def test_no_key_at_all_is_said_plainly() -> None:
    assert "no signing key" in signing_page([]).lower()


def test_key_text_is_escaped() -> None:
    page = signing_page([key_view(id="SHA256:<script>x</script>", warning="<script>y</script>")])
    assert "<script>" not in page


def test_write_reads_the_registry_and_marks_what_the_catalogue_lists(tmp_path: Path) -> None:
    from tests.helpers import FAKE_ID

    statuspage.write(tmp_path, Index(engine_version="0.22.0", serial=1, signers=[{"id": FAKE_ID}]))
    page = (tmp_path / "status.html").read_text()
    assert FAKE_ID in page and "in the catalogue" in page
```

(The autouse fake registry supplies the one key `write` reads.) Run: `.venv/bin/python -m pytest tests/test_statuspage.py -q -x` — Expected: FAIL, `TypeError: render() got an unexpected keyword argument 'keys'`.

- [ ] **Step 2: The page**

`src/bunker/statuspage.py`: add `from collections.abc import Sequence`, `from bunker import __version__, keys, signing`, `from bunker.keys import KeyView`; change `render`'s signature to `def render(index: Index, *, disk_used: int, keys: Sequence[KeyView] = ()) -> str:` (rename the module import to `from bunker import keys as keymod` so the parameter does not shadow it), and insert after the *Last run* block (before `per_unit`):

```python
    out += _signing_section(index, keys)
```

with

```python
def _signing_section(index: Index, shown: Sequence[KeyView]) -> list[str]:
    out = ["<h2>Signing</h2>"]
    published = f"catalogue serial {_e(index.serial)}" if index.serial else "no catalogue published yet"
    active = [k for k in shown if k.retired is None]
    signed = [k.last_signed for k in active if k.last_signed]
    last = f", last signed {_e(max(signed))}" if signed else ""
    out.append(f"<p>{published}{last}.</p>")
    if not active:
        out.append(
            '<p class="bad">This Bunker has no signing key, so it cannot publish a catalogue a '
            "laptop will accept. Add one with <code>bunker keys add</code>.</p>"
        )
    if shown:
        out.append(
            '<div class="wrap"><table><thead><tr><th>Key</th><th>Kind</th><th>Algorithm</th>'
            "<th>Size</th><th>Last signed</th><th>Catalogue</th><th>Note</th></tr></thead><tbody>"
        )
        for k in shown:
            kind = "hardware" if k.hardware else k.backend
            state = f"retired {k.retired}" if k.retired else ("in the catalogue" if k.in_catalogue else "not in the catalogue")
            note = ""
            if k.warning:
                css = "warn" if k.warning.startswith("strength not checked") else "bad"
                note = f'<span class="{css}">{_e(k.warning)}</span>'
            out.append(
                f"<tr><td><code>{_e(k.id)}</code></td><td>{_e(kind)}</td><td>{_e(k.algorithm)}</td>"
                f"<td>{_e(k.bits)}-bit</td><td>{_e(k.last_signed or 'never')}</td>"
                f"<td>{_e(state)}</td><td>{note}</td></tr>"
            )
        out.append("</tbody></table></div>")
    weak = [k for k in active if k.warning and not k.warning.startswith("strength not checked")]
    if weak:
        one = len(weak) == 1
        out.append(
            f'<p class="bad">{len(weak)} weak key{"" if one else "s"} sign{"s" if one else ""} this '
            f"catalogue: replace {'it' if one else 'them'} (<code>bunker keys list</code>).</p>"
        )
    if active and not any(k.hardware for k in active):
        out.append(
            '<p class="warn">No hardware key configured. A hardware key keeps the signing key '
            "off this disk, so a copy of the volume cannot sign for you. It is recommended, never "
            "required: <code>bunker keys add --backend security-key</code>.</p>"
        )
    return out
```

Add:

```python
def key_views(root: Path, index: Index) -> list[KeyView]:
    """The registry's keys as the page and ``bunker status`` show them."""
    try:
        registry = signing.load_registry(root)
    except signing.SigningError:
        return []
    return keymod.views(registry, signing.load_signed(root), {str(s.get("id")) for s in index.signers})
```

and change `write` to `write_atomic(root / "status.html", render(index, disk_used=disk_used(root), keys=key_views(root, index)).encode("utf-8"))`. Update the closing paragraph's link text to `catalogue.json` if Task 1 did not.

Run: `.venv/bin/python -m pytest tests/test_statuspage.py -q` — Expected: PASS.

- [ ] **Step 3: `bunker status`**

Write the failing test in `tests/test_cli.py`:

```python
def test_status_says_when_no_hardware_key_is_configured_and_lists_the_keys(invoke: Any, scene: Scene) -> None:
    invoke("run")
    code, out, _ = invoke("status")
    assert code == 0
    assert "Signing: catalogue serial 1, 1 active key(s)" in out
    assert "No hardware key configured" in out
    code, out, _ = invoke("status", "--json")
    document = json.loads(out)
    assert document["serial"] == 1 and document["hardware_key"] is False
    assert [k["backend"] for k in document["keys"]] == ["file"] and "warning" not in document["keys"][0]
    assert document["weak_keys"] == []
```

Run it — Expected: FAIL (`Signing:` not in the output).

In `src/bunker/cli.py` change `_status_body` to `def _status_body(root: Path, idx: index.Index) -> dict[str, Any]:` and import `statuspage` into `cli`. Before its `return`, add

```python
    shown = statuspage.key_views(root, idx)
    weak = [
        k.id
        for k in shown
        if k.retired is None and k.warning and not k.warning.startswith("strength not checked")
    ]
```

and add these entries to the returned dict:

```python
        "serial": idx.serial or None,
        "hardware_key": any(k.hardware and k.retired is None for k in shown),
        "keys": [
            {key: value for key, value in asdict(k).items() if key != "warning"} for k in shown
        ],
        "weak_keys": weak,
```

`cmd_status` calls `_status_body(cfg.storage.root, index.load(cfg.storage.root))`; in the text branch, after the `Held:` line, print

```python
    active = [k for k in body["keys"] if not k["retired"]]
    print(f"Signing: catalogue serial {body['serial'] or 'none yet'}, {len(active)} active key(s)")
    for k in body["keys"]:
        if k["id"] in body["weak_keys"]:
            print(f"  weak key: {k['id']} ({k['algorithm']} {k['bits']}-bit): replace it (`bunker keys list`)")
    if not body["hardware_key"]:
        print("  No hardware key configured (recommended: `bunker keys add --backend security-key`).")
```

Regenerate: `BUNKER_UPDATE_GOLDENS=1 .venv/bin/python -m pytest tests/test_cli.py -q`; read the diff of `tests/golden/status.json`: it gains `serial`, `hardware_key`, `keys` (the one fake key, `in_catalogue` true, `last_signed` the scene clock) and `weak_keys: []`.

- [ ] **Step 4: Docs, falsification, commit**

`docs/reference.md`: the `status` row of the documents table gains `serial`, `hardware_key`, `keys` (`id`, `backend`, `algorithm`, `bits`, `hardware`, `retired`, `added`, `last_signed`, `in_catalogue`), `weak_keys`. `docs/guide.md` section 5: add "- **Signing**: each key with its algorithm, size and kind, when it last signed, and whether it is in the published catalogue; a weak key (RSA of 2048 bits or fewer) with the suite's warning; and a plain line when no hardware key is configured." `CHANGELOG.md`: "- The status page and `bunker status` show the signing keys: algorithm, size, hardware or file, last signature, weak-key warnings and a line when no hardware key is configured."

Falsify: change `warn if k.warning.startswith(...)` to always `"warn"`; `test_a_weak_key_carries_the_engines_warning_and_is_marked` FAILS (`class="bad"` missing); restore.

Run: `make check; echo "exit=$?"` — Expected: `exit=0`.

```bash
git add src/bunker/statuspage.py src/bunker/cli.py tests/test_statuspage.py tests/test_cli.py tests/golden/status.json docs/reference.md docs/guide.md CHANGELOG.md
git commit -m "Status page and bunker status show the signing keys

Algorithm, size, hardware or file, last signature, whether each is in the
published catalogue, the engine's weak-key warning, and a plain line when no
hardware key is configured."
```

### Task 8: `bunker export --to DIR`

`bunker export --to DIR` writes the published catalogue, its signatures, the inputs and every file in the layout the server answers (`<dir>/<unit>/<name>` is the file itself, `<dir>/inputs/<kind>/<name>`, `<dir>/catalogue.json`, `<dir>/catalogue.sig.d/<n>.sig`), so a drive plugged into a laptop reads the same paths a LAN mirror serves (phase 3 builds the engine's `file://` reader; the layout is fixed now). Every byte is re-hashed against the catalogue while it is copied. The old catalogue on the drive is removed first and the new one written last, so a copy that stops halfway leaves a drive no laptop will believe.

**Files:**
- Create: `src/bunker/export.py`, `tests/test_export.py`
- Modify: `src/bunker/cli.py` (`COMMANDS`, `parser`), `docs/reference.md`, `docs/guide.md`, `CHANGELOG.md`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `bunker.index.FILE`, `bunker.volume.RunLock`, `artifact_dir`, `input_path`, `UnsafeName`; the published `catalogue.json` and `catalogue.sig.d/`.
- Produces: `bunker.export.ExportError(Exception)`, `ExportRefused(ExportError)`, `ExportFailed(ExportError)`; `ExportReport(to: str, serial: int, files: int = 0, bytes: int = 0, skipped_owned: list[str], failed: list[dict[str, str]])` with `exit_code` and `as_dict()`; `export(cfg: Config, to: Path) -> ExportReport`; CLI `bunker export --to DIR [--json]`, document kind `export`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_export.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import errno
import json
from pathlib import Path
from typing import Any

import pytest

from bunker import cli, enrol, export
from bunker.volume import RunLock
from tests.helpers import entry, input_item
from tests.scene import REGION, TILE, Scene, sha
from tests.test_server import Served


def drive(scene: Scene) -> Path:
    return scene.tmp / "drive"


def do_export(scene: Scene) -> export.ExportReport:
    return export.export(scene.cfg(), drive(scene))


def test_the_served_layout_is_written(scene: Scene) -> None:
    url = scene.pub.put("/geofabrik/europe/monaco.poly", b"monaco\n1\n2 3\nEND\nEND\n")
    scene.list(inputs=[input_item("region-outline", "europe/monaco", "europe/monaco.poly", url=url)])
    scene.run()
    report = do_export(scene)
    out = drive(scene)
    assert report.exit_code == 0 and report.serial == 1 and report.files == 4 and report.failed == []
    assert (out / "catalogue.json").read_bytes() == (scene.root / "catalogue.json").read_bytes()
    assert (out / "catalogue.sig.d/1.sig").read_bytes() == (scene.root / "catalogue.sig.d/1.sig").read_bytes()
    assert (out / "country-files/cty.dat").read_bytes() == scene.data["cty"]
    assert (out / "osm-regions" / REGION).read_bytes() == scene.data["region"]
    assert (out / "inputs/region-outline/europe/monaco.poly").read_bytes() == b"monaco\n1\n2 3\nEND\nEND\n"
    names = {p.name for p in out.rglob("*") if p.is_file()}
    assert not [n for n in names if n.endswith((".sha256", ".previous")) or n.startswith(".")]


def test_the_exported_tree_is_what_the_server_answers(scene: Scene) -> None:
    scene.run()
    do_export(scene)
    served = Served(scene.root)
    try:
        for unit, name in (("country-files", "cty.dat"), ("osm-regions", REGION), ("dem-copernicus", TILE)):
            assert (drive(scene) / unit / name).read_bytes() == served.request(f"/{unit}/{name}")[2]
    finally:
        served.httpd.shutdown()
        served.httpd.server_close()


def test_a_source_file_that_no_longer_matches_is_not_exported_and_fails_the_export(scene: Scene) -> None:
    scene.run()
    path = scene.file("osm-regions", REGION)
    path.write_bytes(b"!" + path.read_bytes()[1:])
    report = do_export(scene)
    assert report.exit_code == 1
    assert [f["name"] for f in report.failed] == [f"osm-regions/{REGION}"]
    assert "no longer match" in report.failed[0]["reason"]
    assert not (drive(scene) / "osm-regions" / REGION).exists()
    assert (drive(scene) / "country-files/cty.dat").exists(), "one damaged file does not stop the rest"


def test_a_missing_source_file_is_reported_and_skipped(scene: Scene) -> None:
    scene.run()
    scene.file("country-files", "cty.dat").unlink()
    report = do_export(scene)
    assert [f["name"] for f in report.failed] == ["country-files/cty.dat"]


def test_nested_names_that_cannot_both_be_files_fail_by_name(scene: Scene) -> None:
    extra = b"a parent region " * 50
    url = scene.pub.put("/geofabrik/north-america/us.osm.pbf", extra)
    scene.list([*scene.entries(), entry("osm-regions", "north-america/us", url, "sha256", sha(extra), size=len(extra))])
    scene.run()
    report = do_export(scene)
    assert len(report.failed) == 1 and "clash" in report.failed[0]["reason"]
    both = [(drive(scene) / "osm-regions/north-america/us").is_file(), (drive(scene) / "osm-regions" / REGION).is_file()]
    assert sorted(both) == [False, True]


def test_a_full_drive_leaves_no_catalogue_behind(scene: Scene, monkeypatch: pytest.MonkeyPatch) -> None:
    scene.run()
    do_export(scene)  # an earlier, complete export
    assert (drive(scene) / "catalogue.json").exists()
    scene.clock.advance(days=8)
    scene.run()
    real = export._copy
    calls: list[Path] = []

    def full(source: Path, target: Path, expected: str | None) -> int:
        calls.append(target)
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(source, target, expected)

    monkeypatch.setattr(export, "_copy", full)
    with pytest.raises(export.ExportFailed, match="No space left on device.*no catalogue was written"):
        do_export(scene)
    assert not (drive(scene) / "catalogue.json").exists(), "a half copy must not be believed"
    assert list((drive(scene) / "catalogue.sig.d").glob("*.sig")) == []
    assert not [p for p in drive(scene).rglob("*.part.*")]


def test_export_is_locked_out_by_a_run(scene: Scene) -> None:
    scene.run()
    with RunLock(scene.root), pytest.raises(export.ExportRefused, match="run is in progress"):
        do_export(scene)
    assert not drive(scene).exists()


def test_a_second_export_replaces_the_catalogue_and_leaves_other_files(scene: Scene) -> None:
    scene.run()
    do_export(scene)
    (drive(scene) / "notes.txt").write_text("the operator's own file")
    scene.clock.advance(days=8)
    scene.run()
    again = do_export(scene)
    assert again.serial == 2
    assert json.loads((drive(scene) / "catalogue.json").read_text())["serial"] == 2
    assert (drive(scene) / "notes.txt").exists(), "deleting is for a person"


def test_nothing_is_exported_before_a_catalogue_is_published(scene: Scene) -> None:
    with pytest.raises(export.ExportRefused, match="bunker run"):
        do_export(scene)


@pytest.mark.parametrize("where", ["inside", "same", "above"])
def test_the_target_may_not_overlap_the_volume(scene: Scene, where: str) -> None:
    scene.run()
    target = {"inside": scene.root / "drive", "same": scene.root, "above": scene.tmp}[where]
    with pytest.raises(export.ExportRefused, match="overlaps the volume"):
        export.export(scene.cfg(), target)


def test_group_mode_owned_artifacts_are_listed_but_not_written(scene: Scene) -> None:
    scene.extra += '[bunker]\nmode = "group"\nbyo_owner = "alice"\n'
    scene.root.mkdir(parents=True, exist_ok=True)
    enrol.add(scene.root, "alice", "2026-09-29T00:00:00Z")
    snapshot = b"callsign,frequency\n" * 20
    url = scene.pub.put("/snap/etcc.csv", snapshot)
    scene.list([*scene.entries(), entry("repeater-snapshots", "etcc.csv", url, "unverified-fetch", None, size=len(snapshot))])
    scene.run()
    report = do_export(scene)
    assert report.skipped_owned == ["repeater-snapshots/etcc.csv"] and report.exit_code == 0
    assert not (drive(scene) / "repeater-snapshots").exists()
    listed = [a["name"] for a in json.loads((drive(scene) / "catalogue.json").read_text())["artifacts"]]
    assert "etcc.csv" in listed, "the catalogue is signed as it is; the engine skips what is not shared with it"


def test_the_command(scene: Scene, capsys: pytest.CaptureFixture[str]) -> None:
    scene.run()
    cfg_path = scene.tmp / "bunker.toml"
    assert cli.main(["export", "--to", str(drive(scene)), "--config", str(cfg_path)]) == 0
    assert "3 files" in capsys.readouterr().out
    assert cli.main(["export", "--to", str(drive(scene)), "--json", "--config", str(cfg_path)]) == 0
    document: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert document["kind"] == "export" and document["files"] == 3 and document["serial"] == 1
    assert cli.main(["export", "--to", str(scene.root), "--config", str(cfg_path)]) == 2
```

Run: `.venv/bin/python -m pytest tests/test_export.py -q -x` — Expected: FAIL at collection, `ImportError: cannot import name 'export' from 'bunker'`.

- [ ] **Step 2: Write `src/bunker/export.py`**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""``bunker export --to DIR``: the published catalogue, its signatures, the
inputs and every file, in the layout the server answers.

``<dir>/<unit>/<name>`` is the file itself (on the volume it is a directory
holding the dated file), so a reader of a directory asks the paths a reader of
a LAN mirror asks. Order is what makes a drive safe to unplug at any moment:
the previous catalogue and signatures are removed first, files and inputs are
copied (each re-hashed against the catalogue while it is read), the signatures
follow, and the catalogue is written last. A copy that stops halfway has no
catalogue, and a laptop does not believe a drive without one.

A group Bunker's ``owner:`` artifacts are not written: a drive has no
enrolment header, so copying them would hand them to whoever holds it. The
catalogue still lists them (it is signed as it is); the engine skips what is
not shared with it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from bunker import index
from bunker.config import Config
from bunker.volume import Locked, RunLock, UnsafeName, artifact_dir, input_path

__all__ = ["ExportError", "ExportFailed", "ExportRefused", "ExportReport", "export"]

_SIGNATURE = re.compile(r"catalogue\.sig\.d/[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.sig")
_CHUNK = 1024 * 1024


class ExportError(Exception):
    """The export did not happen."""


class ExportRefused(ExportError):
    """Nothing was touched: the request cannot be met (exit 2)."""


class ExportFailed(ExportError):
    """Writing the target failed part-way; no catalogue was left there (exit 1)."""


class _Skip(Exception):
    """One file cannot be exported; the rest can."""


@dataclass
class ExportReport:
    to: str
    serial: int
    files: int = 0
    bytes: int = 0
    skipped_owned: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "exit_code": self.exit_code}


def _source(root: Path, relative: str) -> Path:
    parts = relative.split("/")
    if relative.startswith("/") or any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        raise _Skip(f"the catalogue names a path that is not inside the volume: {relative!r}")
    return root.joinpath(*parts)


def _copy(source: Path, target: Path, expected: str | None) -> int:
    """Copy *source* to *target* through a temporary, hashing as it goes; the
    bytes must hash to *expected* (when given) or nothing is left behind."""
    try:
        reader = source.open("rb")
    except OSError as exc:
        raise _Skip(f"cannot be read ({exc.strerror or exc})") from None
    temp = target.with_name(f".{target.name}.part.{os.getpid()}")
    digest, size = hashlib.sha256(), 0
    try:
        with reader:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
            except (NotADirectoryError, FileExistsError):
                raise _Skip("layout clash: a shorter name is already a file on the target") from None
            with temp.open("wb") as writer:
                while chunk := reader.read(_CHUNK):
                    digest.update(chunk)
                    writer.write(chunk)
                    size += len(chunk)
                writer.flush()
                os.fsync(writer.fileno())
        if expected is not None and digest.hexdigest() != expected:
            raise _Skip("its bytes no longer match the catalogue's sha256; not exported")
        try:
            os.replace(temp, target)
        except IsADirectoryError:
            raise _Skip("layout clash: a longer name already lives under this one") from None
    finally:
        temp.unlink(missing_ok=True)
    return size


def _overlaps(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a in b.parents or b in a.parents


def export(cfg: Config, to: Path) -> ExportReport:
    root = cfg.storage.root
    if _overlaps(root, to):
        raise ExportRefused(f"{to} overlaps the volume {root}: export to a separate directory or drive")
    try:
        with RunLock(root):  # a run in progress is moving files about
            return _export(root, to)
    except Locked as exc:
        raise ExportRefused(f"{exc}; export after it finishes") from None


def _export(root: Path, to: Path) -> ExportReport:
    try:
        data = (root / index.FILE).read_bytes()
        document = json.loads(data)
    except (OSError, ValueError):
        raise ExportRefused(f"{root / index.FILE} is missing or damaged: run `bunker run` first") from None
    if not isinstance(document, dict):
        raise ExportRefused(f"{root / index.FILE} is not a catalogue")
    report = ExportReport(str(to), int(document.get("serial", 0)))
    group = isinstance(document.get("bunker"), dict) and document["bunker"].get("mode") == "group"
    try:
        to.mkdir(parents=True, exist_ok=True)
        (to / index.FILE).unlink(missing_ok=True)
        served = to / "catalogue.sig.d"
        if served.is_dir():
            for old in served.glob("*.sig"):
                old.unlink()
        for item in document.get("artifacts", []):
            _artifact(root, to, item, group, report)
        for item in document.get("inputs", []):
            _input(root, to, item, report)
        for signer in document.get("signers", []):
            signature = signer.get("signature") if isinstance(signer, dict) else None
            if isinstance(signature, str) and _SIGNATURE.fullmatch(signature):
                try:
                    _copy(root / signature, to / signature, None)
                except _Skip as exc:
                    raise ExportFailed(f"{signature}: {exc}; no catalogue was written") from None
        temp = to / f".{index.FILE}.part.{os.getpid()}"
        try:
            with temp.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, to / index.FILE)
        finally:
            temp.unlink(missing_ok=True)
    except OSError as exc:
        (to / index.FILE).unlink(missing_ok=True)
        shutil.rmtree(to / "catalogue.sig.d", ignore_errors=True)
        raise ExportFailed(
            f"could not write to {to} ({exc.strerror or exc}); no catalogue was written, so a "
            f"laptop will not believe what is there"
        ) from None
    return report


def _artifact(root: Path, to: Path, item: Any, group: bool, report: ExportReport) -> None:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        return
    unit, name, label = item.get("unit"), item.get("name"), f"{item.get('unit')}/{item.get('name')}"
    if item.get("status") == "corrupted" or not isinstance(unit, str) or not isinstance(name, str):
        return
    share = item.get("share")
    if group and isinstance(share, str) and share.startswith("owner:"):
        report.skipped_owned.append(label)
        return
    try:
        size = _copy(_source(root, item["path"]), artifact_dir(to, unit, name), item.get("sha256"))
    except UnsafeName as exc:
        report.failed.append({"name": label, "reason": str(exc)})
    except _Skip as exc:
        report.failed.append({"name": label, "reason": str(exc)})
    else:
        report.files += 1
        report.bytes += size


def _input(root: Path, to: Path, item: Any, report: ExportReport) -> None:
    if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("kind", "name", "path")):
        return
    label = f"inputs/{item['kind']}/{item['name']}"
    try:
        size = _copy(_source(root, item["path"]), input_path(to, item["kind"], item["name"]), item.get("sha256"))
    except (UnsafeName, _Skip) as exc:
        report.failed.append({"name": label, "reason": str(exc)})
    else:
        report.files += 1
        report.bytes += size
```

The lock message is "a run is in progress (…/.lock is held)", which the test matches.

- [ ] **Step 3: The command**

`src/bunker/cli.py`: `from bunker import ... export ...`, and

```python
def cmd_export(args: argparse.Namespace, emit: Emit | None) -> int:
    cfg = _config(args)
    try:
        report = export.export(cfg, args.to)
    except export.ExportRefused as exc:
        _err(str(exc))
        return EXIT_REFUSED
    except export.ExportFailed as exc:
        _err(str(exc))
        return EXIT_FAILED
    if emit is not None:
        emit("export", report.as_dict())
        return report.exit_code
    print(
        f"bunker export: catalogue serial {report.serial} and {report.files} files "
        f"({report.bytes} bytes) written to {report.to}"
    )
    for label in report.skipped_owned:
        print(f"  not written (owned by an enrolment, not shared with a drive): {label}")
    for failure in report.failed:
        print(f"  not exported: {failure['name']}: {failure['reason']}")
    return report.exit_code
```

`"export": cmd_export,` in `COMMANDS`; in `parser()`:

```python
    p_export = sub.add_parser("export", parents=[common], help="write the catalogue and files to a directory or drive")
    p_export.add_argument("--to", type=Path, required=True, metavar="DIR", help="an empty or previous-export directory outside the volume")
```

(`ExportRefused` is caught inside `cmd_export`; a `Locked` never escapes `export`.)

- [ ] **Step 4: Run, docs, falsify, commit**

Run: `.venv/bin/python -m pytest -q -W error::DeprecationWarning; echo "exit=$?"` — Expected: `exit=0`.

`docs/reference.md`: Commands row `bunker export --to DIR` (JSON `export`: `to`, `serial`, `files`, `bytes`, `skipped_owned`, `failed`, `exit_code`); exit codes (2 when the target overlaps the volume or there is no catalogue yet, 1 when a file failed or the target filled up, 125 while a run holds the volume). `docs/guide.md`: a section "Taking the catalogue to a drive": what is written and in what layout, that the previous catalogue on the drive is removed first and the new one written last so unplugging early leaves a drive nobody believes, that a group Bunker's `owner:` files are not written, that the drive can be any filesystem the laptop reads, that the engine reads a `file://` catalogue from phase 3 (not yet), and how to check a drive by hand with `ssh-keygen -Y verify` as in the signing section. `CHANGELOG.md`: "- `bunker export --to DIR`: the catalogue, its signatures, the inputs and every file in the served layout, each re-hashed against the catalogue as it is copied; the catalogue is removed first and written last."

Falsify: in `_export` move the catalogue write above the artifact loop; `test_a_full_drive_leaves_no_catalogue_behind` FAILS (a catalogue is left behind); restore. In `_copy` skip the `expected` comparison; `test_a_source_file_that_no_longer_matches...` FAILS; restore.

Run: `make check; echo "exit=$?"` — Expected: `exit=0`.

```bash
git add src/bunker/export.py src/bunker/cli.py tests/test_export.py docs/reference.md docs/guide.md CHANGELOG.md
git commit -m "bunker export --to DIR: the catalogue and files in the served layout

Each file re-hashed against the catalogue as it is copied; the old catalogue is
removed first and the new one written last, so a drive that stops halfway has
none; a group Bunker's owner: files are not written."
```

### Task 9: Hardware keys in the container — commented examples and a guide section

The Bunker runs in a container, so a token has to be handed to it on purpose: a FIDO2 key as its `/dev/hidraw*` node, a PIV card by mounting the host's `pcscd` socket (or a host `ssh-agent` socket). `compose.yaml` and the Podman quadlet get **commented** examples and never a default device mapping; `docs/guide.md` gets the section that explains when and how, with every step nobody has run on the NAS marked as a bench item.

**Files:**
- Modify: `compose.yaml` (after `security_opt` 33-34, in `volumes` 24-28), `packaging/bunker.container` (after `NoNewPrivileges` 31), `docs/guide.md` (new section before "Security posture" 276), `README.md` (feature list), `tests/test_packaging.py`, `CHANGELOG.md`
- Test: `tests/test_packaging.py`, `tests/test_docs.py` (unchanged: holds links and cited paths)

**Interfaces:**
- Consumes: `[signing] agent_socket` (Task 3), `bunker keys add --backend security-key|agent` (Task 3).
- Produces: nothing importable; two tests that fail if a device or socket mapping is ever uncommented.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_packaging.py` (the file already has `ROOT`, `yaml`, `re` and `Any`):

```python
def _compose_text() -> str:
    return (ROOT / "compose.yaml").read_text()


def _quadlet_text() -> str:
    return (ROOT / "packaging" / "bunker.container").read_text()


def test_no_token_is_mapped_by_default() -> None:
    """A token passthrough widens what the container can reach: it is the
    operator's decision for their own hardware, never a default."""
    service = yaml.safe_load(_compose_text())["services"]["bunker"]
    assert "devices" not in service and "privileged" not in service
    assert not [v for v in service["volumes"] if "pcscd" in v or "hidraw" in v or "agent" in v]
    assert "device_cgroup_rules" not in service
    quadlet = _quadlet_text()
    assert not re.search(r"^(AddDevice|Volume|PodmanArgs)=.*(hidraw|pcscd|agent|--device)", quadlet, re.M)


def test_the_hardware_examples_are_there_and_every_one_is_a_comment() -> None:
    compose, quadlet = _compose_text(), _quadlet_text()
    assert "#   - /dev/hidraw" in compose and "#   - /run/pcscd/pcscd.comm" in compose
    assert "# AddDevice=/dev/hidraw" in quadlet and "# Volume=/run/pcscd/pcscd.comm" in quadlet
    for text in (compose, quadlet):
        for line in text.splitlines():
            if "hidraw" in line or "pcscd" in line:
                assert line.lstrip().startswith("#"), f"a hardware mapping is not a comment: {line!r}"
    assert "docs/guide.md" in compose, "the example points at the section that explains it"
```

Run: `.venv/bin/python -m pytest tests/test_packaging.py -q -k "token or hardware"` — Expected: `test_no_token_is_mapped_by_default` PASSES (nothing is mapped yet); `test_the_hardware_examples_are_there...` FAILS on `assert "#   - /dev/hidraw" in compose`.

- [ ] **Step 2: `compose.yaml`**

Insert after the `security_opt:` block (after line 34):

```yaml
    # --- Hardware signing keys: examples, all commented out ----------------------
    # docs/guide.md, "Hardware signing keys", says when this is worth doing and
    # what has and has not been run on a NAS. Nothing here is on by default: handing
    # a token to the container is a decision about your own hardware.
    #
    # A FIDO2 security key (any: YubiKey, Immurok, SoloKey, Nitrokey, Token2, Feitian)
    # is passed in as its hidraw node. `fido2-token -L` on the host names it. The
    # container's user (uid 10001) must be allowed to open that node.
    # devices:
    #   - /dev/hidraw3:/dev/hidraw3
    #
    # A PIV smart card is reached through the host's pcscd: add this line to `volumes`
    # above (the host runs pcscd; the image carries opensc and the pcsc client library).
    #   - /run/pcscd/pcscd.comm:/run/pcscd/pcscd.comm
    # Or hand over a host ssh-agent that already holds the key, and set
    # [signing] agent_socket = "/run/agent.sock" in bunker.toml:
    #   - /run/user/1026/agent.sock:/run/agent.sock
```

The `volumes:` list keeps its two real entries; the two commented list items sit below the `devices:` comment so the mapping stays one block of comments.

- [ ] **Step 3: The quadlet**

Insert after `NoNewPrivileges=true` in `packaging/bunker.container`:

```ini
# Hardware signing keys: examples, commented out (docs/guide.md, "Hardware signing keys").
# Rootless Podman can only pass a device your own user may open; the usual route is a
# udev rule that gives the logged-in user the token (uaccess), checked with
# `ls -l /dev/hidraw*` before and after. Nothing here is on by default.
# A FIDO2 security key, as its hidraw node (`fido2-token -L` names it):
# AddDevice=/dev/hidraw3
# A PIV smart card, through the host's pcscd:
# Volume=/run/pcscd/pcscd.comm:/run/pcscd/pcscd.comm
```

- [ ] **Step 4: The guide section**

Insert before `## Security posture` in `docs/guide.md`:

````markdown
## Hardware signing keys

A laptop that enrols your Bunker accepts a catalogue only if a key it was shown signed it. By default the
Bunker signs with a **file key** in `<volume>/.keys`, which is enough to make the catalogue tamper-evident
but means a copy of the volume (a backup, a stolen disk) is a copy of the key. A hardware key keeps the
private half on a token: it is **recommended, never required**, and the Bunker works without one (the status
page keeps a line saying none is configured).

**Which token.** Any FIDO2 authenticator: a YubiKey, an Immurok, a SoloKey, a Nitrokey, a Token2, a Feitian.
The Bunker asks for an `ed25519-sk` key and falls back to `ecdsa-sk` (P-256) if the token cannot do Ed25519;
FIDO2 has no RSA. A PIV smart card signs through `ssh-agent` and PKCS#11: RSA 3072 or 4096 and P-384 on a
YubiKey with firmware 5.7 or newer, ECDSA and RSA on older PIV tokens. Keys are classified by the same rule
the laptops use; RSA of 2048 bits or fewer is accepted and warned, wherever it is shown.

**Touch or no touch.** A key made with touch needs someone to tap the token whenever the catalogue changes
(`bunker run`, a key or enrolment change): a scheduled refresh at 03:00 with nobody there waits
`signing.sign_timeout` seconds (60) and then publishes with the keys that could sign. A key made
`--no-touch` signs unattended. The usual arrangement is both: a file key that signs every scheduled refresh
and a touch-required token that adds its signature when you are there. Losing one token never locks the
fleet out, because a laptop accepts a catalogue when any key it enrolled signed it. (A laptop can be set to
require a hardware signature.)

**Passing a token to the container.** `compose.yaml` and `packaging/bunker.container` carry commented
examples and map nothing by default.

1. With the token plugged into the NAS, find its node: `fido2-token -L` (the image has it too).
2. Uncomment the `devices:` example with that node, and make sure uid 10001 (or your user, under rootless
   Podman) may open it. On a Debian host a udev rule that grants the logged-in user the token does it;
   on a Synology it is a bench item (below).
3. Redeploy, then make the key at a terminal, because the token asks for its PIN and a touch:

   ```
   podman exec -it hammunition-bunker bunker keys add --backend security-key
   podman exec -it hammunition-bunker bunker keys add --backend security-key --no-touch
   ```

   (Docker Compose: `docker exec -it ...`.) `bunker keys list` shows it, with `hardware` and when it last
   signed.
4. For a **PIV** card, either mount the host's `pcscd` socket and load the card into an agent inside the
   container, or run `ssh-agent` on the host, `ssh-add -s <the opensc PKCS#11 module>` there, mount the agent
   socket and set `[signing] agent_socket = "/run/agent.sock"`. Then register its public key (`ssh-add -L`
   prints it): `bunker keys add --backend agent --public-key key.pub --hardware`. The Bunker stores only the
   public half, in a file with no private key beside it, so signing must go through the agent.
5. Retire a lost token with `bunker keys retire FINGERPRINT`; the catalogue is signed again at once without it.

**What has been run and what has not.** Signing and verifying with file keys (Ed25519, ECDSA, RSA) and with a
real `ssh-agent` is covered by the test suite and was measured with OpenSSH 10.3. Not run, and to be run on
the NAS before you rely on it: signing with a FIDO2 token from inside the container (touch and no-touch);
the Immurok's algorithms; a PIV RSA key through the agent; the hidraw permissions on a Synology; how long a
touch-required signature takes on a scheduled refresh; and whether `ykman` in Ubuntu's archive can generate
RSA 3072 or 4096 in PIV on firmware 5.7.
````

`README.md`: add one bullet to the feature list near the top (read the file for the list it already has): "- **Signed.** The Bunker publishes a signed catalogue of everything it holds; file keys by default, FIDO2 and PIV hardware keys when you want them (`docs/guide.md`, *Hardware signing keys*)."

- [ ] **Step 5: Run, falsify, commit**

Run: `.venv/bin/python -m pytest tests/test_packaging.py tests/test_docs.py -q; echo "exit=$?"` — Expected: `exit=0`.

Falsify: uncomment `#   - /dev/hidraw3:/dev/hidraw3` into a real `devices:` entry in `compose.yaml` and run `-k token` — Expected: `test_no_token_is_mapped_by_default` FAILS on `"devices" not in service`; restore.

`CHANGELOG.md`: "- Hardware keys in the container: commented examples for a FIDO2 `/dev/hidraw*` passthrough and the host `pcscd` or `ssh-agent` socket in `compose.yaml` and the quadlet (never a default mapping, tested), and a guide section on tokens, touch and no-touch, PIV, and what has not been run on a NAS."

Run: `make check; echo "exit=$?"` — Expected: `exit=0`.

```bash
git add compose.yaml packaging/bunker.container docs/guide.md README.md CHANGELOG.md tests/test_packaging.py
git commit -m "Hardware keys: commented device and socket examples, never a default

A FIDO2 hidraw node and the host pcscd or ssh-agent socket as commented examples
in compose.yaml and the quadlet, a test that fails if one is ever on by default,
and a guide section on tokens, touch, PIV and what has not been run on a NAS."
```

### Task 10: The network-isolated integration test

One test proves the whole chain with the internet gone: a real Bunker volume, signed with a real key, served by the real server, and the **pinned engine** in a network namespace where nothing but the Bunker answers. An offline data-unit install succeeds, and a missing catalogue, a bad signature and an older serial each refuse.

**How the namespace is made, and why not a veth pair or Podman.** The spec allows `unshare -n` plus a veth pair, or Podman's internal network. This test uses the simpler thing that gives the same guarantee: `unshare -r -n` (a fresh user and network namespace; measured on the maintainer's laptop to work unprivileged, with `lo` as its only interface and `ENETUNREACH` for any address outside it), with **both** the Bunker's server and the engine run inside it. "Only the Bunker is reachable" then holds by construction rather than by a firewall rule: there is no other interface to reach anything on, and the test probes it (the internet, the loopback publisher of the first phase, an unused loopback port) before it believes the rest. Where unprivileged user namespaces are refused (GitHub-hosted `ubuntu-24.04` restricts them with AppArmor), the harness falls back to `sudo -n unshare -n`, which hosted runners allow; where neither works (the distro-matrix containers, an unprivileged laptop) the tests skip with the reason. The repository's CI is GYST's `python-ci`, which runs `test-command` on the hosted runners and in the distro containers and has no container-run job of its own, so this is the one mechanism that needs no new job and no new GYST pin. *Not measured:* that `sudo -n unshare -n` works on a hosted runner (it is documented to; the first CI run decides).

**The test runs the engine, which writes state.** It only runs when `BUNKER_NETNS_TEST=1` **and** (`CI=true` or `BUNKER_NETNS_THROWAWAY=1`): never on a machine whose Hammunition station matters (an earlier fixture capture overwrote a real station file through a `HOME` override). Every engine step gets a `HOME` and `XDG_*` inside `tmp_path`, and under `unshare -r` the engine's user is uid 0 in a namespace that owns nothing outside it.

**Files:**
- Create: `tests/netns.py`, `tests/netns_scenario.py`, `tests/test_offline_integration.py`
- Modify: `.github/workflows/ci.yml` (the `install-command` and `test-command` values of the `ci` job only; the `uses:` pin line is not touched), `CONTRIBUTING.md` (the checks table, a section), `CHANGELOG.md`
- Test: `tests/test_offline_integration.py`

**Interfaces:**
- Consumes: `bunker.server.make_server`, `bunker.run.run`, `bunker.publish.publish`, `bunker.signing.SshKeygenBackend`, `tests.realkeys.make_file_key`, `tests.conftest.Publisher`; Plan A: `hammunition.signers`, the engine's `mirror enrol` and `install --offline`.
- Produces: `tests.netns.allowed() -> bool`; `isolation_prefix() -> list[str] | None`; `run_scenario(spec: dict[str, Any], prefix: Sequence[str], *, timeout: float = 600.0) -> Outcome`; `Outcome(probes: dict[str, bool], steps: list[StepResult], bunker_log: str)` with `step(name)` and `isolated()`; `StepResult(name, returncode, stdout, stderr)`; `EngineDriver(command: str, catalog: Path)` with `enrol(url, fingerprint)` and `install(unit)`; `make_engine_catalog(source: Path, dest: Path, *, url: str, data: bytes) -> None`.

> **Which parts need the Plan A engine release.** Needs nothing: `tests/netns.py`, `tests/netns_scenario.py` and `test_the_namespace_reaches_only_the_bunker` (it fetches the catalogue and fails to fetch the internet from inside the namespace, with the Python standard library). Needs Plan A: the other four tests (`hammunition.signers` is imported first, so they skip on v0.21.0) and, inside them, the engine command lines in `EngineDriver`: `mirror enrol URL` reading the typed fingerprint on stdin (the spec: "asks the operator to type the fingerprint … as the D-040 repository-key step does") and `install UNIT --offline --yes`. If Plan A spells either differently, `EngineDriver` is the only place to change. Also assumed, unread: a `data` unit installs without root (`unshare -r` makes the engine uid 0 in the namespace, which may be enough for a user data prefix and not for a system one); the first run on the Plan A engine settles it.

- [ ] **Step 1: The harness**

Create `tests/netns.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run a scenario in a network namespace where only the Bunker answers.

The scenario (``tests/netns_scenario.py``) starts the Bunker's server and then
runs the engine's commands, all inside one fresh network namespace whose only
interface is loopback. See the plan (Task 10) for why this and not a veth pair.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCENARIO = ROOT / "tests" / "netns_scenario.py"


def allowed() -> bool:
    """Only where the engine may write state into a throwaway HOME."""
    return os.environ.get("BUNKER_NETNS_TEST") == "1" and (
        os.environ.get("CI") == "true" or os.environ.get("BUNKER_NETNS_THROWAWAY") == "1"
    )


def isolation_prefix() -> list[str] | None:
    """An argv prefix that runs a command in a fresh network namespace, or None."""
    if shutil.which("unshare") is None:
        return None
    for prefix in (["unshare", "-r", "-n"], ["sudo", "-n", "unshare", "-n"]):
        if prefix[0] == "sudo" and shutil.which("sudo") is None:
            continue
        done = subprocess.run([*prefix, "true"], capture_output=True, check=False, timeout=60)
        if done.returncode == 0:
            return prefix
    return None


@dataclass
class StepResult:
    name: str
    returncode: int
    stdout: str
    stderr: str


@dataclass
class Outcome:
    probes: dict[str, bool]
    steps: list[StepResult]
    bunker_log: str
    """The server's request lines (stderr of the namespace process)."""

    def step(self, name: str) -> StepResult:
        return next(s for s in self.steps if s.name == name)

    def isolated(self) -> bool:
        return self.probes == {
            "internet unreachable": True,
            "first-phase publisher unreachable": True,
            "bunker reachable": True,
        }

    def explain(self) -> str:
        parts = [f"probes: {self.probes}"]
        for s in self.steps:
            parts.append(f"--- {s.name}: exit {s.returncode}\n{s.stdout}\n{s.stderr}")
        parts.append(f"--- bunker log\n{self.bunker_log}")
        return "\n".join(parts)


def run_scenario(spec: dict[str, Any], prefix: Sequence[str], *, timeout: float = 600.0) -> Outcome:
    results = Path(spec["results"])
    spec_path = results.with_suffix(".spec.json")
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    pythonpath = f"{ROOT / 'src'}{os.pathsep}{ROOT}"
    core = [sys.executable, str(SCENARIO), str(spec_path)]
    if prefix[0] == "sudo":  # sudo resets the environment: pass what the scenario needs
        argv = ["sudo", "-n", "env", f"PYTHONPATH={pythonpath}", *prefix[2:], *core]
        env = None
    else:
        argv = [*prefix, *core]
        env = {**os.environ, "PYTHONPATH": pythonpath}
    done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, check=False)
    if not results.exists():
        raise AssertionError(f"the scenario died (exit {done.returncode}):\n{done.stderr}")
    document = json.loads(results.read_text(encoding="utf-8"))
    return Outcome(
        probes=document["probes"],
        steps=[StepResult(**s) for s in document["steps"]],
        bunker_log=done.stderr,
    )


class EngineDriver:
    """The one place this test knows the engine's command line. Plan A's forms,
    taken from the spec and not run: ``mirror enrol URL`` reads the fingerprint
    the operator types on stdin; ``install UNIT --offline --yes`` plans from the
    enrolled Bunker's catalogue and contacts no publisher."""

    def __init__(self, command: str, catalog: Path) -> None:
        self.command = command
        self.catalog = catalog

    def _base(self) -> list[str]:
        return [self.command, "--catalog", str(self.catalog)]

    def enrol(self, url: str, fingerprint: str) -> dict[str, Any]:
        return {"name": "enrol", "argv": [*self._base(), "mirror", "enrol", url], "stdin": fingerprint + "\n"}

    def install(self, unit: str) -> dict[str, Any]:
        return {"name": "install", "argv": [*self._base(), "install", unit, "--offline", "--yes"]}


def fixture_zip() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("cty.dat", "Monaco: 14: 27: EU: 43.73: -7.40: -1.0: 3A:\n")
    return out.getvalue()


def make_engine_catalog(source: Path, dest: Path, *, url: str, data: bytes) -> None:
    """A copy of the engine's catalog whose ``country-files`` unit pins *data* at
    *url* (a loopback publisher): the unit's shape is
    ``install[0].install.artifacts[0]`` with ``url``, ``sha256`` and ``size``
    (catalog/packages/country-files.yaml in the engine)."""
    shutil.copytree(source, dest)
    unit = dest / "packages" / "country-files.yaml"
    document = yaml.safe_load(unit.read_text(encoding="utf-8"))
    artifact = document["install"][0]["install"]["artifacts"][0]
    artifact.update(url=url, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    unit.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
```

Create `tests/netns_scenario.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Runs inside the network namespace (``tests/netns.py`` starts it with
``unshare``): brings loopback up, serves the Bunker's volume, probes what can
and cannot be reached, then runs the scenario's steps in order.

The spec is a JSON file: ``root`` (the volume), ``port``, ``publisher_port``
(where the first phase's publisher listened in the outer namespace), ``results``
(where to write the answers), ``env`` (the whole environment of every engine
step: nothing is inherited) and ``steps``, each either a command
(``name``, ``argv``, ``stdin``) or an ``edit`` of the volume (``delete`` a file,
or ``copy_file`` ``from`` an absolute path ``to`` a path under the volume).
Server request lines go to stderr, which the test reads.
"""

from __future__ import annotations

import fcntl
import json
import shutil
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from bunker import server


def loopback_up() -> None:
    """``ip link set lo up`` without needing ``ip``: the flags ioctl."""
    get_flags, set_flags, up = 0x8913, 0x8914, 0x1
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        request = struct.pack("16sH14s", b"lo", 0, b"")
        flags = struct.unpack("16sH14s", fcntl.ioctl(s.fileno(), get_flags, request))[1]
        fcntl.ioctl(s.fileno(), set_flags, struct.pack("16sH14s", b"lo", flags | up, b""))


def reachable(address: tuple[str, int]) -> bool:
    try:
        socket.create_connection(address, timeout=2).close()
    except OSError:
        return False
    return True


def edit(root: Path, change: dict[str, Any]) -> None:
    if "delete" in change:
        (root / change["delete"]).unlink()
    else:
        shutil.copyfile(change["copy_file"]["from"], root / change["copy_file"]["to"])


def main(spec_path: str) -> int:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    root = Path(spec["root"])
    loopback_up()
    httpd = server.make_server(root, "127.0.0.1", spec["port"])
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    probes = {
        "internet unreachable": not reachable(("1.1.1.1", 53)),
        "first-phase publisher unreachable": not reachable(("127.0.0.1", spec["publisher_port"])),
        "bunker reachable": reachable(("127.0.0.1", spec["port"])),
    }
    steps: list[dict[str, Any]] = []
    for step in spec["steps"]:
        if "edit" in step:
            edit(root, step["edit"])
            continue
        done = subprocess.run(  # noqa: S603 - the test's own argv
            step["argv"], input=step.get("stdin", ""), capture_output=True, text=True,
            env=spec["env"], timeout=900, check=False,
        )  # fmt: skip
        steps.append(
            {"name": step["name"], "returncode": done.returncode, "stdout": done.stdout, "stderr": done.stderr}
        )
    httpd.shutdown()
    Path(spec["results"]).write_text(json.dumps({"probes": probes, "steps": steps}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
```

- [ ] **Step 2: The harness test, which needs no engine**

Create `tests/test_offline_integration.py` with the shared pieces and the first test:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The whole chain with the internet gone. See ``tests/netns.py`` and Task 10 of
the plan for how the namespace is made, what runs in it and what is assumed
about the engine. Marked ``real_signing``: the catalogue is signed with a real
key and the engine verifies it with the real ``ssh-keygen``."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bunker import config, publish, run
from bunker.index import Index
from bunker.signing import SshKeygenBackend
from tests import netns, plan_a, realkeys
from tests.conftest import Publisher
from tests.helpers import config_text

pytestmark = pytest.mark.real_signing

PORT = 18080


@pytest.fixture(scope="module")
def isolation() -> list[str]:
    if not netns.allowed():
        pytest.skip(
            "set BUNKER_NETNS_TEST=1 and (CI=true or BUNKER_NETNS_THROWAWAY=1): this test runs "
            "the engine with a throwaway HOME and must not run where a real station exists"
        )
    prefix = netns.isolation_prefix()
    if prefix is None:
        pytest.skip("cannot create a network namespace here (`unshare -r -n` and `sudo -n unshare -n` both fail)")
    return prefix


def tiny_volume(tmp: Path) -> Path:
    root = tmp / "vol"
    realkeys.make_file_key(root)
    path = tmp / "bunker.toml"
    path.write_text(config_text(str(root)))
    publish.publish(config.load(path), Index(engine_version="0.22.0"), generated="2026-10-07T12:00:00Z")
    return root


def test_the_namespace_reaches_only_the_bunker(tmp_path: Path, isolation: list[str]) -> None:
    root = tiny_volume(tmp_path)
    fetch = "import sys, urllib.request; print(urllib.request.urlopen(sys.argv[1], timeout=3).status)"
    outcome = netns.run_scenario(
        {
            "root": str(root),
            "port": PORT,
            "publisher_port": 1,
            "results": str(tmp_path / "results.json"),
            "env": {"PATH": os.environ.get("PATH", "")},
            "steps": [
                {"name": "the Bunker", "argv": [sys.executable, "-c", fetch, f"http://127.0.0.1:{PORT}/catalogue.json"]},
                {"name": "the internet", "argv": [sys.executable, "-c", fetch, "http://1.1.1.1/"]},
            ],
        },
        isolation,
    )
    assert outcome.isolated(), outcome.explain()
    assert outcome.step("the Bunker").stdout.strip() == "200", outcome.explain()
    assert outcome.step("the internet").returncode != 0, "the internet must not answer in here"
    assert "GET /catalogue.json" in outcome.bunker_log
```

Run: `BUNKER_NETNS_TEST=1 BUNKER_NETNS_THROWAWAY=1 .venv/bin/python -m pytest tests/test_offline_integration.py -q -x` on a machine with unprivileged user namespaces — Expected: PASS. Without the environment variables: `1 skipped` with the reason printed (run it once that way too: a skip that says why is part of the contract). Falsify the isolation: temporarily run the scenario with a plain `[]` prefix (no `unshare`) and see `outcome.isolated()` FAIL on `internet unreachable`; restore.

- [ ] **Step 3: The four engine tests**

Append to `tests/test_offline_integration.py`:

```python
@dataclass
class Fleet:
    volume: Path
    """A published Bunker volume at serial 2, holding the fixture ``country-files``."""
    catalog: Path
    engine: str
    fingerprint: str
    older: Path
    """Serial 1's catalogue and signature, validly signed, kept to replay."""
    bad_signature: Path
    """A well-formed signature by the Bunker's key over different bytes."""
    publisher_port: int


@pytest.fixture(scope="module")
def fleet(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Fleet]:
    plan_a.module("hammunition.signers")
    source = os.environ.get("HAMMUNITION_CATALOG")
    if not source or not Path(source).is_dir():
        pytest.skip("HAMMUNITION_CATALOG does not name the engine's catalog directory")
    engine = shutil.which("hammunition") or str(Path(sys.executable).with_name("hammunition"))
    base = tmp_path_factory.mktemp("fleet")
    data = netns.fixture_zip()
    publisher = Publisher()
    try:
        catalog = base / "catalog"
        netns.make_engine_catalog(Path(source), catalog, url=publisher.put("/cf/bigcty-fixture.zip", data), data=data)
        root = base / "vol"
        key = realkeys.make_file_key(root)
        cfg_path = base / "bunker.toml"
        cfg_path.write_text(
            config_text(
                str(root),
                selection='map_regions = []\nunits = ["country-files"]',
                extra=f'[engine]\ncommand = "{engine}"\ncatalog = "{catalog}"\n[bunker]\nname = "shack-1"\n',
            )
        )
        cfg = config.load(cfg_path)
        now = datetime.now(UTC)
        first = run.run(cfg, now=lambda: now - timedelta(days=9))
        assert first.exit_code == 0 and first.counts()["fetched"] >= 1, first.summary_lines()
        older = base / "serial1"
        (older / "catalogue.sig.d").mkdir(parents=True)
        shutil.copy(root / "catalogue.json", older / "catalogue.json")
        shutil.copy(root / "catalogue.sig.d" / "1.sig", older / "catalogue.sig.d" / "1.sig")
        second = run.run(cfg, now=lambda: now)  # nine days on: signed again
        assert second.catalogue is not None and second.catalogue["serial"] == 2
        bad = base / "bad.sig"
        bad.write_bytes(SshKeygenBackend().sign(key, b"some other bytes", timeout=30))
        yield Fleet(root, catalog, engine, key.id, older, bad, int(publisher.server.server_address[1]))
    finally:
        publisher.close()


def case(tmp_path: Path, fleet: Fleet, isolation: list[str], name: str, port: int, steps: list[dict[str, Any]]) -> netns.Outcome:
    work = tmp_path / name
    shutil.copytree(fleet.volume, work / "vol", ignore=shutil.ignore_patterns(".incoming", ".lock"))
    home = work / "home"
    assert tmp_path in home.parents, "the engine must never be given a real home"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "HAMMUNITION_CATALOG": str(fleet.catalog),
        "LANG": "C.UTF-8",
    }
    home.mkdir(parents=True)
    return netns.run_scenario(
        {
            "root": str(work / "vol"),
            "port": port,
            "publisher_port": fleet.publisher_port,
            "results": str(work / "results.json"),
            "env": env,
            "steps": steps,
        },
        isolation,
    )


def driver(fleet: Fleet) -> netns.EngineDriver:
    return netns.EngineDriver(fleet.engine, fleet.catalog)


def mirror(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def test_an_offline_data_unit_install_succeeds_from_the_bunker(
    tmp_path: Path, fleet: Fleet, isolation: list[str]
) -> None:
    d = driver(fleet)
    outcome = case(tmp_path, fleet, isolation, "ok", PORT + 1, [d.enrol(mirror(PORT + 1), fleet.fingerprint), d.install("country-files")])
    assert outcome.isolated(), outcome.explain()
    assert [outcome.step(n).returncode for n in ("enrol", "install")] == [0, 0], outcome.explain()
    for needle in ("GET /catalogue.json", "GET /catalogue.sig.d/1.sig", "GET /country-files/"):
        assert needle in outcome.bunker_log, f"the bytes did not come from the Bunker: {needle}\n{outcome.explain()}"


def refused(outcome: netns.Outcome, keyword: str) -> None:
    assert outcome.isolated(), outcome.explain()
    assert outcome.step("enrol").returncode == 0, outcome.explain()
    install = outcome.step("install")
    assert install.returncode != 0, f"the install must refuse\n{outcome.explain()}"
    assert keyword in (install.stdout + install.stderr).lower(), outcome.explain()


def test_a_missing_catalogue_refuses(tmp_path: Path, fleet: Fleet, isolation: list[str]) -> None:
    d = driver(fleet)
    outcome = case(
        tmp_path, fleet, isolation, "missing", PORT + 2,
        [d.enrol(mirror(PORT + 2), fleet.fingerprint),
         {"edit": {"delete": "catalogue.json"}},
         d.install("country-files")],
    )  # fmt: skip
    refused(outcome, "catalogue")


def test_a_bad_signature_refuses(tmp_path: Path, fleet: Fleet, isolation: list[str]) -> None:
    d = driver(fleet)
    outcome = case(
        tmp_path, fleet, isolation, "badsig", PORT + 3,
        [d.enrol(mirror(PORT + 3), fleet.fingerprint),
         {"edit": {"copy_file": {"from": str(fleet.bad_signature), "to": "catalogue.sig.d/1.sig"}}},
         d.install("country-files")],
    )  # fmt: skip
    refused(outcome, "signature")


def test_an_older_serial_refuses_and_names_the_remedy(tmp_path: Path, fleet: Fleet, isolation: list[str]) -> None:
    d = driver(fleet)
    outcome = case(
        tmp_path, fleet, isolation, "older", PORT + 4,
        [d.enrol(mirror(PORT + 4), fleet.fingerprint),
         {"edit": {"copy_file": {"from": str(fleet.older / "catalogue.json"), "to": "catalogue.json"}}},
         {"edit": {"copy_file": {"from": str(fleet.older / "catalogue.sig.d/1.sig"), "to": "catalogue.sig.d/1.sig"}}},
         d.install("country-files")],
    )  # fmt: skip
    refused(outcome, "accept-older")
```

Run: `BUNKER_NETNS_TEST=1 BUNKER_NETNS_THROWAWAY=1 HAMMUNITION_CATALOG=/path/to/Hammunition/catalog .venv/bin/python -m pytest tests/test_offline_integration.py -q` against the Plan A checkout in a throwaway VM — Expected: all five PASS. On the pinned v0.21.0: the four engine tests SKIP (`hammunition.signers` comes with the Plan A engine release) and the harness test passes.

- [ ] **Step 4: CI, CONTRIBUTING, the GYST issue**

`.github/workflows/ci.yml` — change only these two values inside the `ci` job's `with:` (leave the `uses:` line, `runners`, `distros`, `python-versions` and everything else byte-identical):

```yaml
      install-command: |
        python -m pip install --upgrade "pip>=25.3"
        pip install -e ".[dev]"
        if command -v git >/dev/null 2>&1; then
          git clone --depth 1 --branch v0.22.0 https://github.com/Renegade-Penguin/Hammunition "$RUNNER_TEMP/hammunition" \
            && echo "HAMMUNITION_CATALOG=$RUNNER_TEMP/hammunition/catalog" >> "$GITHUB_ENV" \
            || echo "no engine catalog: the offline integration test will skip"
        fi
      test-command: BUNKER_NETNS_TEST=1 pytest -W error::DeprecationWarning
```

(The test additionally needs `CI=true`, which GitHub sets. Unmeasured: that `$GITHUB_ENV` carries into the `test-command` step of GYST's `python-ci` and that `RUNNER_TEMP` exists in its distro containers; either failure makes the four engine tests skip, which the log says.) Run `.venv/bin/python -m pytest tests/test_packaging.py -q` — Expected: PASS (`test_gyst_pins_agree` and the pin tests read the `uses:` lines, which are unchanged).

`CONTRIBUTING.md`: add a row to *What the checks hold*: "| `tests/test_offline_integration.py` | the whole chain with the internet gone: a signed Bunker served inside a network namespace where nothing else answers, the pinned engine installing a data unit from it, and a missing catalogue, a bad signature and an older serial each refused |"; and a section "The offline integration test" saying: it needs `unshare -r -n` (or passwordless `sudo`), the engine's catalog directory in `HAMMUNITION_CATALOG`, and the two environment variables; that it **writes engine state into a throwaway HOME and must never be run on a machine whose Hammunition station matters** (use the CI runner or a VM); and that the harness is local until GYST has a reusable "run with no network except named hosts" step.

File the GYST issue (the spec asks for it when the plan is written; it is the only step here that is not a commit). Check the account first (`ghwho`, `ghsw` to switch: GYST is a personal-account repository), then:

```bash
gh issue create --repo ChiefGyk3D/git-your-ship-together \
  --title "A reusable step that runs a command with no network except named hosts" \
  --body "Several suite repositories need to prove that something works offline: the Hammunition Bunker's integration test runs the engine in a network namespace where only the Bunker answers (unshare -r -n, falling back to sudo -n unshare -n on hosted runners). That harness is local to the Bunker repository today (tests/netns.py). A reusable GYST step or workflow input that runs a command with no network except named hosts would let other repositories (Hammunition itself, Penguin Overlord, the offline docs server) call it instead of copying it. Measured: unshare -r -n works unprivileged on a Debian 13 laptop; not measured: sudo -n unshare -n on ubuntu-24.04 hosted runners, and inside container jobs."
```

`CHANGELOG.md`: "- An integration test that runs the pinned engine in a network namespace where only the Bunker answers: an offline data-unit install succeeds; a missing catalogue, a bad signature and an older serial each refuse. It runs only where `BUNKER_NETNS_TEST=1` and a throwaway environment is declared, and `ci.yml`'s install and test commands set that up (the `uses:` pin is untouched)."

Run: `make check; echo "exit=$?"` — Expected: `exit=0`.

```bash
git add tests/netns.py tests/netns_scenario.py tests/test_offline_integration.py .github/workflows/ci.yml CONTRIBUTING.md CHANGELOG.md
git commit -m "Integration test: the pinned engine offline against a signed Bunker

A network namespace with only loopback holds the Bunker's server and the
engine; an offline data-unit install succeeds, and a missing catalogue, a bad
signature and an older serial each refuse. Gated to throwaway environments."
```

### Task 11: Pin the Plan A engine release

Everything above was written against a local checkout of the Plan A branch. This task makes that the pinned engine: the tag moves in every place the repository names it (held together by tests), the floor rises to the release that has `hammunition.catalogue`, `hammunition.keystrength`, `hammunition.signers` and the mirror-first methods, the skips that waited for it become failures, and the docs stop saying a mirror cannot make an install work offline. **Needs the Plan A release to exist.** This plan assumes it is tagged `v0.22.0` (the contract's example `engine_version`); if it is another number, use that number everywhere `0.22.0` appears below. Cutting the Bunker release itself (`__version__`, the image tags, moving the changelog under a version) is the maintainer's step per CONTRIBUTING.md and is not done here.

**Files:**
- Modify: `src/bunker/__init__.py` (14-33), `src/bunker/enginelib.py` (`validate_catalogue`), `pyproject.toml` (23), `Dockerfile` (23, 26), `.github/workflows/live.yml` (31), `.github/workflows/ci.yml` (comment 8-9 and the Task 10 `--branch`), `README.md` (25, 80), `CONTRIBUTING.md` (94), `CLAUDE.md`, `docs/reference.md` (139, 257), `docs/guide.md` (26-32, 183-187), `CHANGELOG.md`, `tests/plan_a.py`, `tests/helpers.py` (10), `tests/conftest.py` (87), `tests/test_kinds.py` (113), `tests/test_doctor.py` (39, 45), `tests/test_engine.py` (103, 259-262), `tests/test_run.py` (the `engine_version` assertion Task 1 wrote), `tests/test_repo_hygiene.py` (75-91), `tests/golden/doctor.json`, `tests/golden/run.json`, `tests/golden/status.json`, `tests/golden/keys.json`
- Test: `tests/test_repo_hygiene.py`, plus the whole suite on a fresh venv

**Interfaces:**
- Consumes: the Plan A release tag and its tag archive.
- Produces: `bunker.ENGINE_CONTRACT = "0.22.0"`, `bunker.ENGINE_FLOOR = "0.22.0"`; `plan_a.REQUIRE_PLAN_A = True`; `enginelib.validate_catalogue` that raises instead of skipping when the module is missing.

- [ ] **Step 1: Measure the release (CONTRIBUTING.md, "Cutting a release", step 2)**

```bash
tmp="$(mktemp -d)"
curl -fLo "$tmp/engine.tar.gz" https://github.com/Renegade-Penguin/Hammunition/archive/refs/tags/v0.22.0.tar.gz
sha256sum "$tmp/engine.tar.gz"
curl -fLo "$tmp/engine2.tar.gz" https://github.com/Renegade-Penguin/Hammunition/archive/refs/tags/v0.22.0.tar.gz
sha256sum "$tmp/engine2.tar.gz"
gzip -dc "$tmp/engine.tar.gz" | git get-tar-commit-id
git ls-remote https://github.com/Renegade-Penguin/Hammunition 'refs/tags/v0.22.0^{}'
```

Expected: the two digests are identical (measured twice), and the commit id in the archive equals the tag's commit from `ls-remote`. If either differs, stop: do not fill the digest. Keep `$tmp` for Step 4.

- [ ] **Step 2: Write the failing tests**

In `tests/test_repo_hygiene.py` add (after `test_engine_floor_agrees`):

```python
def test_every_place_that_names_the_engine_names_the_pinned_release() -> None:
    contract = re.escape(bunker.ENGINE_CONTRACT)
    live = (ROOT / ".github" / "workflows" / "live.yml").read_text(encoding="utf-8")
    assert re.search(rf"^\s+ref: v{contract}$", live, re.M), "live.yml checks out another engine"
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert re.search(rf"--branch v{contract} ", ci), "ci.yml fetches another engine's catalog"
    assert f"Hammunition v{bunker.ENGINE_CONTRACT}" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"tags/v{bunker.ENGINE_CONTRACT}.tar.gz" in (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")


def test_the_floor_is_the_release_that_has_the_catalogue_modules() -> None:
    assert bunker.ENGINE_FLOOR == "0.22.0"


def test_the_pinned_engine_has_everything_the_catalogue_needs() -> None:
    import importlib

    from bunker.enginelib import Fetcher

    for module in ("hammunition.catalogue", "hammunition.keystrength", "hammunition.signers"):
        importlib.import_module(module)
    assert hasattr(Fetcher, "fetch_etag") and hasattr(Fetcher, "fetch_sized")


def test_the_plan_a_skips_are_failures_now() -> None:
    from tests import plan_a

    assert plan_a.REQUIRE_PLAN_A is True
```

Run: `.venv/bin/python -m pytest tests/test_repo_hygiene.py -q` — Expected: FAIL: `test_the_floor_is_the_release_that_has_the_catalogue_modules` (`'0.19.0' != '0.22.0'`) and `test_the_plan_a_skips_are_failures_now`.

- [ ] **Step 3: Move the pin**

`src/bunker/__init__.py`: set `ENGINE_FLOOR = "0.22.0"` and `ENGINE_CONTRACT = "0.22.0"`, and rewrite the two comment blocks above them (14-33) to say: the floor is the oldest release with `hammunition.catalogue`, `hammunition.keystrength`, `hammunition.signers`, `Fetcher.fetch_etag` and `Fetcher.fetch_sized` (the Bunker cannot publish or classify a key without them), and the contract is the newest release whose `artifacts` document the check table was written against; keep the sentence that `ENGINE_CONTRACT` is the pin and `tests/test_repo_hygiene.py` holds the three together.

```bash
sed -i 's#Hammunition@v0.21.0#Hammunition@v0.22.0#' pyproject.toml
sed -i 's#^ARG ENGINE_VERSION=0.21.0#ARG ENGINE_VERSION=0.22.0#' Dockerfile
sed -i 's#ref: v0.21.0#ref: v0.22.0#' .github/workflows/live.yml
sed -i 's#--branch v0.21.0 #--branch v0.22.0 #; s#(Hammunition v0.21.0)#(Hammunition v0.22.0)#' .github/workflows/ci.yml
sed -i 's#Hammunition v0.21.0#Hammunition v0.22.0#' README.md
sed -i 's#tags/v0.21.0.tar.gz#tags/v0.22.0.tar.gz#' CONTRIBUTING.md
digest="$(sha256sum "$tmp/engine.tar.gz" | cut -d' ' -f1)"
sed -i "s#^ARG ENGINE_SHA256=.*#ARG ENGINE_SHA256=${digest}#" Dockerfile
git diff --stat
```

Expected: eight files changed; `git diff Dockerfile` shows `ENGINE_VERSION` and `ENGINE_SHA256` only (the digest equal to Step 1's). The `uses:` pin lines of the workflows are untouched (`git diff .github` shows the two `ref`/`--branch` lines and the comment).

Update the `ci.yml` comment (lines 8-9) to say the pinned engine "has `hammunition.catalogue`, `keystrength` and `signers`, the mirror-first fetch methods and every check kind's engine method".

- [ ] **Step 4: Make the waits strict**

`tests/plan_a.py`: `REQUIRE_PLAN_A = True`. `src/bunker/enginelib.py`:

```python
def validate_catalogue(data: bytes) -> None:
    """Raise unless the engine's own reader accepts *data*: the Bunker never
    publishes a document a laptop would refuse."""
    catalogue_module().parse(data)
```

Constants that stand for "the engine's version" in tests: `tests/helpers.py` line 10 `ENGINE_VERSION = "0.22.0"`; `tests/conftest.py` line 87 default `"0.22.0"`; `tests/test_kinds.py` line 113 default `"0.22.0"`; `tests/test_doctor.py` line 39 `assert ENGINE_VERSION in ...` (import it from `tests.helpers`) and line 45 `assert not check.ok and ENGINE_FLOOR in check.detail` (import `ENGINE_FLOOR` from `bunker`); `tests/test_engine.py` line 103 `assert listing.engine_version == ENGINE_VERSION`, and the `test_meets_floor` parameters (259-262) become `[("0.22.0", True), ("0.22.1", True), ("1.0.0", True), ("0.21.9", False), ("0.19.0", False)]`; `tests/test_run.py`: the Task 1 assertion `raw["engine_version"] == "0.21.0"` becomes `== "0.22.0"`. Leave `tests/data/engine-v0.21.0-repeater-snapshots.json` and the tests that name v0.21.0 as a capture alone: they record what that release printed.

Then regenerate the goldens on a fresh venv installed from the pinned tag (the environment the maintainer's CI will have):

```bash
rm -rf .venv && make venv
BUNKER_UPDATE_GOLDENS=1 .venv/bin/python -m pytest tests/test_cli.py -q
git diff tests/golden
```

Expected diff: `doctor.json` (`Hammunition 0.22.0 answers (floor 0.22.0)`), `run.json`, `status.json` (`engine_version`) and `keys.json` (the same). Nothing else may change; read it.

- [ ] **Step 5: Docs**

`docs/reference.md` line 139: the floor is now v0.22.0 (the first release with the catalogue modules and `fetch_etag`/`fetch_sized`) and the pin is v0.22.0; line 257: "the engine this Bunker pins (v0.22.0) emits it". `docs/guide.md` lines 26-32: the laptop needs Hammunition 0.22.0 or later for the signed catalogue and offline planning; the older sentences about 0.19.0 and 0.21.0 are replaced by one: older engines still take files from a mirror (D-070) but cannot read the catalogue or plan offline. Replace the paragraph at 183-187 ("**A mirror does not make an install work offline.** ...") with:

```markdown
**Offline planning.** `hammunition mirror enrol http://<nas-address>:8080/` fetches the catalogue and its
signatures, shows each signing key (algorithm, size, hardware or file, fingerprint, any weak-key warning)
and asks you to type the fingerprint of at least one, as the repository-key step does. From then on
`hammunition install --offline` plans from the repository's pins and this Bunker's signed catalogue and
contacts no publisher; without the flag, a publisher that stays unreachable falls back to the catalogue
and the plan says so. A signature means "this Bunker recorded this", never more: a pinned artifact is
still checked against the repository's sha256, and what the Bunker could only record (a publisher's
MD5, an ETag) is checked against that and said so in the plan. The catalogue is replaced by a newer
serial and refused if the serial goes backwards (`hammunition mirror accept-older` after you have
restored the Bunker from a backup). Hammunition's own
[LAN mirror guide](https://github.com/Renegade-Penguin/Hammunition/blob/main/docs/guides/lan-mirror.md)
describes the laptop side.
```

`README.md` status block (line 25 area): the engine paragraph names Hammunition v0.22.0 and "every check kind the document can emit, the catalogue modules and the mirror-first fetch methods". `CLAUDE.md` invariants: change "**One verifier.** Every download goes through the engine's own `hammunition.fetch.Fetcher`" to also say "and every catalogue the Bunker writes must pass the engine's own `hammunition.catalogue.parse()` before it is published (`bunker.publish`)", and the Layout block to add `signing, keys, publish, enrol, inputs, gitbundle, export`. `CHANGELOG.md` under *Unreleased → Changed*: "- The engine pin is Hammunition v0.22.0 (was v0.21.0): `ENGINE_CONTRACT`, `ENGINE_FLOOR` (now v0.22.0: the Bunker needs `hammunition.catalogue`, `hammunition.keystrength`, `hammunition.signers`, `Fetcher.fetch_etag` and `Fetcher.fetch_sized`), `pyproject.toml`, the Dockerfile (tag and the tag archive's sha256, measured twice, commit equal to the tag's), the live workflow's ref and `ci.yml`'s catalog clone. `bunker doctor` reports an engine below the floor. The skips that waited for the release are failures."

- [ ] **Step 6: Run everything on the pinned engine and commit**

```bash
make check; echo "exit=$?"
```

Expected: `exit=0`, with no test skipped for a missing Plan A module: `.venv/bin/python -m pytest -q -rs 2>&1 | grep -i "plan a"` prints nothing (this `grep` reads the report; the gate is the `exit=` line above, not this). Also run the integration test where it can run (a throwaway VM or the CI runner): `BUNKER_NETNS_TEST=1 BUNKER_NETNS_THROWAWAY=1 HAMMUNITION_CATALOG=<catalog of v0.22.0> .venv/bin/python -m pytest tests/test_offline_integration.py -q` — Expected: five PASS. If an engine command line in `tests/netns.py::EngineDriver` is wrong, fix it there and re-run; that is the end of the Plan A assumptions.

```bash
git add src/bunker/__init__.py src/bunker/enginelib.py pyproject.toml Dockerfile .github/workflows/live.yml .github/workflows/ci.yml README.md CONTRIBUTING.md CLAUDE.md docs/reference.md docs/guide.md CHANGELOG.md tests
git commit -m "Pin Hammunition v0.22.0; the floor rises to the release with the catalogue modules

ENGINE_CONTRACT, ENGINE_FLOOR, the pyproject pin, the Dockerfile tag and tag
archive digest, the live workflow ref and the CI catalog clone move together,
held by tests; the Plan A skips become failures; the guide describes offline
planning instead of saying a mirror cannot make an install work offline."
```

---

## Spec coverage

| Spec section | Task |
|---|---|
| Rulings 1-3 (order, B then C then USB, personal and group) | 1 (`bunker.mode`), 6 (group), 8 (the drive layout) |
| Ruling 4 (the Bunker as a base station; the catalogue is its general record) | 1 (the document), 4 and 5 (what it records), 7 (what it shows) |
| Ruling 5 (hardware keys built in, recommended, never required; any FIDO2 authenticator) | 2 (backends), 3 (setup, `keys`), 9 (container, guide) |
| Ruling 6 (key strength order, RSA ≤ 2048 warned) | 3 (generation order, `describe`), 7 (page and status), 3 (doctor) |
| Ruling 7 (security-key components installed and checked) | 3 (Dockerfile packages, `signing` doctor check, token detection); the host `security-keys` profile and PAM are the engine's |
| Scope: catalogue v3 and signatures (Bunker) | 1, 2 |
| Scope: key backends, setup prompt, `bunker keys` | 2, 3 |
| Scope: mirror routes for every remaining data kind, payload and git bundles | 4, 5, 6 |
| Scope: tests including one network-isolated integration test | every task's tests; 10 |
| The catalogue: top-level fields (`serial`, `generated`, `bunker`, `signers`) | 1 |
| The catalogue: per-entry `publisher_*`, `share` | 1 (fields), 4 (publisher facts), 6 (share) |
| The catalogue: `inputs` | 1 (fields), 4 (fetch and record) |
| The catalogue: served at `/catalogue.json` and `/index.json` for one release | 1 (alias), 6 (signatures, inputs) |
| Freshness and rollback (serial never lowered; 30-day age) | 1 (serial high-water file), 2 (re-sign at 7 days so the 30-day warning never fires on a quiet Bunker); the reader's refusal is the engine's |
| Signing (`ssh-keygen -Y sign`, one per key, namespace) | 2 |
| Key backends `file`, `security-key`, `agent` | 2 (signing), 3 (making and registering them) |
| Key strength | 3, 7 |
| Setup and later (`fido2-token -L`, PIV via `pcscd`, `keys list|add|retire`) | 3 |
| The Bunker runs in a container (hidraw, pcscd socket, commented examples) | 9 |
| Enrolment and laptop policy | the engine's; the Bunker's group-mode half is 6 |
| Offline planning | the engine's; the Bunker's inputs and publisher facts are 4, 5 |
| Fetch routes: mirror-first kinds and git bundles | 5 (the Bunker's side), 6 (routes) |
| The `security-keys` profile and `doctor` | the engine's; the Bunker's own `signing` check is 3 |
| Bunker side summary: v3 writer and upgrade | 1 |
| Bunker side summary: signing after every change, status page | 2, 7 |
| Bunker side summary: new fetch kinds | 4, 5 |
| Bunker side summary: `bunker export --to DIR` | 8 |
| Bunker side summary: group-mode filtering | 6 |
| Decision record D-085 | the engine's; the Bunker's changelog entries in every task, and 11 |
| Tests: Bunker unit tests (v2 to v3, signing per backend with a fake seam, `share` filtering) | 1, 2, 6 |
| Tests: one integration test | 10 |
| CI and GYST (integration test local; generic part to GYST) | 10 (the harness stays local; the GYST issue is filed there) |
| Phase 3 (the layout fixed now) | 8 |
| Phase 2 (apt and pip) | out of scope here, as in the spec |
| What is measured and not | each task's notes; 9 (guide), 10 (assumptions), Self-review below |

## Self-review

Written from the Bunker code at `origin/main` (dc668e7, engine pin v0.21.0), the spec and the contract; the plan itself has not been executed against the repository. Things measured in this session, in a scratch directory: `ssh-keygen -Y sign` (stdin, namespace `hammunition-bunker-catalogue`) and `-Y verify` with Ed25519, ECDSA P-384 and RSA 1024/2048/3072 keys on OpenSSH 10.3; a real `ssh-agent` signing through a `.pub` file with no private key beside it (and the fallback to the private key when one *is* beside it, which is why the agent test copies the `.pub` alone); the SHA256 fingerprint computed in pure Python equal to `ssh-keygen -l`; principal and namespace mismatches failing; `ssh-keygen` refusing RSA under 1024 bits; `unshare -r -n` working unprivileged with loopback the only interface and `ENETUNREACH` for any other address; the git clone, `update-ref`, `config --blob` and `bundle create` sequence on local repositories with submodules.

**Found in the contract, not changed:** the contract says the engine renders `no-touch-required` into the allowed-signers line for an `sk-*` key made that way. OpenSSH 10.3 rejects it: `allowed:1: bad options: unknown key option` (an allowed-signers file takes `cert-authority`, `namespaces`, `valid-after` and `valid-before` only), and `ssh-keygen -Y verify -O no-touch-required` is `Invalid option`. An engine that writes that option would fail every verification. The Bunker's own local verification writes no such option. Whether `-Y verify` enforces the user-presence flag of a touch-required sk signature was not measured (no token); the engine owner should decide what "hardware key" means for a verifier if it does not.

**Not grounded in code or output I read:**
- Plan A's `artifacts --json` additions (task A10): `publisher_name`, `publisher_size` and an `inputs` list of `{kind, region, name, url, content}` are this plan's guess from the contract's catalogue names (Task 4); the check names `etag`, `sized`, `git-commit`, the call shapes of `Fetcher.fetch_etag` and `Fetcher.fetch_sized`, and how git pins and their submodules are listed (Task 5). Step 3 of Task 5 and the existing `test_the_table_covers_every_kind_the_installed_engine_can_emit` settle the names the first time they run against the Plan A checkout.
- `hammunition.catalogue.parse()`: that it takes `bytes`, accepts a null `engine_version` on an empty volume, and what it checks of a signer (id against fingerprint, bits against algorithm). `hammunition.keystrength.classify()`: how it refuses DSA (the Bunker wraps any exception) and whether `warning` is `None` or `""` when not weak.
- The engine command lines in the integration test (`mirror enrol URL` reading the fingerprint on stdin, `install UNIT --offline --yes`), whether a `data` install needs a root-owned prefix, and the keywords of the three refusals (`catalogue`, `signature`, `accept-older`; the last is the spec's own).
- The output formats of `fido2-token -L` and `opensc-tool --list-readers` (written from memory), whether `ssh-keygen -t ed25519-sk -O resident` fails in a way that justifies the `ecdsa-sk` retry (the plan retries on any failure and says so), and everything about a real token, a PIV card in the container, the Immurok, hidraw permissions on a Synology and touch timing on a scheduled refresh: nothing here touches hardware and the guide lists each as a bench item.
- That `sudo -n unshare -n` works on a GitHub-hosted runner, that `$GITHUB_ENV` and `$RUNNER_TEMP` are usable from GYST's `python-ci` install step, and that `openssh-client` and `git` exist in the distro-matrix containers (the signing and git tests skip when they do not).
- The Plan A tag is assumed `v0.22.0`.
- The GYST issue for the generic "no network except named hosts" step is written out in Task 10 but not filed: I made no network calls and the account choice (`ghwho`, `ghsw`) is the maintainer's.
- The code blocks are not pre-formatted to ruff's style (line length, `# fmt: skip` placement, `__all__` order under RUF022); run `make format` and `ruff check --fix` before `make check`.
