# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""``bunker verify``: re-hash every held file against its sidecar.

Nothing is fetched and the engine is not asked. A file whose bytes no
longer match (or that has gone) is marked ``corrupted`` in the index, which
stops the server offering it; the next run fetches it again. The sidecar is
a claim, not proof, and this is the command that tests the claim on demand.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from bunker import statuspage
from bunker.config import Config
from bunker.index import load as load_index
from bunker.index import save as save_index
from bunker.run import iso
from bunker.volume import RunLock, hash_file, read_sidecar

__all__ = ["Result", "VerifyReport", "verify"]


@dataclass
class Result:
    unit: str
    name: str
    path: str | None
    ok: bool
    reason: str | None = None


@dataclass
class VerifyReport:
    started: str
    finished: str = ""
    results: list[Result] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 0 if all(r.ok for r in self.results) else 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "finished": self.finished,
            "checked": len(self.results),
            "corrupted": sum(1 for r in self.results if not r.ok),
            "results": [asdict(r) for r in self.results],
            "exit_code": self.exit_code,
        }

    def summary_lines(self) -> list[str]:
        bad = [r for r in self.results if not r.ok]
        lines = [f"bunker verify: {len(self.results)} checked, {len(bad)} corrupted"]
        lines += [f"  corrupted: {r.unit}/{r.name}: {r.reason}" for r in bad]
        return lines


def verify(
    cfg: Config, *, units: Sequence[str] = (), now: Callable[[], datetime] | None = None
) -> VerifyReport:
    clock = now if now is not None else (lambda: datetime.now(UTC))
    root = cfg.storage.root
    root.mkdir(parents=True, exist_ok=True)
    with RunLock(root):
        idx = load_index(root)
        report = VerifyReport(started=iso(clock()))
        for entry in idx.artifacts:
            if units and entry.unit not in units:
                continue
            if entry.path is None:
                continue
            path = root / entry.path
            if not path.is_file():
                reason = f"the file is missing ({entry.path})"
            else:
                sha256, _ = hash_file(path)
                claimed = read_sidecar(path)
                if claimed is None:
                    reason = "its sidecar is missing or unreadable"
                elif sha256 != claimed:
                    reason = f"its bytes no longer match its sidecar (sha256 {sha256[:12]}…)"
                else:
                    reason = None
            if reason is None:
                entry.verified = report.started
                report.results.append(Result(entry.unit, entry.name, entry.path, True))
            else:
                entry.status = "corrupted"
                entry.reason = f"{reason}; the next run fetches it again"
                report.results.append(Result(entry.unit, entry.name, entry.path, False, reason))
        report.finished = iso(clock())
        save_index(root, idx, generated=report.finished)
        statuspage.write(root, idx)
        return report
