#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Open eyes are SHOWN as a list, never taken off automatically.

The eye is the only indicator of "not answered". If the bridge took it off by
itself the signal would go out while the matter stayed — so the bridge only
puts the list under the assistant's nose, and the eye closes on a real answer.

The function is loaded on its own against a temporary directory: the stand must
not depend on a config file and must never touch the working queue.
"""
import re, json, time, os, types, tempfile, shutil, pathlib

def _load(name):
    src = pathlib.Path(__file__).resolve().parent.joinpath("tg_bridge.py").read_text(encoding="utf-8")
    m = re.search(rf"def {name}\(.*?\n\n\n", src, re.S)
    assert m, f"{name} not found — the stand must fail loudly, not pass on nothing"
    ns = {"json": json, "time": time, "now": lambda: "T"}
    exec(compile(m.group(0), "<eyes>", "exec"), ns)
    return ns

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")

ns = _load("pending_eyes")
tmp = pathlib.Path(tempfile.mkdtemp()); req = tmp/"req"; srv = tmp/"srv"
req.mkdir(); srv.mkdir()
ns["C"] = types.SimpleNamespace(REQUESTS=req, SERVED=srv, EYES_AFTER_MIN=0)
pe = ns["pending_eyes"]

def mk(n, text="hi"):
    p = req/n; p.write_text(json.dumps({"text": text}), encoding="utf-8")
    os.utime(p, (time.time()-3600, time.time()-3600))

mk("677-1.json", "hello"); mk("882-1.json", "a question")
mk("control-9-1.json"); mk("reaction-9-1.json")     # must be excluded
pe()
pf = list(req.glob("pending-eyes-*.json"))
check("one list is written", len(pf) == 1, f"files: {[p.name for p in pf]}")
lst = json.loads(pf[0].read_text(encoding="utf-8"))["text"] if pf else ""
check("real requests are named", "677-1" in lst and "882-1" in lst)
check("CONTROL: service files are NOT named",
      "control-9-1" not in lst and "reaction-9-1" not in lst,
      "the assistant is nagged about its own bookkeeping")

before = set(req.glob("pending-eyes-*.json")); pe()
check("CONTROL: the same set does not nag twice",
      set(req.glob("pending-eyes-*.json")) == before,
      "a fresh list on every pass turns the signal into noise")

(req/"677-1.json").unlink(); (req/"882-1.json").unlink(); pe()
check("nothing hanging retires the list",
      not list(req.glob("pending-eyes-*.json")) and bool(list(srv.glob("pending-eyes-*.json"))),
      "the list outlives the thing it was about")

mk("991-1.json", "new one"); pe()
check("CONTROL: a CHANGED set makes a new list",
      any("991-1" in json.loads(p.read_text(encoding="utf-8"))["text"]
          for p in req.glob("pending-eyes-*.json")),
      "the list froze on its first content and stopped tracking")

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nPENDING-EYES {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
raise SystemExit(1 if fail else 0)
