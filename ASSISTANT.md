# How an assistant (an AI) uses the bridge

The bridge holds the token and does the I/O; the assistant only **reads files
and writes files**. A mistake is a mistake in a file, not in somebody's chat.
This document is the operational contract for ANY AI driving the bot — not about
rights, which live in `PROTOCOL.md`.

All of it was learned the painful way on 2026-08-22; the traps are marked ⚠.

## 0. If you are the one installing it

An assistant often installs the bridge for its person, so the install lives here
too and not only in the README: an instruction belongs where the one doing the
work will read it. The whole install is two steps, whoever performs them:

1. The person creates a bot at `@BotFather` and gives you the token. Only they
   can: Telegram lets nobody automate it.
2. Run `python3 setup.py`, paste the token, and ask the person to send the bot
   any message. Setup takes the rest from that message and ends with `READY` or
   with exactly what to fix.

Four traps, in the order they bite. `doctor.py` names each one:

- **group privacy on** — in a group the bot sees only commands;
- **privacy turned off, but the bot not removed and re-added** — still deaf,
  while every step looks done;
- **a webhook left set** — getUpdates returns nothing, ever;
- **two processes on one token** — 409, and it "works sometimes".

When in doubt, run `python3 doctor.py` and pass its whole output on: it never
prints the token.

## 1. Incoming: what was addressed to you

    requests/<mid>-<chat>.json     messages that began with the assistant's name
    tg_log.jsonl                   the WHOLE allowed chat (context)

The bridge itself puts 👀 on what was addressed — "received, it will be
answered". That is a promise; keeping it is your work.

## 2. Answer in words

    outbox/<any-name>.json
    {"chat_id": N, "text": "...",
     "answers": ["<mid>-<chat>"],     // WHAT is being closed — see §4
     "done_emoji": "👍"}              // optional; 👍 by default

The bridge sends the text, moves the request(s) named in `answers` into
`served/`, and CHANGES 👀 to `done_emoji`. Without `answers` the eye stays 👀 and
requests pile up → false "nobody picked it up" nudges. ⚠ **Always name the
request you are answering.**

## 3. Send a file

    {"chat_id": N, "file": "/absolute/path", "text": "caption"}

⚠ The key is **file**, not `path`; the caption is **text**, not `caption`. A
wrong key drops the message SILENTLY (nothing in sent/, nothing in the log). The
arbiter of a file's delivery is a line in `sent_by_rule.log`.

## 4. Close the eye (👀 → done)

The eye is a REACTION on a message. Closing it means CHANGING that reaction, not
sending a thumbs-up beside it. Two ways:

    in the answer:  the "answers": ["<mid>-<chat>"] field   (see §2)
    by a mark:      outbox/<mid>-<chat>.react.json
                    {"chat_id": N, "message_id": M, "emoji": "👍"}

⚠⚠ **The emoji must come from Telegram's reaction set** (`config.VALID_REACTIONS`).
`✅ ❌ 🟢 ✔` and most others are NOT reactions. An invalid emoji is now refused
loudly (`REACTION_INVALID` in the log). Before 2026-08-22 it fell through into
sending the emoji as a SEPARATE message — about twenty "✅" went out that way
while no eye changed. For "done" use **👍**. To remove the eye entirely:
`*.unreact.json` (an empty reaction).

The arbiter: `mark 👍 -> chat/mid: reaction` (good) versus `: message` (fell
through).

## 5. Reminders

    reminders/<name>.json
    {"at": "2026-08-22T17:00:00+00:00", "chat_id": N, "text": "...",
     "ack": true, "every_min": 5, "max_tries": 24}   // the ack fields are optional

`at` is exact UTC — parsing human time is your work, not the bridge's. With
`"ack": true` the bridge sends again every `every_min` minutes UNTIL someone
reacts (any mark means "seen"), or until it hits `max_tries` (then it gives up
out loud). Without `ack`, once. To cancel: the operator's reaction, or remove the
file.

## 6. Verify delivery — never by the absence of a log line

    text went out  → a file in sent/
    file went out  → a line in sent_by_rule.log
    mark went out  → `mark ... reaction` in bridge.out

⚠ A diagnosis drawn from a MISSING log line deceives: silence also happens when
the message was swallowed by the machinery. Look at the destination, not at its
trace.

## 7. What NOT to do
- Do not leave a request without `answers` (the eyes pile up).
- Do not set an invalid reaction (see §4).
- Do not edit the LIVE tree; work on a clone, and roll out as a separate
  decision of the operator's, with digests compared and `drift.py --approve`
  afterwards.

## 8. Control questions (against the assistant losing its context)

On every 5th addressed message from the principal the bridge drops a SEPARATE
request, `control-<mid>-<chat>.json` (the queue watch announces it as "you are
called", so it will not be missed). Its text comes from `selfcheck present`:
first the DISCLOSURE of the truth about your previous answer (from code, not
from your instinct), then a NEW question. It is written AFTER the human's
request, so the self-check never delays their message. A control request gets no
eye and the nudge does not touch it — it is not a person's.

    you see control_question -> answer the new one:
        ./selfcheck.py commit "your answer"
    the truth about it comes with the NEXT control question (you answer BEFORE
    the disclosure — there is no copying). Missed it -> go and re-read what it
    named.

The judge is code, not the assistant: a drifted you will not let yourself pass.
The checker is an external tool of the installation; its command comes from
`settings.json` (`selfcheck_present`). With no such key, no questions are asked.

Safety of the trigger: the command is a FIXED list
(`config.SELFCHECK_PRESENT`), no `shell=True`, no user input — so there is no
injection. It needs no secrets (the token is not passed). A misfire or a timeout
(8 s) simply means the field does not appear, and delivery does NOT suffer. The
one caveat: the run is synchronous, so a hung checker delays one message by up to
8 s (fail-safe).
