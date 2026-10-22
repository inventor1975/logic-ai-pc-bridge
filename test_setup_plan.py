#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: the short setup decides the right thing from what arrives.

WHY. The operator asked for an install where a person does the minimum: create a
bot, paste the token, write to it. Everything else — who is the principal, which
language, which chats — is now DECIDED by setup from real messages. A decision
nobody sees being made has to be tested, because nobody will notice it being
wrong until a stranger's bot talks to the wrong person.

The negative half matters most: a group is never allowed silently, and a unit
serving another directory is never overwritten.

Offline: no network, no input — plan_install and unit_conflict are pure.
"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import setup as S

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")

BOT = {"first_name": "Logic", "username": "some_test_bot"}
SHIPPED = ["de", "en", "es", "fr", "he", "ru", "uk"]
ME, OTHER = 500600700, 111222333

def private(uid=ME, name="Anna", lang="ru"):
    return {"chat_id": uid, "kind": "private", "title": name,
            "people": {uid: {"name": name, "lang": lang}}}

def group(people, gid=-1001234567890, title="Team"):
    return {"chat_id": gid, "kind": "supergroup", "title": title,
            "people": {u: {"name": "x", "lang": "en"} for u in people}}

print("\nwho and what language")
p = S.plan_install(BOT, [private()], SHIPPED)
check("a private message makes a plan", p["ok"])
check("the writer becomes the principal", p.get("principal") == ME, str(p.get("principal")))
check("the language comes from Telegram (ru)", p["settings"]["lang"] == "ru", p["settings"]["lang"])
check("the name comes from the bot", p["settings"]["bot_name"] == "Logic")
check("the operator is the person who wrote", p["settings"]["operator"] == "Anna")
check("the private chat is allowed and fully addressed",
      p["chats"][str(ME)]["all_addressed"] is True and p["chats"][str(ME)]["principal"] == ME)
check("it answers at once — the operator's word, no question",
      p["settings"]["dry_run"] is False)

print("\nlanguage codes as Telegram actually sends them")
check("pt-br, not shipped -> English", S.lang_from("pt-br", SHIPPED) == "en")
check("de-AT -> de", S.lang_from("de-AT", SHIPPED) == "de")
check("UK in capitals -> uk", S.lang_from("UK", SHIPPED) == "uk")
check("no code at all -> English", S.lang_from(None, SHIPPED) == "en")
check("he -> he", S.lang_from("he", SHIPPED) == "he")

print("\ngroups are a question, never a default")
p = S.plan_install(BOT, [private(), group([ME, OTHER])], SHIPPED)
check("a group the principal wrote in comes back as a QUESTION",
      len(p["groups"]) == 1 and "-1001234567890" not in p["chats"], str(p["groups"])[:80])
p = S.plan_install(BOT, [private(), group([OTHER])], SHIPPED)
check("a group the principal did NOT write in is not even offered", p["groups"] == [])
p = S.plan_install(BOT, [group([ME])], SHIPPED)
check("with no private message there is nothing to decide", p["ok"] is False)
p = S.plan_install(BOT, [], SHIPPED)
check("with nothing at all, no plan", p["ok"] is False)

print("\na stranger who writes too is never made the owner (2026-10-22)")
STRANGER = 555000111
both = [private(STRANGER, "Stranger", "en"), private()]
p = S.plan_install(BOT, both, SHIPPED)
check("two private writers -> nothing decided", p["ok"] is False and "principal" not in p, str(p))
check("both come back as candidates, the stranger first as he arrived",
      [c["uid"] for c in p.get("candidates", [])] == [STRANGER, ME], str(p.get("candidates")))
p = S.plan_install(BOT, both, SHIPPED, principal=ME)
check("the chosen person is the principal", p["ok"] and p["principal"] == ME, str(p))
check("only the chosen person's chat is allowed", list(p["chats"]) == [str(ME)], str(p.get("chats")))
p = S.plan_install(BOT, both, SHIPPED, principal=123)
check("a choice nobody made by writing is refused", p["ok"] is False)

print("\nonly messages written NOW count — not the day of undelivered ones")
import time, types
now = int(time.time())
def fake_call(token, method, **kw):
    if kw.get("offset", 0) == 0:
        return {"ok": True, "result": [
            {"update_id": 1, "message": {"date": now - 3600, "chat": {"id": STRANGER, "type": "private"},
                                         "from": {"id": STRANGER, "first_name": "Stranger"}}},
            {"update_id": 2, "message": {"date": now, "chat": {"id": ME, "type": "private"},
                                         "from": {"id": ME, "first_name": "Anna", "username": "anna"}}}]}
    return {"ok": True, "result": []}
real_call, real_print = S.call, print
S.call = fake_call
import builtins
builtins.print = lambda *a, **k: None
try:
    got = S.wait_for_messages("0:test", seconds=12)
finally:
    builtins.print = real_print
    S.call = real_call
check("an hour-old message from someone else is not read", [c["chat_id"] for c in got] == [ME],
      str([c["chat_id"] for c in got]))
check("the username is kept for the question", got and got[0]["people"][ME].get("username") == "anna")

print("\n'is this you?' — Enter does NOT say yes")
import tempfile, shutil
with tempfile.TemporaryDirectory() as td:
    td = pathlib.Path(td)
    real_here, real_input = S.HERE, builtins.input
    answers = iter(["0:test", ""])                    # the token, then Enter at "is this you"
    S.HERE = td
    S.get_token = lambda: "0:test"
    S.call = lambda token, method, **kw: {"ok": True, "result": {"first_name": "Logic", "username": "x_bot"}}
    S.wait_for_messages = lambda token, seconds=120: [private()]
    builtins.input = lambda prompt="": next(answers)
    builtins.print = lambda *a, **k: None
    try:
        rc = S.main_quick()
    finally:
        builtins.print, builtins.input, S.HERE, S.call = real_print, real_input, real_here, real_call
    check("Enter at the owner question stops setup", rc == 1, str(rc))
    check("and nothing is written", not (td / "chats.json").exists() and not (td / "settings.json").exists())

print("\nthe service of ANOTHER directory is never overwritten")
here = pathlib.Path("/opt/mine")
check("no unit yet -> ours to write", S.unit_conflict(None, here) is False)
check("a unit for this very directory -> ours",
      S.unit_conflict(f"[Service]\nWorkingDirectory={here}\n", here) is False)
check("a unit for another directory -> NOT ours",
      S.unit_conflict("[Service]\nWorkingDirectory=/srv/live-bridge\n", here) is True)
home = pathlib.Path.home()
check("%h is understood as the home directory",
      S.unit_conflict("WorkingDirectory=%h/logic-bridge\n", home / "logic-bridge") is False)
check("a unit whose directory cannot be read is not ours either",
      S.unit_conflict("[Service]\nExecStart=/bin/true\n", here) is True)
u = S.unit_text(here, "/usr/bin/python3")
check("the written unit names THIS directory, nothing to fix by hand",
      f"WorkingDirectory={here}" in u and "%h" not in u)

print("\nthe doctor's verdict, read by its own words")
CLEAN = "  PASS  token.txt found\n  WARN  voice: no transcription\n\nFAILURES: 0\nSend this whole output back."
check("a clean doctor run is NOT a failure — the exact false case found live",
      S.doctor_failures(CLEAN) == [], str(S.doctor_failures(CLEAN)))
ONE = "  PASS  python ok\n  FAIL  token.txt is missing\n        -> put the token in token.txt\n\nFAILURES: 1\n"
got = S.doctor_failures(ONE)
check("a real failure is found, with its words", got == ["FAIL  token.txt is missing"], str(got))
check("a summary claiming failures that cannot be read FAILS CLOSED",
      bool(S.doctor_failures("something changed format\nFAILURES: 2\n")))
check("no summary at all (the doctor crashed) FAILS CLOSED",
      bool(S.doctor_failures("Traceback (most recent call last):\n  ...")))

print("\nCONTROL")
check("CONTROL: the word FAIL inside a WARN is not a failure",
      S.doctor_failures("  WARN  this will FAIL later\nFAILURES: 0\n") == [])
check("CONTROL: across inputs the plan never goes silent (dry_run)",
      all(S.plan_install(BOT, [private(lang=l)], SHIPPED)["settings"]["dry_run"] is False
          for l in ("ru", "en", None, "zz")))
check("CONTROL: the principal never comes from a group",
      S.plan_install(BOT, [group([OTHER]), private()], SHIPPED)["principal"] == ME)

print(f"\nSETUP-PLAN {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
