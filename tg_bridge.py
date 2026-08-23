# -*- coding: utf-8 -*-
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Telegram <-> assistant bridge. Standard library only, no dependencies.

The separation this whole design exists for: **this process holds the token,
and the assistant never sees it.** The bridge writes the conversation to a log
and drops requests as files; the assistant reads files and puts its reply in
outbox/; the bridge sends it. If the assistant gets something wrong, it gets it
wrong in a file rather than in someone else's chat.

Flow:
  1. a message arrives from an allowed chat        -> written to the log
  2. it starts with the assistant's name           -> 👀 reaction, file in requests/
  3. the assistant writes outbox/<id>.json         -> bridge sends "Name: - ..."
                                                      and moves it to sent/

Run:
    python3 tg_bridge.py --whoami    print the chat_id of anyone who writes, exit
    python3 tg_bridge.py             run

Stop: Ctrl+C.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import config as C

API = "https://api.telegram.org/bot{}/{}"
# ONE RULE: the name stands AT THE START of the message and nowhere else.
#
# Earlier versions matched the name anywhere, and every one of these was a
# false positive, measured against real messages:
#
#   "Logically speaking..."   matched with no boundary at all;
#   "Logic-free zone"         matched until the hyphen was excluded;
#   "Aristotle's logic is..." would match a bare word anywhere in the text.
#
# A message ABOUT the assistant is not a message TO it. "We should ask Logic"
# is talk about it. Everyone addresses it by starting with its name, so one
# rule replaces two levels of guessing.
#
# No separator after the name is required, and that is deliberate. This script
# does not decide whether a message is meant for the assistant — it notices
# that the message begins with its name and passes it on. A false positive is
# then discarded silently by the assistant, which costs one wasted wake-up;
# a false negative loses a real question, which costs the user's trust.
#
# TRIGGERS are matched LONGEST FIRST: alternation takes the first match, and
# without ordering a longer name is shadowed by a shorter one that is its
# prefix, leaving the leftover letters inside the question text.
#
# The name must END where it ends: a negative lookahead rejects a following
# word character or hyphen. Without it "Logically speaking" and "Logic-free
# zone" both matched — measured, not imagined — and each cost a wasted wake-up
# and a 👀 on a message that was not an address. What the lookahead cannot fix
# is a trigger that is itself an ordinary word: if "logic" is a trigger, then
# "logic is a branch of philosophy" is an address as far as this regex can
# tell. That one is discarded by the assistant, silently.
_ADDRESS_RE = re.compile(
    r"^\s*(?:" + "|".join(re.escape(t) for t in sorted(C.TRIGGERS, key=len, reverse=True))
    + r")(?![\w-])",
    re.IGNORECASE | re.UNICODE,
)


def call(method: str, _timeout: float = 20.0, _retry: bool = False,
         **params: Any) -> dict[str, Any]:
    """One Bot API call. Returns the error instead of killing the bridge.

    THE TIMEOUT DIFFERS PER CALL, and that is not a detail. It used to be a
    single value sized for the long poll — 65 seconds. So the sending thread,
    on hitting one stalled request, froze for a minute, and the reply sat in
    the queue although both the function and the thread were healthy. That
    diagnoses badly: from outside it looks like "the thread is dead".

    The timeout is PER BLOCKING OPERATION, not a bound on the whole call —
    measured, not assumed: a request with _timeout=20 was observed taking 40
    seconds, twenty to connect and twenty to read. Do not read this argument
    as a guarantee of when the call returns.
    """
    if not C.TOKEN:
        raise SystemExit("no token: create token.txt or set BRIDGE_BOT_TOKEN")
    data = urllib.parse.urlencode(
        {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
         for k, v in params.items() if v is not None}
    ).encode()
    req = urllib.request.Request(API.format(C.TOKEN, method), data=data)
    try:
        with urllib.request.urlopen(req, timeout=_timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"ok": False, "error_code": e.code, "description": body}

        # RATE LIMITS ARE OBEYED, NOT FOUGHT. Telegram answers 429 with the
        # number of seconds to wait. The earlier code treated that as an
        # ordinary failure and left the file in the outbox, so the next pass —
        # one second later — sent it again. That turns one refusal into a
        # storm, and a storm into a longer ban. Waiting the stated time and
        # trying once more is both cheaper and the only behaviour that ends.
        wait = (parsed.get("parameters") or {}).get("retry_after")
        if e.code == 429 and wait and not _retry:
            print(f"[{now()}] rate limited on {method}, waiting {wait}s as told")
            time.sleep(float(wait) + 1)
            return call(method, _timeout, _retry=True, **params)
        return parsed
    except Exception as e:                      # a network blink is no reason to die
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_line(rec: dict[str, Any]) -> None:
    # ONE LOCK ON THE LOG (_LOG_LOCK, declared next to _WHISPER_LOCK). log_line
    # is called from the main loop AND the voice/file worker threads. O_APPEND
    # makes each write() syscall atomic, but one long line (a big context or a
    # transcript) splits into several write()s and can interleave with another
    # thread's line — a corrupt JSONL line that readers silently skip.
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with _LOG_LOCK:
        with C.LOG.open("a", encoding="utf-8") as f:
            f.write(line)


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + os.replace, so a reader sees either the old file
    whole or the new file whole, but NEVER a half-written one.

    grants.json/rules.json are written from the pump and read from the pump too
    (rule_for/grant_for in flush_outbox) and from the main thread. A plain
    write_text is truncate then write; a reader landing mid-write got broken
    JSON. os.replace is atomic on one filesystem.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def announce(chat_id: int) -> None:
    """Notice that this chat is logged — once per chat, BEFORE anything from it
    lands on disk.

    THE KEY IS NOT THE ROOM, IT IS THE ROOM PLUS A FINGERPRINT OF THE TEXT. The
    first version remembered only the chat id, so a changed notice would never
    reach those already told: the program collects more, but people know it by
    the old wording. A fingerprint in the key means that widening the collection
    raises a fresh notice by itself.
    """
    text = C.announce_text(chat_id)
    key = f"{chat_id}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    done: set[str] = set()
    if C.ANNOUNCED.exists():
        done = {x.strip() for x in C.ANNOUNCED.read_text().split() if x.strip()}
    if key in done or C.DRY_RUN:
        return
    if call("sendMessage", chat_id=chat_id, text=text).get("ok"):
        with C.ANNOUNCED.open("a") as f:
            f.write(f"{key}\n")
        print(f"[{now()}] privacy notice -> {chat_id} ({key.split(':')[1]})")


def tail(chat_id: int, n: int) -> list[dict[str, Any]]:
    """The last n messages of this chat, so the assistant answers in context.

    A bare mention is undecidable on its own: "shall we ask Logic?" may be an
    address or talk about it. The preceding lines usually settle the question.
    """
    if not C.LOG.exists():
        return []
    # READ THE TAIL, NOT THE FILE. read_text() pulls the whole log into memory
    # on every single message. At 50 KB nobody notices; the log only grows,
    # and the day it is 500 MB the bridge stalls on every reply for a reason
    # nobody will connect to this line. Seeking from the end costs the same
    # today and keeps costing the same later.
    try:
        with C.LOG.open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 262_144))       # 256 KB is far more
            chunk = fh.read().decode("utf-8", "replace")   # than 400 lines
    except Exception:
        return []
    out = []
    for line in chunk.splitlines()[-400:]:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("chat_id") == chat_id:
            out.append({"from": r.get("from"), "text": r.get("text")})
    return out[-n:]


def ack(chat_id: int, message_id: int, emoji: str | None = None) -> str:
    """"Recognised." A reaction; if that fails, the same icon as a message.

    Reactions arrived late in the Bot API and an older server may not have the
    method. Swallowing that silently is not an option: this mark is the only
    sign a human gets that the message was noticed at all. So the failure is
    caught and replaced by the same icon sent as an ordinary reply.
    """
    if C.DRY_RUN:
        return "dry-run"
    emoji = emoji or C.ACK_EMOJI
    # A reaction only exists for emojis Telegram accepts. Sending an invalid
    # one used to fall through to a shouted message; now it fails loud and
    # stays quiet, because twenty stray "✅" messages are worse than a log line.
    if emoji not in C.VALID_REACTIONS:
        print(f"[{now()}] REACTION_INVALID: {emoji!r} is not a Telegram "
              f"reaction; refusing (would have shouted it as a message). "
              f"Pick from C.VALID_REACTIONS — 👍 is the safe done-mark.")
        return "invalid-emoji"
    t0 = time.monotonic()
    r = call("setMessageReaction", chat_id=chat_id, message_id=message_id,
             reaction=[{"type": "emoji", "emoji": emoji}])
    spent = time.monotonic() - t0
    if spent > 1.5:
        # Same reason as the send timer: "the icon is slow" must resolve into a
        # number, or it resolves into a theory.
        print(f"[{now()}] SLOW MARK: {spent:.1f}s for {emoji}")
    if r.get("ok"):
        return "reaction"

    # TRY THE REACTION ONCE MORE BEFORE GIVING UP ON IT. The one observed
    # failure was a stalled request, not a refusal — and the fallback is
    # visibly worse: a message containing nothing but an emoji is rendered
    # large by Telegram, so the reader sees a shout where a quiet mark was
    # meant. Cheap to retry, and it keeps the loud path for real outages.
    r = call("setMessageReaction", _timeout=10.0, chat_id=chat_id,
             message_id=message_id,
             reaction=[{"type": "emoji", "emoji": emoji}])
    if r.get("ok"):
        return "reaction (second try)"

    # Still no. Send it as a message rather than stay silent — a mark that
    # never appears is indistinguishable from a message that never arrived.
    r2 = call("sendMessage", chat_id=chat_id, text=emoji,
              reply_to_message_id=message_id)
    return "message" if r2.get("ok") else f"FAILED: {r.get('description')}"


# The bot's own numeric id, learned at startup. Needed to recognise a reply to
# one of its own messages: replying IS addressing, and demanding the name on
# top of it would be pedantry the sender will not forgive twice.
_ME = [0]

# Unknown chats already reported, so one stray group does not fill the log.
_SEEN_UNKNOWN: set[int] = set()


_WHISPER_LOCK = threading.Lock()
_WHISPER = [None]
# Serialises appends to the chat log from the main loop and worker threads.
_LOG_LOCK = threading.Lock()
# ONE LOCK ON THE STATE JOURNALS. grants.json and rules.json are read-modify-
# written from TWO threads: the main loop (_close via decide) and the pump
# (spend_grant, and sweep_proposals->_close). Without a shared lock two threads
# read one list, each appends its own change and writes over the other — a lost
# update. Worst case: spend_grant sets used_at and _close overwrites the list
# without it, so one-time consent RESURRECTS. RLock: _close nests under it.
_STATE_LOCK = threading.RLock()


def rule_for(chat_id: int, path: Path,
             rules: list | None = None) -> dict[str, Any] | None:
    """Which standing rule covers sending THIS file to THIS room.

    By default it covers nothing: an empty journal means "ask about everything".
    A permission is only ADDED by an explicit record and is never inferred.

    TWO LEVELS OF SUBJECT, by the curator's word ("we named specific ones, and
    only then is it allowed, all by full path; and folders the same way"):

        paths  exact full paths — THIS file and no other is allowed
        dirs   a whole folder, with a name pattern inside it

    An exact path is stricter and therefore comes first: where specific files
    are listed, a new file in the same folder is NOT allowed until it is named.

    ROOMS ARE ENUMERATED. A rule may name several, but cannot say "any": there
    is no such field. A room nobody thought of will never fall into a rule — not
    by vigilance, but by the shape of the format.

    `project` is a LABEL for a human reading the journal. It is NEVER checked: a
    label can slip, a path cannot. Checking by the label would mean it is enough
    to call someone else's folder by the right word.
    """
    rules = C.file_rules() if rules is None else rules
    try:
        real = path.resolve()
    except OSError:
        return None
    nowts = datetime.now(timezone.utc)
    approver_ids = C.all_approvers()
    for r in rules:
        rooms = r.get("chats") or ([r["chat_id"]] if r.get("chat_id") else [])
        if chat_id not in rooms:
            continue
        # A rule must carry the id of a REAL approver, not just a nonempty field.
        # The principal places a mark, the bridge writes their id; a record with
        # an arbitrary nonzero id (a corrupted file, a hand-edit) used to pass —
        # now the id must be an approver of at least one chat.
        if r.get("added_by_user_id") not in approver_ids:
            print(f"[{now()}] RULE NOT FROM AN APPROVER, skipped: {r.get('id')} "
                  f"(added_by={r.get('added_by_user_id')})")
            continue
        exp = r.get("expires_at")
        if exp:
            try:
                dt = datetime.fromisoformat(exp)
                # A NAIVE DATE MUST NOT CRASH THE WHOLE SEND LOOP. A tz-less
                # expiry (`--until 2026-12-01T00:00:00`) compared with aware
                # nowts raises TypeError — not ValueError, which was the only
                # one caught — and the exception left flush_outbox, aborting
                # EVERY send each pass. Normalise to UTC.
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt <= nowts:
                    continue
            except (ValueError, TypeError):
                continue        # unreadable expiry — NOT in favour of sending

        for pth in (r.get("paths") or []):
            try:
                if Path(pth).expanduser().resolve() == real:
                    return r
            except OSError:
                continue

        dirs = r.get("dirs")
        if dirs is None and r.get("dir"):      # v1.4 form, still supported
            dirs = [{"dir": r["dir"], "glob": r.get("glob")}]
        for d in (dirs or []):
            base_s = d.get("dir") if isinstance(d, dict) else d
            if not base_s:
                continue
            try:
                base = Path(base_s).expanduser().resolve()
            except OSError:
                continue
            if not real.is_relative_to(base):
                continue
            glob = (d.get("glob") if isinstance(d, dict) else None) or "*"
            if fnmatch.fnmatch(real.name, glob):
                return r
    return None


def grant_for(chat_id: int, path: Path) -> dict[str, Any] | None:
    """A one-time permission for THIS file in THIS room, not yet spent.

    Bound by FINGERPRINT, not by name: what was approved is what the human saw
    in the proposal. Swap the contents after the mark and the fingerprint no
    longer matches, so the permission does not fire. The name is here for
    reading, the fingerprint for acting.
    """
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    approver_ids = C.all_approvers()
    for g in C.grants():
        if g.get("used_at"):
            continue
        # Like a rule: the id must be a REAL approver, not merely nonempty.
        if g.get("added_by_user_id") not in approver_ids:
            print(f"[{now()}] PERMISSION NOT FROM AN APPROVER, skipped: {g.get('id')} "
                  f"(added_by={g.get('added_by_user_id')})")
            continue
        if g.get("chat_id") == chat_id and g.get("sha256") == digest:
            return g
    return None


def spend_grant(gid: str) -> None:
    """Spend a permission. One-time means one-time.

    Under _STATE_LOCK and atomic: otherwise a concurrent _close (main thread)
    appending a new grant would overwrite this used_at, and one-time consent
    would resurrect — the file could be sent again without a fresh yes.
    """
    with _STATE_LOCK:
        gs = C.grants()
        for g in gs:
            if g.get("id") == gid and not g.get("used_at"):
                g["used_at"] = now()
                _atomic_write(C.GRANTS, json.dumps(gs, ensure_ascii=False, indent=1))
                return


def send_file(chat_id: int, path: Path, caption: str = "",
              as_photo: bool = False) -> dict[str, Any]:
    """Send a file to a chat. Our own multipart assembly, no third-party libraries.

    WHY A SEPARATE FUNCTION AND NOT A PARAMETER TO `call`. An ordinary call
    encodes the fields as urlencoded; a file cannot be sent that way. This is
    not "one more method", it is a different way of talking to the same API, and
    mixing them into one function means hiding a difference that will bite
    someone later.

    The caption is trimmed to 1024 characters — as much as the Bot API allows.
    We trim it IN ADVANCE and say so, or the server refuses the whole thing and
    the file never leaves over one extra line of text.
    """
    if not path.exists():
        return {"ok": False, "description": f"no such file: {path}"}
    method = "sendPhoto" if as_photo else "sendDocument"
    field = "photo" if as_photo else "document"
    if len(caption) > 1024:
        print(f"[{now()}] caption {len(caption)} > 1024, trimmed")
        caption = caption[:1021] + "..."

    boundary = "----LogicBridge" + hashlib.sha256(
        f"{chat_id}{path.name}{path.stat().st_size}".encode()).hexdigest()[:16]
    parts: list[bytes] = []

    def field_part(name: str, value: str) -> None:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(value.encode() + b"\r\n")

    field_part("chat_id", str(chat_id))
    if caption:
        field_part("caption", caption)
    # THE FILE NAME GOES INTO A HEADER, SO IT MUST BE SANITISED. A quote or a
    # newline in the name is not cosmetic: the header closes early, and anything
    # can be appended past it. The file name comes from an allowed folder, but
    # whoever drops files there is the one who chooses their names.
    safe = path.name.replace('"', "'").replace("\r", " ").replace("\n", " ")
    parts.append(f"--{boundary}\r\n".encode())
    parts.append((f'Content-Disposition: form-data; name="{field}"; '
                  f'filename="{safe}"\r\n'
                  f'Content-Type: application/octet-stream\r\n\r\n').encode())
    parts.append(path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{C.TOKEN}/{method}", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}


def fetch_file(file_id: str, dest: Path, max_bytes: int | None = None) -> bool:
    """Download a file the bot was sent. Separate from call(): the file API
    lives on a different host and returns bytes, not JSON.

    THE CAP IS CHECKED HERE, NOT ONLY AT THE CALLER. The first version looked
    at `file_size` from the update and read the whole response with a single
    `read()`. Two holes in one line: the `file_size` field may be ABSENT from
    the update altogether — then the check silently did nothing — and an
    unbounded `read()` reads as much as it is given. The promise of "twenty
    megabytes" rested on the sender's honesty.

    Now: we ask the API itself for the size, read IN CHUNKS and break off on
    overrun, and delete a partial download — half a file is worse than nothing,
    because it looks like a file.
    """
    cap = C.MEDIA_MAX_BYTES if max_bytes is None else max_bytes
    r = call("getFile", file_id=file_id)
    res = r.get("result") or {}
    path = res.get("file_path")
    if not path:
        print(f"[{now()}] getFile failed: {r.get('description')}")
        return False
    told = res.get("file_size")
    if told and told > cap:
        print(f"[{now()}] refused by size: the API says {told} > {cap}")
        return False
    url = f"https://api.telegram.org/file/bot{C.TOKEN}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, \
                dest.open("wb") as out:
            got = 0
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                if got > cap:
                    out.close()
                    dest.unlink(missing_ok=True)
                    print(f"[{now()}] BROKEN OFF: the stream exceeded {cap} bytes "
                          f"(the API promised {told}) — partial download deleted")
                    return False
                out.write(chunk)
        return True
    except Exception as e:
        dest.unlink(missing_ok=True)
        print(f"[{now()}] download failed: {type(e).__name__}: {e}")
        return False


_WHISPER_SCRIPT = """
import json, sys
try:
    from faster_whisper import WhisperModel
except Exception as e:
    print(json.dumps({"error": "faster-whisper not importable: %s" % e})); raise SystemExit(0)
path, model, device, lang = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
m = WhisperModel(model, device=device, compute_type="int8")
seg, _ = m.transcribe(path, language=(lang or None), vad_filter=True)
print(json.dumps({"text": " ".join(s.text.strip() for s in seg).strip()}))
"""


def transcribe(path: Path) -> str | None:
    """Voice note -> text, or None if this install cannot do it.

    Runs under C.WHISPER_PYTHON as a subprocess, behind a lock so two notes
    arriving together do not load the model twice and fight for the cores.

    Returning None is a real answer, not a failure to handle — the caller
    tells the sender their audio was kept but not read, which is better than
    silence and better than a guess at what they said.
    """
    with _WHISPER_LOCK:
        t0 = time.monotonic()
        try:
            r = subprocess.run(
                [C.WHISPER_PYTHON, "-c", _WHISPER_SCRIPT, str(path),
                 C.WHISPER_MODEL, C.WHISPER_DEVICE, C.VOICE_LANG or ""],
                capture_output=True, text=True, timeout=600)
        except Exception as e:
            print(f"[{now()}] transcriber failed to start: {type(e).__name__}: {e}")
            return None
    out = (r.stdout or "").strip().splitlines()
    try:
        got = json.loads(out[-1]) if out else {}
    except Exception:
        got = {}
    if "error" in got or "text" not in got:
        print(f"[{now()}] no transcription: {got.get('error') or (r.stderr or '')[:200]}")
        return None
    print(f"[{now()}] transcribed {path.name} in {time.monotonic() - t0:.1f}s: "
          f"{got['text'][:60]!r}")
    return got["text"]


def whisper_ready() -> str:
    """Checked AT STARTUP, not at the first voice note.

    A capability discovered to be missing by the user, mid-conversation, is a
    capability that was never really checked. Printing it here costs a second
    and turns a silent gap into a line in the log.
    """
    try:
        r = subprocess.run([C.WHISPER_PYTHON, "-c",
                            "import faster_whisper, sys; sys.stdout.write('ok')"],
                           capture_output=True, text=True, timeout=60)
        return "ok" if r.stdout.strip() == "ok" else (r.stderr or "").strip().splitlines()[-1][:120]
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def _guarded(fn, *args) -> None:
    """Run a worker-thread body so a crash SHOUTS instead of dying in silence.

    voice_job/file_job run in daemon threads off the polling loop. A daemon
    thread that raises just disappears — the message it was carrying is lost
    with no trace, and the sender is left on 🤔 forever. This wrapper catches
    everything and prints a full traceback, so a silent loss becomes a loud one.
    """
    try:
        fn(*args)
    except Exception:
        print(f"[{now()}] JOB CRASHED ({fn.__name__}):\n{traceback.format_exc()}")


def voice_job(chat_id: int, msg: dict[str, Any], rec: dict[str, Any],
              media: dict[str, Any]) -> None:
    """Runs off the polling loop: downloading and transcribing take seconds.

    Two marks, both true when placed. 🤔 means "heard you, working on it";
    👀 means "stored, and it will be answered". Collapsing them into one would
    force a choice between a slow acknowledgement and a lying one.
    """
    C.VOICE.mkdir(exist_ok=True)
    # HOW MUCH OF THE WAIT IS OURS. msg["date"] is stamped by Telegram when it
    # accepted the message; the gap to now covers the sender's upload and the
    # queue, none of which is ours to fix. Printing both halves stops "the
    # first icon is slow" from being answered by guesswork.
    lag = time.time() - (msg.get("date") or time.time())
    t0 = time.monotonic()
    ack(chat_id, msg["message_id"], C.HEARD_EMOJI)
    print(f"[{now()}] voice: {lag:.1f}s before us (upload+queue), "
          f"{time.monotonic() - t0:.1f}s to place {C.HEARD_EMOJI}")
    dest = C.VOICE / f"{msg['message_id']}-{chat_id}.ogg"
    if not fetch_file(media["file_id"], dest):
        # NOT SILENTLY. A failed download used to be a bare return: no log
        # line, no word to the sender — they saw 🤔 and then forever silence.
        # That is exactly the "stored-but-not" class. Say the same thing as a
        # failed transcription: the audio did not arrive, please send it again.
        rec["text"] = ""
        rec["voice_download_failed"] = True
        log_line(rec)
        C.OUTBOX.joinpath(f"novoice-{msg['message_id']}-{chat_id}.json").write_text(
            json.dumps({"chat_id": chat_id, "reply_to": msg["message_id"],
                        "text": "I received your voice message but could not "
                                "download it (a network glitch or the file was "
                                "unavailable). Please send it again."},
                       ensure_ascii=False), encoding="utf-8")
        print(f"[{now()}] voice: download FAILED {msg['message_id']}/{chat_id} "
              f"— sender told, no request created")
        return
    text = transcribe(dest)
    rec["voice"] = str(dest)
    rec["voice_seconds"] = media.get("duration")
    if text is None:
        rec["text"] = ""
        log_line(rec)
        C.OUTBOX.joinpath(f"novoice-{msg['message_id']}-{chat_id}.json").write_text(
            json.dumps({"chat_id": chat_id, "reply_to": msg["message_id"],
                        "text": "I received your voice message and kept the audio, "
                                "but this install has no transcription "
                                "(faster-whisper is not available), so I cannot "
                                "read it. Please send it as text."},
                       ensure_ascii=False), encoding="utf-8")
        return
    rec["text"] = text
    if not text:
        # Silence, noise, or a failed detection. Queueing an empty request
        # would wake the assistant with nothing to answer, and the sender
        # would get a puzzled reply instead of "say it again".
        log_line(rec)
        C.OUTBOX.joinpath(f"noword-{msg['message_id']}-{chat_id}.json").write_text(
            json.dumps({"chat_id": chat_id, "reply_to": msg["message_id"],
                        "text": "I could not make out any words in that one — "
                                "silence or noise. Say it again, or send text."},
                       ensure_ascii=False), encoding="utf-8")
        return
    accept(chat_id, msg, rec, text, msg.get("from", {}) or {}, voice=True)


def replying_to_me(msg: dict[str, Any]) -> bool:
    """Is this a reply to one of the assistant's own messages?

    Telegram's reply is a pointer at a specific message; using it on one of the
    assistant's own messages says "I am talking to you" more exactly than any
    name at the front of a sentence. Requiring the name as well would be
    pedantry, and the sender would stop bothering.
    """
    replied = msg.get("reply_to_message") or {}
    return bool(_ME[0]) and (replied.get("from") or {}).get("id") == _ME[0]


_EYE_CACHE: dict = {}                          # {chat_id: (ts, [message_id, ...])}


def open_eye_backlog(chat_id: int) -> list:
    """message_ids in this chat that wear 👀 (a request exists) and were NOT
    closed by `answers` — the full open set.

    The curator navigates by these eyes (👀 = not processed), so the whole
    backlog rides on every request to the assistant. It catches eyes that aged
    out of requests/ into served/ and so dropped out of sight — over a long
    session more than a hundred piled up that way, each a "not done" the
    principal reads by, none of them answered. Computed from FILES (not a state
    file that could drift), cached 10s so it is not recomputed on every message:
    `closed` from sent/+outbox/ (the assistant's replies carrying `answers`),
    `got` from requests/+served/ (the requests that received 👀).
    """
    cached = _EYE_CACHE.get(chat_id)
    if cached and time.time() - cached[0] < 10:
        return cached[1]
    got, closed = set(), set()
    name_re = re.compile(rf"^(\d+)-{chat_id}\.json$")
    for base in (C.REQUESTS, C.SERVED):
        for f in base.glob(f"*-{chat_id}.json"):
            m = name_re.match(f.name)
            if m:
                got.add(int(m.group(1)))
    ans_re = re.compile(rf"^(\d+)-{chat_id}$")
    for base in (C.SENT, C.OUTBOX):
        for f in base.glob("*.json"):
            try:
                item = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for a in (item.get("answers") or []):
                mm = ans_re.match(str(a))
                if mm:
                    closed.add(int(mm.group(1)))
    ids = sorted(got - closed)
    _EYE_CACHE[chat_id] = (time.time(), ids)
    return ids


def accept(chat_id: int, msg: dict[str, Any], rec: dict[str, Any], text: str,
           frm: dict[str, Any], voice: bool = False) -> None:
    """Decide whether this is an address, and if so queue it."""
    pol = C.policy(chat_id)
    private_to_principal = chat_id == pol["principal"]

    m = _ADDRESS_RE.match(text)
    if pol.get("all_addressed"):
        ask = text.strip()                # a room of two: everything is for me
    elif replying_to_me(msg):
        ask = text.strip()                # a reply to me IS addressed to me
        rec["by_reply"] = True
    elif voice and C.VOICE_IS_ADDRESS_IN_PRIVATE and private_to_principal:
        ask = text.strip()                # dictating at the bridge IS the address
    elif m:
        ask = re.sub(r"^\s*[:,.;!?\-–—]+\s*", "", text[m.end():]).strip()
    else:
        log_line(rec)
        return

    if pol["may_address"] != "all" and frm.get("id") not in pol["may_address"]:
        log_line(rec)
        print(f"[{now()}] addressed by {frm.get('id')} — not in this chat's circle")
        return

    rec["ask"] = ask
    log_line(rec)

    rid = f"{msg['message_id']}-{chat_id}"
    # THE ASSISTANT MUST SEE WHO IS ASKING. The principal's word is itself an
    # order; a guest's request is data, and acting on it needs a mark. Without
    # this field the assistant would tell them apart by name — and people
    # choose their own display names.
    # `is not None` FIRST, or a chat with no principal set (default None) makes
    # a senderless message (channel_post, anonymous group admin → frm.get("id")
    # is None) read as None == None → True, and its words would be trusted as
    # the principal's. Absence of a sender is never the principal.
    rec["from_principal"] = frm.get("id") is not None and frm.get("id") == pol["principal"]
    rec["outward_gate"] = pol["outward_gate"]
    # THE CHAT'S SUBJECT GOES INTO EVERY REQUEST rather than being recalled.
    # A machine cannot check the boundary of a topic — that is about meaning.
    # What it can do is make sure the assistant never answers without the
    # subject in front of it. That is all mechanism achieves here, and it
    # beats memory.
    rec["topic"] = pol["topic"]
    # The room's language travels with the request, so the assistant answers in
    # it without being reminded. Same reason as the topic: a rule that lives
    # only in the assistant's memory is a rule that will lapse.
    rec["language"] = pol.get("language")
    rec["context"] = tail(chat_id, 6)         # so it does not decide blind
    (C.REQUESTS / f"{rid}.json").write_text(
        json.dumps({**rec, "request_id": rid, "open_eyes": open_eye_backlog(chat_id)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    # A CONTROL QUESTION IS ITS OWN PING, not a field on someone else's request.
    # Buried in a field the assistant reads only sometimes, the check does not
    # fire; as a separate request file the watcher announces it like any other
    # "you are called", so it cannot be missed. Written AFTER the real request
    # so a self-check never delays a human's message.
    if rec.get("from_principal"):
        cq = control_question()
        if cq:
            cid = f"control-{msg['message_id']}-{chat_id}"
            (C.REQUESTS / f"{cid}.json").write_text(
                json.dumps({"request_id": cid, "chat_id": chat_id,
                            "from_principal": False, "selfcheck": True,
                            "text": cq}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            print(f"[{now()}] control question emitted: {cid}")

    # THE MARK GOES UP ONLY AFTER THE REQUEST IS ON DISK, and the order is the
    # whole point. A mark placed first would mean "bytes seen"; placed here it
    # means "stored, and it will be answered". If the write fails, no mark
    # appears and the sender is not told a comforting lie.
    #
    # This is a documented failure of at least one shipped Telegram bridge:
    # the acknowledging reaction fires before delivery, so the user sees the
    # eyes and believes the message landed when it did not. The fix costs one
    # file write of delay — microseconds — and buys the mark its meaning.
    how = ack(chat_id, msg["message_id"])
    print(f"[{now()}] addressed{' by voice' if voice else ''}: "
          f"{ask[:60]!r}  mark={how}")


def attachments_of(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """What of this message is a file we should fetch.

    Deliberately NOT a catch-all: stickers and dice are decoration, and
    fetching them would fill the disk with noise the reader never asked for.
    """
    out: list[dict[str, Any]] = []
    photos = msg.get("photo") or []
    if photos:
        # Telegram sends a ladder of sizes; the last is the largest.
        out.append({**photos[-1], "kind": "photo", "file_name": "photo.jpg"})
    for key in ("document", "video", "animation", "audio", "voice", "video_note"):
        m = msg.get(key)
        if m:
            out.append({**m, "kind": key})
    return out


_SAFE_NAME = re.compile(r"[^A-Za-z0-9А-Яа-яЁё._ -]")


def safe_name(name: str | None, default: str) -> str:
    """A name that came from someone else is not a path.

    Everything before the last separator is dropped, then anything outside a
    small alphabet is replaced. A file called `../../config.py` becomes
    `config.py` and lands in the request's own directory, where it can
    overwrite nothing.
    """
    base = PurePosixPath(str(name or default)).name or default
    base = _SAFE_NAME.sub("_", base).strip(". ") or default
    return base[:120]


def file_job(chat_id: int, msg: dict[str, Any], rec: dict[str, Any],
             att: list[dict[str, Any]], caption: str) -> None:
    """Download attachments off the polling loop and queue the request.

    THE TRUST BOUNDARY MOVES HERE, and it should be said plainly rather than
    left in the code. Until now the bridge accepted TEXT from another machine;
    now it accepts BYTES. Three things carry that weight, and a fourth was
    considered and rejected:

      * the size cap, checked from Telegram's own metadata BEFORE any download,
        so a large file costs one API call and not a full disk;
      * the name, which is treated as data and never as a path (`safe_name`);
      * the directory, one per request, holding nothing that is imported,
        executed, or on any search path;
      * REJECTED: a deny-list of extensions. It would read as protection while
        providing none — the danger is never the suffix, it is execution, and
        the rule against execution belongs in PROTOCOL.md where a human can
        read it, not in a list that invites the game of finding what is not on
        it.

    Nothing here is made executable. The assistant may READ what arrives. It
    may never run it.
    """
    lag = time.time() - (msg.get("date") or time.time())
    ack(chat_id, msg["message_id"], C.HEARD_EMOJI)
    rid = f"{msg['message_id']}-{chat_id}"
    d = C.MEDIA / rid
    d.mkdir(parents=True, exist_ok=True)

    got: list[dict[str, Any]] = []
    for a in att:
        size = a.get("file_size")
        if size and size > C.MEDIA_MAX_BYTES:
            got.append({"kind": a.get("kind"), "name": a.get("file_name"),
                        "bytes": size, "refused": "TOO_LARGE",
                        "limit_bytes": C.MEDIA_MAX_BYTES})
            print(f"[{now()}] attachment refused, {size} > {C.MEDIA_MAX_BYTES}")
            continue
        name = safe_name(a.get("file_name"), f"{a.get('kind', 'file')}.bin")
        dest = d / name
        if dest.exists():                       # two files, one name
            dest = d / f"{dest.stem}-{len(got)}{dest.suffix}"
        if not fetch_file(a["file_id"], dest):
            got.append({"kind": a.get("kind"), "name": name,
                        "refused": "DOWNLOAD_FAILED"})
            continue
        raw = dest.read_bytes()
        got.append({"kind": a.get("kind"), "name": dest.name, "path": str(dest),
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "mime": a.get("mime_type")})

    rec["files"] = got
    ok = [g for g in got if "path" in g]
    print(f"[{now()}] attachments: {len(ok)}/{len(att)} fetched, "
          f"{lag:.1f}s before us")

    # A REQUEST MUST NEVER BE EMPTY. The caption carries the address when there
    # is one; when there is none, the attachment describes itself, so the inbox
    # shows a thing instead of a blank line.
    text = caption.strip()
    if not text:
        what = ", ".join(f"{g['name']} ({g.get('bytes', 0) // 1024} KB)"
                         if "path" in g else f"{g.get('name')} — {g['refused']}"
                         for g in got) or "attachment"
        text = f"[attachment: {what}]"
    rec["text"] = text
    accept(chat_id, msg, rec, text, msg.get("from", {}))


def handle(update: dict[str, Any], whoami: bool) -> None:
    msg = update.get("message") or update.get("channel_post")
    if not msg:
        return
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    text = msg.get("text") or msg.get("caption") or ""

    if whoami:
        print(f"  chat_id={chat_id}  type={chat.get('type')}  "
              f"title={chat.get('title') or chat.get('username') or chat.get('first_name')}")
        return

    # THE FILTER SITS BEFORE THE WRITE: a chat that is not allowed never
    # reaches the disk at all, not even the log.
    #
    # One exception, and it is deliberately narrow: the chat's ID, TYPE and
    # TITLE are printed to the console log — never the message, never the
    # sender. Without it, adding a new group is a dead end: the filter hides
    # the very number needed to allow the chat, and the operator is left
    # writing into a void wondering why nothing answers. The identifier of a
    # room is not its contents.
    if not C.allowed(chat_id):
        if chat_id not in _SEEN_UNKNOWN:
            if len(_SEEN_UNKNOWN) > 500:
                _SEEN_UNKNOWN.clear()      # a set that only grows is a leak
            _SEEN_UNKNOWN.add(chat_id)
            print(f"[{now()}] message from a chat that is NOT allowed: "
                  f"chat_id={chat_id} type={chat.get('type')} "
                  f"title={chat.get('title') or chat.get('first_name') or '?'} "
                  f"— add it to chats.json to let it in")
        return

    # Once per chat: say that this chat is logged — before the first line of
    # it is stored, not after.
    announce(chat_id)

    frm = msg.get("from", {})
    rec = {
        "at": now(),
        "chat_id": chat_id,
        "chat": chat.get("title") or chat.get("username") or chat.get("first_name"),
        "message_id": msg.get("message_id"),
        "from": frm.get("username") or frm.get("first_name"),
        "from_id": frm.get("id"),
        "text": text,
    }

    # A voice note has no text at all: before this, none of the matching below
    # could ever fire and the message vanished without a trace the sender
    # could see. Transcription happens off this thread — it takes seconds and
    # the polling loop must not wait for it.
    media = msg.get("voice") or msg.get("video_note") or msg.get("audio")
    if media and not text:
        threading.Thread(target=_guarded, args=(voice_job, chat_id, msg, rec, media),
                         daemon=True).start()
        return

    # AN ATTACHMENT WITHOUT A CAPTION ARRIVED AS AN EMPTY REQUEST — and once
    # that already cost a lost picture: on 2026-08-21 a third party's photo
    # landed in the inbox as a blank and was closed as "nothing to answer". The
    # bridge read only text and caption; everything else did not exist for it.
    att = attachments_of(msg)
    if att:
        threading.Thread(target=_guarded, args=(file_job, chat_id, msg, rec, att, text),
                         daemon=True).start()
        return

    accept(chat_id, msg, rec, text, frm)


def handle_reaction(mr: dict[str, Any]) -> None:
    """The principal's reaction to one of the assistant's messages.

    MEASURED, not assumed: the Bot API documentation says a bot must be an
    administrator of the chat to receive message_reaction, and whether that
    extends to private chats is unclear. It was tested — in a private chat
    reactions arrive with no admin rights. In a GROUP this is untested.

    This is the mechanism behind the consent gate: a proposal is acted on not
    because it arrived, but because the principal marked it. Absence of a mark
    is refusal, never consent.
    """
    chat_id = (mr.get("chat") or {}).get("id")
    if not C.allowed(chat_id):
        return
    emoji = [e.get("emoji") for e in mr.get("new_reaction", []) if e.get("type") == "emoji"]
    user = mr.get("user") or {}
    uid = user.get("id")
    rec = {"at": now(), "chat_id": chat_id, "message_id": mr.get("message_id"),
           "emoji": emoji, "user_id": uid, "name": user.get("first_name"),
           "approver": uid in C.policy(chat_id)["approvers"]}
    with C.ROOT.joinpath("reactions.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    who = "PRINCIPAL" if rec["approver"] else f"outsider ({uid})"
    print(f"[{now()}] reaction {emoji} on {mr.get('message_id')} by {who}")

    # THE BRIDGE'S OWN REACTIONS ARE NOT EVENTS. Without this the bridge would
    # answer its own acknowledgement with another acknowledgement, forever.
    if uid == _ME[0]:
        return

    mid = mr.get("message_id")
    if (C.PROPOSALS / f"{chat_id}-{mid}.json").exists() or \
            (C.DECIDED / f"{chat_id}-{mid}.json").exists():
        decide(chat_id, mid, emoji, rec["approver"], uid)
        return

    # A REACTION IS AN ACT, NOT NOISE. An earlier version marked it seen and
    # stopped there, reasoning that it carried no instruction. That threw away
    # meaning: 👍 on a claim is agreement, 👎 is dissent, and a reaction chosen
    # instead of words is still a choice. The bridge marks it seen at once and
    # wakes the assistant, which then decides how — or whether — to answer.
    #
    # Deciding NOT to answer is part of the job. A mark that closes an exchange
    # should not reopen it: answering a 👍 with a paragraph is how a light
    # signal turns back into a conversation nobody can end.
    if rec["approver"] and emoji:
        ack(chat_id, mid)
        C.REQUESTS.joinpath(f"reaction-{chat_id}-{mid}.json").write_text(
            json.dumps({"at": now(), "chat_id": chat_id, "message_id": mid,
                        "from": user.get("first_name"), "from_id": uid,
                        "from_principal": True, "reaction": emoji,
                        "on_my_message": what_i_said(chat_id, mid),
                        "text": f"reaction {' '.join(emoji)}",
                        "ask": f"reaction {' '.join(emoji)} on my message",
                        "topic": C.policy(chat_id).get("topic"),
                        "language": C.policy(chat_id).get("language"),
                        "context": tail(chat_id, 4)}, ensure_ascii=False, indent=2),
            encoding="utf-8")


def what_i_said(chat_id: int, message_id: int) -> str:
    """The text of the assistant's own message that was reacted to.

    Without it a reaction is a thumb pointing at nothing: the assistant would
    know that something was approved of, but not what.
    """
    for f in C.SENT.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("sent_message_id") == message_id and d.get("chat_id") == chat_id:
            return (d.get("text") or "")[:600]
    return ""


def _close(pf: Path, prop: dict[str, Any], verdict: str,
           uid: int | None = None, emoji: list[str] | None = None) -> None:
    """Record the verdict and take it out of pending — decided only once.

    THE DECISION ARTIFACT CARRIES WHO DECIDED. The gate's whole claim is that
    a mark transfers responsibility to an identifiable human; an authorization
    record that does not name that human does not support the claim it is made
    of. It was reconstructible from the reaction log, which is not the same
    thing: the record consumed downstream must be self-contained.

    `uid` is None for an expiry — nobody decided, the proposal lapsed — and
    that is recorded as such rather than left blank.

    DECIDED ONLY ONCE, UNDER THE LOCK. Two paths race to close one proposal —
    a mark (decide, main thread) and expiry (sweep_proposals, pump). Whoever
    takes _STATE_LOCK first decides; the loser sees the decision already
    recorded and returns. So a grant minted by APPROVED is never overwritten
    by a late EXPIRED, nor the reverse — no mixed state where the consent log
    says EXPIRED yet a grant exists.
    """
    with _STATE_LOCK:
        if (C.DECIDED / pf.name).exists():
            return
        _close_locked(pf, prop, verdict, uid, emoji)


def _close_locked(pf: Path, prop: dict[str, Any], verdict: str,
                  uid: int | None = None, emoji: list[str] | None = None) -> None:
    """Implementation of _close; always called holding _STATE_LOCK."""
    prop["verdict"] = verdict
    prop["decided_at"] = now()
    prop["decided_by_user_id"] = uid
    prop["decision_reaction"] = emoji
    prop["decision_event_at"] = now()
    prop["proposal_message_id"] = prop.get("message_id")
    prop["proposal_chat_id"] = prop.get("chat_id")
    # A STANDING RULE IS BORN HERE AND NOWHERE ELSE. A proposal may carry a
    # rule; it reaches the journal only together with the numeric id of whoever
    # placed the mark, the mark itself, and the proposal number. The assistant
    # PROPOSES a rule and never writes it in — the same prohibition as in
    # institutional clearances: the constrained party does not manufacture the
    # object that constrains it.
    # A BATCH. One mark — one CONSIGNMENT to ONE room, and every file in it is
    # named by fingerprint. This is not "a to-do list under one checkmark": five
    # files of one consignment are one matter with five parts, while five
    # separate matters still cannot be joined this way.
    if verdict == "APPROVED" and prop.get("batch") and uid:
        try:
            gs = C.grants()
            n = len(gs)
            for i, item in enumerate(prop["batch"]["files"], 1):
                gs.append({"id": f"G{n + i:03d}",
                           "chat_id": prop["batch"]["chat_id"],
                           "name": item["name"], "sha256": item["sha256"],
                           "bytes": item.get("bytes"),
                           "added_at": now(), "added_by_user_id": uid,
                           "decision_reaction": emoji,
                           "proposal_message_id": prop.get("message_id"),
                           "used_at": None})
            _atomic_write(C.GRANTS, json.dumps(gs, ensure_ascii=False, indent=1))
            print(f"[{now()}] BATCH APPROVED: {len(prop['batch']['files'])} "
                  f"files -> {prop['batch']['chat_id']} (mark {uid})")
        except Exception as e:
            print(f"[{now()}] batch NOT written: {type(e).__name__}: {e}")

    if verdict == "APPROVED" and prop.get("rule") and uid:
        try:
            rules = C.file_rules()
            rule = dict(prop["rule"])
            rule.update({"id": f"R{len(rules) + 1:03d}",
                         "added_at": now(), "added_by_user_id": uid,
                         "decision_reaction": emoji,
                         "proposal_message_id": prop.get("message_id")})
            rules.append(rule)
            _atomic_write(C.RULES, json.dumps(rules, ensure_ascii=False, indent=1))
            where = ", ".join(str(d.get("dir")) for d in (rule.get("dirs") or [])) \
                or ", ".join(rule.get("paths") or []) or rule.get("dir") or "?"
            rooms = rule.get("chats") or [rule.get("chat_id")]
            print(f"[{now()}] RULE ADDED {rule['id']} "
                  f"«{rule.get('project') or '—'}»: {where} -> {rooms} "
                  f"(mark {uid})")
        except Exception as e:
            print(f"[{now()}] rule NOT written: {type(e).__name__}: {e}")

    # The decision record — atomic, and FIRST of the final steps: its presence
    # is what _close's idempotency checks, so it must land whole before pf is
    # gone. os.replace leaves no half-file.
    _atomic_write(C.DECIDED / pf.name, json.dumps(prop, ensure_ascii=False))
    pf.unlink(missing_ok=True)
    # Wake the assistant by the same path an ordinary message wakes it.
    C.REQUESTS.joinpath(f"verdict-{pf.stem}.json").write_text(
        json.dumps({"at": now(), "chat_id": prop["chat_id"],
                    "message_id": prop["message_id"], "from": "GATE",
                    # The APPROVER's numeric id, not the chat's. The chat id
                    # named a room; only this names a person.
                    "from_id": uid,
                    "decided_by_user_id": uid,
                    "decision_reaction": emoji,
                    "decision_event_at": prop["decision_event_at"],
                    "proposal_message_id": prop.get("proposal_message_id"),
                    "proposal_chat_id": prop.get("proposal_chat_id"),
                    "text": f"{verdict}: {prop['one_line']}",
                    "ask": f"{verdict}: {prop['one_line']}",
                    "action": prop.get("action"), "verdict": verdict,
                    "target_chat": prop.get("target_chat"),
                    "context": []}, ensure_ascii=False), encoding="utf-8")


def decide(chat_id: int, message_id: int | None, emoji: list[str],
           approver: bool, uid: int | None) -> None:
    """A mark on a pending proposal is an order. Nothing else is."""
    pf = C.PROPOSALS / f"{chat_id}-{message_id}.json"
    if not pf.exists():
        return                       # a reaction to an ordinary message, not the gate
    prop = json.loads(pf.read_text(encoding="utf-8"))
    if not approver:
        # Not silently: an outsider marking the gate is an event, not noise.
        print(f"[{now()}] OUTSIDER marked proposal {pf.stem} (uid {uid}) — not an order")
        return
    if datetime.now(timezone.utc) > datetime.fromisoformat(prop["expires"]):
        _close(pf, prop, "EXPIRED")
        C.OUTBOX.joinpath(f"stale-{pf.stem}.json").write_text(
            json.dumps({"chat_id": chat_id, "reply_to": message_id,
                        "text": "that proposal has expired — the mark does not "
                                "count. If it is still wanted, I will hang it "
                                "again."},
                       ensure_ascii=False), encoding="utf-8")
        return
    approve = bool(set(emoji) & C.APPROVE_EMOJI)
    reject = bool(set(emoji) & C.REJECT_EMOJI)

    # AN AMBIGUOUS VERDICT IS NEVER PERMISSION.
    #
    # The first version read "APPROVED if any approve emoji, else REFUSED if
    # any reject emoji". A reaction set containing BOTH therefore resolved to
    # APPROVED, because the approve branch was tested first. For a consent
    # gate that is a fail-open: the one direction an unclear signal must never
    # take is the permissive one.
    #
    # Telegram permits more than one reaction on a message, so the set really
    # can contain both. The proposal stays pending, nothing is executed, and
    # the principal is told — an ambiguity that vanished silently would be
    # indistinguishable from never having marked at all.
    if approve and reject:
        print(f"[{now()}] AMBIGUOUS mark on {pf.stem}: {emoji} — refusing to "
              f"read this as permission; proposal stays pending")
        C.OUTBOX.joinpath(f"ambiguous-{pf.stem}.json").write_text(
            json.dumps({"chat_id": chat_id, "reply_to": message_id,
                        "text": "your reaction carries both an approval and a "
                                "refusal, so I am not treating it as either. "
                                "The proposal is still pending — clear the marks "
                                "and leave exactly one."},
                       ensure_ascii=False), encoding="utf-8")
        return

    verdict = "APPROVED" if approve else "REFUSED" if reject else None
    if verdict is None:
        return                       # not a verdict: the proposal stays pending
    # THE BRIDGE PLACES THE MARK, NOT THE ASSISTANT — waiting for the assistant
    # to wake would make "seen" arrive ten seconds late and stop meaning seen.
    #
    # But it places it AFTER the verdict is written, never before. "Mark
    # accepted" must mean the verdict is recorded; a mark that goes up first
    # would confirm receipt of something that a failed write then loses.
    #
    # (An earlier revision of this comment said "before", left behind when the
    # order was corrected and the code moved on without it. A comment that
    # teaches the inverse of the code is worse than no comment: the next reader
    # trusts it, and the reader after that restores the bug to match. Found by
    # an external source review.)
    _close(pf, prop, verdict, uid=uid, emoji=emoji)
    print(f"[{now()}] mark accepted: {verdict} by {uid} — "
          f"{ack(chat_id, message_id)}")



def _seen(chat_id: int, message_id: int) -> bool:
    """Did the PRINCIPAL react to this exact message? Any emoji counts.

    To place a reaction you must have opened the message, so a reaction — 👍
    or anything else — proves it was seen. That is the whole ack signal an
    escalating reminder waits for.

    THE REACTOR MUST BE AN APPROVER, not just anyone. In a group the reminder
    hangs in, an outsider could put any emoji on the bot's message and silently
    retire an escalation the principal never saw. So we require `approver`,
    which handle_reaction already stamps on every record (uid in approvers).
    This also excludes the bridge's OWN marks: it is not an approver, so its
    👀 never counts as "the principal saw it".
    """
    log = C.ROOT / "reactions.jsonl"
    if message_id is None or not log.exists():
        return False
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("chat_id") == chat_id and rec.get("message_id") == message_id \
                and rec.get("emoji") and rec.get("approver"):
            return True
    return False


def control_question() -> str | None:
    """On every SELFCHECK_EVERY-th address from the principal, return the text of
    a control question (present), otherwise None. Counts by a counter file. Fully
    guarded: any misfire -> None, message delivery does not suffer."""
    try:
        n = 0
        if C.SELFCHECK_COUNT.exists():
            n = int(C.SELFCHECK_COUNT.read_text().strip() or "0")
        n += 1
        C.SELFCHECK_COUNT.write_text(str(n))
        if n % C.SELFCHECK_EVERY != 0:
            return None
        r = subprocess.run(C.SELFCHECK_PRESENT, capture_output=True,
                           text=True, timeout=8)
        out = (r.stdout or "").strip()
        return out or None
    except Exception as e:
        print(f"[{now()}] selfcheck skipped: {type(e).__name__}: {e}")
        return None


def due_reminders() -> None:
    """Send whatever has come due.

    The schedule lives in the BRIDGE, not in the assistant, and that is the
    point: a reminder that hangs on the assistant waking up dies with its
    session — while a person was counting on it. The bridge survives a closed
    window and a reboot.

    Parsing human time ("in an hour", "tomorrow at nine") is the assistant's
    job; it writes an exact UTC stamp here. The bridge only waits and sends.

    ESCALATION. A reminder with "ack": true does not retire after one send.
    A sent reminder that was never seen is a reminder that failed — from the
    outside "delivered" and "missed" look the same. So the bridge resends it
    every "every_min" minutes UNTIL the principal reacts to it (👍 = "I saw
    it"), and only then falls silent. A safety cap ("max_tries") stops it from
    nagging forever if no one ever answers — and it says so out loud rather
    than vanishing.
    """
    now_ts = datetime.now(timezone.utc)

    def retire(f: pathlib.Path, why: str) -> None:
        f.rename(C.SENT_REMINDERS / f.name)
        print(f"[{now()}] reminder retired ({why}): {f.name}")

    for f in sorted(C.REMINDERS.glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            when = datetime.fromisoformat(r["at"])
        except Exception as e:
            print(f"[{now()}] malformed reminder {f.name}: {e}")
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when > now_ts:
            continue
        if not C.allowed(r.get("chat_id")):
            print(f"[{now()}] REFUSED: reminder {f.name} targets a chat not allowed")
            continue

        ack = bool(r.get("ack"))
        # already delivered once and now acknowledged? fall silent.
        if ack and r.get("last_msg_id") and _seen(r["chat_id"], r["last_msg_id"]):
            print(f"[{now()}] reminder acknowledged 👍 -> {r['chat_id']}: {r['text'][:40]}")
            retire(f, "acknowledged")
            continue

        tries = int(r.get("tries", 0))
        max_tries = int(r.get("max_tries", 24))   # 24 × 5 min ≈ 2 hours
        if ack and tries >= max_tries:
            give_up = (f"{C.REPLY_PREFIX} reminder (giving up after {tries} tries, "
                       f"you seem not to have seen it): {r['text']}")
            if not C.DRY_RUN:
                call("sendMessage", chat_id=r["chat_id"], text=give_up)
            print(f"[{now()}] reminder CAPPED unacked -> {r['chat_id']}: {r['text'][:40]}")
            retire(f, "capped-unacked")
            continue

        again = "  (reminding again — like it if you saw it)" if tries else ""
        text = f"{C.REPLY_PREFIX} reminder: {r['text']}{again}"
        resp = None if C.DRY_RUN else call("sendMessage", chat_id=r["chat_id"], text=text)
        if C.DRY_RUN or (resp and resp.get("ok")):
            if ack:
                r["tries"] = tries + 1
                if resp:
                    r["last_msg_id"] = resp.get("result", {}).get("message_id")
                every = int(r.get("every_min", 5))
                r["at"] = (now_ts + timedelta(minutes=every)).isoformat()
                f.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
                print(f"[{now()}] reminder sent (try {r['tries']}, awaiting 👍) "
                      f"-> {r['chat_id']}: {r['text'][:40]}")
            else:
                retire(f, "sent once")
                print(f"[{now()}] reminder sent -> {r['chat_id']}: {r['text'][:50]}")


def nudge_unanswered() -> None:
    """Tell the human that their message was accepted, but NOBODY TOOK IT UP.

    The 👀 mark means "stored, and it will be answered". That is a promise. If
    the assistant is not running, there is no one to keep the promise, and the
    human never learns it: from outside "being read" and "being forgotten" look
    the same.

    So the bridge, the only thing here that is certainly alive, speaks for
    itself. ONCE per message — otherwise the reminder turns into a clatter and
    gets switched off.
    """
    cutoff = time.time() - C.NUDGE_AFTER_MIN * 60
    for f in sorted(C.REQUESTS.glob("*.json")):
        if f.name.startswith(("verdict-", "needsfile-", "reaction-", "control-")):
            continue                       # these are my own notes, not his waiting
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if r.get("nudged") or f.stat().st_mtime > cutoff:
            continue
        chat_id, mid = r.get("chat_id"), r.get("message_id")
        if not C.allowed(chat_id):
            continue
        mins = int((time.time() - f.stat().st_mtime) / 60)
        text = (f"{C.REPLY_PREFIX} accepted and sitting in the inbox, but in "
                f"{mins} min nobody has picked it up. The 👀 mark promised a "
                f"reply — the promise is not yet kept. The message is not lost.")
        if C.DRY_RUN or call("sendMessage", chat_id=chat_id, text=text,
                             reply_to_message_id=mid).get("ok"):
            r["nudged"] = now()
            f.write_text(json.dumps(r, ensure_ascii=False, indent=2),
                         encoding="utf-8")
            print(f"[{now()}] NOBODY TO TAKE IT: {f.stem}, {mins} min, told in chat")


def sweep_old_files() -> None:
    """Throw away what nobody will ever look at again.

    Voice notes are the reason: a minute of audio is a hundred kilobytes, and
    nothing ever deleted them. A bridge that quietly fills a disk over a year
    is a bridge that stops one morning for a reason nobody connects to voice
    messages. Transcripts stay in the log; only the audio goes.
    """
    cutoff = time.time() - C.KEEP_DAYS * 86400
    for folder in (C.VOICE, C.SENT, C.SERVED):
        if not folder.exists():
            continue
        for f in folder.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass


def sweep_media(root: Path | None = None, budget: int | None = None,
                pending: set[str] | None = None) -> list[str]:
    """Attachments are cleared by OVERFLOW, not by age.

    The curator's word: a file sent half a year ago may be needed, while forty
    of today's may not. Age does not know what matters; volume is at least
    honest.

    Three rules, and the second is the most important:

    1. A request's DIRECTORY is removed whole. One message's attachments are one
       thing; throwing away half means leaving something unintelligible.
    2. **A request directory that has NOT YET BEEN ANSWERED is never touched.**
       Otherwise the sweep eats exactly what is sitting and waiting for me, and
       the inbox shows a link into the void.
    3. Every deletion is printed with its size. A silent sweep is
       indistinguishable from a loss, and a loss is later blamed on anything.

    Returns the list of what was cleared — so the caller need not guess.
    """
    root = root or C.MEDIA
    budget = C.MEDIA_BUDGET_BYTES if budget is None else budget
    if not root.exists():
        return []
    items = []
    total = 0
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        total += size
        items.append((d.stat().st_mtime, size, d))
    if total <= budget:
        return []

    if pending is None:
        pending = {p.stem for p in C.REQUESTS.glob("*.json")}
    items.sort(key=lambda x: x[0])            # oldest first
    removed: list[str] = []
    for _, size, d in items:
        if total <= budget:
            break
        if d.name in pending:
            continue                          # awaiting a reply — do not touch
        shutil.rmtree(d, ignore_errors=True)
        total -= size
        removed.append(d.name)
        print(f"[{now()}] media sweep: cleared {d.name}, {size} bytes, "
              f"{total} of {budget} left")
    if total > budget:
        # Say it out loud rather than quietly accept it: space has run out and
        # there is nothing to clear, because everything left is awaiting a
        # reply. This is about me, not the disk.
        print(f"[{now()}] media sweep: still {total} > {budget}, "
              f"the rest awaits a reply — clear the inbox")
    return removed


def sweep_proposals() -> None:
    """Clear expired proposals. Silence is not consent — expiry means no."""
    nowt = datetime.now(timezone.utc)
    for pf in sorted(C.PROPOSALS.glob("*.json")):
        try:
            prop = json.loads(pf.read_text(encoding="utf-8"))
            if nowt <= datetime.fromisoformat(prop["expires"]):
                continue
        except Exception:
            continue
        _close(pf, prop, "EXPIRED")
        print(f"[{now()}] cleared expired proposal {pf.stem}")


LIMIT = 4000          # Telegram's own cap is 4096; leave room for the prefix


def split_for_telegram(text: str) -> list[str]:
    """One message, or several that read as one.

    Splits on blank lines first, then single lines, then hard characters.
    Anything else — refusing to send, or truncating — loses the reader either
    the message or the end of it, silently.
    """
    if len(text) <= LIMIT:
        return [text]
    out, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 <= LIMIT:
            cur = f"{cur}\n\n{para}" if cur else para
            continue
        if cur:
            out.append(cur); cur = ""
        while len(para) > LIMIT:
            cut = para.rfind("\n", 0, LIMIT)
            if cut < LIMIT // 2:
                cut = LIMIT
            out.append(para[:cut]); para = para[cut:].lstrip("\n")
        cur = para
    if cur:
        out.append(cur)
    return out


def clear_inbox(item: dict[str, Any], mark_done: bool = False) -> None:
    """Move every request this reply names out of the inbox.

    A request leaves requests/ only by being NAMED, whatever form the answer
    took — words or a mark. The inbox must agree with what actually happened,
    or it becomes another thing to remember rather than a thing to consult.

    AND THE EYES COME OFF. 👀 means "accepted, not yet done"; leaving it on a
    message that has just been answered makes the mark lie, and a mark that
    sometimes lies stops being read. Doing it here rather than by hand is the
    whole point: the rule was written and then broken one message later, which
    is what happens to every rule that depends on being remembered.
    """
    for rid in (item.get("answers") or []):
        req = C.REQUESTS / f"{rid}.json"
        # MARK FIRST, THEN MOVE. Renaming the request into served BEFORE the
        # 👍 was placed meant a failed ack left the inbox empty while 👀 still
        # burned on the phone — done in the record, not-done to the human.
        # Placing the mark first keeps the two in step; the move happens either
        # way, because a named request IS answered and must leave the inbox.
        if mark_done:
            try:
                # SPLIT FROM THE LEFT. A group's chat id is NEGATIVE, so the
                # request id reads "284--5101395964" — and splitting from the
                # right cut it at the id's own minus sign, giving message id
                # "284-", which is not a number. The failure was caught and
                # swallowed, so in groups the eyes simply never came off and
                # nothing said why.
                #
                # The message id is always a positive integer and always
                # first, so the first hyphen is the only safe boundary. Ids
                # that begin with a word — verdict-..., reaction-... — still
                # fail int() and are skipped, which is what they should do.
                mid, chat = rid.split("-", 1)
                done = item.get("done_emoji") or "👍"
                # AN INVALID done_emoji USED TO LEAVE 👀 IN PLACE. ack() refuses
                # an emoji Telegram does not accept and returns without touching
                # the reaction, so the assistant read the request as answered
                # while the eye stayed open on the phone — 26 piled up that way
                # in one session before this was found. Substitute the safe mark
                # so the eye ALWAYS closes, and tell the assistant in a FILE (it
                # never reads the stdout log where REACTION_INVALID is printed).
                if done not in C.VALID_REACTIONS:
                    note = C.REQUESTS / f"emoji-notice-{int(time.time()*1000)}.json"
                    note.write_text(json.dumps({
                        "request_id": note.stem, "chat_id": None,
                        "from_principal": False, "selfcheck": True,
                        "text": (f"INVALID done_emoji {done!r} on {rid}: Telegram "
                                 f"does not accept it, used 👍 instead. Take "
                                 f"done_emoji ONLY from config.VALID_REACTIONS "
                                 f"(👍 by default) — otherwise the eye does not "
                                 f"close on the phone.")},
                        ensure_ascii=False), encoding="utf-8")
                    print(f"[{now()}] done_emoji {done!r} invalid -> 👍; note {note.name}")
                    done = "👍"
                how = ack(int(chat), int(mid), done)
                # LOGGED, because an action nobody can see is an action nobody
                # can check. This one was placed correctly and left no trace,
                # so the only way to know it happened was to look at the phone.
                print(f"[{now()}] done {done} -> {chat}/{mid}: {how}")
            except (ValueError, KeyError):
                pass                  # ids like "verdict-..." carry no message
        if req.exists():
            req.rename(C.SERVED / req.name)


def outgoing_prefix(pol: dict[str, Any], item: dict[str, Any]) -> str:
    """Which signature this message carries.

    AN EMPTY SIGNATURE IS A CHOICE, NOT AN OMISSION. `or` would silently restore
    the name: "" is falsy in Python, so a chat configured to speak without a
    signature would keep signing. Testing for the KEY distinguishes "not
    configured" from "configured to nothing", and that distinction is the whole
    of the setting.

    Only the assistant's OWN speech can be unsigned, and only where the reader
    already knows who is speaking. The two outward signatures — words carried
    out of this chat, and the principal's words in translation — are chosen
    first and are not affected: a text that travels must say whose it is.
    """
    if item.get("no_marker"):          # meant to be copied out of this chat
        return pol.get("copy_prefix") or C.COPY_PREFIX
    if item.get("relay"):              # the principal's words, not mine
        return pol.get("relay_prefix") or C.RELAY_PREFIX
    return pol["reply_prefix"] if "reply_prefix" in pol else C.REPLY_PREFIX


def compose(prefix: str, text: str) -> str:
    """Signature and text, without the leading space an empty prefix would leave."""
    return f"{prefix} {text}" if prefix else text


def flush_outbox() -> None:
    """Drain the assistant's outbox: marks first, then replies.

    Two kinds of file, and the order matters. `*.react.json` is "taken up" and
    should land as early as possible. `*.json` is the reply itself, which
    arrives later anyway.
    """
    # TAKING A MARK BACK. The bridge places 👀 on anything that begins with the
    # name, because deciding whether a message is really an address takes
    # judgement and judgement is slow. So the mark means "recognised, queued",
    # and the assistant — once awake — removes it if the message was not for
    # it after all. Without this the icon would slowly become a lie: present
    # on messages nobody ever answered.
    #
    # Two stages, and that is the point: the bridge is fast and dumb, the
    # assistant is slow and can judge. Neither has to be both.
    for f in sorted(C.OUTBOX.glob("*.unreact.json")):
        try:
            item = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            f.unlink(missing_ok=True); continue
        if C.allowed(item.get("chat_id")) and not C.DRY_RUN:
            call("setMessageReaction", chat_id=item["chat_id"],
                 message_id=item["message_id"], reaction=[])
            print(f"[{now()}] mark withdrawn — not addressed to me: "
                  f"{item['chat_id']}/{item['message_id']}")
        f.unlink(missing_ok=True)

    for f in sorted(C.OUTBOX.glob("*.react.json")):
        try:
            item = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            f.unlink(missing_ok=True); continue
        if C.allowed(item.get("chat_id")):
            # An emoji chosen by the assistant REPLACES the bridge's automatic
            # 👀 — a bot may hold only one reaction per message. That is the
            # point rather than a limitation: the eyes mean "received and
            # stored", and once the assistant has actually read the thing, a
            # chosen mark says more, and says it instead of a paragraph.
            how = ack(item["chat_id"], item["message_id"], item.get("emoji"))
            print(f"[{now()}] mark {item.get('emoji') or C.ACK_EMOJI} -> "
                  f"{item['chat_id']}/{item['message_id']}: {how}")
            # A MARK IS AN ANSWER TOO. Only word-replies used to clear the
            # inbox, so a request answered with 👍 sat there looking unserved.
            # Two ways of answering and one way of recording it is how the
            # record and the truth drift apart.
            #
            # BUT ONLY IF THE MARK ACTUALLY LANDED. If ack failed — invalid
            # emoji, or the whole thing FAILED with no fallback message — then
            # nothing is visible to the human, and clearing the inbox anyway
            # would record "answered" over a message that shows no answer at
            # all. Leave it open and say why. ("message" fallback DID reach
            # them, so that still clears.)
            if how == "invalid-emoji" or how.startswith("FAILED"):
                print(f"[{now()}] MARK DID NOT LAND ({how}) — NOT clearing the "
                      f"request, eye stays: {item.get('answers')}")
            else:
                clear_inbox(item)
        f.unlink(missing_ok=True)

    # EDITING ONE OF THE ASSISTANT'S OWN MESSAGES. Telegram allows a bot to
    # edit only what the bot itself sent — a user's message is untouchable, so
    # "rewrite my text in place" is not available at any price.
    #
    # Useful anyway: a translation that needs another pass updates in place
    # instead of growing a thread of near-identical drafts.
    #
    # A PROPOSAL IS NEVER EDITABLE, and that is not a detail. If the text of a
    # proposal could change after it was hung, the principal would approve
    # version A and version B would be what gets acted on — the mark would
    # certify nothing. One mark belongs to one exact text; a changed text needs
    # a new proposal and a new mark.
    for f in sorted(C.OUTBOX.glob("*.edit.json")):
        try:
            item = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            f.unlink(missing_ok=True); continue
        chat_id, mid = item.get("chat_id"), item.get("message_id")
        stem = f"{chat_id}-{mid}.json"
        if not C.allowed(chat_id):
            print(f"[{now()}] REFUSED: edit {f.name} targets a chat not allowed")
            f.unlink(missing_ok=True); continue
        if (C.PROPOSALS / stem).exists() or (C.DECIDED / stem).exists():
            print(f"[{now()}] REFUSED: {stem} carries a proposal — hang a new one "
                  f"instead of editing the text a mark refers to")
            f.unlink(missing_ok=True); continue
        if not C.DRY_RUN:
            r = call("editMessageText", chat_id=chat_id, message_id=mid,
                     text=f"{C.REPLY_PREFIX} {item.get('text', '').strip()}")
            print(f"[{now()}] edited {chat_id}/{mid}: "
                  f"{'ok' if r.get('ok') else r.get('description')}")
        f.unlink(missing_ok=True)

    for f in sorted(C.OUTBOX.glob("*.json")):
        if (f.name.endswith(".react.json") or f.name.endswith(".unreact.json")
                or f.name.endswith(".edit.json")):
            continue
        try:
            item = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            # DO NOT SWALLOW SILENTLY, AND DO NOT STORM FOREVER. A malformed
            # JSON used to stay in outbox and be re-read every second without
            # end — undelivered to the human and unreturned to the assistant as
            # broken. But the first failure may just be a half-written file
            # (write_text = truncate then write), so quarantine only what has
            # not fixed itself in a few seconds; the write window is
            # microseconds, 5s is a wide margin.
            try:
                stale = time.time() - f.stat().st_mtime > 5
            except OSError:
                stale = False
            if stale:
                (C.OUTBOX / "rejected").mkdir(exist_ok=True)
                f.rename(C.OUTBOX / "rejected" / f.name)
                print(f"[{now()}] OUTBOX REJECTED — malformed JSON ({e}): "
                      f"{f.name} -> rejected/")
            else:
                print(f"[{now()}] malformed outbox file {f.name}: {e} "
                      f"(fresh — waiting, may be a partial write)")
            continue
        chat_id, text = item.get("chat_id"), (item.get("text") or "").strip()
        if not C.allowed(chat_id):
            # A REAL refusal (chat not in the list) goes to rejected/, or it
            # would storm the log forever. BUT only if the list actually
            # loaded: with a broken chats.json, allowed() is falsely False for
            # everyone, and a blind quarantine would drain the whole outbox.
            # Empty list = broken/missing config = do not quarantine, wait.
            if C._chats():
                (C.OUTBOX / "rejected").mkdir(exist_ok=True)
                item["_rejected"] = f"chat {chat_id} not in the allowed list"
                (C.OUTBOX / "rejected" / f.name).write_text(
                    json.dumps(item, ensure_ascii=False, indent=1),
                    encoding="utf-8")
                f.unlink(missing_ok=True)
                print(f"[{now()}] OUTBOX REJECTED — chat {chat_id} not allowed: "
                      f"{f.name} -> rejected/")
            else:
                print(f"[{now()}] REFUSED (chats.json empty/broken?): {f.name} "
                      f"-> {chat_id}; NOT quarantining, waiting for a fix")
            continue
        # A FILE IN THE QUEUE. The ask was "send a file into this chat"; until
        # v1.3.0 the bridge could only do text, and that was an honest refusal,
        # not an oversight: it had ACCEPTED files since v1.1.0 but did not send
        # them. Now both directions work.
        if item.get("file"):
            fp = Path(item["file"])
            # A GATE ON THE FILE. Sending a file is not a letter: it goes out
            # whole, cannot be appended to afterwards, and getting the room
            # wrong costs more here. So anything a standing rule does not cover
            # is asked about.
            rule = rule_for(chat_id, fp)
            grant = None if rule else grant_for(chat_id, fp)
            if rule is None and grant is None:
                print(f"[{now()}] FILE NOT SENT: {fp.name} -> {chat_id} "
                      f"covered by no rule — a proposal is needed")
                # OUT OF THE QUEUE, NOT RENAMED IN PLACE. The first version left
                # a refused file in the outbox under a new name — and the next
                # pass renamed it again, and again, growing the prefix and trying
                # to send forever. Exactly the same pit already described above
                # for messages longer than 4096 characters; I fell into it a
                # second time, in the same file, on the same day.
                C.NEEDS_CONSENT.mkdir(exist_ok=True)
                dest = C.NEEDS_CONSENT / f.name
                f.rename(dest)
                # AND TELL ME, NOT SET IT ASIDE SILENTLY. The first version just
                # moved the file aside: not a line to the inbox, no way back. It
                # made a dead end built for safety's sake — and a dead end nobody
                # knows about is indistinguishable from a loss.
                rid = f"needsfile-{dest.stem}"
                C.REQUESTS.joinpath(f"{rid}.json").write_text(json.dumps({
                    "at": now(), "chat_id": chat_id, "from": "GATE",
                    "from_id": None, "message_id": None,
                    "text": f"file awaiting a decision: {fp}",
                    "ask": (f"FILE NOT SENT — no rule.\n"
                            f"    file:  {fp}\n"
                            f"    to:    {chat_id}\n"
                            f"Hang it on a mark with one command:\n"
                            f"    ./propose.py --batch '{fp}' --to {chat_id} "
                            f"--why '<why>'"),
                    "needs_consent_file": str(dest), "path": str(fp),
                    "target_chat": chat_id, "context": []},
                    ensure_ascii=False), encoding="utf-8")
                continue
            r = send_file(chat_id, fp, item.get("text", "")[:1024],
                          as_photo=bool(item.get("as_photo")))
            if r.get("ok"):
                # A LOG OF WHAT WAS SENT BY RULE. A rule settles the question IN
                # ADVANCE, so the only check left is AFTERWARDS — and there must
                # be one, or a standing permission becomes a blind spot. One line
                # per send, with the rule's number.
                who = (rule or grant).get("id")
                kind = "rule" if rule else "grant"
                if grant:
                    spend_grant(who)
                with C.ROOT.joinpath("sent_by_rule.log").open(
                        "a", encoding="utf-8") as lg:
                    lg.write(f"{now()}\t{who}\t{chat_id}\t"
                             f"{fp}\t{fp.stat().st_size}\n")
                print(f"[{now()}] file sent by {kind} "
                      f"{who} -> {chat_id}: {fp.name}, "
                      f"{fp.stat().st_size} bytes")
                # A FILE IS AN ANSWER TOO, AND THE EYE MUST COME OFF. The text
                # branch closes the named request via clear_inbox; the file
                # branch silently dropped the answers field — the file went out
                # but the request stayed, 👀 lit, a false "nobody took it" nudge
                # 20 minutes later. Same "did (file sent) ≠ recorded (request
                # not closed)" class.
                clear_inbox(item, mark_done=True)
                item["sent_at"] = now()
                f.rename(C.SENT / f.name)
            else:
                print(f"[{now()}] file NOT sent: {r.get('description')}")
                f.rename(C.SENT / f"failed-{f.name}")
            continue

        if not text:
            f.unlink(); continue
        # "relay": these are the principal's words, not the assistant's.
        #
        # THE SIGNATURE FOLLOWS THE LANGUAGE OF THE ROOM. A Cyrillic name in
        # the middle of an English sentence trips the reader exactly where he
        # is working out whose words these are — and in a room whose subject is
        # attribution, that is the worst possible place to trip him. Each chat
        # may therefore carry its own pair of prefixes.
        pol = C.policy(chat_id)
        prefix = outgoing_prefix(pol, item)
        # "no_marker": a message meant to be COPIED ELSEWHERE — a translation,
        # a draft to forward — carries no action marker, because the marker
        # would travel with it into someone else's inbox. The exemption is
        # DECLARED in the file rather than inferred from the text: a silent
        # exemption is how a rule stops applying without anyone deciding that
        # it should.
        # The marker answers "is anything owed by the PRINCIPAL", so it belongs
        # in the principal's own chat and nowhere else. A greeting addressed to
        # a guest in a room does not owe him a marker, and stamping one there
        # would turn a discipline into a tic.
        pol_now = C.policy(chat_id)
        speaks_to_principal = chat_id == pol_now.get("principal")
        if speaks_to_principal and len(text) >= C.MARKER_MIN_CHARS and \
                not item.get("no_marker") and \
                not any(m in text.upper() for m in C.NEEDS_MARKER):
            print(f"[{now()}] NO ACTION MARKER on a {len(text)}-char reply — "
                  f"the reader has to work out for himself whether he is owed "
                  f"anything")
        body = compose(prefix, text)
        if C.DRY_RUN:
            print(f"[{now()}] DRY-RUN, not sent -> {chat_id}: {body[:80]}")
            f.rename(C.SENT / f.name); continue
        # TIMING THE SEND is not a luxury. Twice in one day "the assistant is
        # slow" turned out to be a stalled request, and both times the cause
        # was INFERRED rather than seen. Now a slow send leaves a trace, and
        # next time there will be a number here instead of a guess.
        # TELEGRAM REFUSES ANYTHING OVER 4096 CHARACTERS, and the refusal is
        # permanent: the first version left the file in the outbox, so it was
        # retried every second forever, filling the log and blocking whatever
        # queued behind it. A message that cannot be sent as one is split
        # rather than retried, on paragraph boundaries where possible so the
        # break falls where the reader would have paused anyway.
        chunks = split_for_telegram(body)
        if len(chunks) > 1:
            print(f"[{now()}] long message split into {len(chunks)} parts "
                  f"({len(body)} chars)")

        t0 = time.monotonic()
        for i, chunk in enumerate(chunks):
            r = call("sendMessage", chat_id=chat_id, text=chunk,
                     reply_to_message_id=item.get("reply_to") if i == 0 else None)
            if not r.get("ok"):
                break
            if i + 1 < len(chunks):
                time.sleep(0.4)
        spent = time.monotonic() - t0
        if spent > 3.0:
            print(f"[{now()}] SLOW SEND: {spent:.1f}s (threshold 3s)")
        if r.get("ok"):
            # REMEMBER THE NUMBER OF WHAT WE SENT. Without it a later edit has
            # nothing to aim at: the log records incoming messages, and the
            # assistant would be editing by guesswork.
            mid_sent = (r.get("result") or {}).get("message_id")
            item["sent_message_id"] = mid_sent
            item["sent_at"] = now()
            prop = item.get("proposal")
            if prop:
                # Binding the proposal to the MESSAGE ID is mandatory: the
                # mark arrives on a message, not on a file. Without the
                # binding there is nothing to attach the consent to, and
                # "approved in general" is not consent.
                mid = (r.get("result") or {}).get("message_id")
                if mid:
                    born = datetime.now(timezone.utc)
                    C.PROPOSALS.joinpath(f"{chat_id}-{mid}.json").write_text(
                        json.dumps({"chat_id": chat_id, "message_id": mid,
                                    "action": prop.get("action"),
                                    "one_line": prop.get("one_line") or text,
                                    "target_chat": prop.get("target_chat"),
                                    # THE FIELD WAS LOST HERE. The proposal was
                                    # written by a whitelist of fields, and
                                    # "rule" was not on it: the rule reached the
                                    # message and died before reaching the
                                    # decision. The mark was placed, the verdict
                                    # was APPROVED, yet NOTHING reached the
                                    # journal — and silently, because the writing
                                    # branch simply never fired. Found on the
                                    # very first live rule.
                                    "rule": prop.get("rule"),
                                    "batch": prop.get("batch"),
                                    "created": born.isoformat(timespec="seconds"),
                                    "expires": (born + timedelta(
                                        hours=C.PROPOSAL_TTL_HOURS)).isoformat(
                                        timespec="seconds")},
                                   ensure_ascii=False), encoding="utf-8")
                    print(f"[{now()}] proposal pending: {chat_id}-{mid}")
                else:
                    print(f"[{now()}] WARNING: proposal without message_id — no mark can reach it")
            # AN ANSWERED REQUEST LEAVES THE INBOX. Without this, requests/
            # only ever grows and there is no way to see what is still owed —
            # the assistant's own attention becomes the only record of what it
            # has replied to, and attention is exactly what fails when two
            # things arrive at once. It happened: two requests came together,
            # one was answered, the other silently dropped, and the sender had
            # to ask whether he had been heard.
            clear_inbox(item, mark_done=True)
            C.SENT.joinpath(f.name).write_text(
                json.dumps(item, ensure_ascii=False), encoding="utf-8")
            f.unlink(missing_ok=True)
            print(f"[{now()}] sent -> {chat_id} (msg {mid_sent})")
            # A short pause between sends. Telegram tolerates about one
            # message per second to the same chat; a queue of replies would
            # otherwise leave as a burst and earn a 429 for no gain — nobody
            # reads five messages in the same second anyway.
            time.sleep(0.4)
        else:
            print(f"[{now()}] NOT sent: {r.get('description')}")


def main() -> int:
    whoami = "--whoami" in sys.argv
    for d in (C.REQUESTS, C.OUTBOX, C.SENT, C.REMINDERS, C.SENT_REMINDERS,
              C.PROPOSALS, C.DECIDED, C.VOICE, C.SERVED, C.MEDIA,
              C.NEEDS_CONSENT):
        d.mkdir(exist_ok=True)
    if whoami:
        print("Write to the bot now (and in any group you want). Ctrl+C to exit.\n")
    else:
        print(f"Bridge running. DRY_RUN={C.DRY_RUN}, allowed chats: "
              f"{len(C.all_chats())}")
        if C.DRY_RUN:
            print("  DRY_RUN: nothing is sent and no reactions are placed.")
        me = call("getMe")
        _ME[0] = (me.get("result") or {}).get("id") or 0
        print(f"  bot id {_ME[0] or 'UNKNOWN — replies will not count as addressing'}")
        ready = whisper_ready()
        print(f"  voice: {'transcription available' if ready == 'ok' else 'NO transcription — ' + ready}"
              f"  [{C.WHISPER_PYTHON}]")
        if not C.all_chats():
            print("  WARNING: chats.json is empty or missing — everything "
                  "will be ignored. Run ./setup.py")

    # THE OUTBOX IS DRAINED BY A SEPARATE THREAD.
    #
    # flush_outbox() used to be called after getUpdates, which blocks on the
    # long poll for up to POLL_TIMEOUT seconds. So a reply could sit in the
    # queue for a minute, and it looked like the assistant was slow when it
    # was the bridge. Receiving and sending are independent tasks; tying them
    # to one loop was the mistake.
    nonlocal_tick = [0.0, 0.0]
    if not whoami:
        def pump() -> None:
            while True:
                try:
                    flush_outbox()
                except Exception as e:
                    print(f"[{now()}] send failed: {type(e).__name__}: {e}")
                nonlocal_tick[0] += C.OUTBOX_SCAN
                nonlocal_tick[1] += C.OUTBOX_SCAN
                if nonlocal_tick[0] >= C.REMINDER_SCAN:
                    nonlocal_tick[0] = 0.0
                    try:
                        due_reminders()
                    except Exception as e:
                        print(f"[{now()}] reminders failed: {type(e).__name__}: {e}")
                if nonlocal_tick[1] >= C.PROPOSAL_SCAN:
                    nonlocal_tick[1] = 0.0
                    try:
                        sweep_proposals()
                    except Exception as e:
                        print(f"[{now()}] expiry sweep failed: {type(e).__name__}: {e}")
                    # sweep_old_files WAS WRITTEN AND NEVER ONCE CALLED. Its
                    # docstring promised that voice notes do not pile up forever;
                    # the promise held only because the bridge is young and has
                    # not yet lived thirty days. Found 2026-08-22 while building
                    # attachment cleanup — looking for one thing, found the one
                    # next to it.
                    try:
                        nudge_unanswered()
                        sweep_old_files()
                        sweep_media()
                    except Exception as e:
                        print(f"[{now()}] sweep failed: {type(e).__name__}: {e}")
                time.sleep(C.OUTBOX_SCAN)
        threading.Thread(target=pump, daemon=True).start()

    # THE TAMPER GUARD STANDS BEFORE THE FIRST NETWORK CALL AND BEFORE READING
    # THE OFFSET. The bridge tends the consent gate — that is, it decides what
    # counts as permission. Running as who-knows-what code is worse for it than
    # not running at all. A warning here would not do: it is addressed to a
    # reader who may not be there. So a refusal, its own return code, and a
    # durable record.
    if not whoami and not C.DRY_RUN:
        try:
            import drift
            ok, detail = drift.check()
            if not ok:
                with drift.REFUSALS.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(detail, ensure_ascii=False) + "\n")
                print(f"[{now()}] REFUSED ON TAMPER: {detail.get('reason')} — "
                      f"not starting up. Details in {drift.REFUSALS.name}; "
                      f"if the state is correct, approve: ./drift.py --approve")
                return drift.EXIT_DRIFT
            print(f"  no tampering: {detail['files']} files match")
        except Exception as e:
            # A broken guard is also a refusal. A guard that lets things through
            # when it breaks only guards in fair weather.
            print(f"[{now()}] TAMPER GUARD BROKEN: {type(e).__name__}: {e} — "
                  f"not starting up")
            return 91

    offset = int(C.OFFSET.read_text()) if C.OFFSET.exists() else 0
    while True:
        r = call("getUpdates", _timeout=C.POLL_TIMEOUT + 15, offset=offset,
                 timeout=C.POLL_TIMEOUT,
                 allowed_updates=["message", "channel_post", "message_reaction"])
        if not r.get("ok"):
            print(f"[{now()}] getUpdates: {r.get('description')}")
            time.sleep(5); continue
        for upd in r.get("result", []):
            offset = upd["update_id"] + 1
            if "message_reaction" in upd:
                try:
                    handle_reaction(upd["message_reaction"])
                except Exception as e:
                    print(f"[{now()}] reaction failed: {type(e).__name__}: {e}")
                continue
            try:
                handle(upd, whoami)
            except Exception as e:            # one bad message must not kill the bridge
                print(f"[{now()}] update {upd.get('update_id')} failed: "
                      f"{type(e).__name__}: {e}")
        C.OFFSET.write_text(str(offset))
        time.sleep(0.2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
