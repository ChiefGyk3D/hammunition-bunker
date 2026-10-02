# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""``status.html``: the index, readable, at the server root.

Last run, per-unit counts, every problem with its reason, disk used, and
each unit's licence line, because the mirror redistributes on the LAN what
each licence permits and the page says so. One self-contained page: no
script, no external stylesheet, no font, nothing fetched. Every value that
came from the engine or a publisher is escaped.
"""

from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path

from bunker import __version__
from bunker.checks import UNVERIFIED_LABEL
from bunker.index import STATUSES, Index, held_unverified
from bunker.volume import disk_used, write_atomic

__all__ = ["human_size", "render", "write"]

_STYLE = """
:root { --bg: #fbfaf7; --fg: #1d1d1b; --muted: #6b6a66; --line: #dddad2; --bad: #a3321f;
        --warn: #8a5a00; --ok: #2f6b2f; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #151514; --fg: #ecebe6; --muted: #a09e97; --line: #34332f; --bad: #f08b77;
          --warn: #e6b450; --ok: #8fcf8f; }
}
body { background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, sans-serif;
       margin: 0 auto; max-width: 60rem; padding: 1.5rem 1rem 3rem; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
p.lede, .muted { color: var(--muted); }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid var(--line);
         vertical-align: top; overflow-wrap: anywhere; }
th { font-weight: 600; } .bad { color: var(--bad); } .warn { color: var(--warn); }
.ok { color: var(--ok); } code { font-size: .92em; }
.wrap { overflow-x: auto; }
"""


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for suffix in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024
        if value < 1024 or suffix == "TiB":
            return f"{value:.1f} {suffix}"
    raise AssertionError  # pragma: no cover


def _e(value: object) -> str:
    return escape("" if value is None else str(value))


def render(index: Index, *, disk_used: int) -> str:
    """The page, as a string."""
    run = index.last_run or {}
    out: list[str] = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Hammunition Bunker</title>",
        f"<style>{_STYLE}</style></head><body>",
        "<h1>Hammunition Bunker</h1>",
        '<p class="lede">A verified LAN mirror of Hammunition\'s offline data. It serves '
        "without authentication, over plain HTTP, because every machine that takes a file "
        "from it checks every byte against a digest it already holds. It belongs on your "
        "LAN only: never publish its port on an interface the internet can reach.</p>",
        "<h2>Last run</h2>",
    ]
    if not run:
        out.append("<p>No run yet.</p>")
    else:
        out.append(
            f"<p>{_e(run.get('started'))} to {_e(run.get('finished'))}: "
            f"{_e(run.get('fetched', 0))} fetched, {_e(run.get('verified', 0))} verified, "
            f"{_e(run.get('stale', 0))} stale, {_e(run.get('failed', 0))} failed, "
            f"{_e(run.get('corrupted', 0))} corrupted.</p>"
        )
        if run.get("error"):
            out.append(f'<p class="bad">The run failed: {_e(run["error"])}</p>')
        plain = run.get("plain_http") or []
        if plain:
            out.append(
                f"<p>{len(plain)} publisher URL(s) are plain HTTP, as the catalog names "
                f"them; the digest is the check, not the transport: "
                f"{_e(', '.join(str(p) for p in plain))}</p>"
            )

    per_unit: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(STATUSES, 0))
    sizes: dict[str, int] = defaultdict(int)
    licences: dict[str, str] = {}
    for entry in index.artifacts:
        per_unit[entry.unit][entry.status] += 1
        sizes[entry.unit] += entry.size or 0
        licences.setdefault(entry.unit, entry.licence)
    out += [
        "<h2>Units</h2>",
        '<div class="wrap"><table><thead><tr><th>Unit</th><th>Current</th><th>Stale</th>'
        "<th>Failed</th><th>Corrupted</th><th>Size</th></tr></thead><tbody>",
    ]
    for unit in sorted(per_unit):
        c = per_unit[unit]
        out.append(
            f"<tr><td>{_e(unit)}</td>\n<td>{c['current']}</td>\n<td>{c['stale']}</td>\n"
            f"<td>{c['failed']}</td>\n<td>{c['corrupted']}</td>\n"
            f"<td>{human_size(sizes[unit])}</td></tr>"
        )
    if not per_unit:
        out.append('<tr><td colspan="6">Nothing held yet.</td></tr>')
    out.append("</tbody></table></div>")

    problems = [e for e in index.artifacts if e.status != "current"]
    out.append("<h2>Not current</h2>")
    if problems:
        out.append(
            '<div class="wrap"><table><thead><tr><th>Artifact</th><th>Status</th>'
            "<th>Reason</th></tr></thead><tbody>"
        )
        for e in problems:
            css = "warn" if e.status == "stale" else "bad"
            out.append(
                f"<tr><td><code>{_e(e.unit)}/{_e(e.name)}</code></td>"
                f'<td class="{css}">{_e(e.status)}</td><td>{_e(e.reason)}</td></tr>'
            )
        out.append("</tbody></table></div>")
    else:
        out.append('<p class="ok">Everything held is current.</p>')

    unverified = held_unverified(index)
    if unverified:
        out.append(
            f"<h2>{_e(UNVERIFIED_LABEL)}</h2><p>No digest exists for these: the publisher "
            f"offers none and the file changes. Only the file's own structure was checked "
            f"(a damaged download is caught, an altered one is not). They are held because "
            f"the maintainer ruled, on 2026-10-02, that a Bunker may keep them for users to "
            f"download. The ACMA register includes licensees' names and addresses "
            f"(<code>client.csv</code>), which its licence bars passing on in a derivative: "
            f"keep this mirror on your LAN. Turn it off with "
            f"<code>[selection] hold_unverified = false</code>.</p>"
            '<div class="wrap"><table><thead><tr><th>Artifact</th><th>Check</th><th>Size</th>'
            "<th>Fetched</th></tr></thead><tbody>"
        )
        for e in unverified:
            size = human_size(e.size) if e.size is not None else "unknown"
            out.append(
                f"<tr><td><code>{_e(e.unit)}/{_e(e.name)}</code></td>"
                f"<td>{_e(e.publisher_check)}</td><td>{size}</td><td>{_e(e.fetched)}</td></tr>"
            )
        out.append("</tbody></table></div>")

    if index.deferred:
        out.append("<h2>Deferred by the engine</h2><ul>")
        for d in index.deferred:
            name = f"/{_e(d.get('name'))}" if d.get("name") else ""
            out.append(f"<li><code>{_e(d.get('unit'))}{name}</code>: {_e(d.get('reason'))}</li>")
        out.append("</ul>")

    if index.declined:
        out.append("<h2>Declined by your configuration</h2><ul>")
        for d in index.declined:
            name = f"/{_e(d.get('name'))}" if d.get("name") else ""
            out.append(f"<li><code>{_e(d.get('unit'))}{name}</code>: {_e(d.get('reason'))}</li>")
        out.append("</ul>")

    out.append(
        "<h2>Licences</h2><p>What each unit's publisher permits; this mirror "
        "redistributes on your LAN under those terms.</p><ul>"
    )
    for unit in sorted(licences):
        out.append(f"<li><code>{_e(unit)}</code>: {_e(licences[unit])}</li>")
    out += [
        "</ul>",
        f"<h2>Disk</h2><p>{human_size(disk_used)} used on the volume.</p>",
        f'<p class="muted">Index generated {_e(index.generated)} by Bunker {_e(__version__)} '
        f"for Hammunition {_e(index.engine_version or 'unknown')}. The machine-readable "
        'form is <a href="index.json">index.json</a>.</p>',
        "</body></html>",
        "",
    ]
    return "\n".join(out)


def write(root: Path, index: Index) -> None:
    """Render and write ``<root>/status.html`` atomically."""
    root.mkdir(parents=True, exist_ok=True)
    write_atomic(root / "status.html", render(index, disk_used=disk_used(root)).encode("utf-8"))
