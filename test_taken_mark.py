#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: the ✍ mark at wake-up (the operator, 2026-10-22).

👀 is the bridge's, on arrival. The moment the watch wakes a session on a
message it must put ✍ in the outbox — and ONLY for a message of its own zone:
a "peer:" call, a service notice or a mail call carries no take. The item names
no answers, so the request stays open: ✍ is taken, not done.

Runs a copy of queue_watch.py in a temporary directory with pending.py replaced
by a fixed queue report; the real outbox is never touched.
"""
import json, os, pathlib, shutil, subprocess, sys, tempfile

ok = fail = 0
HERE = pathlib.Path(__file__).resolve().parent


def check(name, cond, why=""):
    global ok, fail
    if cond: print(f"  OK   {name}"); ok += 1
    else: print(f"  FAIL {name} — {why}"); fail += 1


REQ = {
    "100-500":           {"chat_id": 500, "text": "a private question"},
    "4122--9999000111": {"chat_id": -9999000111, "text": "yes"},
    "pending-eyes-1":    {"chat_id": None, "text": "OPEN EYES\n 100-500  4m"},
    "mailwatch-7":       {"chat_id": None, "text": "mail came"},
    "300-777":           {"chat_id": 777, "text": "another zone", "nudged": "2026-10-22T15:49:26"},
}

ENV = dict(os.environ, BRIDGE_BOT_TOKEN="0:test")

with tempfile.TemporaryDirectory() as td:
    t = pathlib.Path(td)
    for f in ("queue_watch.py", "config.py"):
        shutil.copy(HERE / f, t / f)
    shutil.copytree(HERE / "locale", t / "locale")
    (t / "requests").mkdir()
    for n, d in REQ.items():
        (t / "requests" / f"{n}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    lines = "".join(f"  12:00 1m [req] {n}\n      preview of {n}\n" for n in REQ)
    (t / "pending.py").write_text(f"print({lines!r})\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "queue_watch.py", "--except", "777", "--no-mail",
                        "--watch-peer", "--until-called"], cwd=t, env=ENV, capture_output=True,
                       text=True, timeout=60)
    out = t / "outbox"
    marks = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in out.glob("*.react.json")} \
        if out.exists() else {}
    check("the watch woke the session", r.returncode == 0 and r.stdout.strip(), r.stdout + r.stderr)
    check("a private message got ✍", marks.get("100-500.react.json", {}).get("emoji") == "✍", marks)
    g = marks.get("4122--9999000111.react.json", {})
    check("a group message got ✍ with the NEGATIVE chat kept whole",
          g.get("emoji") == "✍" and g.get("chat_id") == -9999000111 and g.get("message_id") == 4122, g)
    check("no mark names answers — the request stays open",
          all(not m.get("answers") for m in marks.values()), marks)
    check("the other zone's message (a peer: call) got NO mark", "300-777.react.json" not in marks, marks)
    check("a service notice and mail got no mark", len(marks) == 2, sorted(marks))

    # A SECOND START must not mark again what was already shouted.
    for p in out.glob("*.react.json"): p.unlink()
    subprocess.run([sys.executable, "queue_watch.py", "--except", "777", "--no-mail", "--once"],
                   cwd=t, env=ENV, capture_output=True, text=True, timeout=60)
    check("--once (a look, not a wake) marks nothing", not list(out.glob("*.react.json")))

sys.path.insert(0, str(HERE))
import config as C
src = (HERE / "queue_watch.py").read_text(encoding="utf-8")
check("✍ is a reaction Telegram accepts (else the bridge refuses it and 👀 stays)",
      'TAKEN_EMOJI = "✍"' in src and "✍" in C.VALID_REACTIONS)

print(f"test_taken_mark: {ok} ok, {fail} failed")
sys.exit(1 if fail else 0)
