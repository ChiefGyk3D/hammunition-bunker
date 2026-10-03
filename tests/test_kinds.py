# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every check kind the engine's ``artifacts`` document can emit: the table
that names them, the two kinds the first cut did not verify (``sha1-publisher``
and ``unverified-zip``), the switch that declines unverified artifacts, and
the message when the engine is newer than this Bunker knows.

The ``unverified-zip`` tests build a synthetic register in the real file's
layout with the engine's own table of members and columns
(``hammunition.acma.TABLES``); nothing real is fetched, and the register is
never downloaded.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import zipfile
from html import escape
from pathlib import Path
from typing import Any

import pytest

from bunker import ENGINE_CONTRACT, ENGINE_FLOOR, checks, config, doctor, engine, run, verify
from bunker.checks import KINDS
from bunker.enginelib import BackendError, Fetcher
from bunker.index import load as load_index
from tests.conftest import FakeEngine, Publisher
from tests.helpers import artifacts_doc, config_text, entry
from tests.scene import Clock, sha

needs_sha1 = pytest.mark.skipif(
    not hasattr(Fetcher, "fetch_sha1"),
    reason=f"this engine (floor {ENGINE_FLOOR}) has no Fetcher.fetch_sha1; "
    "a release that carries it (v0.17.0 or later) runs these",
)


def has_acma() -> bool:
    try:
        importlib.import_module("hammunition.acma")
    except ImportError:
        return False
    return hasattr(Fetcher, "fetch_checked")


needs_acma = pytest.mark.skipif(
    not has_acma(),
    reason="the engine at the floor has no hammunition.acma / Fetcher.fetch_checked "
    "(D-074's 2026-10-01 amendment); the release that carries it runs these",
)

LICENCE = "ACMA register licence; client information stays out of derivatives"


def sha1(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


def register_zip(day: int = 1, *, pad: bytes = b"") -> bytes:
    """A synthetic ACMA register in the 2026-10 layout: the members and
    columns the engine's reader needs, a ``client.csv`` that nothing here
    opens, and a stored member of *pad* that only a CRC pass reads."""
    acma = importlib.import_module("hammunition.acma")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:

        def add(name: str, body: bytes) -> None:
            info = zipfile.ZipInfo(name, date_time=(2026, 10, day, 7, 31, 0))
            archive.writestr(info, body)

        add(acma.LICENCE_FILE, b"LICENCE TO USE THE REGISTER (a stand-in)\r\n")
        for table, columns in acma.TABLES.items():
            add(table, (",".join(columns) + "\r\n").encode())
        add("client.csv", b"LICENCEE,ADDRESS\r\nSomeone,1 Example Street\r\n")
        add("padding.csv", pad)
    return out.getvalue()


def flip_in_stored_member(data: bytes, needle: bytes) -> bytes:
    """*data* with one byte of the stored member holding *needle* changed:
    the zip still opens, and only a CRC pass notices."""
    at = data.index(needle)
    return data[:at] + bytes([data[at] ^ 0x01]) + data[at + 1 :]


class Bench:
    """A volume, the fake engine and a loopback publisher for one kind."""

    def __init__(
        self, tmp_path: Path, engine_: FakeEngine, pub: Publisher, *, extra: str = ""
    ) -> None:
        self.tmp, self.engine, self.pub = tmp_path, engine_, pub
        self.root = tmp_path / "vol"
        self.clock = Clock()
        self.extra = extra

    def cfg(self) -> config.Config:
        path = self.tmp / "bunker.toml"
        path.write_text(
            config_text(
                str(self.root),
                selection="map_regions = []",
                extra='[schedule]\ndefault = "daily"\n' + self.extra,
            )
        )
        return config.load(path)

    def list(self, entries: list[dict[str, Any]], *, engine_version: str = "0.19.0") -> None:
        self.engine.set_doc(artifacts_doc(entries, engine=engine_version))

    def run(self, **kw: Any) -> run.RunReport:
        return run.run(self.cfg(), now=self.clock, **kw)

    def held(self, unit: str, name: str) -> Path:
        found = load_index(self.root).find(unit, name)
        assert found is not None and found.path is not None
        return self.root / found.path


@pytest.fixture
def bench(tmp_path: Path, fake_engine: FakeEngine, publisher: Publisher) -> Bench:
    return Bench(tmp_path, fake_engine, publisher)


# ---------------------------------------------------------------------------
# The table.
# ---------------------------------------------------------------------------


def test_the_table_covers_every_kind_the_installed_engine_can_emit() -> None:
    contract = importlib.import_module("hammunition.interface.artifacts")
    missing = [c for c in contract.CHECKS if c not in KINDS]
    assert not missing, f"the engine emits {missing}; add them to bunker.checks.KINDS"


def test_the_engine_contract_kinds_are_listed_literally() -> None:
    """The installed engine may be the old floor, where the test above checks
    little: the six kinds of the contract release, spelled out."""
    assert {
        "sha256",
        "md5-publisher",
        "etag-md5",
        "sha1-publisher",
        "sha256-publisher",
        "unverified-zip",
        "unverified-fetch",
    } == set(KINDS)


def test_the_table_is_complete_and_consistent() -> None:
    assert set(KINDS) == {
        "sha256",
        "sha256-publisher",
        "md5-publisher",
        "etag-md5",
        "sha1-publisher",
        "unverified-zip",
        "unverified-fetch",
    }
    for name, kind in KINDS.items():
        assert kind.name == name
        assert kind.method in {"fetch", "fetch_md5", "fetch_sha1", "fetch_checked"}
        assert kind.algorithm in {"sha256", "md5", "sha1"} or kind.unverified
        assert kind.summary
    assert [n for n, k in KINDS.items() if k.unverified] == ["unverified-zip", "unverified-fetch"]
    assert [n for n, k in KINDS.items() if k.zip_structure] == ["unverified-zip"]
    assert checks.is_unverified("unverified-zip") and not checks.is_unverified("sha256")
    assert checks.is_unverified("unverified-fetch")
    assert not checks.is_unverified("blake3-publisher")


def test_the_contract_release_is_not_below_the_floor() -> None:
    assert engine.meets_floor(ENGINE_CONTRACT, ENGINE_FLOOR)


# ---------------------------------------------------------------------------
# An unknown kind is refused by name, with the engine's version.
# ---------------------------------------------------------------------------


def unknown_kind_doc(bench: Bench) -> None:
    bench.list(
        [
            entry("a-unit", "one", "https://p/one", "blake3-publisher", "c" * 64, size=1),
            entry("a-unit", "two", bench.pub.put("/two", b"two"), "sha256", sha(b"two"), size=3),
        ],
        engine_version="0.99.0",
    )


def test_an_unknown_kind_is_refused_by_name_with_the_engine_version(bench: Bench) -> None:
    unknown_kind_doc(bench)
    listing = engine.ask_engine(bench.cfg())
    assert [a.name for a in listing.artifacts] == ["two"]
    (refused,) = listing.deferred
    assert refused.refused
    for must in ("blake3-publisher", "0.99.0", "sha256", "unverified-zip", "unverified-fetch"):
        assert must in refused.reason, refused.reason


def test_an_unknown_kind_fails_the_run_loudly_and_downloads_nothing_for_it(bench: Bench) -> None:
    unknown_kind_doc(bench)
    report = bench.run()
    assert report.exit_code == 1
    assert [o.name for o in report.outcomes] == ["two"]  # the rest still mirrors
    assert bench.pub.requests("/one") == 0
    assert any("blake3-publisher" in line and "0.99.0" in line for line in report.summary_lines())
    body = report.as_dict()
    assert body["refused"] and "blake3-publisher" in body["refused"][0]["reason"]
    assert any(d["name"] == "one" for d in body["deferred"])


# ---------------------------------------------------------------------------
# An engine newer than the Bunker knows says so.
# ---------------------------------------------------------------------------


def test_a_newer_engine_document_is_named_in_the_run(bench: Bench) -> None:
    bench.list(
        [entry("a-unit", "two", bench.pub.put("/two", b"two"), "sha256", sha(b"two"), size=3)],
        engine_version="0.99.0",
    )
    report = bench.run()
    assert report.exit_code == 0  # nothing it lists is unknown: a note, not a failure
    (note,) = report.warnings
    for must in ("0.99.0", ENGINE_CONTRACT, "update the Bunker"):
        assert must in note
    assert note in "\n".join(report.summary_lines())


def test_the_contract_release_itself_is_not_newer(bench: Bench) -> None:
    bench.list(
        [entry("a-unit", "two", bench.pub.put("/two", b"two"), "sha256", sha(b"two"), size=3)],
        engine_version=ENGINE_CONTRACT,
    )
    assert bench.run().warnings == []


def test_doctor_says_when_the_engine_is_newer(
    tmp_path: Path, fake_engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_engine.set_version("0.99.0")
    path = tmp_path / "bunker.toml"
    path.write_text(config_text(str(tmp_path / "vol")))
    check = {c.name: c for c in doctor.doctor(config.load(path)).checks}["engine"]
    assert check.ok  # the floor is met; unknown kinds are refused one by one
    assert "0.99.0" in check.detail and ENGINE_CONTRACT in check.detail


# ---------------------------------------------------------------------------
# sha1-publisher (CoMaps).
# ---------------------------------------------------------------------------

MWM = b"a CoMaps map file " * 400


def sha1_entry(bench: Bench, data: bytes = MWM, **kw: Any) -> dict[str, Any]:
    url = bench.pub.put("/comaps/260101/Vermont.mwm", data)
    return entry(
        "comaps-maps",
        "260101/Vermont.mwm",
        url,
        "sha1-publisher",
        kw.pop("digest", sha1(data)),
        size=kw.pop("size", len(data)),
        licence="ODbL 1.0",
        **kw,
    )


@needs_sha1
def test_sha1_publisher_is_fetched_verified_and_recorded(bench: Bench) -> None:
    bench.list([sha1_entry(bench)])
    report = bench.run()
    assert report.exit_code == 0, report.summary_lines()
    path = bench.held("comaps-maps", "260101/Vermont.mwm")
    assert path.read_bytes() == MWM
    stored = load_index(bench.root).find("comaps-maps", "260101/Vermont.mwm")
    assert stored is not None
    assert (stored.publisher_check, stored.publisher_digest) == ("sha1-publisher", sha1(MWM))
    assert stored.sha256 == sha(MWM)  # the sidecar is sha256 whatever the check was
    # a second run keeps it, and re-checks the held bytes against the sidecar
    before = bench.pub.total()
    bench.clock.advance(hours=1)
    again = bench.run()
    assert [o.action for o in again.outcomes] == ["verified"]
    assert bench.pub.total() == before


@needs_sha1
def test_sha1_publisher_with_the_wrong_digest_keeps_nothing(bench: Bench) -> None:
    bench.list([sha1_entry(bench, digest="0" * 40)])
    report = bench.run()
    assert report.exit_code == 1
    assert "SHA-1" in (report.outcomes[0].reason or "")
    assert not list(bench.root.glob("comaps-maps/**/*.mwm"))


@needs_sha1
def test_sha1_publisher_with_no_size_is_refused_by_name(bench: Bench) -> None:
    bench.list([sha1_entry(bench, size=None)])
    report = bench.run()
    assert report.exit_code == 1
    assert "no size" in (report.outcomes[0].reason or "")
    assert bench.pub.requests("/comaps/260101/Vermont.mwm") == 0


@needs_sha1
def test_a_held_sha1_copy_is_rechecked_by_its_sha1_when_no_record_says(bench: Bench) -> None:
    """An index moved aside: the copy is hashed against the engine's SHA-1,
    not trusted for being on disk."""
    bench.list([sha1_entry(bench)])
    bench.run()
    (bench.root / "index.json").unlink()
    before = bench.pub.total()
    bench.clock.advance(hours=1)
    report = bench.run()
    assert [o.action for o in report.outcomes] == ["verified"]
    assert bench.pub.total() == before


def test_an_engine_without_the_method_is_named_not_guessed(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(Fetcher, "fetch_sha1", raising=False)
    bench.list([sha1_entry(bench)])
    report = bench.run()
    assert report.exit_code == 1
    reason = report.outcomes[0].reason or ""
    assert "sha1-publisher" in reason and "fetch_sha1" in reason and "Hammunition" in reason
    assert bench.pub.requests("/comaps/260101/Vermont.mwm") == 0


# ---------------------------------------------------------------------------
# unverified-zip (the ACMA register), held by the maintainer's ruling.
# ---------------------------------------------------------------------------

NEEDLE = b"ONLY-A-CRC-PASS-READS-THIS-MEMBER"


def acma_entry(bench: Bench, data: bytes, **kw: Any) -> dict[str, Any]:
    url = bench.pub.put("/rrl/spectra_rrl.zip", data)
    return entry(
        "acma-register",
        "spectra_rrl.zip",
        url,
        "unverified-zip",
        None,
        size=kw.pop("size", len(data)),
        licence=LICENCE,
        **kw,
    )


@needs_acma
def test_the_register_is_held_with_its_size_and_date(bench: Bench) -> None:
    data = register_zip(1, pad=NEEDLE)
    bench.list([acma_entry(bench, data)])
    report = bench.run()
    assert report.exit_code == 0, report.summary_lines()
    path = bench.held("acma-register", "spectra_rrl.zip")
    assert path.read_bytes() == data
    stored = load_index(bench.root).find("acma-register", "spectra_rrl.zip")
    assert stored is not None
    assert stored.publisher_check == "unverified-zip" and stored.publisher_digest is None
    assert stored.size == len(data) and stored.fetched == "2026-09-29T03:00:00Z"
    assert stored.sha256 == sha(data) and stored.status == "current"
    assert report.warnings == []


@needs_acma
def test_the_register_is_refetched_on_schedule_not_before(bench: Bench) -> None:
    first = register_zip(1, pad=NEEDLE)
    bench.list([acma_entry(bench, first)])
    bench.run()
    requests = bench.pub.requests("/rrl/spectra_rrl.zip")
    # The publisher rebuilds it daily, but the schedule says daily: not due after one hour.
    second = register_zip(2, pad=NEEDLE)
    bench.list([acma_entry(bench, second)])
    bench.clock.advance(hours=1)
    quiet = bench.run()
    assert [o.action for o in quiet.outcomes] == ["verified"]
    assert bench.pub.requests("/rrl/spectra_rrl.zip") == requests
    assert bench.held("acma-register", "spectra_rrl.zip").read_bytes() == first
    # Due: fetched again, the previous kept beside it.
    bench.clock.advance(hours=24)
    due = bench.run()
    assert [o.action for o in due.outcomes] == ["fetched"]
    assert bench.held("acma-register", "spectra_rrl.zip").read_bytes() == second
    stored = load_index(bench.root).find("acma-register", "spectra_rrl.zip")
    assert stored is not None and stored.fetched == "2026-09-30T04:00:00Z"
    assert stored.previous is not None


@needs_acma
def test_the_register_is_never_marked_stale(bench: Bench) -> None:
    """There is no digest to compare, so a copy is either due or kept."""
    bench.list([acma_entry(bench, register_zip(1))])
    bench.run()
    bench.list([acma_entry(bench, register_zip(2))])
    bench.clock.advance(hours=2)
    assert load_index(bench.root).artifacts[0].status == "current"
    assert bench.run().counts()["stale"] == 0


@needs_acma
def test_a_damaged_register_is_discarded_and_the_last_good_copy_serves(bench: Bench) -> None:
    good = register_zip(1, pad=NEEDLE)
    bench.list([acma_entry(bench, good)])
    bench.run()
    bench.list([acma_entry(bench, flip_in_stored_member(register_zip(2, pad=NEEDLE), NEEDLE))])
    bench.clock.advance(hours=25)
    report = bench.run()
    assert report.exit_code == 1
    assert "CRC" in (report.outcomes[0].reason or "")
    assert bench.held("acma-register", "spectra_rrl.zip").read_bytes() == good


@needs_acma
def test_a_web_page_is_not_a_register(bench: Bench) -> None:
    page = b"<html>Service unavailable</html>"
    bench.list([acma_entry(bench, page)])
    report = bench.run()
    assert report.exit_code == 1 and report.outcomes[0].action == "failed"
    assert not list(bench.root.glob("acma-register/**/*.zip"))


@needs_acma
def test_verify_runs_the_zips_crc_pass_over_a_held_register(bench: Bench) -> None:
    """The sidecar rewritten to match damaged bytes: only the CRC pass notices.
    (Falsified: without the structure check this passes.)"""
    data = register_zip(1, pad=NEEDLE)
    bench.list([acma_entry(bench, data)])
    bench.run()
    assert verify.verify(bench.cfg(), now=bench.clock).exit_code == 0
    path = bench.held("acma-register", "spectra_rrl.zip")
    damaged = flip_in_stored_member(data, NEEDLE)
    path.write_bytes(damaged)
    path.with_name(path.name + ".sha256").write_text(f"{sha(damaged)}  {path.name}\n")
    report = verify.verify(bench.cfg(), now=bench.clock)
    assert report.exit_code == 1
    assert "CRC" in (report.results[0].reason or "")
    stored = load_index(bench.root).find("acma-register", "spectra_rrl.zip")
    assert stored is not None and stored.status == "corrupted"


@needs_acma
def test_a_register_verify_found_damaged_is_refetched_by_the_next_run(bench: Bench) -> None:
    """Even on cadence `never`: `verify` promises the next run fetches it again,
    and a sidecar that matches the damaged bytes must not talk the run out of it."""
    bench.extra = '[schedule.units]\nacma-register = "never"\n'
    data = register_zip(1, pad=NEEDLE)
    bench.list([acma_entry(bench, data)])
    bench.run()
    path = bench.held("acma-register", "spectra_rrl.zip")
    damaged = flip_in_stored_member(data, NEEDLE)
    path.write_bytes(damaged)
    path.with_name(path.name + ".sha256").write_text(f"{sha(damaged)}  {path.name}\n")
    assert verify.verify(bench.cfg(), now=bench.clock).exit_code == 1
    report = bench.run()
    assert [o.action for o in report.outcomes] == ["fetched"]
    assert bench.held("acma-register", "spectra_rrl.zip").read_bytes() == data
    stored = load_index(bench.root).find("acma-register", "spectra_rrl.zip")
    assert stored is not None and stored.status == "current"


# ---------------------------------------------------------------------------
# unverified-fetch (the on-request repeater lists, D-078): size and date only.
# ---------------------------------------------------------------------------

SNAPSHOT = b"callsign,txMHz,rxMHz\nN0TST,146.940,146.340\n"
needs_checked = pytest.mark.skipif(not has_acma(), reason="the engine has no Fetcher.fetch_checked")


def snapshot_entry(bench: Bench, data: bytes, **kw: Any) -> dict[str, Any]:
    url = bench.pub.put("/csvcreate_all.php", data)
    return entry(
        "repeater-snapshots",
        "etcc.csv",
        url,
        "unverified-fetch",
        None,
        size=kw.pop("size", len(data)),
        licence="RSGB ETCC: no licence stated",
        **kw,
    )


@needs_checked
def test_a_repeater_snapshot_is_held_with_its_size_and_date_and_no_structure_check(
    bench: Bench,
) -> None:
    bench.list([snapshot_entry(bench, SNAPSHOT)])  # not a zip, not anything: bytes
    report = bench.run()
    assert report.exit_code == 0, report.summary_lines()
    assert bench.held("repeater-snapshots", "etcc.csv").read_bytes() == SNAPSHOT
    stored = load_index(bench.root).find("repeater-snapshots", "etcc.csv")
    assert stored is not None
    assert stored.publisher_check == "unverified-fetch" and stored.publisher_digest is None
    assert stored.size == len(SNAPSHOT) and stored.fetched == "2026-09-29T03:00:00Z"
    assert stored.status == "current" and report.warnings == []
    assert held_names(bench) == ["repeater-snapshots/etcc.csv"]
    # `verify` re-hashes it and does not ask the zip reader about a CSV.
    assert verify.verify(bench.cfg(), now=bench.clock).exit_code == 0


def held_names(bench: Bench) -> list[str]:
    from bunker.index import held_unverified

    return [f"{e.unit}/{e.name}" for e in held_unverified(load_index(bench.root))]


@needs_checked
def test_a_repeater_snapshot_is_refetched_on_schedule_and_never_stale(bench: Bench) -> None:
    bench.list([snapshot_entry(bench, SNAPSHOT)])
    bench.run()
    requests = bench.pub.requests("/csvcreate_all.php")
    newer = SNAPSHOT + b"N0CALL,147.000,147.600\n"
    bench.list([snapshot_entry(bench, newer)])
    bench.clock.advance(hours=1)
    assert [o.action for o in bench.run().outcomes] == ["verified"]
    assert bench.pub.requests("/csvcreate_all.php") == requests
    assert load_index(bench.root).artifacts[0].status == "current"
    bench.clock.advance(hours=24)
    assert [o.action for o in bench.run().outcomes] == ["fetched"]
    assert bench.held("repeater-snapshots", "etcc.csv").read_bytes() == newer


@needs_checked
def test_an_empty_repeater_snapshot_is_refused_and_nothing_is_kept(bench: Bench) -> None:
    bench.list([snapshot_entry(bench, b"", size=0)])
    report = bench.run()
    assert report.exit_code == 1 and report.outcomes[0].action == "failed"
    assert "empty file arrived" in (report.outcomes[0].reason or "")
    assert not list(bench.root.glob("repeater-snapshots/**/*.csv"))


@needs_checked
def test_a_snapshot_far_past_its_listed_size_is_refused(bench: Bench) -> None:
    """The cap is four times what the engine's HEAD listed, at least 1 MiB."""
    big = register_zip(1, pad=b"x" * (5 * 1024 * 1024))  # a whole zip: only the cap refuses it
    bench.list([snapshot_entry(bench, big, size=100)])
    report = bench.run()
    assert report.exit_code == 1 and report.outcomes[0].action == "failed"
    assert "CRC" not in (report.outcomes[0].reason or "")
    assert not list(bench.root.glob("repeater-snapshots/**/*.csv"))


@needs_checked
def test_a_snapshot_with_no_listed_size_is_still_held(bench: Bench) -> None:
    bench.list([snapshot_entry(bench, SNAPSHOT, size=None)])
    assert bench.run().exit_code == 0
    assert bench.held("repeater-snapshots", "etcc.csv").read_bytes() == SNAPSHOT


@needs_checked
def test_switched_off_a_repeater_snapshot_is_declined_by_name_and_never_fetched(
    tmp_path: Path, fake_engine: FakeEngine, publisher: Publisher
) -> None:
    off = Bench(tmp_path, fake_engine, publisher)
    path = tmp_path / "bunker.toml"
    path.write_text(
        config_text(
            str(off.root),
            selection="map_regions = []\nhold_unverified = false",
            extra='[schedule]\ndefault = "daily"\n',
        )
    )
    off.list([snapshot_entry(off, SNAPSHOT)])
    report = run.run(config.load(path), now=off.clock)
    assert report.outcomes == [] and publisher.requests("/csvcreate_all.php") == 0
    (declined,) = report.declined
    assert declined["unit"] == "repeater-snapshots"
    assert "hold_unverified = false" in (declined["reason"] or "")
    assert "unverified-fetch" in (declined["reason"] or "")


def test_an_engine_without_the_register_check_is_named_not_guessed(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(Fetcher, "fetch_checked", raising=False)
    bench.list([acma_entry(bench, b"not fetched")])
    report = bench.run()
    assert report.exit_code == 1
    reason = report.outcomes[0].reason or ""
    assert "unverified-zip" in reason and "fetch_checked" in reason and "Hammunition" in reason
    assert bench.pub.requests("/rrl/spectra_rrl.zip") == 0


# ---------------------------------------------------------------------------
# hold_unverified.
# ---------------------------------------------------------------------------


def test_hold_unverified_defaults_to_true(tmp_path: Path) -> None:
    path = tmp_path / "bunker.toml"
    path.write_text(config_text(str(tmp_path / "vol")))
    assert config.load(path).selection.hold_unverified is True


@pytest.mark.parametrize("bad", ['"yes"', "1", "[]"])
def test_hold_unverified_must_be_a_boolean(tmp_path: Path, bad: str) -> None:
    path = tmp_path / "bunker.toml"
    path.write_text(config_text(str(tmp_path / "vol"), selection=f"hold_unverified = {bad}"))
    with pytest.raises(config.ConfigError, match=r"selection\.hold_unverified"):
        config.load(path)


@needs_acma
def test_switched_off_the_register_is_declined_by_name_and_never_fetched(
    tmp_path: Path,
    fake_engine: FakeEngine,
    publisher: Publisher,
    capsys: pytest.CaptureFixture[str],
) -> None:
    off = Bench(tmp_path, fake_engine, publisher)
    path = tmp_path / "bunker.toml"
    path.write_text(
        config_text(
            str(off.root),
            selection="map_regions = []\nhold_unverified = false",
            extra='[schedule]\ndefault = "daily"\n',
        )
    )
    cfg = config.load(path)
    off.list(
        [
            acma_entry(off, register_zip(1)),
            entry("a-unit", "two", publisher.put("/two", b"two"), "sha256", sha(b"two"), size=3),
        ]
    )
    report = run.run(cfg, now=off.clock)
    assert report.exit_code == 0, report.summary_lines()
    assert [o.name for o in report.outcomes] == ["two"]
    assert publisher.requests("/rrl/spectra_rrl.zip") == 0
    (declined,) = report.declined
    assert declined["unit"] == "acma-register"
    assert report.deferred == []
    assert declined["reason"] is not None
    assert "hold_unverified = false" in declined["reason"]
    assert "unverified-zip" in declined["reason"]
    idx = load_index(off.root)
    assert idx.declined == report.declined and idx.deferred == []
    from bunker import cli

    assert cli.main(["status", "--json", "--config", str(path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["declined"] == report.declined and status["deferred"] == []
    html = (off.root / "status.html").read_text()
    assert "Declined by your configuration" in html
    assert "Deferred by the engine" not in html


@needs_acma
def test_switching_off_withdraws_a_register_already_held(
    tmp_path: Path, fake_engine: FakeEngine, publisher: Publisher
) -> None:
    on = Bench(tmp_path, fake_engine, publisher)
    on.list([acma_entry(on, register_zip(1))])
    on.run()
    held = on.held("acma-register", "spectra_rrl.zip")
    path = tmp_path / "bunker.toml"
    path.write_text(
        config_text(str(on.root), selection="map_regions = []\nhold_unverified = false", extra="")
    )
    report = run.run(config.load(path), now=on.clock)
    assert [d["unit"] for d in report.dropped] == ["acma-register"]
    assert load_index(on.root).find("acma-register", "spectra_rrl.zip") is None
    assert held.exists()  # left for the operator to delete, as every dropped file is
    assert any("hold_unverified" in line for line in report.summary_lines())


# ---------------------------------------------------------------------------
# status, the status page and doctor say what is unverified and held.
# ---------------------------------------------------------------------------


@needs_acma
def test_status_and_the_page_list_the_register_under_the_ruling(
    bench: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    from bunker import cli

    bench.list([acma_entry(bench, register_zip(1))])
    bench.run()
    cfg_path = bench.tmp / "bunker.toml"
    assert cli.main(["status", "--config", str(cfg_path)]) == 0
    text = capsys.readouterr().out
    assert checks.UNVERIFIED_LABEL in text and "acma-register/spectra_rrl.zip" in text
    assert cli.main(["status", "--json", "--config", str(cfg_path)]) == 0
    doc = json.loads(capsys.readouterr().out)
    (row,) = doc["unverified"]
    assert row["unit"] == "acma-register" and row["check"] == "unverified-zip"
    assert row["size"] > 0 and row["fetched"] == "2026-09-29T03:00:00Z"
    html = (bench.root / "status.html").read_text()
    assert escape(checks.UNVERIFIED_LABEL) in html and "spectra_rrl.zip" in html


def test_status_has_no_unverified_section_when_nothing_is_unverified(
    bench: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    from bunker import cli

    bench.list(
        [entry("a-unit", "two", bench.pub.put("/two", b"two"), "sha256", sha(b"two"), size=3)]
    )
    bench.run()
    assert cli.main(["status", "--config", str(bench.tmp / "bunker.toml")]) == 0
    assert checks.UNVERIFIED_LABEL not in capsys.readouterr().out


def doctor_checks(cfg: config.Config) -> dict[str, doctor.Check]:
    return {c.name: c for c in doctor.doctor(cfg).checks}


@needs_acma
def test_doctor_names_the_unverified_artifacts_held(bench: Bench) -> None:
    bench.list([acma_entry(bench, register_zip(1))])
    bench.run()
    check = doctor_checks(bench.cfg())["unverified"]
    assert check.ok
    assert "acma-register/spectra_rrl.zip" in check.detail
    assert "hold_unverified = true" in check.detail


def test_doctor_says_when_nothing_unverified_is_held(bench: Bench) -> None:
    check = doctor_checks(bench.cfg())["unverified"]
    assert check.ok and "none held" in check.detail


def test_doctor_says_the_switch_is_off(tmp_path: Path, fake_engine: FakeEngine) -> None:
    path = tmp_path / "bunker.toml"
    path.write_text(
        config_text(str(tmp_path / "vol"), selection="map_regions = []\nhold_unverified = false")
    )
    check = doctor_checks(config.load(path))["unverified"]
    assert check.ok and "hold_unverified = false" in check.detail
    assert "not held" in check.detail


@needs_acma
def test_verify_on_an_engine_that_cannot_check_does_not_call_it_corrupt(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench.list([acma_entry(bench, register_zip(1))])
    bench.run()
    import bunker.verify as verify_module

    def missing() -> Any:
        raise BackendError("the installed Hammunition has no hammunition.acma")

    monkeypatch.setattr(verify_module, "acma", missing)
    report = verify.verify(bench.cfg(), now=bench.clock)
    assert report.exit_code == 1 and "not checked" in (report.results[0].reason or "")
    stored = load_index(bench.root).find("acma-register", "spectra_rrl.zip")
    assert stored is not None and stored.status == "current"


@needs_checked
def test_the_status_page_describes_a_held_repeater_snapshot_without_the_zip_wording(
    bench: Bench,
) -> None:
    bench.list([snapshot_entry(bench, SNAPSHOT)])
    bench.run()
    html = (bench.root / "status.html").read_text()
    assert "repeater-snapshots" in html and "only the size and the date" in html
    assert "client.csv" not in html and "own structure" not in html
    check = doctor._unverified(bench.cfg())
    assert "repeater" in check.detail and "unverified-zip" not in check.detail
