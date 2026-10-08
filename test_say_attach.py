#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: say.py --attach sends a FILE through the same door as a message —
the zone gate, the author stamp, the wait — instead of a JSON written into the
outbox by hand, which skipped all of them.

Refusals BEFORE queueing: a missing file; a caption over Telegram's 1024; a file
no standing rule covers (the bridge's own rule_for decides, imported, not
copied). After queueing: the record carries "file"; a delivery is reported as
SENT; a file the bridge parked in needs_consent/ is reported as NOT SENT.
"""
import contextlib, io, json, pathlib, sys, tempfile, threading, time, types

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as C            # noqa: E402
import say as S               # noqa: E402

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else:    fail += 1; print(f"  FAIL {name}: {why}")

tmp = pathlib.Path(tempfile.mkdtemp(prefix="say-attach-"))
C.OUTBOX, C.SENT, C.NEEDS_CONSENT = tmp / "outbox", tmp / "sent", tmp / "needs_consent"
for d in (C.OUTBOX, C.SENT, C.NEEDS_CONSENT):
    d.mkdir()
caption = tmp / "c.txt"; caption.write_text("a caption", encoding="utf-8")
doc = tmp / "report.md"; doc.write_text("# report\n", encoding="utf-8")

COVERED = {"value": {"id": "R-test"}}
fake = types.ModuleType("tg_bridge")
fake.rule_for = lambda chat, path: COVERED["value"]
fake.grant_for = lambda chat, path: None
sys.modules["tg_bridge"] = fake

def run(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = S.main([str(caption), "--chat", "1", *args])
    return rc, buf.getvalue()

rc, out = run("--attach", str(tmp / "missing.pdf"), "--no-wait")
check("a missing file is refused", rc == 1 and "no such file" in out, out)
long = tmp / "long.txt"; long.write_text("x" * 1025, encoding="utf-8")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = S.main([str(long), "--chat", "1", "--attach", str(doc), "--no-wait"])
check("a caption over 1024 is refused", rc == 1 and "1024" in buf.getvalue(), buf.getvalue())
COVERED["value"] = None
rc, out = run("--attach", str(doc), "--name", "u1", "--no-wait")
check("an uncovered file is refused BEFORE queueing", rc == 1 and "no standing rule" in out, out)
check("... and nothing reached the queue", not (C.OUTBOX / "u1.json").exists())
COVERED["value"] = {"id": "R-test"}
rc, out = run("--attach", str(doc), "--name", "c1", "--no-wait")
item = json.loads((C.OUTBOX / "c1.json").read_text(encoding="utf-8")) if (C.OUTBOX / "c1.json").exists() else {}
check("a covered file is queued with its path", rc == 0 and item.get("file") == str(doc.resolve()), out)
check("... and the caption as its text", item.get("text") == "a caption")

def later(act):
    t = threading.Thread(target=lambda: (time.sleep(0.4), act())); t.start(); return t
def deliver():
    q = C.OUTBOX / "c2.json"
    (C.SENT / "c2.json").write_text(q.read_text(encoding="utf-8"), encoding="utf-8"); q.unlink()
t = later(deliver)
rc, out = run("--attach", str(doc), "--name", "c2", "--wait", "5")
t.join()
check("a delivered file is reported SENT", rc == 0 and "SENT" in out, out)
def park():
    q = C.OUTBOX / "c3.json"; q.rename(C.NEEDS_CONSENT / "c3.json")
t = later(park)
rc, out = run("--attach", str(doc), "--name", "c3", "--wait", "5")
t.join()
check("a parked file is reported NOT SENT (needs consent)", rc == 1 and "needs_consent" in out, out)

print(f"\n{'SAY ATTACH GREEN' if fail == 0 else 'SAY ATTACH RED'}: {ok} OK, {fail} FAIL")
