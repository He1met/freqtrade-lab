#!/usr/bin/env python3
"""Append-only observable wall-time receipts; never changes research budgets."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time
from datetime import datetime, timezone

PHASES = ("SEARCH_READ", "REPORT", "MAINTENANCE_WAIT", "USER_IDLE")
SCHEMA = "perp-discovery-timing-v1"
CLOCK_TOLERANCE_SECONDS = 2.0


def _clock():
    """No guessed boot identity: unavailable identity makes accounting unknown."""
    boot, clock_error = None, None
    try:
        if os.uname().sysname == "Darwin":
            value = subprocess.check_output(
                ["/usr/sbin/sysctl", "-n", "kern.boottime"], timeout=2,
                stderr=subprocess.PIPE, text=True).strip()
            if value.startswith("{ sec = "):
                boot = "macos:kern.boottime:" + value
        else:
            boot = "linux:boot_id:" + Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except (OSError, subprocess.SubprocessError) as error:
        clock_error = getattr(error, "stderr", None) or str(error)
    return dict(utc=datetime.now(timezone.utc).isoformat(),
                monotonic_ns=time.monotonic_ns(), boot_id=boot,
                boot_identity_error=clock_error)


def _binding(path, require_json=False):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    if require_json:
        json.loads(raw)
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())


def _timestamp(event):
    value = datetime.fromisoformat(event["utc"])
    if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
        raise ValueError("receipt timestamp must be UTC")
    if type(event["monotonic_ns"]) is not int or event["monotonic_ns"] < 0:
        raise ValueError("invalid monotonic timestamp")
    if event["boot_id"] is not None and not isinstance(event["boot_id"], str):
        raise ValueError("invalid boot identity")
    return value


def _read(handle):
    handle.seek(0)
    raw = handle.read()
    if not raw or not raw.endswith("\n"):
        raise ValueError("empty or incomplete receipt; reconcile without overwriting")
    events = [json.loads(line) for line in raw.splitlines()]
    for i, event in enumerate(events):
        if event["schema"] != SCHEMA or event["sequence"] != i:
            raise ValueError("invalid receipt schema/sequence")
        _timestamp(event)
        if event["event"] not in (("BEGIN",) if i == 0 else ("PHASE", "FINISH")):
            raise ValueError("invalid event order")
        if event["event"] == "FINISH":
            if i != len(events) - 1 or event["phase"] is not None:
                raise ValueError("append after finish or invalid finish")
        elif event["phase"] not in PHASES:
            raise ValueError("invalid phase")
        if event.get("evidence") is not None and _binding(event["evidence"]["path"]) != event["evidence"]:
            raise ValueError("evidence binding changed")
    first = events[0]
    if not first["purpose"].strip() or _binding(first["reference"]["path"], True) != first["reference"]:
        raise ValueError("reference binding changed or missing purpose")
    return events


def _summary(events):
    known = dict.fromkeys(PHASES, 0.0)
    conservative = dict.fromkeys(PHASES, 0.0)
    unknown, issues, intervals = set(), [], []
    for left, right in zip(events, events[1:]):
        wall = (_timestamp(right) - _timestamp(left)).total_seconds()
        monotonic = (right["monotonic_ns"] - left["monotonic_ns"]) / 1e9
        reliable = (bool(left["boot_id"]) and left["boot_id"] == right["boot_id"]
                    and wall >= 0 and monotonic >= 0
                    and abs(wall - monotonic) <= CLOCK_TOLERANCE_SECONDS)
        phase = left["phase"]
        if reliable:
            known[phase] += wall
            conservative[phase] += max(wall, monotonic)
        else:
            unknown.add(phase)
            issues.append(dict(sequence=right["sequence"], reason="UNKNOWN_CLOCK_RECONCILE"))
        intervals.append(dict(phase=phase, start_utc=left["utc"], end_utc=right["utc"],
                              wall_seconds=wall if reliable else None,
                              utc_elapsed_seconds=wall, monotonic_elapsed_seconds=monotonic,
                              conservative_seconds=max(wall, monotonic) if reliable else None,
                              clock_reliable=bool(reliable),
                              potentially_excludable=phase in PHASES[2:],
                              start_evidence=left.get("evidence"), end_evidence=right.get("evidence")))
    finished = events[-1]["event"] == "FINISH"
    if not finished:
        unknown.add(events[-1]["phase"])
        issues.append(dict(sequence=events[-1]["sequence"], reason="OPEN_INTERVAL_RETAINS_RESERVATION"))
    totals = {key: None if key in unknown else value for key, value in known.items()}
    charged = {key: None if key in unknown else value for key, value in conservative.items()}
    complete = finished and not issues
    return dict(schema=SCHEMA, status="FINISHED" if complete else "UNKNOWN_RECONCILE" if finished else "OPEN",
                accounting_status="COMPLETE" if complete else "UNKNOWN",
                reference=events[0]["reference"], purpose=events[0]["purpose"],
                phase_wall_seconds=totals, known_closed_phase_seconds=known,
                phase_conservative_seconds=charged, known_closed_conservative_phase_seconds=conservative,
                search_read_plus_report_seconds=(charged[PHASES[0]] + charged[PHASES[1]])
                if not unknown.intersection(PHASES[:2]) else None,
                reliable_closed_seconds=sum(conservative.values()),
                conservative_charged_seconds=sum(conservative.values()) if complete else None,
                pending_reservation=not complete, automatic_budget_mutation=False,
                automatically_excluded_seconds=0, cpu_seconds=None, exact_model_cost=None,
                measurement="wall_seconds is UTC; conservative and reliable_closed seconds sum "
                "max(UTC, monotonic) per reliable interval, including tool waits; not CPU",
                clock_tolerance_seconds=CLOCK_TOLERANCE_SECONDS,
                intervals=intervals, issues=issues)


def run(command, log, *, reference=None, purpose=None, phase=None, evidence=None, _clock_fn=_clock):
    log = Path(log).resolve()
    if any((parent / ".git").exists() for parent in log.parents):
        raise ValueError("runtime receipt must stay outside Git")
    if phase is not None and phase not in PHASES:
        raise ValueError("invalid phase")
    if command not in ("begin", "phase", "finish", "status"):
        raise ValueError("invalid command")
    if command == "begin" and (not reference or not purpose or not purpose.strip() or not phase):
        raise ValueError("begin requires reference, purpose and phase")
    if command == "phase" and not phase:
        raise ValueError("phase requires phase")
    if command in ("status", "finish") and phase is not None:
        raise ValueError("phase is not allowed for status/finish")
    binding = _binding(reference, True) if command == "begin" else None
    proof = _binding(evidence) if evidence else None
    flags = os.O_RDONLY if command == "status" else os.O_RDWR | os.O_APPEND
    if command == "begin":
        flags |= os.O_CREAT | os.O_EXCL
    fd = os.open(log, flags | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r" if command == "status" else "r+", encoding="utf-8") as handle:
        mode = fcntl.LOCK_SH if command == "status" else fcntl.LOCK_EX
        fcntl.flock(handle, mode | fcntl.LOCK_NB)
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("receipt must be a regular file")
        events = [] if command == "begin" else _read(handle)
        if command != "status":
            if events and events[-1]["event"] == "FINISH":
                raise ValueError("finished receipt is immutable")
            event = dict(schema=SCHEMA, sequence=len(events), event=command.upper(),
                         phase=phase, evidence=proof, **_clock_fn())
            _timestamp(event)
            if command == "begin":
                event.update(reference=binding, purpose=purpose)
            handle.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            events.append(event)
        return _summary(events)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("begin", "phase", "finish", "status"):
        child = commands.add_parser(command)
        child.add_argument("--log", required=True, type=Path)
        if command == "begin":
            child.add_argument("--reference", required=True, type=Path)
            child.add_argument("--purpose", required=True)
        if command in ("begin", "phase"):
            child.add_argument("--phase", choices=PHASES, required=True)
        if command != "status":
            child.add_argument("--evidence", type=Path)
    try:
        print(json.dumps(run(**vars(parser.parse_args())), indent=2, sort_keys=True))
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        parser.exit(2, "timing receipt refused: " + str(error) + "\n")


if __name__ == "__main__":
    main()
