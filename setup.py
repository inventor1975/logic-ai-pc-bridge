#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""First-run setup: token, name, chats, boundaries. Writes the JSON for you.

Nothing here edits Python. Everything this asks for lands in two gitignored
files next to the code — settings.json and chats.json — so an installation is
data, not a patched source tree.

    python3 setup.py

Stop the bridge before running this: two processes polling one token conflict.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.telegram.org/bot{}/{}"


def call(token: str, method: str, **params) -> dict:
    data = urllib.parse.urlencode(
        {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
         for k, v in params.items() if v is not None}).encode()
    req = urllib.request.Request(API.format(token, method), data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}


def _has_whisper(python: str) -> bool:
    import subprocess
    try:
        r = subprocess.run([python, "-c", "import faster_whisper"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    got = input(f"{prompt}{suffix}: ").strip()
    return got or default


def yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    got = input(f"{prompt} [{d}]: ").strip().lower()
    return default if not got else got.startswith("y")


def get_token() -> str:
    f = HERE / "token.txt"
    if f.exists() and f.read_text(encoding="utf-8").strip():
        if yes("token.txt already exists. Keep it?"):
            return f.read_text(encoding="utf-8").strip()
    print("\nCreate a bot first: open @BotFather in Telegram, /newbot, pick a name.")
    print("It replies with a token that looks like 123456789:AAE....")
    token = ask("Paste the token here").strip()
    f.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass          # Windows has no POSIX modes; the file is still gitignored
    print("saved to token.txt (gitignored — it must never leave this machine)")
    return token


def discover(token: str) -> list[dict]:
    """Find chats by looking at what actually arrives.

    Asking a person to hunt for their numeric chat_id is a bad first step: it
    is the one number nobody knows and every client hides. Watching real
    messages is both easier and more honest — you allow the chats you actually
    used, not the ones you believed you used.
    """
    print("\nNow write something to your bot in Telegram.")
    print("If you want it in a group: add it to the group and write there too.")
    print("For groups, also turn OFF Group Privacy in @BotFather → /mybots →")
    print("  your bot → Bot Settings → Group Privacy, or it sees only commands.")
    print("Reactions in a group additionally require the bot to be an ADMIN.")
    input("\nPress Enter when you have written the messages... ")

    seen: dict[int, dict] = {}
    offset = 0
    for _ in range(3):
        r = call(token, "getUpdates", offset=offset, timeout=2,
                 allowed_updates=json.dumps(["message", "channel_post"]))
        for upd in r.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat = msg.get("chat") or {}
            if not chat.get("id"):
                continue
            frm = msg.get("from") or {}
            seen.setdefault(chat["id"], {
                "chat_id": chat["id"],
                "kind": chat.get("type"),
                "title": chat.get("title") or chat.get("username")
                         or chat.get("first_name") or "?",
                "people": {},
            })
            if frm.get("id"):
                seen[chat["id"]]["people"][frm["id"]] = (
                    frm.get("username") or frm.get("first_name") or "?")
        time.sleep(1)
    return list(seen.values())


def main() -> int:
    print("=" * 66)
    print("  Telegram bridge — setup")
    print("=" * 66)

    token = get_token()
    me = call(token, "getMe")
    if not me.get("ok"):
        print(f"\nThat token did not work: {me.get('description')}")
        return 1
    bot = me["result"]
    print(f"\nConnected: @{bot.get('username')} ({bot.get('first_name')})")

    name = ask("\nWhat should people call the assistant", bot.get("first_name") or "Logic")
    operator = ask("Whose assistant is it (shown in every reply)", "the operator")
    extra = ask("Other spellings of the name, comma-separated (optional)", "")
    triggers = [name.lower()] + [x.strip().lower() for x in extra.split(",") if x.strip()]
    triggers = sorted(set(triggers), key=len, reverse=True)

    chats = discover(token)
    if not chats:
        print("\nNo messages arrived, so there is nothing to allow yet.")
        print("Run setup again after writing to the bot.")
        return 1

    allowed: dict[str, dict] = {}
    for c in chats:
        print(f"\n  chat_id {c['chat_id']}  ({c['kind']})  {c['title']}")
        for uid, who in c["people"].items():
            print(f"      wrote here: {who}  id {uid}")
        if not yes("  Allow this chat?"):
            continue
        ids = list(c["people"])
        principal = ask("  Principal's user id (whose word is itself an order)",
                        str(ids[0]) if ids else "")
        topic = ask("  Subject of this chat (the assistant stays inside it)",
                    "not declared")
        # In a one-to-one chat with the bot there is nobody else to address,
        # so requiring the name would be friction with nothing behind it. In a
        # room it is required, or the assistant takes other people's
        # conversation as its own business.
        one_to_one = c["kind"] == "private"
        allowed[str(c["chat_id"])] = {
            "_": c["title"],
            "principal": int(principal),
            "approvers": [int(principal)],
            "may_address": "all",
            "all_addressed": one_to_one,
            "topic": topic,
            "language": ask("  Language of this chat", "English"),
            "outward_gate": True,
            "announce": True,
        }

    if not allowed:
        print("\nNo chats allowed — the bridge would ignore everything. Nothing written.")
        return 1

    dry = yes("\nStart in DRY_RUN (reads and logs, sends nothing)?", True)
    prefix = ask("\nHow should replies be signed",
                 f"{name} AI({operator}):")

    # VOICE. Checked here rather than discovered by the user mid-conversation.
    # This exact thing went wrong once: faster-whisper was installed in a
    # virtual environment for machine-learning work, the service ran
    # /usr/bin/python3, and "it is installed" was true of the wrong
    # interpreter. Measuring the import from a shell says nothing about the
    # daemon.
    whisper_py = sys.executable
    if not _has_whisper(whisper_py):
        print(f"\nVoice notes: faster-whisper is not available to {whisper_py}.")
        print("Transcription runs as a subprocess, so it may live in another")
        print("environment — give its python here, or press Enter to skip voice.")
        other = ask("python with faster-whisper", "")
        if other and _has_whisper(other):
            whisper_py = other
            print("  found it.")
        elif other:
            print("  not there either — voice notes will be saved but not read.")
        else:
            print("  voice notes will be saved but not read.")
    else:
        print(f"\nVoice notes: transcription available via {whisper_py}")
    (HERE / "settings.json").write_text(json.dumps({
        "bot_name": name, "operator": operator, "reply_prefix": prefix,
        "triggers": triggers, "dry_run": dry,
        "whisper_python": whisper_py, "whisper_model": "small",
        "whisper_device": "cpu",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "chats.json").write_text(
        json.dumps(allowed, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nWritten: settings.json, chats.json, token.txt")
    print(f"Replies will be signed:  {prefix}")
    print("\nRun it:      python3 tg_bridge.py")
    print("Test it:     python3 test_gate.py")
    if dry:
        print('\nDRY_RUN is on — it stays silent. Set "dry_run": false in')
        print("settings.json when you are satisfied with what it logs.")
    print("\nRead PROTOCOL.md before letting it act on anything outside a chat.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ncancelled — nothing written")
        sys.exit(1)
