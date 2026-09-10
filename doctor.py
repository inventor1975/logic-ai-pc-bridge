#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""doctor.py — why the bot is not answering. One check per link in the chain, in order.

    python3 doctor.py

Reads only. Sends no message, changes no file, installs nothing. Stop the bridge
first if it is running — two processes polling one token is itself a fault, and
this tool has to poll once to see what Telegram says.

The token is never printed. Chat ids are printed, because you need them.

Every line is PASS, WARN or FAIL followed by what to do about it. Send the whole
output back; it contains no secret.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.telegram.org/bot{}/{}"
BAD = 0


def say(state: str, what: str, do: str = "") -> None:
    global BAD
    if state == "FAIL":
        BAD += 1
    print(f"  {state:4}  {what}")
    if do:
        for line in do.strip().split("\n"):
            print(f"        -> {line}")


def call(token: str, method: str, **params) -> dict:
    data = urllib.parse.urlencode(
        {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
         for k, v in params.items() if v is not None}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(API.format(token, method), data=data), timeout=35) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:                     # 409 and 401 arrive here, and they are the answer
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error_code": e.code, "description": str(e)}
    except Exception as e:
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}


print("logic-bridge doctor — reading only, nothing is sent\n")

# ---------------------------------------------------------------- 1. the files
print("1. files")
missing = [n for n in ("config.py", "tg_bridge.py") if not (HERE / n).exists()]
if missing:
    say("FAIL", f"not the bridge directory: {', '.join(missing)} missing",
        "run this from inside the unpacked logic-bridge folder")
    sys.exit(1)
say("PASS", "bridge sources are here")

if sys.version_info < (3, 9):
    say("FAIL", f"python {sys.version.split()[0]} is too old", "use python3.9 or newer")
else:
    say("PASS", f"python {sys.version.split()[0]}")

# ---------------------------------------------------------------- 2. the token
print("\n2. token")
tok_path = HERE / "token.txt"
if not tok_path.exists():
    say("FAIL", "token.txt is missing",
        "put the BotFather token in token.txt (one line, nothing else)\n"
        "then: chmod 600 token.txt")
    sys.exit(1)
raw = tok_path.read_text(encoding="utf-8")
token = raw.strip()
if raw not in (token, token + "\n"):                       # one trailing newline is a normal text file
    say("WARN", "token.txt has stray whitespace around the token",
        "harmless here (it is stripped), but rewrite it as one clean line")
if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_\-]{30,}", token):
    say("FAIL", "token.txt does not look like a BotFather token",
        "expected <digits>:<35 or so letters/digits/-/_>\n"
        "in BotFather: /mybots -> your bot -> API Token")
    sys.exit(1)
say("PASS", f"token shape is right (bot id {token.split(':')[0]}, secret not printed)")
mode = oct(tok_path.stat().st_mode & 0o777)
say("PASS" if mode == "0o600" else "WARN", f"token.txt permissions {mode}",
    "" if mode == "0o600" else "chmod 600 token.txt")

# ------------------------------------------------------------ 3. is it running
print("\n3. another consumer of the same token")
try:
    ps = subprocess.run(["ps", "ax"], capture_output=True, text=True, timeout=20).stdout
except Exception:
    ps = ""
mine = [l for l in ps.split("\n") if "tg_bridge.py" in l and "grep" not in l]
if mine:
    say("WARN", f"{len(mine)} tg_bridge.py process(es) already running",
        "stop the bridge before trusting the answers below — two pollers on one\n"
        "token make Telegram return 409 to whichever asks second")

me = call(token, "getMe")
if not me.get("ok"):
    code = me.get("error_code")
    if code == 401:
        say("FAIL", "Telegram says the token is not valid (401)",
            "the token was revoked or mistyped: BotFather -> /mybots -> API Token -> Revoke\n"
            "then put the NEW token in token.txt")
    else:
        say("FAIL", f"getMe failed: {me.get('description')}",
            "if this is a network error, check the machine can reach api.telegram.org:\n"
            "  curl -s -o /dev/null -w '%{http_code}\\n' https://api.telegram.org")
    sys.exit(1)
bot = me["result"]
say("PASS", f"bot reachable: @{bot.get('username')} (id {bot.get('id')})")

# --------------------------------------------------------------- 4. delivery
print("\n4. how updates are delivered")
wh = call(token, "getWebhookInfo")
url = (wh.get("result") or {}).get("url") or ""
if url:
    say("FAIL", "a WEBHOOK is set, so getUpdates will never return anything",
        "this bridge polls; a webhook takes the updates instead. Clear it:\n"
        f"  curl -s 'https://api.telegram.org/bot<TOKEN>/deleteWebhook?drop_pending_updates=false'\n"
        "(run it with your real token; it is not printed here)")
else:
    say("PASS", "no webhook set — polling is the delivery path, as this bridge expects")
pending = (wh.get("result") or {}).get("pending_update_count")
if isinstance(pending, int):
    say("PASS", f"{pending} update(s) waiting to be fetched")

upd = call(token, "getUpdates", timeout=0, limit=1)
if not upd.get("ok"):
    if upd.get("error_code") == 409:
        say("FAIL", "409 Conflict — something else is polling this token right now",
            "stop the other process (the bridge, a second copy, another machine,\n"
            "or an old launchd/systemd unit) and run this again")
    else:
        say("FAIL", f"getUpdates failed: {upd.get('description')}")
else:
    n = len(upd.get("result") or [])
    say("PASS", f"getUpdates works ({n} update(s) available right now)")
    if n == 0 and not pending:
        say("WARN", "nothing is waiting — Telegram has no message for this bot",
            "that is normal if the bot has already read everything. If you just\n"
            "wrote to it and this still says 0, the cause is section 6 below.")

# --------------------------------------------------------------- 5. settings
print("\n5. settings.json and chats.json")
for name in ("settings.json", "chats.json"):
    p = HERE / name
    if not p.exists():
        say("FAIL", f"{name} is missing", f"run: python3 setup.py   (it writes {name} for you)")
        continue
    try:
        json.loads(p.read_text(encoding="utf-8"))
        say("PASS", f"{name} is valid JSON")
    except Exception as e:
        say("FAIL", f"{name} is not valid JSON: {e}", "fix it, or delete it and run: python3 setup.py")

chats = {}
try:
    chats = {k: v for k, v in json.loads((HERE / "chats.json").read_text(encoding="utf-8")).items()
             if not k.startswith("_")}
except Exception:
    pass
if not chats:
    say("FAIL", "no allowed chats are configured",
        "the bridge answers ONLY in chats listed in chats.json. Run: python3 setup.py")
else:
    say("PASS", f"{len(chats)} allowed chat(s): {', '.join(chats)}")
try:
    dry = bool(json.loads((HERE / "settings.json").read_text(encoding="utf-8")).get("dry_run", True))
    say("WARN" if dry else "PASS", f"dry_run = {dry}",
        "nothing will actually be sent to Telegram while this is true.\n"
        "Set \"dry_run\": false in settings.json when you are ready." if dry else "")
except Exception:
    pass

# --------------------------------------------------------- 6. the chats it sees
print("\n6. can the bot actually see the messages")
say("PASS" if bot.get("can_read_all_group_messages") else "WARN",
    f"group privacy mode: reading all group messages = {bool(bot.get('can_read_all_group_messages'))}",
    "" if bot.get("can_read_all_group_messages") else
    "THIS IS THE USUAL REASON A BOT LOOKS DEAD IN A GROUP.\n"
    "With privacy ON, the bot receives ONLY messages that @mention it, reply to\n"
    "one of its messages, or start with /command. Plain group talk never arrives.\n"
    "To change it: BotFather -> /mybots -> your bot -> Bot Settings -> Group\n"
    "Privacy -> Turn off. THEN REMOVE THE BOT FROM THE GROUP AND ADD IT AGAIN —\n"
    "the setting only takes effect on re-join. In a PRIVATE chat this does not\n"
    "matter: the bot always sees everything written to it.")

for cid in chats:
    r = call(token, "getChat", chat_id=cid)
    if r.get("ok"):
        c = r["result"]
        say("PASS", f"chat {cid}: {c.get('type')} {c.get('title') or c.get('username') or ''}".rstrip())
        if c.get("type") in ("group", "supergroup"):
            m = call(token, "getChatMember", chat_id=cid, user_id=bot["id"])
            st = (m.get("result") or {}).get("status")
            say("PASS" if st in ("member", "administrator") else "FAIL",
                f"chat {cid}: the bot's status there is {st!r}",
                "" if st in ("member", "administrator") else "add the bot to that group")
    else:
        d = r.get("description", "")
        say("FAIL", f"chat {cid}: {d}",
            "chat not found usually means the id is wrong or the bot was never added.\n"
            "A group id starts with -100. Get the real id by writing in the group and\n"
            "reading it from getUpdates, or run: python3 setup.py")

print()
print("FAILURES:", BAD)
print("Send this whole output back. It contains no token.")
