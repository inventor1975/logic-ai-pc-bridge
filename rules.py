#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Show the rule book: what is allowed, who approved it, what went out under it.

    ./rules.py

A PERMISSION NOBODY LOOKS AT stops being a decision within a month and becomes a
habit. A rule settles the question IN ADVANCE — so the only check left happens
AFTERWARDS, and it has to be within reach, not buried in a 40 000-line log.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import config as C


def main() -> int:
    rules = C.file_rules()
    if not rules:
        print("the book is empty — NOTHING is allowed, every file is asked about")
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
        if r.get("dir"):                       # the v1.4 shape
            print(f"    folder   {r['dir']}  ({r.get('glob') or '*'})")
        for n in names:
            print(f"    to       {n}")
        print(f"    until    {r.get('expires_at') or 'no deadline'}")
        # WHO approved it, as a number rather than a name: a name is something
        # a person picks for themselves and can change tomorrow.
        who = r.get("added_by_user_id")
        print(f"    by       {who if who else 'NOBODY — the rule is void'}"
              f"  {r.get('decision_reaction') or ''}  {r.get('added_at') or ''}")
        print(f"    sent     {used.get(rid, 0)}"
              + (f", last {last[rid]}" if rid in last else ""))

    total = sum(used.values())
    print(f"\n{len(rules)} rules, {total} sends under them")
    if total and not log.exists():
        print("INCONSISTENT: there is a count but no send log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
