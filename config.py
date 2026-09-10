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
    except FileNotFoundError:
        return {}                      # no file is normal; take the defaults
    except Exception as e:
        # BROKEN JSON IS NOT SILENT. A typo in settings.json used to drop every
        # setting back to its default without a word; the cause was hunted blind.
        import sys
        print(f"[config] WARNING: settings.json did NOT parse ({e}) — using "
              f"empty settings; check the JSON syntax", file=sys.stderr)
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


_CHATS_WARN_AT = [0.0]


def _chats() -> dict:
    """Contents of chats.json.

    Read EVERY TIME rather than at startup: changing a boundary must not cost
    a restart of the bridge, or the change gets postponed.
    """
    try:
        import json as _j
        raw = _j.loads(CHATS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}                      # no file: stay quiet (may be before setup)
    except Exception as e:
        # A BROKEN chats.json = allowed()=False FOR EVERYONE = the bridge goes
        # mute. This used to happen in silence while the log filled with "chat
        # NOT allowed" about the principal's own chat — the cause (broken JSON)
        # was named nowhere. It is read on every message, hence the 60 s
        # throttle, so as not to flood the log.
        import sys, time
        if time.time() - _CHATS_WARN_AT[0] > 60:
            _CHATS_WARN_AT[0] = time.time()
            print(f"[config] WARNING: chats.json did NOT parse ({e}) — the "
                  f"bridge is MUTE FOR EVERYONE until the JSON is fixed. The "
                  f"'chat NOT allowed' lines below are a consequence of this, "
                  f"not the cause.", file=sys.stderr)
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


def all_approvers() -> set[int]:
    """Every id whose mark counts as consent anywhere — the union across chats.

    A rule or grant is only born at the gate (`_close` behind approver=True),
    but the file on disk can be corrupted or appended to around the gate.
    Checking merely that `added_by_user_id` is NON-EMPTY is not enough: any
    non-zero id would pass. The approver must be a REAL approver of at least one
    chat, which cuts out a random id. A "folder→group" rule approved in a
    private chat still works: the principal of that private chat is here too.
    """
    out: set[int] = set()
    for cfg in _chats().values():
        out.update(cfg.get("approvers") or [])
    return out


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
# Control questions against the assistant losing its context: on every Nth
# addressed message from the principal the bridge runs "selfcheck present" as a
# SEPARATE process (it does not pull the checker into itself) and puts the
# question and its answer into the request's note. The judge is code. A crash or
# a timeout is skipped in silence: a control question must NEVER cost a delivery.
# SWITCHED OFF 2026-08-26 by the operator's word, and the reason matters more
# than the switch. The exam measured the assistant's MEMORY. From that same day
# a hook tells it to look into the note store on every message — and the
# assistant honestly looked, while answering a question about Agrippa's
# trilemma. The operator: "if you look things up straight away then it is not an
# exam, it is a reminder." The instrument stopped measuring what it was built
# for, so it says nothing rather than pretending. 0 = ask no questions at all.
SELFCHECK_EVERY = 0
# THE PATH TO THE CHECKER COMES FROM SETTINGS, NOT FROM CODE. The checker is an
# instrument of ONE INSTALLATION; the product does not know about it and must
# not — a hard-coded absolute path led to a single machine. With no
# selfcheck_present key the command is empty and no control questions are asked.
#   "selfcheck_present": ["python3", "~/…/selfcheck.py", "present"]
SELFCHECK_PRESENT = [str(Path(a).expanduser()) if "/" in str(a) else str(a)
                     for a in (_S.get("selfcheck_present") or [])]
VALID_REACTIONS = frozenset(
    "👍 👎 ❤ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 👌 🕊 🤡 🥱 🥴 😍 🐳 "
    "🌚 🌭 💯 🤣 ⚡ 🍌 🏆 💔 🤨 😐 🍓 🍾 💋 🖕 😈 😴 😭 🤓 👻 👀 🎃 🙈 😇 😨 "
    "🤝 ✍ 🤗 🫡 🎅 🎄 ☃ 💅 🤪 🗿 🆒 💘 🙉 🦄 😘 💊 🙊 😎 👾 😡".split())

# --------------------------------------------------------------------------
# LANGUAGE
# --------------------------------------------------------------------------
# The product speaks English. Every other language is a FILE, not a fork:
# locale/<code>.json holds the same keys with translated values, and an
# installation picks one with "lang" in settings.json. A key missing from a
# translation falls back to English rather than to a blank — a half-translated
# bridge must still be usable, and a silent empty string is worse than a
# foreign word.
#
# Why keys and not the sentences themselves: the sentences change. When the
# wording of a warning is edited in English, every translation of it must be
# findable, and grep over quoted Russian is not a way to find anything.
LANG = str(_S.get("lang") or "en")
LOCALE_DIR = Path(__file__).resolve().parent / "locale"

def _load_locale(code: str) -> dict:
    f = LOCALE_DIR / f"{code}.json"
    if not f.exists():
        return {}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if not k.startswith("_")}
    except (ValueError, OSError) as e:
        print(f"WARNING: locale/{code}.json is not readable ({e}), falling back to English")
        return {}

_EN = _load_locale("en")
_LC = _load_locale(LANG) if LANG != "en" else {}
if LANG != "en" and not _LC:
    print(f"WARNING: language {LANG!r} not found in locale/, speaking English")

def T(key: str, **kw) -> str:
    """One phrase for the reader, in the installation's language.

    An unknown key returns the KEY ITSELF, loudly and visibly. Returning "" or
    the English fallback would hide the mistake exactly where it is hardest to
    notice — in a language the author does not read.
    """
    tpl = _LC.get(key) or _EN.get(key)
    if tpl is None:
        return f"?{key}?"
    try:
        return tpl.format(**kw) if kw else tpl
    except (KeyError, IndexError) as e:
        return f"?{key}: {e}?"


# A SUBSTANTIVE REPLY MUST END BY SAYING WHETHER IT NEEDS THE READER TO ACT.
#
# The operator asked for this and the reason is worth keeping: a long answer
# without it forces him to re-read the whole thing to work out whether he is
# on the hook. The marker is a JUDGEMENT — what, exactly, is still owed by
# whom — so the bridge does NOT append it. It only says loudly when it is
# missing, because a marker written by the machine would say nothing and would
# stop the assistant from thinking about the question.
# English is ALWAYS accepted, in every language: the assistant on the other end
# may answer in English even when the installation speaks something else, and a
# marker rejected for being in the wrong language would be a marker missing.
NEEDS_MARKER = tuple(dict.fromkeys(
    [T("marker.action_needed"), T("marker.no_action_needed"),
     "ACTION NEEDED", "NO ACTION NEEDED"]))
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
# WHAT PEOPLE ARE TOLD BY THE FIRST MESSAGE. The text lists what is ACTUALLY
# collected, not what used to be. Since 1.1.0 the bridge downloads and keeps
# ATTACHMENTS — images, documents, voice — while the notice still spoke only of
# the conversation. A notice that has fallen behind the program is worse than no
# notice at all: it reads as a promise.
#
# The wording lives in locale/<lang>.json, not here. This is the one text with
# legal weight, and a translation of it must be reviewed by someone who reads
# that language — which is only possible if it sits in a file a reader can open.
def announce_text(chat_id: int) -> str:
    signed = (T("notice.signed", name=BOT_NAME, op=OPERATOR)
              if policy(chat_id).get("reply_prefix", REPLY_PREFIX) else "")
    return T("notice.body", name=BOT_NAME, op=OPERATOR, signed=signed)


POLL_TIMEOUT = 50         # long poll, seconds
OUTBOX_SCAN = 1.0         # how often to look at the outbox, seconds
                          # (own thread — it must not wait on the long poll)

# --------------------------------------------------------------------------
# PATHS
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
SELFCHECK_COUNT = ROOT / "selfcheck_count"   # counts the principal's messages
LOG = ROOT / "tg_log.jsonl"
# The chat log grows without limit — the one thing that was never swept. Past
# LOG_MAX_BYTES it moves to tg_log.jsonl.1 (a single backup) and is started
# again. Voice transcripts are in the log anyway; losing the old is no great
# loss, the disk matters more.
LOG_MAX_BYTES = int(_S.get("log_max_bytes", 50 * 1024 ** 2))
REQUESTS = ROOT / "requests"            # AWAITING AN ANSWER — the assistant's inbox
SERVED = ROOT / "served"                # answered, moved out of sight
OUTBOX = ROOT / "outbox"
SENT = ROOT / "sent"
REMINDERS = ROOT / "reminders"          # scheduled; the BRIDGE sends these
SENT_REMINDERS = ROOT / "sent_reminders"
REMINDER_SCAN = 20.0                    # how often to check the schedule, seconds
MEDIA = ROOT / "media"                  # attachments, one directory per request

# A CORRESPONDENT'S MAIL FOLDER — THE WATCH LIVES IN THE BRIDGE, NOT IN THE
# ASSISTANT'S SESSION. A watch inside the assistant dies with the session, and
# worse: a process may survive from a PREVIOUS session while events no longer
# reach the current one — from outside, "stalled" and "deaf" look the same
# (measured 2026-08-24). The bridge is a systemd service; it outlives sessions,
# so the guarantee must hang on it. The operator's word: look ONCE A MINUTE, not
# once in ten — the check costs pennies.
# THE PATHS LIVE IN settings.json (which is gitignored), NOT IN THE CODE. One
# person's private wiring must not travel into a public repository along with
# the bridge. With no mail_watch key the watch simply says nothing and the
# bridge works exactly as before.
#
#   "mail_watch": {"inbox": "~/…/Inbox-Vitaly", "outbox": "~/…/Inbox-Arkadiy",
#                  "mirror": "~/Exchange-mirror", "scan_seconds": 60}
_MW = _S.get("mail_watch") or {}
def _mw_path(key: str):
    v = _MW.get(key)
    return Path(v).expanduser() if v else None
MAILWATCH_IN = _mw_path("inbox")        # the OTHER side writes here, we read
MAILWATCH_OUT = _mw_path("outbox")      # WE write here, they read
MAILWATCH_MIRROR = _mw_path("mirror")   # a copy outside the cloud folder and git
MAILWATCH_SCAN = float(_MW.get("scan_seconds", 60.0))    # once a minute
# BINDING A FOLDER TO A ROOM. A correspondent, 2026-09-01: events of ONE topic
# falling into the shared room were breaking their working channel. An empty
# list -> behave exactly as before.
FOLDER_ROOMS = [r for r in (_MW.get("folder_rooms") or [])
                if r.get("match") and r.get("chat_id")]
MAILWATCH_STATE = ROOT / "mail_watch_seen.json"  # what was shown; do not call twice
# THE NOTICE'S HEADING COMES FROM SETTINGS. Whose folder it is, is known to the
# installation and not to the product: a correspondent's name in the code is one
# person's private wiring inside a stranger's repository. With no key the
# heading is generic and the bridge works exactly as before.
MAILWATCH_LABEL = str(_MW.get("label") or T("mail.label"))

# HOW MANY BYTES WE AGREE TO TAKE FROM SOMEONE ELSE'S MACHINE. Checked against
# Telegram's metadata BEFORE downloading, so a large file costs one API call
# rather than disk. Twenty megabytes is the Bot API's own getFile ceiling: to
# ask for more is to promise what the server will not give anyway.
MEDIA_MAX_BYTES = int(_S.get("media_max_bytes", 20 * 1024 * 1024))

# HOW MUCH ROOM ATTACHMENTS GET IN TOTAL. Cleaning happens on OVERFLOW, not by
# age — the operator's word, 2026-08-22: a file sent six months ago may still be
# needed while forty of today's are not. Age does not know what matters; volume
# is at least honest.
#
# Two gigabytes, and here is where the number comes from. The per-file ceiling
# is twenty megabytes, so a hundred of the largest attachments — or, at a
# typical screenshot of about a hundred and twenty kilobytes, some seventeen
# thousand images. Ordinary use will never reach it; a runaway sender reaches it
# quickly and eats no disk. Against the free space this is a fraction of a
# percent.
MEDIA_BUDGET_BYTES = int(_S.get("media_budget_bytes", 2 * 1024 ** 3))

# THE RULE BOOK FOR SENDING FILES.
#
# The operator's word, 2026-08-22: "files are not letters any more, there has to
# be protection against a fool… but I would not want full determinism. A
# confirmation every single time is a pain. It should go by a book of rules: for
# this project just send, ask about something new, and about what was agreed
# earlier and is ready in the folder do not ask at all."
#
# Hence the design: the confirmation moves FROM THE INSTANCE TO THE RULE. A
# CLASS of sends is approved once — this folder into this room — and from then
# on everything inside the class goes without a question. Everything outside it
# is asked about.
#
# A RULE CANNOT COME FROM ME. It is written here only by the bridge and only on
# the operator's mark, together with their numeric id, the mark itself and the
# proposal's number. A rule without those fields is not a rule but a forgery.
# This is the same prohibition stated for warrants elsewhere: the constrained
# party does not manufacture the object that constrains it.
NEEDS_CONSENT = ROOT / "needs_consent"   # files awaiting a decision of their own

# AN UNKNOWN CHAT LEAVES A TRACE, NOT SILENCE. A message from a chat outside the
# allow list used to be discarded, leaving ONE line in the log and nothing else.
# That is not enough: an absence of files is indistinguishable from the message
# never having existed, and from an empty folder one cannot tell whether the
# sender is silent or the instrument is. A diagnosis from such a "zero" comes
# out confident and wrong.
# Now a refusal LEAVES A FILE — one per chat, with everything needed to admit
# it. The same principle the BACKLOG states for the outbox: drop what you do not
# recognise WITH A REASON, not into silence.
NEEDS_WHITELIST = ROOT / "needs_whitelist"

RULES = ROOT / "rules.json"
GRANTS = ROOT / "grants.json"            # ONE-OFF grants for particular files


def grants() -> list:
    """One-off grants. A rule is for a stream, a grant is for one occasion.

    They live apart from rules DELIBERATELY. A rule describes a CLASS and holds
    from now on; a grant is named by a digest, is spent once and afterwards
    means nothing. Putting both in one file means that in a month you cannot
    tell "I allowed files like this" from "I allowed THIS file".
    """
    try:
        data = json.loads(GRANTS.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


# HOW MANY FILES MAY HANG UNDER ONE MARK. Ten is not a round number chosen for
# looks: past that length people stop reading the list with their eyes, and a
# mark under an unread list is a rubber stamp whatever it is called. The bridge
# has said so since day one: "a mark under a list of five items becomes a stamp
# within a week." The answer to "many files" is not a bigger batch but a RULE on
# the folder.
BATCH_MAX = int(_S.get("batch_max", 10))

# AFTER HOW MANY MINUTES TO SAY THAT NOBODY PICKED IT UP. Twenty: less, and the
# bridge talks over an assistant that is merely thinking; more, and the person
# has already decided they were forgotten. Counted from the write into the
# inbox, not from the send.
NUDGE_AFTER_MIN = int(_S.get("nudge_after_min", 20))
# After how many minutes a lingering open eye is shown to the ASSISTANT as a
# list (the operator's design: the eye is a "not done" indicator and may only be
# put out by a real answer; the bridge merely holds the list under its nose
# instead of relying on memory).
EYES_AFTER_MIN = int(_S.get("eyes_after_min", 3))
# Anti-flood, of the "against a fool" kind. A sender who sends more than FLOOD_N
# messages within FLOOD_T seconds is muted for FLOOD_K minutes: their messages
# are logged but not acted upon, and they get ONE notification. EVERYONE is
# muted, the principal included — a compromised principal account must not be
# the exception (that would be the hole itself). The operator's word,
# 2026-08-23.
FLOOD_N = int(_S.get("flood_n", 10))
FLOOD_T = int(_S.get("flood_t", 20))
FLOOD_K = int(_S.get("flood_k", 5))


def file_rules() -> list:
    """File-sending rules. An empty list when there is no book — that is, by
    default NOTHING is allowed and everything is asked about."""
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

# Service wake-up requests in requests/ (reaction-/control-/verdict-/pending-
# eyes-) are signals that live exactly once: pending_eyes and nudge already skip
# them, they create no false eyes — but they never leave either, and requests/
# swells. Past this age they are moved into served/. needsfile- is NOT swept: it
# is a file awaiting the operator's consent, a genuinely open request.
SERVICE_REQUEST_KEEP_HOURS = int(_S.get("service_request_keep_hours", 6))

# --------------------------------------------------------------------------
# EXTERNAL HANDLERS — the product's extension point
# --------------------------------------------------------------------------
# The bridge ships no features of its operator's own. Anything specific to one
# installation — a private search index, a company tool, a home automation — is
# an EXTERNAL PROGRAM declared here, and the bridge knows nothing about it
# beyond "a command maps to a process". Delete the bridge, install it again,
# put settings.json back, and the command works: nothing of yours ever lived
# in the product's source.
#
#   "handlers": [
#     {"command": "/ac", "run": ["python3", "~/tools/store.py"],
#      "help": "search my notes", "where": "principal_private",
#      "timeout_seconds": 180}
#   ]
#
# "pattern" is optional and wins over "command" when a family of commands must
# be caught at once (e.g. "^/f([1-9])$"); its groups reach the program.
#
# WHERE IS DEFAULT-DENY. Without an explicit "where" a handler runs ONLY in the
# principal's private chat. An extension usually reaches private material, and a
# group is exactly where one wrong word publishes it to third parties. Opening
# it up must be a decision someone typed, never a default they inherited.
import re as _re
_HANDLER_WHERE = ("principal_private", "anywhere")
HANDLERS = []
for _h in (_S.get("handlers") or []):
    _cmd, _run = _h.get("command"), _h.get("run")
    if not _run or not (_cmd or _h.get("pattern")):
        print(f"WARNING: handler without command/pattern or without run, skipped: {_h!r}")
        continue
    _where = _h.get("where", "principal_private")
    if _where not in _HANDLER_WHERE:
        print(f"WARNING: handler {_cmd!r}: unknown where={_where!r}, "
              f"using principal_private")
        _where = "principal_private"
    _pat = _h.get("pattern") or (r"^\s*" + _re.escape(_cmd) + r"(?:[\s:]+(?P<arg>.+))?\s*$")
    try:
        _rx = _re.compile(_pat, _re.I | _re.U | _re.S)
    except _re.error as _e:
        print(f"WARNING: handler {_cmd!r}: broken pattern ({_e}), skipped")
        continue
    HANDLERS.append({
        "command": _cmd or _h.get("pattern"),
        "re": _rx,
        "run": [str(Path(_a).expanduser()) if "/" in str(_a) else str(_a) for _a in _run],
        "where": _where,
        "help": _h.get("help", ""),
        "timeout": float(_h.get("timeout_seconds", 60)),
    })

VOICE = ROOT / "voice"            # downloaded audio, kept next to its transcript
ANNOUNCED = ROOT / ".announced"   # which chats have been told
OFFSET = ROOT / ".offset"         # which update has already been handled


# --------------------------------------------------------------------------
# THE BRIDGE CREATES ITS OWN DIRECTORIES
# --------------------------------------------------------------------------
# Measured 2026-09-10 on a CLEAN install: requests/ does not exist and the
# bridge dies with FileNotFoundError on the VERY FIRST incoming message. Here
# the directories existed — someone made them by hand long ago — and from inside
# one's own installation this trouble is invisible: the person who installs the
# product is not the person who developed it. Exactly the argument by which the
# machine-path guard lives in this package.
#
# Why here and not in setup.py: EVERY entry point imports config — the bridge,
# pending, propose, react. A directory made by the installer does not help
# someone who ran a tool from a copy. mkdir(exist_ok=True) costs microseconds
# once per start. Files (LOG, OFFSET, ANNOUNCED, MAILWATCH_STATE) are left
# alone: they are created by whoever writes them, and an empty one here would be
# a lie that something had already happened.
for _d in (REQUESTS, SERVED, OUTBOX, SENT, REMINDERS, SENT_REMINDERS, MEDIA,
           NEEDS_CONSENT, NEEDS_WHITELIST, PROPOSALS, DECIDED, VOICE):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError as _e:                    # read-only mount, foreign volume: not ours
        print(f"WARNING: could not create {_d}: {_e}")
del _d
