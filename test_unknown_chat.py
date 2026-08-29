#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: a message from a chat OUTSIDE the allow-list must leave A TRACE ON DISK.

Why this stand exists. Such messages used to be dropped, leaving a single line in
the log. An empty folder is indistinguishable from no message ever arriving — and
a diagnosis built on that kind of "zero" comes out confident and wrong.

Every check has a CONTROL. Showing that a trace appears for an unknown chat is not
enough: it must also NOT appear for an allowed one, otherwise the stand is happy
with an instrument that scatters files at everything.
"""
import json, pathlib, shutil, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as C            # noqa: E402
import tg_bridge as B         # noqa: E402

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")

def upd(chat_id, title, text, ctype="group"):
    return {"message": {"message_id": 1, "date": 0,
                        "chat": {"id": chat_id, "type": ctype, "title": title},
                        "from": {"id": 1, "first_name": "Someone"},
                        "text": text}}

# EVERY path of the instrument is redirected into a temporary folder. Redirecting
# only needs_whitelist is not enough: the control call with an allowed chat would
# write a real request into the WORKING queue. A stand that litters the working
# inbox is itself a defect.
tmp = pathlib.Path(tempfile.mkdtemp())
C.NEEDS_WHITELIST = tmp / "needs_whitelist"
for _name in ("REQUESTS", "SERVED", "MEDIA", "OUTBOX", "SENT", "NEEDS_CONSENT"):
    if hasattr(C, _name):
        setattr(C, _name, tmp / _name.lower())
        getattr(C, _name).mkdir(parents=True, exist_ok=True)
B._SEEN_UNKNOWN.clear()

# --- 1. An UNKNOWN chat leaves a trace ---
B.handle(upd(-9999000111, "A completely unknown group", "first message"), whoami=False)
f = C.NEEDS_WHITELIST / "-9999000111.json"
check("unknown chat left a file", f.exists(),
      "the refusal goes into silence again — the exact failure this guards against")
if f.exists():
    d = json.loads(f.read_text(encoding="utf-8"))
    check("file carries the chat id", d.get("chat_id") == -9999000111)
    check("file carries the title", d.get("title") == "A completely unknown group")
    check("file carries the first text", d.get("first_text") == "first message")
    check("file says WHY it was dropped", "DROPPED" in (d.get("why") or ""))
    check("file says HOW to admit it", "chats.json" in (d.get("how_to_admit") or ""))

# --- 2. CONTROL: an allowed chat leaves NO trace ---
# The allowed chat is INJECTED, not read from chats.json. A fresh clone has no
# chats.json at all (it holds real ids and is gitignored), and a control whose
# premise depends on a file that may be missing does not control anything: it
# passes an "allowed" chat that is in fact not allowed, and the check succeeds
# for the wrong reason. Here the premise is made true by construction.
known = 424242424242
_real_allowed = C.allowed
C.allowed = lambda cid, _f=_real_allowed: True if cid == known else _f(cid)
before = set(p.name for p in C.NEEDS_WHITELIST.glob("*.json")) if C.NEEDS_WHITELIST.exists() else set()
try:
    B.handle(upd(int(known), "an allowed chat", "text"), whoami=False)
except Exception:
    pass   # further down the bridge may reach for the network — only the folder matters here
after = set(p.name for p in C.NEEDS_WHITELIST.glob("*.json")) if C.NEEDS_WHITELIST.exists() else set()
check("CONTROL: allowed chat left NO trace", before == after,
      f"the instrument scatters files at everything: {after - before}")
check("CONTROL OF THE CONTROL: the injected chat really was allowed",
      C.allowed(known) and not _real_allowed(known),
      "the previous check would pass even with the trace-writing removed")
C.allowed = _real_allowed

# --- 3. CONTROL: one chat, one file — not one file per message ---
n1 = len(list(C.NEEDS_WHITELIST.glob("*.json")))
for i in range(3):
    B.handle(upd(-9999000111, "A completely unknown group", f"more {i}"), whoami=False)
n2 = len(list(C.NEEDS_WHITELIST.glob("*.json")))
check("CONTROL: repeats do not multiply files", n1 == n2, f"was {n1}, now {n2}")

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nUNKNOWN-CHAT {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
