#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""A name with one wrong letter is still the name.

Silence over a typo reads as a broken bot, not as strictness. But the slack has
to be bounded: too much of it and the bot answers to words that were never its
name. Every check here has a CONTROL on the other side of that line.
"""
import os, sys, pathlib
os.environ.setdefault("BRIDGE_BOT_TOKEN", "0:test")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as C            # noqa: E402
import tg_bridge as B         # noqa: E402

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")

assert C.TRIGGERS, "no triggers configured — the stand would prove nothing"
name = C.TRIGGERS[0]                       # "logic" by default

def rest(text):
    i = B.fuzzy_address(text)
    return None if i is None else text[i:].lstrip(" ,:;!?-–—")

check("the exact name is recognised", rest(f"{name}, are you there?") == "are you there?")
check("one wrong letter still calls us",
      rest(f"{name[:-1]}k, are you there?") == "are you there?",
      "a single typo silences the bot, and silence reads as broken")
check("a swapped pair of letters still calls us",
      rest(f"{name[1]}{name[0]}{name[2:]}, hello") == "hello")

check("CONTROL: an unrelated word does NOT call us",
      B.fuzzy_address("bicycle, are you there?") is None,
      "the slack is so wide the bot answers to anything")
check("CONTROL: a short word does NOT call us",
      B.fuzzy_address("log, hello") is None,
      "words under four letters must not match — too many collisions")
check("CONTROL: the name in the MIDDLE is not an address",
      B.fuzzy_address(f"I asked {name} about it") is None,
      "the rule must anchor on the first word, or every mention becomes a summons")
check("CONTROL: empty text does not crash and does not match",
      B.fuzzy_address("") is None and B.fuzzy_address(None) is None)

print(f"\nFUZZY-ADDRESS {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
raise SystemExit(1 if fail else 0)
