#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""First-run setup. By default it asks almost nothing.

    python3 setup.py              the short way: paste the token, write to your bot
    python3 setup.py --advanced   every question, as before

What a person must do by hand is only what Telegram does not let anyone
automate: create a bot with @BotFather and paste its token. Everything else is
taken from what actually arrives — who wrote, from which chat, in which
language — and the rest are defaults that can be changed later in
settings.json.

Nothing here edits Python. Everything lands in gitignored files next to the
code — settings.json and chats.json — so an installation is data, not a
patched source tree.

Stop the bridge before running this: two processes polling one token conflict.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
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


def main_advanced() -> int:
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


# ═══ THE SHORT WAY ═══════════════════════════════════════════════════════════
#
# The operator's word, 2026-09-10: "as simple as possible, so the user does the
# minimum." And on the one question that was left, "answer at once or watch
# first?": "why ask — let it answer at once." He was right for a reason beyond
# convenience: a silent first run still RECORDED the conversation while holding
# back the notice that tells people they are recorded. The real safeguard is the
# list of allowed chats, and setup builds it with the person, from the chats they
# themselves wrote in.

LOCALE_DIR = HERE / "locale"
SHIPPED = sorted(p.stem for p in LOCALE_DIR.glob("*.json")) or ["en"]
UNIT_NAME = "logic-bridge.service"


def lang_from(code, shipped) -> str:
    """The client's language when the bridge speaks it, English otherwise.

    Telegram sends language_code with every message ("ru", "de", sometimes
    "pt-br"), so asking for it is a question whose answer is already here."""
    c = str(code or "").lower().replace("_", "-").split("-")[0]
    return c if c in shipped else "en"


def plan_install(bot: dict, chats: list, shipped) -> dict:
    """What arrived -> settings and chats. No network, no input: the DECISION,
    kept apart from the talking so it can be tested.

    The principal is whoever wrote to the bot in a PRIVATE chat first. A person
    setting up their own bot writes to it; nobody else knows it exists yet.

    Groups are NEVER allowed silently. Recording a room is a decision about other
    people, so a group comes back as a question — and only a group the principal
    wrote in during setup, never one the bot merely happened to be in."""
    private = [c for c in chats if c.get("kind") == "private" and c.get("people")]
    if not private:
        return {"ok": False, "why": "no private message arrived"}
    first = private[0]
    uid, person = next(iter(first["people"].items()))
    name = bot.get("first_name") or "Logic"
    operator = person.get("name") or "the operator"
    settings = {"bot_name": name, "operator": operator,
                "triggers": [name.lower()],
                "lang": lang_from(person.get("lang"), shipped),
                "dry_run": False}
    chats_out = {str(first["chat_id"]): {
        "_": f"private chat with {operator}",
        "principal": int(uid), "approvers": [int(uid)],
        "may_address": "all", "all_addressed": True,
        "topic": "not declared", "outward_gate": True, "announce": True}}
    groups = [c for c in chats if c.get("kind") in ("group", "supergroup")
              and uid in (c.get("people") or {})]
    return {"ok": True, "settings": settings, "chats": chats_out,
            "groups": groups, "principal": int(uid)}


def group_policy(title: str, principal: int) -> dict:
    return {"_": title, "principal": principal, "approvers": [principal],
            "may_address": "all", "all_addressed": False,
            "topic": "not declared", "outward_gate": True, "announce": True}


def wait_for_messages(token: str, seconds: int = 120) -> list:
    """Wait until someone writes to the bot. No Enter to press: the arrival of a
    message IS the signal that the person has done it."""
    print("\nNow write any message to your bot in Telegram. Waiting", end="", flush=True)
    seen, offset, deadline, first_private = {}, 0, time.time() + seconds, None
    while time.time() < deadline:
        r = call(token, "getUpdates", offset=offset, timeout=5,
                 allowed_updates=json.dumps(["message", "channel_post"]))
        for upd in r.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat, frm = msg.get("chat") or {}, msg.get("from") or {}
            if not chat.get("id"):
                continue
            c = seen.setdefault(chat["id"], {
                "chat_id": chat["id"], "kind": chat.get("type"),
                "title": chat.get("title") or chat.get("username")
                         or chat.get("first_name") or "?",
                "people": {}})
            if frm.get("id") and not frm.get("is_bot"):
                c["people"].setdefault(frm["id"], {
                    "name": frm.get("first_name") or frm.get("username") or "?",
                    "lang": frm.get("language_code")})
            if chat.get("type") == "private" and first_private is None:
                first_private = time.time()
        print(".", end="", flush=True)
        # A few seconds more after the first private message, so a group written
        # to at the same moment is caught as well.
        if first_private and time.time() - first_private > 6:
            break
    print()
    return list(seen.values())


def unit_text(here: Path, python: str) -> str:
    """The service unit with THIS directory in it — nothing for a person to fix."""
    return (
        "[Unit]\nDescription=Telegram bridge for an AI assistant\n"
        "After=network-online.target\nWants=network-online.target\n\n"
        "[Service]\nType=simple\n"
        f"WorkingDirectory={here}\n"
        f"ExecStart={python} -u {here / 'tg_bridge.py'}\n"
        "Restart=always\nRestartSec=5\n"
        f"StandardOutput=append:{here / 'bridge.out'}\n"
        f"StandardError=append:{here / 'bridge.out'}\n\n"
        "[Install]\nWantedBy=default.target\n")


def unit_conflict(existing, here: Path) -> bool:
    """True when a unit of the same name already serves ANOTHER directory.

    Overwriting it would silently move someone's running bridge. On the machine
    this was written on, a second setup in a scratch directory would have
    replaced the unit of a live installation — found before it happened, while
    designing this function, 2026-09-10. A unit whose directory cannot be read
    is not ours to overwrite either."""
    if not existing:
        return False
    for line in existing.splitlines():
        line = line.strip()
        if line.startswith("WorkingDirectory="):
            d = line.split("=", 1)[1].strip().replace("%h", str(Path.home()))
            return Path(d).expanduser().resolve() != here.resolve()
    return True


def install_service(here: Path) -> str:
    if platform.system() != "Linux" or not shutil.which("systemctl"):
        return "manual"
    unit = Path.home() / ".config" / "systemd" / "user" / UNIT_NAME
    if unit_conflict(unit.read_text(encoding="utf-8") if unit.exists() else None, here):
        return "conflict"                    # checked BEFORE asking: nothing to decide
    if not yes("\nStart the bridge now and at every boot?", True):
        return "declined"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(unit_text(here, sys.executable), encoding="utf-8")
    for cmd in (["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", UNIT_NAME],
                # Without linger a user service stops at logout, and an evening
                # reminder never arrives. Not optional, so not a question.
                ["loginctl", "enable-linger", os.environ.get("USER", "")]):
        subprocess.run(cmd, capture_output=True)
    r = subprocess.run(["systemctl", "--user", "is-active", UNIT_NAME],
                       capture_output=True, text=True)
    return "running" if r.stdout.strip() == "active" else "failed"


def run_doctor(here: Path):
    """The same checks a person would run after a failure — run BEFORE the service
    starts, because the doctor itself polls once and would collide with it."""
    try:
        r = subprocess.run([sys.executable, str(here / "doctor.py")], cwd=here,
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return [f"FAIL doctor did not run: {e}"], ""
    return doctor_failures(r.stdout), r.stdout


_FAIL_LINE = __import__("re").compile(r"^\s*FAIL\s{2}\S")
_SUMMARY = __import__("re").compile(r"^FAILURES:\s*(\d+)\s*$", __import__("re").M)


def doctor_failures(out: str) -> list:
    """The doctor's real failures, read by its OWN words.

    The first version took every line starting with "FAIL" — and the doctor's
    closing line "FAILURES: 0" starts with FAIL too. A clean run was read as a
    failure and setup said "NOT READY — FAILURES: 0". Caught 2026-09-10 on the
    test bot: the very kind of word-match that cannot tell a use from a mention.

    Now the doctor's own summary is the signal, and a failure line is its state
    column exactly: "FAIL", two spaces, the finding. It FAILS CLOSED: if the
    summary is missing (the doctor crashed) or claims failures that cannot be
    read, that is reported as a failure, never as a pass."""
    m = _SUMMARY.search(out or "")
    lines = [l.strip() for l in (out or "").splitlines() if _FAIL_LINE.match(l)]
    if m is None:
        return lines or ["FAIL doctor gave no summary — it may have crashed; run: python3 doctor.py"]
    n = int(m.group(1))
    if n == 0:
        return []
    return lines or [f"FAIL doctor reports {n} failure(s) that could not be read; run: python3 doctor.py"]


def _merge(path: Path, new: dict) -> dict:
    old = {}
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
    old.update(new)
    return old


def main_quick() -> int:
    print("=" * 66)
    print("  Telegram bridge — setup")
    print("=" * 66)
    token = get_token()
    me = call(token, "getMe")
    if not me.get("ok"):
        print(f"\nThat token did not work: {me.get('description')}")
        return 1
    bot = me["result"]
    print(f"Connected: @{bot.get('username')}")

    plan = plan_install(bot, wait_for_messages(token), SHIPPED)
    if not plan["ok"]:
        print("\nNo message reached the bot in two minutes.")
        print("Write to it in Telegram — any word — and run setup again.")
        return 1
    for g in plan["groups"]:
        if yes(f"\nAlso work in the group «{g['title']}»? It records that room "
               f"and tells everyone there so", False):
            plan["chats"][str(g["chat_id"])] = group_policy(g["title"], plan["principal"])
            print("  In a group: @BotFather → /mybots → Bot Settings → Group Privacy: OFF,")
            print("  then REMOVE the bot from the group and ADD it again, or it stays deaf.")
    settings = plan["settings"]
    if _has_whisper(sys.executable):
        settings["whisper_python"] = sys.executable
    (HERE / "settings.json").write_text(json.dumps(_merge(HERE / "settings.json", settings),
                                                    ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "chats.json").write_text(json.dumps(_merge(HERE / "chats.json", plan["chats"]),
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
    fails, report = run_doctor(HERE)
    service = "skipped" if fails else install_service(HERE)

    print()
    if fails:
        print("NOT READY — " + fails[0])
        print("Full report: python3 doctor.py")
        return 1
    who = f"{settings['bot_name']} (language: {settings['lang']})"
    if service == "running":
        print(f"READY. {who} is running. Write to it.")
    elif service == "conflict":
        print(f"READY. {who} is set up, but a bridge service already runs from "
              f"another directory and was NOT touched.")
        print("Start this one by hand:  python3 tg_bridge.py")
    elif service == "failed":
        print(f"SET UP, but the service did not start. See: systemctl --user status {UNIT_NAME}")
        return 1
    else:
        print(f"READY. {who} is set up. Start it:  python3 tg_bridge.py")
    return 0


def main() -> int:
    return main_advanced() if "--advanced" in sys.argv else main_quick()

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ncancelled — nothing written")
        sys.exit(1)
