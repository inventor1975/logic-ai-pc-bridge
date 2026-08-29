#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Anti-flood, the against-foolishness kind: going over the limit mutes the
sender for a pause, sends exactly ONE notice, and the principal is NOT exempt.

The function is loaded on its own, with a stub `call`, so the stand never
touches the network and never depends on a config file being present.
"""
import re, time, types, pathlib

def _load():
    src = pathlib.Path(__file__).resolve().parent.joinpath("tg_bridge.py").read_text(encoding="utf-8")
    m = re.search(r"_FLOOD_TIMES.*?\ndef flood_muted\(.*?\n\n\n", src, re.S)
    assert m, "flood_muted not found — the stand must fail loudly, not pass on nothing"
    calls = []
    ns = {"time": time, "now": lambda: "T", "Any": object,
          "call": lambda method, **kw: (calls.append(kw.get("text", "")) or {"ok": True}),
          "C": types.SimpleNamespace(FLOOD_N=10, FLOOD_T=20, FLOOD_K=5,
                                     DRY_RUN=False, REPLY_PREFIX="Logic")}
    exec(compile(m.group(0), "<flood>", "exec"), ns)
    return ns["flood_muted"], calls

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")

fm, calls = _load()

check("ten messages inside the window are NOT a flood",
      all(fm(777, -1, "guest") is False for _ in range(10)),
      "the limit fires early and ordinary conversation gets muted")
check("the eleventh is muted", fm(777, -1, "guest") is True)
check("exactly ONE notice is sent", len(calls) == 1 and "paused" in calls[0],
      f"notices sent: {calls}")
check("CONTROL: further messages are muted SILENTLY",
      fm(777, -1, "guest") is True and len(calls) == 1,
      "a muted sender gets nagged on every message")

calls.clear()
for _ in range(10):
    fm(500, -1, "principal")
check("the principal is NOT an exemption",
      fm(500, -1, "principal") is True and len(calls) == 1,
      "a compromised principal account is exactly where a flood comes from")

check("CONTROL: a different sender is untouched", fm(999, -1, "other") is False,
      "the mute is global rather than per-sender — it would silence everyone")

print(f"\nFLOOD {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
raise SystemExit(1 if fail else 0)
