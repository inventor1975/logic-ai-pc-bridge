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
import re
import shutil
import subprocess
import threading
import sys
import time
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
    with C.LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def announce(chat_id: int) -> None:
    """Уведомление о записи — один раз на чат, ДО того как из него что-то ляжет
    на диск.

    КЛЮЧ — НЕ КОМНАТА, А КОМНАТА ПЛЮС ОТПЕЧАТОК ТЕКСТА. Первая версия помнила
    только номер чата, поэтому изменившееся уведомление никогда бы не дошло до
    тех, кому уже что-то сказали: программа собирает больше, а люди знают по
    старому. Отпечаток в ключе означает, что расширение сбора само поднимает
    новое уведомление.
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


def rule_for(chat_id: int, path: Path,
             rules: list | None = None) -> dict[str, Any] | None:
    """Какое стоячее правило покрывает отправку ЭТОГО файла в ЭТУ комнату.

    По умолчанию не покрывает ничего: пустой журнал значит «спрашивай всё».
    Разрешение только ДОБАВЛЯЕТСЯ явной записью и никогда не выводится.

    ДВА УРОВНЯ ПРЕДМЕТА, по слову куратора («оговорили конкретные, и только
    тогда можно, всё по полному пути; и папки так же»):

        paths  точные полные пути — разрешён ИМЕННО ЭТОТ файл и никакой другой
        dirs   папка целиком, с образцом имени внутри неё

    Точный путь строже и потому идёт первым: там, где перечислены конкретные
    файлы, новый файл в той же папке НЕ разрешён, пока его не назвали.

    КОМНАТЫ ПЕРЕЧИСЛЯЮТСЯ. Правило может назвать несколько, но не может сказать
    «любая»: такого поля нет. Комната, о которой не подумали, не попадёт в
    правило никогда — не по бдительности, а по устройству формата.

    `project` — ЯРЛЫК для чтения журнала человеком. Он НИКОГДА не проверяется:
    ярлык может сползти, путь не может. Проверка по ярлыку означала бы, что
    достаточно назвать чужую папку правильным словом.
    """
    rules = C.file_rules() if rules is None else rules
    try:
        real = path.resolve()
    except OSError:
        return None
    nowts = datetime.now(timezone.utc)
    for r in rules:
        rooms = r.get("chats") or ([r["chat_id"]] if r.get("chat_id") else [])
        if chat_id not in rooms:
            continue
        # Правило без следа одобрения — не правило. Куратор ставит метку, мост
        # вписывает его номер; запись без номера могла появиться только мимо
        # ворот, и доверять ей нельзя.
        if not r.get("added_by_user_id"):
            print(f"[{now()}] ПРАВИЛО БЕЗ ОДОБРЯЮЩЕГО, пропущено: {r.get('id')}")
            continue
        exp = r.get("expires_at")
        if exp:
            try:
                if datetime.fromisoformat(exp) <= nowts:
                    continue
            except ValueError:
                continue        # нечитаемый срок — НЕ в пользу отправки

        for pth in (r.get("paths") or []):
            try:
                if Path(pth).expanduser().resolve() == real:
                    return r
            except OSError:
                continue

        dirs = r.get("dirs")
        if dirs is None and r.get("dir"):      # форма v1.4, поддерживается
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
    """Разовое разрешение на ЭТОТ файл в ЭТУ комнату, ещё не потраченное.

    Привязка по ОТПЕЧАТКУ, а не по имени: одобрено то, что человек видел в
    предложении. Подменили содержимое после метки — отпечаток разошёлся, и
    разрешение не сработает. Имя тут для чтения, отпечаток для дела.
    """
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    for g in C.grants():
        if g.get("used_at"):
            continue
        if not g.get("added_by_user_id"):
            print(f"[{now()}] РАЗРЕШЕНИЕ БЕЗ ОДОБРЯЮЩЕГО, пропущено: {g.get('id')}")
            continue
        if g.get("chat_id") == chat_id and g.get("sha256") == digest:
            return g
    return None


def spend_grant(gid: str) -> None:
    """Потратить разрешение. Разовое значит разовое."""
    gs = C.grants()
    for g in gs:
        if g.get("id") == gid and not g.get("used_at"):
            g["used_at"] = now()
            C.GRANTS.write_text(json.dumps(gs, ensure_ascii=False, indent=1),
                                encoding="utf-8")
            return


def send_file(chat_id: int, path: Path, caption: str = "",
              as_photo: bool = False) -> dict[str, Any]:
    """Отправить файл в чат. Своя сборка multipart, без сторонних библиотек.

    ПОЧЕМУ ОТДЕЛЬНАЯ ФУНКЦИЯ, А НЕ ПАРАМЕТР К `call`. Обычный вызов кодирует
    поля как urlencoded; файл так не передать. Это не «ещё один метод», это
    другой способ говорить с тем же API, и смешивать их в одной функции значит
    прятать различие, которое потом кого-нибудь укусит.

    Подпись обрезается до 1024 знаков — столько разрешает Bot API. Обрезаем
    ЗАРАНЕЕ и говорим об этом, иначе сервер откажет целиком и файл не уйдёт
    из-за лишней строки текста.
    """
    if not path.exists():
        return {"ok": False, "description": f"нет такого файла: {path}"}
    method = "sendPhoto" if as_photo else "sendDocument"
    field = "photo" if as_photo else "document"
    if len(caption) > 1024:
        print(f"[{now()}] caption {len(caption)} > 1024, обрезана")
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
    # ИМЯ ФАЙЛА ИДЁТ В ЗАГОЛОВОК, ЗНАЧИТ ЕГО НАДО ОБЕЗЗАРАЗИТЬ. Кавычка или
    # перевод строки в имени — это не косметика: заголовок закрывается раньше
    # времени, и дальше в него можно дописать что угодно. Имя файла приходит из
    # разрешённой папки, но кто кладёт туда файлы, тот и выбирает им имена.
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

    ПОТОЛОК ПРОВЕРЯЕТСЯ ЗДЕСЬ, А НЕ ТОЛЬКО У ЗВОНЯЩЕГО. Первая версия смотрела
    на `file_size` из обновления и читала ответ целиком одним `read()`. Две дыры
    в одной строке: поля `file_size` в обновлении может НЕ БЫТЬ вовсе — тогда
    проверка молча не срабатывала, — а `read()` без предела читает столько,
    сколько дадут. Обещание «двадцать мегабайт» держалось на честном слове
    отправителя.

    Теперь: спрашиваем размер у самого API, читаем КУСКАМИ и обрываем на
    превышении, а недокачанное удаляем — половина файла хуже, чем ничего,
    потому что выглядит как файл.
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
        print(f"[{now()}] отказ по размеру: API говорит {told} > {cap}")
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
                    print(f"[{now()}] ОБРЫВ: поток превысил {cap} байт "
                          f"(API обещал {told}) — недокачанное удалено")
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
    rec["from_principal"] = frm.get("id") == pol["principal"]
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
        json.dumps({**rec, "request_id": rid}, ensure_ascii=False, indent=2),
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
        what = ", ".join(f"{g['name']} ({g.get('bytes', 0) // 1024} КБ)"
                         if "path" in g else f"{g.get('name')} — {g['refused']}"
                         for g in got) or "вложение"
        text = f"[вложение: {what}]"
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
        threading.Thread(target=voice_job, args=(chat_id, msg, rec, media),
                         daemon=True).start()
        return

    # ВЛОЖЕНИЕ БЕЗ ПОДПИСИ ПРИХОДИЛО ПУСТЫМ ЗАПРОСОМ — и один раз это уже
    # стоило потерянной картинки: 2026-08-21 снимок от третьего лица лёг в
    # ящик как пустота и был закрыт как «отвечать нечего». Мост читал только
    # text и caption; всё остальное для него не существовало.
    att = attachments_of(msg)
    if att:
        threading.Thread(target=file_job, args=(chat_id, msg, rec, att, text),
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
                        "ask": f"реакция {' '.join(emoji)} на моё сообщение",
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
    """
    prop["verdict"] = verdict
    prop["decided_at"] = now()
    prop["decided_by_user_id"] = uid
    prop["decision_reaction"] = emoji
    prop["decision_event_at"] = now()
    prop["proposal_message_id"] = prop.get("message_id")
    prop["proposal_chat_id"] = prop.get("chat_id")
    # СТОЯЧЕЕ ПРАВИЛО РОЖДАЕТСЯ ЗДЕСЬ И БОЛЬШЕ НИГДЕ. Предложение может нести
    # правило; в журнал оно попадает только вместе с числовым идентификатором
    # того, кто поставил метку, самой меткой и номером предложения. Ассистент
    # правило ПРЕДЛАГАЕТ и никогда не вписывает — тот же запрет, что
    # в институциональных допусках: ограничиваемая сторона не изготавливает объект,
    # который её ограничивает.
    # ПАЧКА. Одна метка — одна ПОСЫЛКА в ОДНУ комнату, и каждый файл в ней
    # назван отпечатком. Это не «список дел под одной галочкой»: пять файлов
    # одной посылки — одно дело с пятью частями, а пять разных дел так
    # объединять по-прежнему нельзя.
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
            C.GRANTS.write_text(json.dumps(gs, ensure_ascii=False, indent=1),
                                encoding="utf-8")
            print(f"[{now()}] ПАЧКА РАЗРЕШЕНА: {len(prop['batch']['files'])} "
                  f"файлов -> {prop['batch']['chat_id']} (метка {uid})")
        except Exception as e:
            print(f"[{now()}] пачка НЕ записана: {type(e).__name__}: {e}")

    if verdict == "APPROVED" and prop.get("rule") and uid:
        try:
            rules = C.file_rules()
            rule = dict(prop["rule"])
            rule.update({"id": f"R{len(rules) + 1:03d}",
                         "added_at": now(), "added_by_user_id": uid,
                         "decision_reaction": emoji,
                         "proposal_message_id": prop.get("message_id")})
            rules.append(rule)
            C.RULES.write_text(json.dumps(rules, ensure_ascii=False, indent=1),
                               encoding="utf-8")
            where = ", ".join(str(d.get("dir")) for d in (rule.get("dirs") or [])) \
                or ", ".join(rule.get("paths") or []) or rule.get("dir") or "?"
            rooms = rule.get("chats") or [rule.get("chat_id")]
            print(f"[{now()}] ПРАВИЛО ДОБАВЛЕНО {rule['id']} "
                  f"«{rule.get('project') or '—'}»: {where} -> {rooms} "
                  f"(метка {uid})")
        except Exception as e:
            print(f"[{now()}] правило НЕ записано: {type(e).__name__}: {e}")

    C.DECIDED.joinpath(pf.name).write_text(
        json.dumps(prop, ensure_ascii=False), encoding="utf-8")
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
    """Did the principal REACT to this exact message? Any emoji counts.

    To place a reaction you must have opened the message, so a reaction — 👍
    or anything else — proves it was seen. That is the whole ack signal an
    escalating reminder waits for.
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
                and rec.get("emoji"):
            return True
    return False


def control_question() -> str | None:
    """Каждое SELFCHECK_EVERY-е обращение принципала — вернуть текст контрольного
    вопроса (present), иначе None. Считает по файлу-счётчику. Полностью
    защищено: любая осечка -> None, доставка сообщения не страдает."""
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
            give_up = (f"{C.REPLY_PREFIX} reminder (сдаюсь после {tries} попыток, "
                       f"ты, похоже, не увидел): {r['text']}")
            if not C.DRY_RUN:
                call("sendMessage", chat_id=r["chat_id"], text=give_up)
            print(f"[{now()}] reminder CAPPED unacked -> {r['chat_id']}: {r['text'][:40]}")
            retire(f, "capped-unacked")
            continue

        again = "  (напоминаю ещё раз — лайкни, если увидел)" if tries else ""
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
    """Сказать человеку, что его сообщение приняли, но НИКТО НЕ ВЗЯЛ.

    Значок 👀 значит «сохранено, и будет отвечено». Это обещание. Если
    ассистент не запущен, обещание некому исполнить, а человек об этом не
    узнает: снаружи «его читают» и «его забыли» выглядят одинаково.

    Поэтому мост, единственный, кто тут точно жив, говорит сам. ОДИН раз на
    сообщение — иначе напоминание превращается в трезвон и его отключат.
    """
    cutoff = time.time() - C.NUDGE_AFTER_MIN * 60
    for f in sorted(C.REQUESTS.glob("*.json")):
        if f.name.startswith(("verdict-", "needsfile-", "reaction-", "control-")):
            continue                       # это мои же записки, не его ожидание
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
        text = (f"{C.REPLY_PREFIX} принято и лежит в ящике, но за {mins} мин "
                f"никто не взял в работу. Значок 👀 обещал ответ — обещание "
                f"пока не исполнено. Сообщение не потеряно.")
        if C.DRY_RUN or call("sendMessage", chat_id=chat_id, text=text,
                             reply_to_message_id=mid).get("ok"):
            r["nudged"] = now()
            f.write_text(json.dumps(r, ensure_ascii=False, indent=2),
                         encoding="utf-8")
            print(f"[{now()}] НЕКОМУ ВЗЯТЬ: {f.stem}, {mins} мин, сказано в чат")


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
    """Вложения убираются по ПЕРЕПОЛНЕНИЮ, а не по сроку.

    Слово куратора: файл, присланный полгода назад, может быть нужен, а сорок
    сегодняшних — нет. Возраст не знает, что важно; объём хотя бы честен.

    Три правила, и второе — самое важное:

    1. Удаляется КАТАЛОГ запроса целиком. Вложения одного сообщения — это одна
       вещь; выбросить половину значит оставить непонятное.
    2. **Каталог запроса, на который ещё НЕ ОТВЕЧЕНО, не трогается никогда.**
       Иначе уборка съест ровно то, что лежит и ждёт меня, и ящик покажет
       ссылку в пустоту.
    3. Каждое удаление печатается с размером. Молчаливая уборка неотличима от
       пропажи, а пропажу потом объясняют чем угодно.

    Возвращает список убранного — чтобы вызывающий мог не гадать.
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
    items.sort(key=lambda x: x[0])            # старое первым
    removed: list[str] = []
    for _, size, d in items:
        if total <= budget:
            break
        if d.name in pending:
            continue                          # ждёт ответа — не трогаем
        shutil.rmtree(d, ignore_errors=True)
        total -= size
        removed.append(d.name)
        print(f"[{now()}] media sweep: убрано {d.name}, {size} байт, "
              f"осталось {total} из {budget}")
    if total > budget:
        # Сказать вслух, а не тихо смириться: место кончилось, а убрать нечего,
        # потому что всё оставшееся ждёт ответа. Это про меня, не про диск.
        print(f"[{now()}] media sweep: всё ещё {total} > {budget}, "
              f"остальное ждёт ответа — разберите ящик")
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
        if req.exists():
            req.rename(C.SERVED / req.name)
        if not mark_done:
            continue
        try:
            # SPLIT FROM THE LEFT. A group's chat id is NEGATIVE, so the
            # request id reads "284--5101395964" — and splitting from the
            # right cut it at the id's own minus sign, giving message id
            # "284-", which is not a number. The failure was caught and
            # swallowed, so in groups the eyes simply never came off and
            # nothing said why.
            #
            # The message id is always a positive integer and always first,
            # so the first hyphen is the only safe boundary. Ids that begin
            # with a word — verdict-..., reaction-... — still fail int() and
            # are skipped, which is what they should do.
            mid, chat = rid.split("-", 1)
            done = item.get("done_emoji") or "👍"
            how = ack(int(chat), int(mid), done)
            # LOGGED, because an action nobody can see is an action nobody can
            # check. This one was placed correctly and left no trace, so the
            # only way to know it had happened was to go and look at the phone.
            print(f"[{now()}] done {done} -> {chat}/{mid}: {how}")
        except (ValueError, KeyError):
            pass                      # ids like "verdict-..." carry no message


def outgoing_prefix(pol: dict[str, Any], item: dict[str, Any]) -> str:
    """Which signature this message carries.

    ПУСТАЯ ПОДПИСЬ — ЭТО ВЫБОР, А НЕ ПРОПУСК. `or` would silently restore the
    name: "" is falsy in Python, so a chat configured to speak without a
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
            print(f"[{now()}] malformed outbox file {f.name}: {e}")
            continue
        chat_id, text = item.get("chat_id"), (item.get("text") or "").strip()
        if not C.allowed(chat_id):
            print(f"[{now()}] REFUSED: outbox {f.name} targets a chat not allowed")
            continue
        # ФАЙЛ В ОЧЕРЕДИ. Просили — «вышли файл сюда в чат»; до v1.3.0 мост
        # умел только текст, и это был честный отказ, а не оплошность: файлы
        # он ПРИНИМАЛ с v1.1.0, но не отдавал. Теперь оба направления.
        if item.get("file"):
            fp = Path(item["file"])
            # ВОРОТА НА ФАЙЛ. Отправка файла — не письмо: он уходит целиком,
            # его нельзя дописать вдогонку, и ошибиться комнатой тут дороже.
            # Поэтому спрашивается всё, чего не покрывает стоячее правило.
            rule = rule_for(chat_id, fp)
            grant = None if rule else grant_for(chat_id, fp)
            if rule is None and grant is None:
                print(f"[{now()}] ФАЙЛ НЕ ОТПРАВЛЕН: {fp.name} -> {chat_id} "
                      f"не покрыт ни одним правилом — нужно предложение")
                # ВОН ИЗ ОЧЕРЕДИ, А НЕ ПЕРЕИМЕНОВАТЬ НА МЕСТЕ. Первая
                # версия оставляла отказанный файл в outbox под новым именем —
                # и следующий обход переименовывал его снова, и снова, растя
                # приставку и пытаясь отправить вечно. Ровно та же яма, что уже
                # описана выше для сообщений длиннее 4096 знаков; я в неё сходил
                # второй раз, в том же файле, в тот же день.
                C.NEEDS_CONSENT.mkdir(exist_ok=True)
                dest = C.NEEDS_CONSENT / f.name
                f.rename(dest)
                # И СКАЗАТЬ МНЕ, А НЕ ПОЛОЖИТЬ МОЛЧА. Первая версия просто
                # убирала файл в сторону: ни строки в ящик, ни пути обратно.
                # Получался тупик, построенный ради безопасности, — а тупик,
                # о котором никто не знает, неотличим от потери.
                rid = f"needsfile-{dest.stem}"
                C.REQUESTS.joinpath(f"{rid}.json").write_text(json.dumps({
                    "at": now(), "chat_id": chat_id, "from": "GATE",
                    "from_id": None, "message_id": None,
                    "text": f"файл ждёт решения: {fp}",
                    "ask": (f"ФАЙЛ НЕ ОТПРАВЛЕН — нет правила.\n"
                            f"    файл:  {fp}\n"
                            f"    куда:  {chat_id}\n"
                            f"Повесить на метку одной командой:\n"
                            f"    ./propose.py --batch '{fp}' --to {chat_id} "
                            f"--why '<зачем>'"),
                    "needs_consent_file": str(dest), "path": str(fp),
                    "target_chat": chat_id, "context": []},
                    ensure_ascii=False), encoding="utf-8")
                continue
            r = send_file(chat_id, fp, item.get("text", "")[:1024],
                          as_photo=bool(item.get("as_photo")))
            if r.get("ok"):
                # ЖУРНАЛ ОТПРАВЛЕННОГО ПО ПРАВИЛУ. Правило снимает вопрос
                # ЗАРАНЕЕ, значит проверка остаётся только ПОСЛЕ — и она
                # обязана быть, иначе стоячее разрешение становится слепой
                # зоной. Одна строка на отправку, с номером правила.
                who = (rule or grant).get("id")
                kind = "правилу" if rule else "разрешению"
                if grant:
                    spend_grant(who)
                with C.ROOT.joinpath("sent_by_rule.log").open(
                        "a", encoding="utf-8") as lg:
                    lg.write(f"{now()}\t{who}\t{chat_id}\t"
                             f"{fp}\t{fp.stat().st_size}\n")
                print(f"[{now()}] файл отправлен по {kind} "
                      f"{who} -> {chat_id}: {fp.name}, "
                      f"{fp.stat().st_size} байт")
                item["sent_at"] = now()
                f.rename(C.SENT / f.name)
            else:
                print(f"[{now()}] файл НЕ отправлен: {r.get('description')}")
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
                                    # ПОЛЕ ТЕРЯЛОСЬ ЗДЕСЬ. Предложение писалось
                                    # по белому списку полей, и "rule" в него не
                                    # входило: правило доезжало до сообщения и
                                    # умирало, не доходя до решения. Метка
                                    # ставилась, вердикт был APPROVED, а в журнал
                                    # не попадало НИЧЕГО — и молча, потому что
                                    # ветка записи просто не срабатывала.
                                    # Найдено на первом же живом правиле.
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
                    # sweep_old_files БЫЛ НАПИСАН И НИ РАЗУ НЕ ВЫЗВАН. Его
                    # докстрока обещала, что голос не копится вечно; обещание
                    # держалось только тем, что мост молод и тридцати дней ещё
                    # не прожил. Найдено 2026-08-22 при постройке уборки
                    # вложений — искали одно, нашли соседнее.
                    try:
                        nudge_unanswered()
                        sweep_old_files()
                        sweep_media()
                    except Exception as e:
                        print(f"[{now()}] sweep failed: {type(e).__name__}: {e}")
                time.sleep(C.OUTBOX_SCAN)
        threading.Thread(target=pump, daemon=True).start()

    # СТОРОЖ ПОДМЕНЫ СТОИТ ДО ПЕРВОГО СЕТЕВОГО ВЫЗОВА И ДО ЧТЕНИЯ СМЕЩЕНИЯ.
    # Мост обслуживает ворота согласия — то есть решает, что считать
    # разрешением. Работать неизвестно каким кодом ему хуже, чем не работать.
    # Предупреждение здесь не годится: оно адресовано читателю, которого может
    # не быть. Поэтому отказ, свой код возврата и durable-запись.
    if not whoami and not C.DRY_RUN:
        try:
            import drift
            ok, detail = drift.check()
            if not ok:
                with drift.REFUSALS.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(detail, ensure_ascii=False) + "\n")
                print(f"[{now()}] ОТКАЗ ПО ПОДМЕНЕ: {detail.get('reason')} — "
                      f"не поднимаюсь. Подробности в {drift.REFUSALS.name}; "
                      f"если состояние верное, одобрить: ./drift.py --approve")
                return drift.EXIT_DRIFT
            print(f"  подмены нет: {detail['files']} файлов сходятся")
        except Exception as e:
            # Сломанный сторож — тоже отказ. Сторож, который при собственной
            # поломке пропускает, охраняет только в хорошую погоду.
            print(f"[{now()}] СТОРОЖ ПОДМЕНЫ СЛОМАН: {type(e).__name__}: {e} — "
                  f"не поднимаюсь")
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
