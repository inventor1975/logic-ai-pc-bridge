# -*- coding: utf-8 -*-
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Telegram bridge — settings. Edited by hand; no code writes here."""
import json
import os
from pathlib import Path

# --------------------------------------------------------------------------
# TOKEN
# --------------------------------------------------------------------------
# Read from token.txt next to this file, or from the environment if that
# variable is set — the environment wins.
#
# A file is the default because a systemd user service starts before anyone
# logs in and therefore has no environment to read. The file is in .gitignore
# and should never leave this machine: the token is full control of the bot,
# and after a leak the only remedy is to revoke it in BotFather and issue a
# new one.
_TOKEN_FILE = Path(__file__).resolve().parent / "token.txt"
if _TOKEN_FILE.exists():
    # The token is full control of the bot. A file the whole group can read is
    # not a secret, and the default umask on many systems makes exactly that.
    # Tightened here rather than in setup only, because a file restored from a
    # backup or copied by hand never went through setup.
    try:
        import stat as _stat
        if _TOKEN_FILE.stat().st_mode & (_stat.S_IRWXG | _stat.S_IRWXO):
            _TOKEN_FILE.chmod(0o600)
    except OSError:
        pass                      # Windows has no POSIX modes
TOKEN = os.environ.get("BRIDGE_BOT_TOKEN") or (
    _TOKEN_FILE.read_text(encoding="utf-8").strip() if _TOKEN_FILE.exists() else ""
)

# --------------------------------------------------------------------------
# SETTINGS THAT DIFFER PER INSTALLATION — settings.json, written by ./setup.py
# --------------------------------------------------------------------------
# Nothing personal lives in the code. The name, the operator, the trigger
# words and the dry-run flag all belong to one installation, not to the tool,
# so they sit in a gitignored file next to it. Editing them must never mean
# editing Python.
_SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"


def _settings() -> dict:
    try:
        import json as _j
        return _j.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


_S = _settings()

# WHILE True, THE BRIDGE SENDS NOTHING.
# It reads, filters, writes the log and the requests — but no reactions and no
# replies. Use it to watch the bridge's behaviour before it speaks in your
# name. TRUE BY DEFAULT: a fresh, unconfigured install must be mute.
DRY_RUN = bool(_S.get("dry_run", True))

# --------------------------------------------------------------------------
# THE NAME
# --------------------------------------------------------------------------
# The assistant is addressed by NAME, and only at the START of a message.
# "Logic, take a look" is addressed to it; "logically speaking" is not.
# Matching anywhere in the message produced constant false positives.
#
# Case is ignored. Whatever follows the name and its punctuation is the
# question itself.
#
# List longer forms first — the matcher tries them in order, so a longer name
# must not be shadowed by a shorter one that is its prefix.
BOT_NAME = _S.get("bot_name", "Logic")
TRIGGERS = tuple(_S.get("triggers") or (BOT_NAME.lower(),))

# Whose assistant this is belongs in the signature, not in a footnote. In a
# shared chat every reply must say who is speaking and on whose behalf:
# "Logic AI(Ada):". Disclosure must not depend on the other person
# remembering which participant is a bot.
OPERATOR = _S.get("operator", "the operator")

# --------------------------------------------------------------------------
# VOICE
# --------------------------------------------------------------------------
# Optional. If faster-whisper is importable the bridge transcribes voice notes
# and treats the transcript as the message; if it is not, the audio is saved
# and the sender is told plainly that it cannot be read. The base install
# stays dependency-free — an optional feature must not turn into a required
# one by silently failing.
#
# Before this existed a voice note was INVISIBLE: the bridge read msg.text,
# a voice note has none, so no name matched, no mark appeared and no request
# was written. Someone could dictate something that mattered, see "delivered",
# and never get an answer. Silent loss, the same class of fault as placing the
# mark before the write.
# WHICH INTERPRETER DOES THE TRANSCRIBING. Not a detail — this one bit us.
# The bridge runs under whatever python the service names (often
# /usr/bin/python3), while faster-whisper is commonly installed in a virtual
# environment for machine-learning work. Measuring the import from a shell
# says nothing about the daemon: different interpreter, different packages.
#
# So transcription runs as a SUBPROCESS under a named interpreter. The bridge
# itself stays dependency-free, the model never occupies the daemon's memory,
# and pointing at another environment costs one line of settings.json instead
# of reinstalling anything.
import sys as _sys
WHISPER_PYTHON = _S.get("whisper_python") or _sys.executable
WHISPER_MODEL = _S.get("whisper_model", "small")   # tiny/base/small/medium/large-v3
WHISPER_DEVICE = _S.get("whisper_device", "cpu")   # a daemon should not squat on the GPU
VOICE_LANG = _S.get("voice_lang") or None          # None = autodetect

# In the principal's own private chat a voice note is ALWAYS an address: they
# would not dictate at the bridge otherwise, and a transcript spells a name
# however it pleases — relying on it would drop real messages. In a group the
# name must appear in the transcript like any other address.
VOICE_IS_ADDRESS_IN_PRIVATE = bool(_S.get("voice_is_address_in_private", True))

# "Heard you, transcribing" — honest at that moment, and different from the
# mark that means "stored, will be answered".
HEARD_EMOJI = "🤔"

# --------------------------------------------------------------------------
# PER-CHAT BOUNDARIES. Why they are shaped this way: PROTOCOL.md.
# This file only says what they are.
#
# The gate stands on the ACTION, not on the SENDER. Anyone in an allowed chat
# may talk to the assistant; an action with consequences OUTSIDE the chat
# happens only on the principal's mark — no matter who asked, a guest AI or a
# guest human. The right to direct is not conferred by the sender being human:
# that is the provenance of the message, not the authority to issue it.
# --------------------------------------------------------------------------
CHAT_DEFAULTS = {
    "principal": None,         # whose word is itself an order; set in chats.json
    "approvers": [],           # whose marks count as consent
                               # EMPTY BY DEFAULT: no approver named means no
                               # one can approve. Refusal-by-default has to
                               # hold even when the file is misconfigured.
    "may_address": "all",      # "all" or a list of user ids
    # In a one-to-one chat with the bot there is nobody else to be talking to:
    # every message is addressed to it, and demanding the name on top of that
    # is friction with nothing on the other side of it. The name exists to
    # single the assistant out of a room, so it belongs in rooms.
    "all_addressed": False,
    "topic": "not declared",   # the subject of this chat; the assistant stays inside it
    "outward_gate": True,      # actions outside the chat need a mark
    "announce": True,          # one-time notice that the chat is logged
}
CHATS_FILE = Path(__file__).resolve().parent / "chats.json"


def _chats() -> dict:
    """Contents of chats.json.

    Read EVERY TIME rather than at startup: changing a boundary must not cost
    a restart of the bridge, or the change gets postponed.
    """
    try:
        import json as _j
        raw = _j.loads(CHATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k: v for k, v in raw.items() if k.lstrip("-").isdigit()}


def allowed(chat_id: int) -> bool:
    """Is this chat allowed?

    Everything else is ignored and NEVER WRITTEN TO THE LOG at all — the
    filter sits BEFORE the write to disk, not after it.
    """
    return str(chat_id) in _chats()


def all_chats() -> list[int]:
    return [int(k) for k in _chats()]


def approvers(chat_id: int) -> list[int]:
    return policy(chat_id)["approvers"]


def policy(chat_id: int) -> dict:
    """This chat's boundaries: defaults, overridden by chats.json."""
    p = dict(CHAT_DEFAULTS)
    p.update(_chats().get(str(chat_id), {}))
    return p


# Every reply goes out with this. The whole string is a setting, not just the
# two names inside it: "AI" is an English word, and an installation working in
# another language needs its own — otherwise disclosure reads as foreign
# boilerplate exactly where it must read as plain speech.
REPLY_PREFIX = _S.get("reply_prefix") or f"{BOT_NAME} AI({OPERATOR}):"

# WHEN THE ASSISTANT CARRIES SOMEONE ELSE'S WORDS, THE SIGNATURE MUST SAY SO.
# Two different acts hide under one bot account: speaking for itself, and
# relaying a human's approved words in another language. In a room whose whole
# subject is who asserts what and on what basis, collapsing them would make
# every claim ambiguous — the reader could not tell an opinion of the tool
# from a statement of the person.
#
# So a relayed message is signed with the human's name and states that it is a
# translation; only the assistant's own speech carries the assistant's prefix.
# A MESSAGE MEANT TO BE COPIED OUT CARRIES THE LANGUAGE OF WHERE IT IS GOING,
# not the language of this chat. The Cyrillic signature travels with the text
# into an English room and lands exactly where the reader is working out who is
# speaking — which is the worst place to put a stumble.
COPY_PREFIX = _S.get("copy_prefix") or f"{BOT_NAME} AI({OPERATOR}) — ready to send:"

RELAY_PREFIX = _S.get("relay_prefix") or (
    f"{OPERATOR} (written in Russian, translated by {BOT_NAME}, "
    f"his AI assistant; approved by {OPERATOR} before sending):")

# THE "RECOGNISED" MARK. Placed by the BRIDGE, instantly, without waking the
# assistant.
#
# The first version had the assistant place it, meaning "I have taken this up".
# That failed a simple question: why wake the assistant to place an icon? If
# the reply arrives within seconds, "taken up" and the reply collapse into one
# another and the icon adds nothing. Worse, an icon that waits for the
# assistant to wake arrives late — exactly when it was meant to say "now".
#
# There is also a fact Telegram's own delivery tick cannot carry: the tick
# appears on ANY message, including "this one is not for you". The mark appears
# only once a message has been recognised as addressed and queued. Write
# "logically speaking..." and no mark appears — visible at a glance.
#
# That fact needs no judgement, so there is nobody to wake.
#
# A bee is impossible: Telegram allows a fixed set of reactions and 🐝 is not
# in it — measured, REACTION_INVALID. Allowed and apt: 🤔 (thinking),
# 👀 (seen), ✍ (writing), 🫡 (acknowledged).
ACK_EMOJI = "👀"

# THE FIXED SET Telegram accepts as a reaction. Anything outside it makes
# setMessageReaction fail, and the old fallback then SHOUTED the emoji as a
# message — measured 2026-08-22: ✅ is NOT here, so twenty "✅" messages went
# out and not one 👀 changed. A done-mark must be chosen from THIS set (👍 is
# the safe default); ✅ ❌ 🟢 ✔️ and most others are not reactions.
# Контрольные вопросы против потери контекста ассистента: каждое N-е адресованное
# сообщение принципала мост запускает selfcheck present ОТДЕЛЬНЫМ процессом (не
# тащит ztl.py в себя) и кладёт вопрос+раскрытие в заметку заявки. Судья — код.
# Упало/таймаут — молча пропускаем: контрольный вопрос НИКОГДА не роняет доставку.
SELFCHECK_EVERY = 5
SELFCHECK_PRESENT = ["python3",
    "/media/vitaly/SSD_1000GB/Projects/SelfCheck/selfcheck.py", "present"]
VALID_REACTIONS = frozenset(
    "👍 👎 ❤ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 👌 🕊 🤡 🥱 🥴 😍 🐳 "
    "🌚 🌭 💯 🤣 ⚡ 🍌 🏆 💔 🤨 😐 🍓 🍾 💋 🖕 😈 😴 😭 🤓 👻 👀 🎃 🙈 😇 😨 "
    "🤝 ✍ 🤗 🫡 🎅 🎄 ☃ 💅 🤪 🗿 🆒 💘 🙉 🦄 😘 💊 🙊 😎 👾 😡".split())

# A SUBSTANTIVE REPLY MUST END BY SAYING WHETHER IT NEEDS THE READER TO ACT.
#
# The operator asked for this and the reason is worth keeping: a long answer
# without it forces him to re-read the whole thing to work out whether he is
# on the hook. The marker is a JUDGEMENT — what, exactly, is still owed by
# whom — so the bridge does NOT append it. It only says loudly when it is
# missing, because a marker written by the machine would say nothing and would
# stop the assistant from thinking about the question.
NEEDS_MARKER = ("ТРЕБУЕТ ДЕЙСТВИЯ", "НЕ ТРЕБУЕТ ДЕЙСТВИЯ",
                "ACTION NEEDED", "NO ACTION NEEDED")
MARKER_MIN_CHARS = 200   # short acknowledgements are exempt

# --------------------------------------------------------------------------
# PRIVACY NOTICE
# --------------------------------------------------------------------------
# Sent ONCE per chat, on the first message from it. The reason: the bot sees
# and logs EVERY message in an allowed chat, not only the ones addressed to it
# — context is what makes the answers worth anything. Someone who was not told
# this is entitled to assume that only messages addressed to the bot are kept.
#
# Edit the wording to name your own operator. Do not remove it.
# ЧТО ЛЮДЯМ ГОВОРИТСЯ ПРИ ПЕРВОМ ЖЕ СООБЩЕНИИ. Текст перечисляет то, что
# ДЕЙСТВИТЕЛЬНО собирается, а не то, что собиралось когда-то. С версии 1.1.0
# мост скачивает и хранит ВЛОЖЕНИЯ — картинки, документы, голос, — а
# объявление всё ещё говорило только про переписку. Уведомление, отставшее от
# программы, хуже отсутствующего: оно выглядит как обещание.
def announce_text(chat_id: int) -> str:
    signed = ("Мои ответы помечены «{name} ИИ({op}):», так что всегда видно, "
              "кто говорит. ".format(name=BOT_NAME, op=OPERATOR)
              if policy(chat_id).get("reply_prefix", REPLY_PREFIX) else "")
    return (
        "Я {name}, ИИ-помощник на стороне {op}.\n\n"
        "Чтобы обратиться ко мне, начните сообщение со слова «{name}». {signed}\n\n"
        "Что нужно знать сразу. ВСЯ ЭТА ПЕРЕПИСКА ПИШЕТСЯ В ФАЙЛ на машине {op} "
        "— не только обращённое ко мне, а всё, потому что без предыдущего я "
        "отвечаю плохо. КРОМЕ ТЕКСТА СОХРАНЯЮТСЯ ВЛОЖЕНИЯ: присланные картинки, "
        "документы и голосовые скачиваются и лежат на том же диске; голос ещё и "
        "расшифровывается в текст. Ничего из этого я не отправляю за пределы "
        "этого чата по своему почину, и всё, что я здесь говорю, разрешено {op}."
    ).format(name=BOT_NAME, op=OPERATOR, signed=signed)


POLL_TIMEOUT = 50         # long poll, seconds
OUTBOX_SCAN = 1.0         # how often to look at the outbox, seconds
                          # (own thread — it must not wait on the long poll)

# --------------------------------------------------------------------------
# PATHS
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
SELFCHECK_COUNT = ROOT / "selfcheck_count"   # счётчик обращений принципала
LOG = ROOT / "tg_log.jsonl"
REQUESTS = ROOT / "requests"            # ЖДУТ ОТВЕТА — это и есть ящик Логика
SERVED = ROOT / "served"                # отвеченное, убрано с глаз
OUTBOX = ROOT / "outbox"
SENT = ROOT / "sent"
REMINDERS = ROOT / "reminders"          # scheduled; the BRIDGE sends these
SENT_REMINDERS = ROOT / "sent_reminders"
REMINDER_SCAN = 20.0                    # how often to check the schedule, seconds
MEDIA = ROOT / "media"                  # вложения, по каталогу на запрос

# СКОЛЬКО БАЙТ МЫ СОГЛАСНЫ ПРИНЯТЬ С ЧУЖОЙ МАШИНЫ. Проверяется по метаданным
# Телеграма ДО загрузки, поэтому крупный файл стоит одного вызова, а не диска.
# Двадцать мегабайт — это и есть потолок getFile у Bot API: просить больше
# значит обещать то, чего сервер всё равно не даст.
MEDIA_MAX_BYTES = int(_S.get("media_max_bytes", 20 * 1024 * 1024))

# СКОЛЬКО МЕСТА ВЛОЖЕНИЯМ ОТВЕДЕНО ВСЕГО. Уборка идёт по ПЕРЕПОЛНЕНИЮ, а не по
# сроку — слово куратора 2026-08-22: файл, присланный полгода назад, может быть
# нужен, а сорок сегодняшних — нет. Возраст не знает, что важно; объём хотя бы
# честен.
#
# Два гигабайта, и вот откуда число. Потолок на файл — двадцать мегабайт, то
# есть сотня самых больших вложений или, при нынешнем размере снимка около ста
# двадцати килобайт, порядка семнадцати тысяч картинок. Обычное употребление
# сюда не упрётся никогда; зарвавшийся отправитель упрётся быстро и диска не
# съест. На фоне свободного места это доли процента.
MEDIA_BUDGET_BYTES = int(_S.get("media_budget_bytes", 2 * 1024 ** 3))

# ЖУРНАЛ ПРАВИЛ НА ОТПРАВКУ ФАЙЛОВ.
#
# Слово куратора 2026-08-22: «файлы — это уже не буковки, надо от дурака
# защищаться… но я бы не хотел полной детерминированности. Каждый раз
# подтверждение — это геморрой. Надо как-то по журналу правил: знакомый класс отправляй,
# что-то новое спроси, ранее согласованное — вообще не спрашивай».
#
# Отсюда устройство: подтверждение переезжает С ЭКЗЕМПЛЯРА НА ПРАВИЛО. Один раз
# одобряется КЛАСС отправок — эта папка в эту комнату, — и дальше всё, что в
# класс попадает, идёт без вопроса. Всё, что не попадает, спрашивается.
#
# Правило НЕ МОЖЕТ появиться от меня. Оно вписывается сюда только мостом и
# только по метке куратора, вместе с его числовым идентификатором, самой меткой
# и номером предложения. Правило без этих полей — не правило, а подделка.
# Тот же запрет, что в институциональных допусках: ограничиваемая
# сторона не изготавливает объект, который её ограничивает.
NEEDS_CONSENT = ROOT / "needs_consent"   # файлы, ждущие отдельного решения

RULES = ROOT / "rules.json"
GRANTS = ROOT / "grants.json"            # РАЗОВЫЕ разрешения на конкретные файлы


def grants() -> list:
    """Разовые разрешения. Правило — для потока, разрешение — для случая.

    Живут отдельно от правил НАМЕРЕННО. Правило описывает КЛАСС и действует
    впредь; разрешение названо по отпечатку, тратится один раз и больше не
    значит ничего. Сложить их в один файл значит через месяц не отличить
    «я разрешил такие файлы» от «я разрешил ЭТОТ файл».
    """
    try:
        data = json.loads(GRANTS.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


# СКОЛЬКО ФАЙЛОВ МОЖНО ПОВЕСИТЬ ПОД ОДНУ МЕТКУ. Десять — не круглое число ради
# красоты: список длиннее читать глазами перестают, а метка под непрочитанным
# списком есть штамп, как её ни назови. В самом мосте это записано с первого
# дня: «метка под списком из пяти дел становится штампом в течение недели».
# Ответ на «много файлов» — не пачка побольше, а ПРАВИЛО на папку.
BATCH_MAX = int(_S.get("batch_max", 10))

# ЧЕРЕЗ СКОЛЬКО МИНУТ СКАЗАТЬ, ЧТО НИКТО НЕ ВЗЯЛ. Двадцать: меньше — и мост
# заговорит поперёк ассистента, который просто думает; больше — и человек уже
# успел решить, что его забыли. Считается от записи в ящик, не от отправки.
NUDGE_AFTER_MIN = int(_S.get("nudge_after_min", 20))


def file_rules() -> list:
    """Правила отправки файлов. Пустой список, если журнала нет — то есть
    по умолчанию НЕ РАЗРЕШЕНО НИЧЕГО, и спрашивается всё."""
    try:
        data = json.loads(RULES.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []
PROPOSALS = ROOT / "proposals"          # pending proposals, awaiting a mark
DECIDED = ROOT / "decided"              # settled: approved / refused / expired

# THE CONSENT GATE. The assistant does nothing outward on its own: it hangs ONE
# LINE — "I propose to do X" — and the principal marks it with a reaction. The
# mark is the order; the text of the proposal is not.
#
# Absence of a mark is REFUSAL, never consent. So there is no "it expired,
# therefore go ahead": expired means no.
#
# One mark = one bounded action. Three actions mean three lines and three
# marks. Otherwise the mark becomes a rubber stamp within a week, which is the
# known fate of every "approve in one click".
APPROVE_EMOJI = {"👍"}
REJECT_EMOJI = {"👎"}
PROPOSAL_TTL_HOURS = 24   # expires; better they ask again than that someone
                          # taps something that has lost its meaning
PROPOSAL_SCAN = 300.0     # how often to clear expired proposals, seconds

# How long saved audio and sent/served records are kept. The conversation log
# itself is never touched — it is the record. This is only the bulky residue.
KEEP_DAYS = int(_S.get("keep_days", 30))

VOICE = ROOT / "voice"            # downloaded audio, kept next to its transcript
ANNOUNCED = ROOT / ".announced"   # which chats have been told
OFFSET = ROOT / ".offset"         # which update has already been handled
