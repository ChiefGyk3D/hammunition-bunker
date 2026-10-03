# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""One pass over the volume: ask the engine, fetch what is due, verify what
is held, rewrite the index, log the run.

For each artifact the engine lists:

- **missing** on disk: fetched, whatever the unit's cadence (``never``
  means "do not refresh", not "do not hold");
- **matches** what the engine lists: kept; its bytes are re-hashed against
  the sidecar when the verify cadence says so, and a mismatch is reported
  as corrupted, removed, and fetched again at once;
- **differs** (a new pin, a new dated region, a new ETag): fetched when the
  unit's cadence is due, or ``--all``, or the unit was named with
  ``--unit``; otherwise marked ``stale`` and left serving.

Every download goes through the engine's own :class:`Fetcher`: the digest
checked is the one the engine listed, and nothing unverified reaches the
volume. A failed fetch leaves the last good copy exactly where it was.
"""

from __future__ import annotations

import json
import threading
import time as _time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Any, cast

from bunker import statuspage
from bunker.checks import KINDS
from bunker.config import Config
from bunker.engine import Artifact, Deferred, EngineError, Listing, ask_engine
from bunker.enginelib import (
    DEFAULT_MAX_BYTES,
    BackendError,
    Fetcher,
    FetchResult,
    RemoteArtifact,
    Transport,
    UrllibTransport,
    acma,
)
from bunker.index import Entry, Index
from bunker.index import load as load_index
from bunker.index import save as save_index
from bunker.volume import (
    RunLock,
    UnsafeName,
    artifact_dir,
    file_name,
    hash_file,
    hash_file_with,
    install,
    read_sidecar,
    sidecar,
    write_sidecar,
)

__all__ = [
    "LARGE",
    "PERIOD",
    "Outcome",
    "RateLimit",
    "RunReport",
    "due",
    "iso",
    "run",
    "verify_due",
]

PERIOD = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=30)}
#: A run that starts a little early still counts: a daily unit fetched at
#: 03:00:40 yesterday is due at 03:00:05 today.
SLACK = timedelta(hours=1)
#: ``auto`` verify: every run below this size, monthly at or above it.
LARGE = 1024**3
MIB = 1024 * 1024

Clock = Callable[[], datetime]


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def due(cadence: str, last: datetime | None, now: datetime) -> bool:
    """Whether a unit on *cadence*, last fetched at *last*, is due at *now*."""
    if last is None:
        return True
    if cadence == "never":
        return False
    return now - last >= PERIOD[cadence] - SLACK


def verify_due(cadence: str, size: int, last: datetime | None, now: datetime) -> bool:
    """Whether a held file's bytes should be re-hashed now."""
    if cadence == "every-run" or last is None:
        return True
    if cadence == "auto":
        if size < LARGE:
            return True
        cadence = "monthly"
    return now - last >= PERIOD[cadence] - SLACK


@dataclass
class Outcome:
    """What happened to one artifact in this run."""

    unit: str
    name: str
    action: str
    """``fetched``, ``verified``, ``unchanged``, ``stale`` or ``failed``."""
    status: str
    reason: str | None = None
    corrupted: bool = False
    """The held copy's bytes no longer matched its sidecar."""
    size: int | None = None


@dataclass
class RunReport:
    started: str
    finished: str = ""
    engine_version: str | None = None
    outcomes: list[Outcome] = field(default_factory=list)
    deferred: list[dict[str, str | None]] = field(default_factory=list)
    dropped: list[dict[str, str | None]] = field(default_factory=list)
    error: str | None = None
    plain_http: list[str] = field(default_factory=list)
    """``unit/name`` of every artifact whose publisher URL is plain HTTP. The
    digest, not the transport, is the check; the spec asks that it be said."""
    refused: list[dict[str, str | None]] = field(default_factory=list)
    """Artifacts whose check kind this Bunker does not know: named, not
    downloaded, and a failure of the run."""
    declined: list[dict[str, str | None]] = field(default_factory=list)
    """Unverified artifacts left alone because ``hold_unverified`` is false."""
    warnings: list[str] = field(default_factory=list)
    """Notes that are not failures, such as an engine newer than this Bunker knows."""

    def counts(self) -> dict[str, int]:
        count = dict.fromkeys(("fetched", "verified", "unchanged", "stale", "failed"), 0)
        for outcome in self.outcomes:
            count[outcome.action] += 1
        count["corrupted"] = sum(1 for o in self.outcomes if o.corrupted)
        count["deferred"] = len(self.deferred)
        return count

    @property
    def exit_code(self) -> int:
        counts = self.counts()
        return 1 if self.error or self.refused or counts["failed"] or counts["corrupted"] else 0

    def summary_lines(self) -> list[str]:
        c = self.counts()
        lines = [
            f"bunker run {self.started} to {self.finished}: {c['fetched']} fetched, "
            f"{c['verified']} verified, {c['unchanged']} unchanged, {c['stale']} stale, "
            f"{c['failed']} failed, {c['corrupted']} corrupted, {c['deferred']} deferred"
        ]
        if self.error:
            lines.append(f"  error: {self.error}")
        lines += [f"  note: {w}" for w in self.warnings]
        for r in self.refused:
            lines.append(f"  refused: {r['unit']}/{r['name']}: {r['reason']}")
        for d in self.declined:
            lines.append(f"  declined: {d['unit']}/{d['name']}: {d['reason']}")
        for o in self.outcomes:
            if o.corrupted:
                lines.append(f"  corrupted: {o.unit}/{o.name} (its bytes no longer matched)")
            if o.action in ("failed", "stale"):
                lines.append(f"  {o.action}: {o.unit}/{o.name}: {o.reason}")
        if self.plain_http:
            lines.append(
                f"  {len(self.plain_http)} publisher URL(s) are plain HTTP, as the catalog "
                f"names them (the digest is the check, not the transport): "
                + ", ".join(self.plain_http)
            )
        for d in self.dropped:
            lines.append(
                f"  dropped from the index: {d['unit']}/{d['name']} (no longer listed; "
                f"its files are left at {d['path']} for you to delete)"
            )
        return lines

    def as_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "finished": self.finished,
            "engine_version": self.engine_version,
            "counts": self.counts(),
            "error": self.error,
            "outcomes": [asdict(o) for o in self.outcomes],
            "deferred": self.deferred,
            "dropped": self.dropped,
            "plain_http": self.plain_http,
            "refused": self.refused,
            "declined": self.declined,
            "warnings": self.warnings,
            "exit_code": self.exit_code,
        }


class _Throttled:
    def __init__(self, stream: IO[bytes], limit: RateLimit) -> None:
        self._stream = stream
        self._limit = limit

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        if chunk:
            self._limit.consume(len(chunk))
        return chunk


class RateLimit:
    """A :class:`Transport` sharing one byte budget across every download of
    a run (``[storage] max_rate``). Each read reserves its bytes' share of
    the timeline and sleeps until that share has passed."""

    def __init__(
        self,
        inner: Transport,
        *,
        rate: int,
        clock: Callable[[], float] = _time.monotonic,
        sleep: Callable[[float], None] = _time.sleep,
    ) -> None:
        self.inner = inner
        self.rate = rate
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next: float | None = None

    def consume(self, n: int) -> None:
        with self._lock:
            now = self._clock()
            start = now if self._next is None else max(self._next, now)
            self._next = start + n / self.rate
            wait = start - now
        if wait > 0:
            self._sleep(wait)

    @contextmanager
    def open(self, url: str) -> Iterator[IO[bytes]]:
        with self.inner.open(url) as stream:
            yield cast(IO[bytes], _Throttled(stream, self))


def _transport(cfg: Config, given: Transport | None) -> Transport:
    base: Transport = given if given is not None else UrllibTransport()
    if cfg.storage.max_rate is not None:
        return RateLimit(base, rate=cfg.storage.max_rate)
    return base


def _download(root: Path, artifact: Artifact, transport: Transport) -> FetchResult:
    """The engine's verified fetch, into ``.incoming/<unit>/``, by the method
    the table in :mod:`bunker.checks` names for the artifact's check."""
    kind = KINDS[artifact.check]
    if kind.needs_digest and artifact.digest is None:
        raise BackendError(
            f"the engine listed no digest for {artifact.url}; nothing unverified is kept "
            f"under a {artifact.check} check"
        )
    if kind.needs_size and artifact.size is None:
        raise BackendError(
            f"the engine listed no size for {artifact.url}; an {artifact.check} "
            f"download is only checked with its size"
        )
    fetcher = Fetcher(cache_dir=root / ".incoming" / artifact.unit, transport=transport)
    method = getattr(fetcher, kind.method, None)
    if method is None:
        raise BackendError(
            f"the installed Hammunition has no Fetcher.{kind.method}, which the "
            f"{artifact.check} check needs; install the Hammunition release that carries it"
        )
    digest = artifact.digest
    if kind.method == "fetch" and digest is not None:
        cap = artifact.size + MIB if artifact.size is not None else DEFAULT_MAX_BYTES
        result = method(RemoteArtifact(url=artifact.url, sha256=digest), max_bytes=cap)
    elif kind.method == "fetch_checked" and not kind.zip_structure:
        # An on-request repeater list (D-078): no digest and no structure to
        # read. Size and date are all that is kept; the only check is that
        # something arrived, within four times the size the engine's HEAD
        # listed (or the engine's default cap when it listed none).
        listed = artifact.size
        cap = max(4 * listed, MIB) if listed is not None else DEFAULT_MAX_BYTES

        def _arrived(path: Path) -> None:
            if path.stat().st_size == 0:
                raise BackendError(f"{artifact.url}: an empty file arrived")

        result = method(artifact.url, max_bytes=cap, check=_arrived)
        return cast(FetchResult, result)
    elif kind.method == "fetch_checked":
        # No digest exists: the engine's own check of the register's structure
        # (the zip's CRC-32s and the tables its reader needs) is the whole of it,
        # and the file changes daily, so the listed size is a HEAD's, not a pin.
        reader = acma()
        result = method(artifact.url, max_bytes=reader.FETCH_LIMIT, check=reader.check_register)
        return cast(FetchResult, result)
    elif digest is not None and artifact.size is not None:
        result = method(artifact.url, digest, expected_size=artifact.size)
    else:  # pragma: no cover - the digest and size checks above make this unreachable
        raise BackendError(f"{artifact.url}: no way to check a {artifact.check} download")
    if artifact.size is not None and result.size != artifact.size:
        result.path.unlink(missing_ok=True)
        raise BackendError(
            f"{artifact.url}: the engine listed {artifact.size} bytes and {result.size} "
            f"arrived; the digest matched, so the listing is wrong"
        )
    return cast(FetchResult, result)


class _Pass:
    """The state one run shares between its download workers."""

    def __init__(
        self,
        cfg: Config,
        idx: Index,
        now: datetime,
        *,
        all_: bool,
        named: Sequence[str],
        transport: Transport,
    ) -> None:
        self.cfg = cfg
        self.root = cfg.storage.root
        self.idx = idx
        self.now = now
        self.stamp = iso(now)
        self.all = all_
        self.named = set(named)
        self.transport = transport
        self.lock = threading.Lock()

    def save(self) -> None:
        save_index(self.root, self.idx, generated=self.stamp)

    def _entry(self, artifact: Artifact) -> Entry:
        with self.lock:
            found = self.idx.find(artifact.unit, artifact.name)
            if found is None:
                found = Entry(
                    unit=artifact.unit,
                    name=artifact.name,
                    path=None,
                    sha256=None,
                    size=None,
                    publisher_check=artifact.check,
                    publisher_digest=None,
                    publisher_url=artifact.url,
                    licence=artifact.licence,
                    fetched=None,
                    verified=None,
                    status="failed",
                    reason="not fetched yet",
                    previous=None,
                )
                self.idx.artifacts.append(found)
            found.licence = artifact.licence
            return found

    def _held(self, entry: Entry, folder: Path, basename: str) -> Path | None:
        """The current copy on disk: the one the index names, else the one
        the layout would put there (an index moved aside)."""
        if entry.path:
            path = self.root / entry.path
            if path.parent == folder and path.is_file():
                return path
        candidate = folder / basename
        return candidate if candidate.is_file() else None

    def _matches(self, artifact: Artifact, entry: Entry, held: Path) -> tuple[bool, bool]:
        """Whether *held* is what the engine lists, and whether deciding that
        just re-hashed it (so it counts as verified)."""
        if artifact.digest is None:
            return False, False
        if artifact.size is not None and held.stat().st_size != artifact.size:
            return False, False
        claimed = read_sidecar(held)
        algorithm = KINDS[artifact.check].algorithm
        if algorithm == "sha256":
            return claimed == artifact.digest, False
        if algorithm is None:  # pragma: no cover - only an unverified kind has none
            return False, False
        rel = held.relative_to(self.root).as_posix()
        if (
            claimed is not None
            and entry.path == rel
            and entry.publisher_check == artifact.check
            and entry.publisher_digest == artifact.digest
        ):
            return True, False
        # No record says what this copy was checked against: hash it now.
        sha256, other = hash_file_with(held, algorithm)
        if other != artifact.digest or (claimed is not None and claimed != sha256):
            return False, True
        if claimed is None:
            write_sidecar(held, sha256)
        with self.lock:
            entry.sha256, entry.verified = sha256, self.stamp
        return True, True

    def one(self, artifact: Artifact) -> Outcome:
        """:meth:`_one`, with any failure it did not expect reported against
        this artifact alone: a truncated body (an ``http.client`` exception,
        not an OSError), an unreadable or failing disk. One artifact never
        takes the run's report with it."""
        try:
            return self._one(artifact)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}".strip()
            with self.lock:
                found = self.idx.find(artifact.unit, artifact.name)
                if found is not None:
                    found.status, found.reason = "failed", reason
                    self.save()
            return Outcome(artifact.unit, artifact.name, "failed", "failed", reason)

    def _one(self, artifact: Artifact) -> Outcome:
        try:
            folder = artifact_dir(self.root, artifact.unit, artifact.name)
        except UnsafeName as exc:
            return Outcome(artifact.unit, artifact.name, "failed", "failed", str(exc))
        entry = self._entry(artifact)
        basename = file_name(artifact.url)
        held = self._held(entry, folder, basename)
        corrupted = False
        forced = False
        if held is not None:
            if KINDS[artifact.check].unverified:
                # No digest exists to compare, so a held copy is never "newer
                # elsewhere" or "stale": it is kept until the schedule says to
                # fetch it again, and its bytes are re-hashed against the
                # sidecar like any other.
                # A copy `bunker verify` found damaged is fetched again at once.
                forced = entry.status == "corrupted"
                due_now = forced or self._fetch_due(artifact, entry)
                matches, hashed = (not due_now), False
                if forced:
                    corrupted = True
            else:
                matches, hashed = self._matches(artifact, entry, held)
            if matches:
                cadence = self.cfg.schedule.verify_cadence(artifact.unit)
                size = held.stat().st_size
                # A copy `bunker verify` found corrupted is hashed now, whatever
                # the cadence: the sidecar it matched on is what went wrong.
                suspect = entry.status == "corrupted"
                if not hashed and (
                    suspect or verify_due(cadence, size, _parse(entry.verified), self.now)
                ):
                    sha256, _ = hash_file(held)
                    hashed = True
                    if sha256 != read_sidecar(held):
                        corrupted = True
                if not corrupted:
                    with self.lock:
                        entry.path = held.relative_to(self.root).as_posix()
                        entry.size = size
                        entry.sha256 = read_sidecar(held)
                        entry.publisher_check = artifact.check
                        entry.publisher_digest = artifact.digest
                        entry.publisher_url = artifact.url
                        entry.status, entry.reason = "current", None
                        if hashed:
                            entry.verified = self.stamp
                        self.save()
                    action = "verified" if hashed else "unchanged"
                    return Outcome(artifact.unit, artifact.name, action, "current", size=size)
                # Its bytes no longer match what was written: never keep serving them.
                held.unlink(missing_ok=True)
                sidecar(held).unlink(missing_ok=True)
                with self.lock:
                    entry.path, entry.sha256 = None, None
                    entry.status = "corrupted"
                    entry.reason = "its bytes no longer matched its sidecar; being re-fetched"
                    self.save()
                held = None
            elif not (forced or self._fetch_due(artifact, entry)):
                cadence = self.cfg.schedule.cadence(artifact.unit)
                reason = (
                    f"the engine lists a newer copy ({artifact.check} "
                    f"{(artifact.digest or '?')[:12]}); {artifact.unit} is refreshed "
                    f"{cadence}, last fetched {entry.fetched or 'never'}"
                )
                with self.lock:
                    entry.status, entry.reason = "stale", reason
                    self.save()
                return Outcome(artifact.unit, artifact.name, "stale", "stale", reason)
        return self._fetch(artifact, entry, basename, corrupted)

    def _fetch_due(self, artifact: Artifact, entry: Entry) -> bool:
        if self.all or artifact.unit in self.named:
            return True
        cadence = self.cfg.schedule.cadence(artifact.unit)
        return due(cadence, _parse(entry.fetched), self.now)

    def _fetch(self, artifact: Artifact, entry: Entry, basename: str, corrupted: bool) -> Outcome:
        try:
            result = _download(self.root, artifact, self.transport)
        except (BackendError, OSError, ValueError) as exc:
            reason = str(exc).strip()
            with self.lock:
                entry.status, entry.reason = "failed", reason
                self.save()
            return Outcome(
                artifact.unit, artifact.name, "failed", "failed", reason, corrupted=corrupted
            )

        def commit(path: str, previous: str | None) -> None:
            entry.path, entry.previous = path, previous
            entry.sha256, entry.size = result.sha256, result.size
            entry.publisher_check = artifact.check
            entry.publisher_digest = artifact.digest
            entry.publisher_url = artifact.url
            entry.fetched = entry.verified = self.stamp
            entry.status, entry.reason = "current", None
            self.save()

        try:
            with self.lock:
                install(
                    self.root,
                    artifact.unit,
                    artifact.name,
                    result.path,
                    basename,
                    result.sha256,
                    keep_previous=self.cfg.storage.keep_previous,
                    current=entry.path,
                    commit=commit,
                )
        except OSError as exc:
            result.path.unlink(missing_ok=True)
            reason = f"verified, but could not be moved into place: {exc}"
            with self.lock:
                entry.status, entry.reason = "failed", reason
                self.save()
            return Outcome(artifact.unit, artifact.name, "failed", "failed", reason, corrupted)
        return Outcome(
            artifact.unit,
            artifact.name,
            "fetched",
            "current",
            corrupted=corrupted,
            size=result.size,
        )


def sweep_incoming(root: Path) -> list[Path]:
    """Remove the partial downloads a killed run left in ``.incoming``.

    Called with the volume's lock held, so no other writer exists. Only the
    engine's temporaries (``*.part.<pid>``) go: in a container the Bunker is
    PID 1 on every start, so a stranded ``.part.1`` would collide with the
    next attempt's, which the engine refuses rather than follows. Verified
    cache entries (content-addressed) stay and are re-verified on use."""
    removed: list[Path] = []
    incoming = root / ".incoming"
    if not incoming.is_dir():
        return removed
    for path in incoming.rglob("*.part.*"):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


def _deferred_of(items: Sequence[Deferred]) -> list[dict[str, str | None]]:
    return [{"unit": d.unit, "name": d.name, "reason": d.reason} for d in items]


def _deferred(listing: Listing) -> list[dict[str, str | None]]:
    return _deferred_of(listing.deferred)


def _is_refused(listing: Listing, item: Mapping[str, str | None]) -> bool:
    return any(
        d.refused and (d.unit, d.name, d.reason) == (item["unit"], item["name"], item["reason"])
        for d in listing.deferred
    )


def _hold_policy(cfg: Config, listing: Listing) -> tuple[Listing, list[Deferred]]:
    """With ``hold_unverified`` false, the artifacts whose check names no digest
    leave the listing and come back as declined. They are not deferred by the
    engine, so :func:`_drop` withdraws one already held."""
    if cfg.selection.hold_unverified:
        return listing, []
    kept: list[Artifact] = []
    declined: list[Deferred] = []
    for a in listing.artifacts:
        if KINDS[a.check].unverified:
            declined.append(
                Deferred(
                    a.unit,
                    a.name,
                    f"declined: its check is {a.check}, which names no digest, and "
                    f"[selection] hold_unverified = false (true, the default, holds it "
                    f"by the maintainer's ruling of 2026-10-02)",
                )
            )
        else:
            kept.append(a)
    return replace(listing, artifacts=tuple(kept)), declined


def _drop(idx: Index, listing: Listing, named: Sequence[str]) -> list[dict[str, str | None]]:
    """Take out of the index what the engine no longer lists. A unit the run
    did not cover (``--unit``) and anything deferred this time are kept."""
    listed = {(a.unit, a.name) for a in listing.artifacts}
    held_back = {(d.unit, d.name) for d in listing.deferred}
    whole = {d.unit for d in listing.deferred if d.name is None}
    kept: list[Entry] = []
    dropped: list[dict[str, str | None]] = []
    for e in idx.artifacts:
        covered = not named or e.unit in named
        if (
            not covered
            or (e.unit, e.name) in listed
            or (e.unit, e.name) in held_back
            or e.unit in whole
        ):
            kept.append(e)
        else:
            dropped.append({"unit": e.unit, "name": e.name, "path": e.path})
    idx.artifacts = kept
    return dropped


def _finish(cfg: Config, idx: Index, report: RunReport, clock: Clock) -> RunReport:
    root = cfg.storage.root
    report.finished = iso(clock())
    counts = report.counts()
    idx.last_run = {
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
    save_index(root, idx, generated=report.finished)
    statuspage.write(root, idx)
    with (root / ".runs.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(report.as_dict(), ensure_ascii=False) + "\n")
    return report


def _order(listing: Listing, named: Sequence[str]) -> list[Artifact]:
    return [a for a in listing.artifacts if not named or a.unit in named]


def run(
    cfg: Config,
    *,
    all_: bool = False,
    units: Sequence[str] = (),
    now: Clock | None = None,
    transport: Transport | None = None,
    listing: Listing | None = None,
) -> RunReport:
    """One pass. Raises :class:`~bunker.volume.Locked` when another run holds
    the volume and :class:`~bunker.index.IndexRefused` when its index cannot
    be read; every other failure is in the report."""
    clock: Clock = now if now is not None else (lambda: datetime.now(UTC))
    root = cfg.storage.root
    root.mkdir(parents=True, exist_ok=True)
    with RunLock(root):
        sweep_incoming(root)
        idx = load_index(root)
        start = clock()
        report = RunReport(started=iso(start))
        try:
            got = listing if listing is not None else ask_engine(cfg)
        except EngineError as exc:
            report.error = str(exc)
            return _finish(cfg, idx, report, clock)
        got, declined = _hold_policy(cfg, got)
        report.engine_version = idx.engine_version = got.engine_version or None
        report.warnings = list(got.warnings)
        report.refused = [d for d in _deferred(got) if _is_refused(got, d)]
        report.declined = _deferred_of(declined)
        report.deferred = idx.deferred = _deferred(got)
        idx.declined = report.declined

        known = {a.unit for a in got.artifacts} | {d.unit for d in got.deferred}
        known |= {d.unit for d in declined}
        unknown = [u for u in units if u not in known]
        if unknown:
            report.error = (
                f"--unit {', '.join(unknown)}: the engine lists no such unit for this "
                f"selection (it lists: {', '.join(sorted(known)) or 'nothing'})"
            )
            return _finish(cfg, idx, report, clock)

        state = _Pass(cfg, idx, start, all_=all_, named=units, transport=_transport(cfg, transport))
        work = _order(got, units)
        report.plain_http = [f"{a.unit}/{a.name}" for a in work if a.url.startswith("http://")]
        with ThreadPoolExecutor(max_workers=cfg.storage.downloads) as pool:
            report.outcomes = list(pool.map(state.one, work))
        report.dropped = _drop(idx, got, units)
        return _finish(cfg, idx, report, clock)


def load_runs(root: Path, limit: int = 1) -> list[Mapping[str, Any]]:
    """The last *limit* entries of ``.runs.jsonl``, oldest first."""
    try:
        lines = (root / ".runs.jsonl").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out: list[Mapping[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
