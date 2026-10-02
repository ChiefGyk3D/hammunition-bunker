# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""``bunker``: run, status, verify, serve, schedule, doctor.

Exit codes: 0 clean; 1 a run or check found failures; 2 refused (the
config, the index, the arguments); 125 another run holds the volume.
``--json`` prints one document in Hammunition's envelope shape (D-059);
``serve`` and ``schedule`` have none and refuse it with an ``error``
document.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any

from bunker import __version__, checks, config, envelope, index, run, schedule, server, verify
from bunker.config import Config, ConfigError
from bunker.doctor import doctor_path
from bunker.index import IndexRefused
from bunker.volume import Locked

__all__ = ["main"]

EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_LOCKED = 0, 1, 2, 125

#: Injected by the tests for deterministic timestamps; None is the real clock.
CLOCK: Callable[[], datetime] | None = None

Emit = Callable[[str, Mapping[str, Any]], None]


def _config(args: argparse.Namespace) -> Config:
    return config.load(config.find(args.config))


def _err(message: str) -> None:
    print(f"bunker: {message}", file=sys.stderr)


def cmd_run(args: argparse.Namespace, emit: Emit | None) -> int:
    cfg = _config(args)
    report = run.run(cfg, all_=args.all, units=tuple(args.unit or ()), now=CLOCK)
    if emit is not None:
        emit("run", report.as_dict())
    else:
        print("\n".join(report.summary_lines()))
    return report.exit_code


def _status_body(idx: index.Index) -> dict[str, Any]:
    counts = dict.fromkeys(index.STATUSES, 0)
    for entry in idx.artifacts:
        counts[entry.status] += 1
    return {
        "engine_version": idx.engine_version,
        "generated": idx.generated,
        "last_run": idx.last_run,
        "counts": counts,
        "not_current": [
            {"unit": e.unit, "name": e.name, "status": e.status, "reason": e.reason}
            for e in idx.artifacts
            if e.status != "current"
        ],
        "deferred": idx.deferred,
        "declined": idx.declined,
        "unverified": [
            {
                "unit": e.unit,
                "name": e.name,
                "check": e.publisher_check,
                "size": e.size,
                "fetched": e.fetched,
                "licence": e.licence,
            }
            for e in index.held_unverified(idx)
        ],
    }


def cmd_status(args: argparse.Namespace, emit: Emit | None) -> int:
    cfg = _config(args)
    body = _status_body(index.load(cfg.storage.root))
    if emit is not None:
        emit("status", body)
        return EXIT_OK
    last = body["last_run"]
    if not last:
        print("No run yet.")
    else:
        print(
            f"Last run: {last.get('started')} to {last.get('finished')}: "
            f"{last.get('fetched', 0)} fetched, {last.get('verified', 0)} verified, "
            f"{last.get('stale', 0)} stale, {last.get('failed', 0)} failed, "
            f"{last.get('corrupted', 0)} corrupted"
        )
        if last.get("error"):
            print(f"  error: {last['error']}")
    counts = body["counts"]
    print("Held: " + ", ".join(f"{n} {status}" for status, n in counts.items()))
    if body["not_current"]:
        print("Not current:")
        for e in body["not_current"]:
            print(f"  {e['status']}: {e['unit']}/{e['name']}: {e['reason']}")
    elif last:
        print("Everything held is current.")
    for d in body["deferred"]:
        name = f"/{d['name']}" if d.get("name") else ""
        print(f"  deferred: {d['unit']}{name}: {d['reason']}")
    for d in body["declined"]:
        name = f"/{d['name']}" if d.get("name") else ""
        print(f"  declined: {d['unit']}{name}: {d['reason']}")
    if body["unverified"]:
        print(f"{checks.UNVERIFIED_LABEL} ({len(body['unverified'])}):")
        for u in body["unverified"]:
            size = f"{u['size']} bytes" if u["size"] is not None else "size unknown"
            print(f"  {u['unit']}/{u['name']}: {u['check']}, {size}, fetched {u['fetched']}")
    return EXIT_OK


def cmd_verify(args: argparse.Namespace, emit: Emit | None) -> int:
    cfg = _config(args)
    report = verify.verify(cfg, units=tuple(args.unit or ()), now=CLOCK)
    if emit is not None:
        emit("verify", report.as_dict())
    else:
        print("\n".join(report.summary_lines()))
    return report.exit_code


def cmd_doctor(args: argparse.Namespace, emit: Emit | None) -> int:
    try:
        path = config.find(args.config)
    except ConfigError as exc:
        path = args.config or Path("bunker.toml")
        _err(str(exc))
    report = doctor_path(path)
    if emit is not None:
        emit("doctor", report.as_dict())
    else:
        print("\n".join(report.lines()))
    return EXIT_OK if report.ok else EXIT_FAILED


def _stop_on_signals(stop: Callable[[], None]) -> None:
    def handler(signum: int, frame: FrameType | None) -> None:
        stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, handler)


def _now_iso() -> str:
    return run.iso(datetime.now(UTC))


def cmd_serve(args: argparse.Namespace, emit: Emit | None) -> int:
    cfg = _config(args)
    index.ensure(cfg.storage.root, generated=_now_iso())
    index.load(cfg.storage.root)  # refuse a newer index before serving it
    httpd = server.make_server(cfg.storage.root, cfg.serve.bind, cfg.serve.port)
    print(f"bunker {__version__}: serving {cfg.storage.root} on {cfg.serve.bind}:{cfg.serve.port}")
    sys.stdout.flush()
    _stop_on_signals(lambda: threading.Thread(target=httpd.shutdown, daemon=True).start())
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return EXIT_OK


def cmd_schedule(args: argparse.Namespace, emit: Emit | None) -> int:
    cfg = _config(args)
    root = cfg.storage.root
    index.ensure(root, generated=_now_iso())
    index.load(root)
    httpd = server.make_server(root, cfg.serve.bind, cfg.serve.port)
    serving = threading.Thread(target=httpd.serve_forever, name="serve", daemon=True)
    serving.start()
    print(
        f"bunker {__version__}: serving {root} on {cfg.serve.bind}:{cfg.serve.port}; "
        f"a pass now, then daily at {cfg.schedule.run_at.strftime('%H:%M')}"
    )
    sys.stdout.flush()
    stop = threading.Event()
    _stop_on_signals(stop.set)

    def once() -> None:
        # Re-read the config each pass: a changed selection takes effect
        # without a restart; a broken one is reported and the last good kept.
        nonlocal cfg
        try:
            cfg = _config(args)
        except ConfigError as exc:
            _err(f"{exc}; this pass uses the configuration the scheduler started with")
        try:
            report = run.run(cfg)
        except Locked as exc:
            _err(f"{exc}; this pass is skipped")
            return
        except IndexRefused as exc:
            _err(str(exc))
            return
        print("\n".join(report.summary_lines()))
        sys.stdout.flush()

    try:
        schedule.loop(cfg.schedule.run_at, stop, once)
    finally:
        httpd.shutdown()
        httpd.server_close()
    return EXIT_OK


COMMANDS: dict[str, Callable[[argparse.Namespace, Emit | None], int]] = {
    "run": cmd_run,
    "status": cmd_status,
    "verify": cmd_verify,
    "serve": cmd_serve,
    "schedule": cmd_schedule,
    "doctor": cmd_doctor,
}
NO_JSON = ("serve", "schedule")


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="bunker",
        description="A verified LAN mirror of Hammunition's offline data.",
    )
    top.add_argument("--version", action="version", version=f"bunker {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="bunker.toml (default: /etc/bunker/bunker.toml, then ./bunker.toml)",
    )
    common.add_argument("--json", action="store_true", help="print one JSON document")
    sub = top.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_run = sub.add_parser("run", parents=[common], help="one pass now")
    p_run.add_argument(
        "--all", action="store_true", help="every artifact is due, whatever its cadence"
    )
    p_run.add_argument(
        "--unit", action="append", metavar="NAME", help="only this unit, and it is due (repeatable)"
    )
    sub.add_parser("status", parents=[common], help="the last run and what is not current")
    p_verify = sub.add_parser(
        "verify", parents=[common], help="re-hash every file against its sidecar; nothing fetched"
    )
    p_verify.add_argument("--unit", action="append", metavar="NAME", help="only this unit")
    sub.add_parser("serve", parents=[common], help="the HTTP server, in the foreground")
    sub.add_parser(
        "schedule",
        parents=[common],
        help="serve, and run on the schedule (the container's entry point)",
    )
    sub.add_parser(
        "doctor", parents=[common], help="the engine, the volume, the port and the config"
    )
    return top


def _dispatch(args: argparse.Namespace, emit: Emit | None) -> int:
    try:
        return COMMANDS[args.command](args, emit)
    except ConfigError as exc:
        _err(str(exc))
        return EXIT_REFUSED
    except IndexRefused as exc:
        _err(str(exc))
        return EXIT_REFUSED
    except Locked as exc:
        _err(str(exc))
        return EXIT_LOCKED


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.json:
        return _dispatch(args, None)
    if args.command in NO_JSON:

        def refuse(emit: Emit) -> int:
            _err(f"`bunker {args.command}` runs until stopped and has no --json form")
            return EXIT_REFUSED

        return envelope.run_json(args.command, refuse)
    return envelope.run_json(args.command, lambda emit: _dispatch(args, emit))
