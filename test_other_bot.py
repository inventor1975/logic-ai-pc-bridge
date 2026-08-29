#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: a command aimed at ANOTHER bot must not become a request for us.

Telegram lets a sender target one bot among several with `/command@BotName`.
In a room where everything counts as addressed, every such command used to
become a request and wake the assistant.

Every check has a CONTROL. Showing that another bot's command is dropped is not
enough: our own command, an unsuffixed command, and plain text must all still
arrive — otherwise the stand is happy with an instrument that drops everything.
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

CHAT = 555000111
tmp = pathlib.Path(tempfile.mkdtemp())
for _name in ("REQUESTS", "SERVED", "MEDIA", "OUTBOX", "SENT",
              "NEEDS_CONSENT", "NEEDS_WHITELIST"):
    if hasattr(C, _name):
        setattr(C, _name, tmp / _name.lower())
        getattr(C, _name).mkdir(parents=True, exist_ok=True)

_POL = {"principal": CHAT, "all_addressed": True, "may_address": "all",
        "outward_gate": False, "topic": "", "language": "",
        "relay_to_principal": False, "ignore_other_bots": True}
C.policy = lambda cid: _POL
B._ME_NAME[0] = "logic_vr_bot"

def requests_after(text):
    for f in C.REQUESTS.glob("*.json"):
        f.unlink()
    msg = {"message_id": 7, "date": 0,
           "chat": {"id": CHAT, "type": "group", "title": "room"},
           "from": {"id": CHAT, "first_name": "Someone"}, "text": text}
    try:
        B.accept(CHAT, msg, {}, text, msg["from"])
    except Exception as e:
        print(f"    (accept raised {type(e).__name__}: {e})")
    return sorted(p.name for p in C.REQUESTS.glob("*.json"))

check("another bot's command makes NO request",
      requests_after("/allow_here@IUSLererBot") == [],
      "every command meant for the other bot still wakes the assistant")

check("CONTROL: our OWN targeted command still arrives",
      requests_after("/allow_here@logic_vr_bot") != [],
      "the filter eats commands addressed to us — worse than the defect")

check("CONTROL: an UNSUFFIXED command still arrives",
      requests_after("/botdialog_here") != [],
      "an unsuffixed command is addressed to every bot; taking it away decides for the sender")

check("CONTROL: plain text still arrives",
      requests_after("hello, are you there?") != [],
      "ordinary speech must be untouched by this rule")

B._ME_NAME[0] = ""
check("CONTROL: with our name UNKNOWN nothing is filtered",
      requests_after("/allow_here@IUSLererBot") != [],
      "when getMe has not succeeded we must wake up rather than swallow an address")
B._ME_NAME[0] = "logic_vr_bot"

check("a plain @mention of another bot makes NO request",
      requests_after("@IUSLererBot, please introduce yourself to everyone") == [],
      "driving another assistant in the room keeps waking us")

check("ESCAPE: a message naming US as well still arrives",
      requests_after("@IUSLererBot, ask Logic whether the digest matched") != [],
      "a message addressed to BOTH must never be taken away")

check("CONTROL: an @mention of a human is untouched",
      requests_after("@arcus18 could you confirm the package?") != [],
      "the rule must not swallow ordinary mentions — only ones naming another bot we know we are not")

check("CONTROL: a command-looking word inside a sentence is not a command",
      requests_after("please run /allow_here@IUSLererBot for me") != [],
      "the rule must anchor at the start, not match anywhere in the text")

# CONTROL OF THE DEFAULT. The rule is opt-in: with the setting off, the other
# bot's command must still arrive. Shipping it as unconditional would decide for
# every operator that another assistant's traffic is never meant for theirs.
_POL["ignore_other_bots"] = False
check("CONTROL: with the setting OFF nothing is filtered",
      requests_after("/allow_here@IUSLererBot") != [],
      "the feature is forced on everyone instead of being a choice")
_POL["ignore_other_bots"] = True

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nOTHER-BOT {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
