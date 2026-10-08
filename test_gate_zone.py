#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""AUTHORIZATION PRECEDES EXECUTION — the zone gate in say.py.

Every check in say.py until now asked whether a message was WELL FORMED: short
enough, a reaction the bridge can set, a chat that exists. None asked whether
THIS OPERATOR MAY WRITE TO THIS CHAT.

Measured 2026-09-21: two operators share one bridge, one answered three chats
belonging to the other, and in each said that side's work was not started while
it was in fact being delivered — one of those statements false at the instant
of sending, by twenty-two seconds. The rule existed, was written down, and was
opened by nobody at the moment it mattered. A rule that lives in a document
holds until the reader is tired.

THREE PROPERTIES CARRY THIS GATE, and each is load-bearing in a different
direction. Losing any one of them turns it from a guard into a hazard:

  1. IT CANNOT CLOSE THE CHANNEL TO THE PRINCIPAL. The operator holding the
     private chat has it INSIDE their zone, so a message to the person is
     always allowed. A gate able to silence the one way back to the human
     would be a worse failure than the one it prevents.

  2. NO DECLARED ZONE -> NO GATE. An installation that never declared zones
     behaves exactly as before. Refusing on an undeclared zone would mean
     guessing an authority, and a guessed authority is what this whole line
     exists to refuse.

  3. AN UNREADABLE GUARD NEVER REFUSES. If the zone cannot be read, the
     message goes. A guard that fails closed on its own malfunction takes the
     channel down with it.

    python3 test_gate_zone.py
"""
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pending as P                                            # noqa: E402

ok = fail = 0
PRIVATE = "123456789"          # from the product's SYNTHETIC set
ROOM = "-1001234567890"


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  OK   {name}")
    else:
        fail += 1
        print(f"  FAIL {name}: got {got!r}, want {want!r}")


QUEUED = []          # what this stand put in the queue, so it can take it back


def say(text_file, chat, extra=()):
    """Run say.py exactly as an operator would.

    A STAND THAT WRITES INTO THE LIVE QUEUE IS A HAZARD, not a test: one day
    a bridge is running beside it and the stand's message goes out for real.
    This one runs say.py unchanged — the gate must be exercised on the real
    path, not on a copy — and then takes back anything that reached the queue.
    `--no-wait` keeps it from waiting on a bridge that may not be there."""
    before = set(p.name for p in (HERE / "outbox").glob("*.json"))
    r = subprocess.run(
        [sys.executable, str(HERE / "say.py"), str(text_file),
         "--chat", str(chat), "--no-wait", *extra],
        capture_output=True, text=True, timeout=60)
    after = set(p.name for p in (HERE / "outbox").glob("*.json"))
    for name in after - before:
        (HERE / "outbox" / name).unlink(missing_ok=True)
        QUEUED.append(name)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


print("the zone gate — who may write where")

own = P.owner()
check("owner of this session is identified", own is not None, True)

if own:
    pid, start = own
    zone_file = HERE / f".zone-{pid}"
    saved = zone_file.read_text(encoding="utf-8") if zone_file.exists() else None
    with tempfile.TemporaryDirectory() as d:
        msg = pathlib.Path(d) / "m.txt"
        msg.write_text("gate stand, not a real message\n", encoding="utf-8")
        try:
            # 3. NO ZONE -> the gate is absent and nothing changes.
            zone_file.unlink(missing_ok=True)
            rc, out = say(msg, ROOM)
            check("no zone declared -> not refused by zone",
                  "REFUSED BY ZONE" in out, False)

            # 1. The principal's chat is inside the zone of the operator who
            #    holds it, so the way back to the person is never closed.
            zone_file.write_text(f"{start} only {PRIVATE} as stand-operator\n",
                                 encoding="utf-8")
            rc, out = say(msg, PRIVATE)
            check("the principal's chat is never refused",
                  "REFUSED BY ZONE" in out, False)

            # 2. THE GATE ITSELF: a chat outside the zone does not get queued.
            rc, out = say(msg, ROOM)
            check("a chat outside the zone IS refused",
                  "REFUSED BY ZONE" in out, True)
            check("refusal is a non-zero exit", rc != 0, True)
            check("the refusal says where to look", "--zone" in out, True)

            # The mirror zone: the room operator may write rooms, not the
            # private chat. Same file format, opposite membership.
            zone_file.write_text(f"{start} except {PRIVATE} as stand-operator\n",
                                 encoding="utf-8")
            rc, out = say(msg, ROOM)
            check("mirror zone: a room is allowed",
                  "REFUSED BY ZONE" in out, False)
            rc, out = say(msg, PRIVATE)
            check("mirror zone: the private chat is refused",
                  "REFUSED BY ZONE" in out, True)

            # 3 again, from the other side: a malformed zone disables the gate
            #    rather than refusing everything.
            zone_file.write_text("nonsense\n", encoding="utf-8")
            rc, out = say(msg, ROOM)
            check("malformed zone -> gate absent, not closed",
                  "REFUSED BY ZONE" in out, False)
        finally:
            if saved is None:
                zone_file.unlink(missing_ok=True)
            else:
                zone_file.write_text(saved, encoding="utf-8")

# The stand must leave the queue exactly as it found it. Saying so out loud,
# because "it cleaned up" is the kind of claim that quietly stops being true.
left = [p.name for p in (HERE / "outbox").glob("*.json") if p.name in QUEUED]
check("the stand left nothing in the queue", left, [])
print(f"  (queued and taken back: {len(QUEUED)})")

print(f"\nGATE-ZONE {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
raise SystemExit(1 if fail else 0)
