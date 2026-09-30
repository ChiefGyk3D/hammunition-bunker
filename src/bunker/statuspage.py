# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""``status.html`` (placeholder until Task 7)."""

from __future__ import annotations

from pathlib import Path

from bunker.index import Index


def write(root: Path, index: Index) -> None:
    (root / "status.html").write_text("<!doctype html><title>Bunker</title>\n")
