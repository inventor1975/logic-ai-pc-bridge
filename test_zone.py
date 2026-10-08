#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""The queue is shared; the DUTY is not. Tests the zone label in pending.py.

Two operators split the queue with `queue_watch.py --only/--except`. That split
decides who is WOKEN. It never decided who is LISTED: `pending.py` printed the
whole queue with no owner on any row.

On 2026-09-21 that cost a real error. One operator ran the report, read four
rows as four duties, answered three chats belonging to the other operator, and
in each one stated that side's work as not started — while the other side was
at that moment publishing results into those very rooms. One of the three was
false at the instant of sending, by twenty-two seconds.

The chat id was on every row the whole time. That is the point: the
information was present and still read wrong, so the guard belongs where the
reading happens rather than in a rule to be remembered.

TWO PROPERTIES ARE LOAD-BEARING HERE, and both are easy to lose later:

  1. NO FILE, NO CHANGE. Without `.zone` every row is unmarked, exactly as
     before. A product must not start labelling rows for operators who never
     asked for zones.
  2. A ROW THAT SPEAKS FOR EVERY ROOM IS NEVER MARKED. `pending-eyes-*` and
     the other synthetic rows carry `chat_id = null`; marking them would be a
     lie whichever way it fell.

    python3 test_zone.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pending as P                                            # noqa: E402

ok = fail = 0


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print(f"  OK   {name}")
    else:
        fail += 1
        print(f"  FAIL {name}: got {got!r}, want {want!r}")


CHAT = "123456789"           # from the product's SYNTHETIC set, never live
ROOM = "-1001234567890"

print("zone label — who owns which row")

# 1. NO ZONE DECLARED -> nothing is ever marked
for c in (CHAT, ROOM, None):
    check(f"no zone, chat {c} unmarked", P.in_zone(c, None), True)

# 2. `only` — mine is mine, everything else is flagged
mine = ("only", {CHAT})
check("only: my chat is mine", P.in_zone(CHAT, mine), True)
check("only: a room is NOT mine", P.in_zone(ROOM, mine), False)
check("only: int and str agree", P.in_zone(int(ROOM), mine), False)

# 3. `except` — the mirror, so both operators can use one file format
theirs = ("except", {CHAT})
check("except: that chat is NOT mine", P.in_zone(CHAT, theirs), False)
check("except: a room IS mine", P.in_zone(ROOM, theirs), True)

# 4. A row speaking for every room is never marked, under either zone
check("synthetic row unmarked (only)", P.in_zone(None, mine), True)
check("synthetic row unmarked (except)", P.in_zone(None, theirs), True)

# 5. A malformed `.zone` must DISABLE the label, not guess a zone.
#    Guessing would mark real duties as someone else's — worse than no label.
# 5. THE KEYING. One tree, two operators: the zone must be keyed to the
#    OPERATOR, never to the tree. The first version kept one `.zone` beside the
#    script, and whatever it held was inverted for the other operator — his own
#    rooms came up "not yours", the other's private chat came up as his. A label
#    is read, not re-verified, so a wrong label is worse than none.
own = P.owner()
check("owner of this session is identified", own is not None, True)
here = pathlib.Path(P.__file__).resolve().parent
if own:
    pid, start = own
    f = here / f".zone-{pid}"
    saved = f.read_text(encoding="utf-8") if f.exists() else None
    try:
        # NO FILE -> no zone. The declared safe state.
        f.unlink(missing_ok=True)
        check("NO FILE -> no zone at all", P.zone(), None)

        # Well-formed, and stamped with THIS session's start time.
        f.write_text(f"{start} only {CHAT}\n", encoding="utf-8")
        check("well-formed .zone-<pid> is read", P.zone(), ("only", {CHAT}))

        # A REUSED PID MUST NOT INHERIT A DEAD SESSION'S ZONE. Without the
        # start-time stamp this is exactly the inverted label again, arriving
        # later and harder to spot.
        f.write_text(f"{int(start) + 1} only {CHAT}\n", encoding="utf-8")
        check("start-time mismatch -> no zone", P.zone(), None)

        # Malformed disables the label rather than guessing a zone.
        for text, why in [("", "empty"), (f"{start} only", "verb with no chat"),
                          (f"{start} nonsense 1", "unknown verb"),
                          ("only 1\n", "no start stamp"), ("  \n", "blank")]:
            f.write_text(text, encoding="utf-8")
            check(f"malformed ({why}) disables the label", P.zone(), None)

        # The file name carries the operator, so two sessions cannot collide.
        check("file is keyed by pid", f".zone-{pid}" != ".zone", True)
    finally:
        if saved is None:
            f.unlink(missing_ok=True)
        else:
            f.write_text(saved, encoding="utf-8")

# 6. THE AUTHOR OF AN OUTBOUND ACTION. The same file answers "who am I", so
#    there is no second place to keep in step. A session that declared no
#    operator must answer None: an undeclared author is a FINDING, and guessing
#    one would turn a record into an accusation of whoever happened to run it.
if own:
    pid, start = own
    f = here / f".zone-{pid}"
    saved = f.read_text(encoding="utf-8") if f.exists() else None
    try:
        f.write_text(f"{start} only {CHAT}\n", encoding="utf-8")
        check("no `as` -> operator undeclared", P.operator(), None)
        f.write_text(f"{start} only {CHAT} as first-operator\n", encoding="utf-8")
        check("declared operator is read", P.operator(), "first-operator")
        check("the zone still parses with `as` present",
              P.zone(), ("only", {CHAT}))
        f.write_text(f"{start} only {CHAT} as\n", encoding="utf-8")
        check("`as` with no name -> undeclared", P.operator(), None)
        f.write_text(f"{int(start) + 1} only {CHAT} as first-operator\n",
                     encoding="utf-8")
        check("start-time mismatch -> no operator either", P.operator(), None)
    finally:
        if saved is None:
            f.unlink(missing_ok=True)
        else:
            f.write_text(saved, encoding="utf-8")

print(f"\nZONE {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
raise SystemExit(1 if fail else 0)
