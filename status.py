#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""The bridge's health at a glance: queue, open eyes, disk, activity.

    python3 status.py

Changes nothing, only reads. Safe to run against a live bridge.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

SERVICE = ("verdict-", "needsfile-", "reaction-", "control-", "pending-eyes-", "mailwatch-")


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.0f} B"


def dir_size(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def count(p: Path, service: bool = False) -> int:
    if not p.exists():
        return 0
    files = [f for f in p.glob("*.json")]
    if not service:
        files = [f for f in files if not f.name.startswith(SERVICE)]
    return len(files)


def open_eyes() -> list[str]:
    if not C.REQUESTS.exists():
        return []
    out = []
    for f in sorted(C.REQUESTS.glob("*.json")):
        if f.name.startswith(SERVICE):
            continue
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            r = {}
        mins = int((time.time() - f.stat().st_mtime) / 60)
        out.append(f"    {f.stem:<22} {mins:>4} min  "
                   f"{(r.get('text') or r.get('ask') or '').replace(chr(10),' ')[:38]}")
    return out


def last_activity() -> str:
    bo = C.ROOT / "bridge.out"
    if not bo.exists():
        return "no bridge.out"
    try:
        last = bo.read_text(encoding="utf-8", errors="replace").splitlines()[-1]
        return last[:90]
    except Exception:
        return "?"


def main() -> None:
    eyes = open_eyes()
    print("\n  BRIDGE — HEALTH SNAPSHOT\n")
    print(f"  OPEN EYES (unanswered)   :  {len(eyes)}")
    for line in eyes:
        print(line)
    if not eyes:
        print("    — the queue is empty, idle")
    print()
    print(f"  service in requests/     :  {count(C.REQUESTS, service=True) - len(eyes)}")
    print(f"  answered (served/)       :  {count(C.SERVED, service=True)}")
    print(f"  sent (sent/)             :  {count(C.SENT, service=True)}")
    print(f"  reminders waiting        :  {count(C.REMINDERS, service=True)}")
    print(f"  outbox (not gone out)    :  {count(C.OUTBOX, service=True)}")
    rej = C.OUTBOX / "rejected"
    if rej.exists() and any(rej.glob('*.json')):
        print(f"  REJECTED (rejected/)     :  {count(rej, service=True)}  <- look, malformed items")
    print()
    print("  DISK:")
    print(f"    log tg_log.jsonl     :  {human(C.LOG.stat().st_size) if C.LOG.exists() else '0'}")
    print(f"    media/               :  {human(dir_size(C.MEDIA))}")
    print(f"    voice/               :  {human(dir_size(C.VOICE))}")
    total = dir_size(C.ROOT)
    print(f"    whole tree           :  {human(total)}")
    print()
    print(f"  last line of the bridge log:\n    {last_activity()}\n")


if __name__ == "__main__":
    main()
