#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: a message from a chat OUTSIDE the allow list must leave A TRACE ON
DISK.

Why this stand exists. Such messages used to be discarded, leaving one line in
the log. An empty folder is indistinguishable from the message never having
existed — and a diagnosis from such a "zero" comes out confident and wrong.

Every check has its CONTROL: showing that a trace appears for a foreign chat is
not enough — one has to show that for OUR OWN chat it does NOT, or the stand is
satisfied by an instrument that scatters files over everything.
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

# --- 1. a FOREIGN chat leaves a trace ---
B.handle(upd(-9999000111, "A completely foreign group", "first message"), whoami=False)
f = C.NEEDS_WHITELIST / "-9999000111.json"
check("the foreign chat left a file", f.exists(),
      "the refusal goes into silence again — exactly what cost us on 2026-08-29")
if f.exists():
    d = json.loads(f.read_text(encoding="utf-8"))
    check("the file holds the chat id", d.get("chat_id") == -9999000111)
    check("the file holds the title", d.get("title") == "A completely foreign group")
    check("the file holds the first text", d.get("first_text") == "first message")
    check("the file says WHY it was discarded", "DISCARDED" in (d.get("why") or ""))
    check("the file says HOW to admit it", "chats.json" in (d.get("how_to_admit") or ""))

# --- 2. CONTROL: our own chat leaves NO trace ---
# The stand DECLARES its own allowed chat instead of borrowing one from the
# installation's chats.json. It used to read that file: green in every installed
# tree, FileNotFoundError in a fresh clone, where no chats.json exists yet. Caught
# 2026-09-10 by the release's hard stop, inside the public tree, before the push.
# The patch is exactly the question handle() asks — C.allowed — and it is undone
# right after, so the foreign-chat checks run on the real function.
known = 500600700
_real_allowed = C.allowed
C.allowed = lambda cid: int(cid) == known
before = set(p.name for p in C.NEEDS_WHITELIST.glob("*.json")) if C.NEEDS_WHITELIST.exists() else set()
try:
    B.handle(upd(known, "our own chat", "text"), whoami=False)
except Exception:
    pass   # further on the bridge may go to the network — only the folder matters
finally:
    C.allowed = _real_allowed
after = set(p.name for p in C.NEEDS_WHITELIST.glob("*.json")) if C.NEEDS_WHITELIST.exists() else set()
check("CONTROL: an allowed chat left NO trace", before == after,
      f"the instrument scatters files over everything: {after - before}")

# --- 3. CONTROL: one chat means one file, not one file per message ---
n1 = len(list(C.NEEDS_WHITELIST.glob("*.json")))
for i in range(3):
    B.handle(upd(-9999000111, "A completely foreign group", f"more {i}"), whoami=False)
n2 = len(list(C.NEEDS_WHITELIST.glob("*.json")))
check("CONTROL: repeats do not breed files", n1 == n2, f"was {n1}, now {n2}")

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nUNKNOWN-CHAT {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
