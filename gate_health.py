#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Is the consent gate still a decision, or has it become a reflex?

    ./gate_health.py

A human gate fails quietly. Nobody announces that they have started approving
without reading; the queue simply grows while the time spent on each item
shrinks, and one day the safeguard is theatre. The published fingerprint of
that failure is exactly that pair: **rising volume, falling time-to-decide.**

So it is measured rather than promised. The protocol says the assistant must
hang proposals rarely; this file is what makes that claim checkable instead of
a matter of the assistant's good intentions.

What it cannot do: judge whether any single decision was considered. A fast
decision on an obvious matter is fine. The signal is in the trend, not in one
row.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import config as C

WEEK = timedelta(days=7)


def load() -> list[dict]:
    out = []
    for f in sorted(C.DECIDED.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            d["_created"] = datetime.fromisoformat(d["created"])
            d["_decided"] = datetime.fromisoformat(d["decided_at"])
            d["_secs"] = (d["_decided"] - d["_created"]).total_seconds()
            out.append(d)
        except Exception:
            continue
    return out


def median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def main() -> int:
    rows = load()
    if not rows:
        print("no decided proposals yet — nothing to measure.")
        return 0

    now = datetime.now(timezone.utc)
    weeks: dict[int, list[dict]] = {}
    for r in rows:
        weeks.setdefault(int((now - r["_decided"]) // WEEK), []).append(r)

    print(f"{'week':>6}  {'hung':>5}  {'approved':>8}  {'refused':>7}  "
          f"{'expired':>7}  {'median time to decide':>22}")
    for w in sorted(weeks, reverse=True):
        g = weeks[w]
        marked = [r for r in g if r["verdict"] in ("APPROVED", "REFUSED")]
        label = "this" if w == 0 else f"-{w}"
        print(f"{label:>6}  {len(g):>5}  "
              f"{sum(r['verdict'] == 'APPROVED' for r in g):>8}  "
              f"{sum(r['verdict'] == 'REFUSED' for r in g):>7}  "
              f"{sum(r['verdict'] == 'EXPIRED' for r in g):>7}  "
              f"{median([r['_secs'] for r in marked]):>19.0f} s")

    recent, older = weeks.get(0, []), weeks.get(1, [])
    if recent and older:
        def med(g):
            return median([r["_secs"] for r in g
                           if r["verdict"] in ("APPROVED", "REFUSED")])
        if len(recent) > len(older) and 0 < med(recent) < med(older):
            print("\nWARNING: volume up and time-to-decide down against last week.")
            print("That pair is what a gate looks like while it stops being one.")
            print("The remedy is on the assistant's side: hang fewer, larger items.")
    print(f"\nrefusal rate: "
          f"{sum(r['verdict'] == 'REFUSED' for r in rows) / len(rows):.0%} "
          f"of {len(rows)} decided")
    print("A refusal rate of zero over many proposals is itself a finding:")
    print("either nothing questionable was ever proposed, or nothing is read.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
