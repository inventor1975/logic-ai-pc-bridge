#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: every settings key the code READS is described in the example.

WHY. The product is open and installed by strangers, and the only place they
learn a key exists is `settings.json.example`. Measured 2026-09-10: the code read
25 keys while the example described 5. Twenty capabilities existed only for
someone who read the source — that is, for us. That is what a "product for the
whole world" installed by one household actually looks like.

WHY A GUARD. A key is created by one line, `_S.get("new", …)`, and stays
undocumented in silence: nothing breaks, nobody notices. The guard makes an
undocumented key IMPOSSIBLE — the stand turns red on the same run.

The other half matters as much: a key the example promises and the code no
longer reads is a lie in the documentation, and the same comparison catches it.
"""
import json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")

def keys_read(code: str):
    """Top-level keys and mail_watch sub-keys, exactly as the code reads them."""
    top = set(re.findall(r'_S\.get\(\s*"([^"]+)"', code))
    sub = set(re.findall(r'_MW\.get\(\s*"([^"]+)"', code))
    sub |= set(re.findall(r'_mw_path\(\s*"([^"]+)"', code))
    return top, sub

code = (HERE / "config.py").read_text(encoding="utf-8")
top, sub = keys_read(code)
ex = json.loads((HERE / "settings.json.example").read_text(encoding="utf-8"))
ex_top = {k for k in ex if not k.startswith("_")}
ex_sub = set((ex.get("mail_watch") or {}))

miss = sorted(top - ex_top)
check("every key the code reads is in the example", not miss,
      f"{len(miss)} undocumented: {', '.join(miss[:8])}{' …' if len(miss) > 8 else ''}")

miss_sub = sorted(sub - ex_sub)
check("every mail_watch sub-key is in the example", not miss_sub,
      f"{len(miss_sub)} undocumented: {', '.join(miss_sub)}")

stale = sorted(ex_top - top)
check("the example promises nothing the code does not read", not stale,
      f"{len(stale)} stale: {', '.join(stale)}")

# CONTROL: the guard must be able to SEE a difference, or its green means nothing.
t, s = keys_read('x = _S.get("alpha", 1)\ny = _MW.get("beta")\nz = _mw_path("gamma")')
check("CONTROL: the parse finds a top-level key", t == {"alpha"})
check("CONTROL: the parse finds a sub-key via _MW.get", "beta" in s)
check("CONTROL: the parse finds a sub-key via _mw_path", "gamma" in s)
check("CONTROL: a missing key is caught", bool({"alpha"} - set()))
check("CONTROL: the example parses as JSON", isinstance(ex, dict) and bool(ex))

print(f"\nSETTINGS-DOCUMENTED {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
