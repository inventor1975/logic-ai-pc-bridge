#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: say.py --answers must name a request that EXISTS, or nothing is sent.

Measured 2026-10-03: --answers 8726 (the message id alone; the request is
8726-<chat>) was queued, say.py printed "closes 1 request(s)", and the eye
stayed open. Here: the short form is completed from --chat; a full id passes
as is; an id of an already answered request passes with a note; an unknown id
is REFUSED and nothing reaches the outbox.

The CONTROL: the same unknown id with a request file present under a DIFFERENT
chat must still be refused — completion uses --chat, never a guess.
"""
import contextlib, io, json, pathlib, shutil, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as C            # noqa: E402
import say as S               # noqa: E402

# THE ZONE IS NOT WHAT IS TESTED. An installation with a declared zone refuses
# chat 77 BEFORE the answers check runs, so the refusal cases below went green
# there for the wrong reason and the passing cases went red (measured on the
# live tree 2026-10-03: 3 OK, 3 FAIL). The zone has its own stand.
S._zone = lambda: None

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else:    fail += 1; print(f"  FAIL {name}: {why}")

tmp = pathlib.Path(tempfile.mkdtemp(prefix="say-answers-"))
C.OUTBOX, C.SENT = tmp / "outbox", tmp / "sent"
C.REQUESTS, C.SERVED = tmp / "requests", tmp / "served"
for d in (C.OUTBOX, C.SENT, C.REQUESTS, C.SERVED):
    d.mkdir()
msg = tmp / "m.txt"
msg.write_text("hello", encoding="utf-8")
(C.REQUESTS / "500-77.json").write_text("{}", encoding="utf-8")
(C.REQUESTS / "501-77.json").write_text("{}", encoding="utf-8")
(C.SERVED / "502-77.json").write_text("{}", encoding="utf-8")
(C.REQUESTS / "600-88.json").write_text("{}", encoding="utf-8")

def run(name, answers):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = S.main([str(msg), "--chat", "77", "--answers", answers, "--name", name, "--no-wait"])
    q = C.OUTBOX / f"{name}.json"
    item = json.loads(q.read_text(encoding="utf-8")) if q.exists() else None
    return rc, buf.getvalue(), item

rc, out, item = run("a1", "500")
check("short id completed from --chat", rc == 0 and item and item.get("answers") == ["500-77"], out)

rc, out, item = run("a2", "501-77")
check("full id passes as is", rc == 0 and item and item.get("answers") == ["501-77"], out)

rc, out, item = run("a3", "502")
check("already answered: passes with a note", rc == 0 and item and item.get("answers") == ["502-77"]
      and "already answered" in out, out)

rc, out, item = run("a4", "999")
check("unknown id: REFUSED, nothing queued", rc == 1 and item is None and "names no request" in out, out)

rc, out, item = run("a5", "600")
check("CONTROL: a request of ANOTHER chat is not guessed", rc == 1 and item is None and "names no request" in out, out)

rc, out, item = run("a6", "500,999")
check("one bad id in a list refuses the whole message", rc == 1 and item is None and "999" in out, out)

shutil.rmtree(tmp)
print(f"say_answers: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
