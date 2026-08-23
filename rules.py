#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Show the rules log: what is allowed, who approved it, and what went out under it.

    ./rules.py

A PERMISSION YOU CANNOT SEE stops being a decision within a month and turns into
a habit. A rule settles the question IN ADVANCE — so the only check left runs
AFTERWARD, and it must be at hand, not buried in a 40-thousand-line log.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import config as C


def main() -> int:
    rules = C.file_rules()
    if not rules:
        print("log is empty — NOTHING is allowed, every file is asked about")
        return 0

    log = C.ROOT / "sent_by_rule.log"
    used: Counter = Counter()
    last: dict[str, str] = {}
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                used[parts[1]] += 1
                last[parts[1]] = parts[0]

    for r in rules:
        rid = r.get("id", "?")
        rooms = r.get("chats") or ([r["chat_id"]] if r.get("chat_id") else [])
        names = []
        for c in rooms:
            pol = C.policy(c)
            names.append(f"{pol.get('_') or c} [{c}]")
        print(f"\n{rid}  «{r.get('project') or '—'}»")
        for d in (r.get("dirs") or []):
            print(f"    folder   {d.get('dir')}  ({d.get('glob') or '*'})")
        for pth in (r.get("paths") or []):
            print(f"    file     {pth}")
        if r.get("dir"):                       # v1.4 form
            print(f"    folder   {r['dir']}  ({r.get('glob') or '*'})")
        for n in names:
            print(f"    to       {n}")
        print(f"    expires  {r.get('expires_at') or 'no expiry'}")
        # WHO approved — by number, not by name: people pick their own names.
        who = r.get("added_by_user_id")
        print(f"    approved {who if who else 'NOBODY — rule is invalid'}"
              f"  {r.get('decision_reaction') or ''}  {r.get('added_at') or ''}")
        print(f"    sent     {used.get(rid, 0)}"
              + (f", last {last[rid]}" if rid in last else ""))

    total = sum(used.values())
    print(f"\ntotal rules {len(rules)}, sends under them {total}")
    if total and not log.exists():
        print("MISMATCH: there is a count but no send log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
