# How the assistant (AI) uses the bridge

The bridge holds the token and does the I/O; the assistant only **reads files and writes
files**. If you get it wrong, you get it wrong in a file, not in someone else's chat. This file is the operational
contract for ANY AI that drives the bot (not about permissions — permissions live in `PROTOCOL.md`).

Everything here was measured through pain on 2026-08-22; pitfalls are marked ⚠.

## 1. Incoming: what was addressed to you

    requests/<mid>-<chat>.json     messages that start with the assistant's name
    tg_log.jsonl                   the ENTIRE permitted chat (context)

The bridge itself puts 👀 on anything addressed to you — "received, will be answered." That's a promise;
keeping it is your job.

## 2. Answer in words

    outbox/<any-name>.json
    {"chat_id": N, "text": "...",
     "answers": ["<mid>-<chat>"],     // WHAT we're closing — see §4
     "done_emoji": "👍"}              // optional; defaults to 👍

The bridge will send the text, move the request(s) listed in `answers` into `served/`, and CHANGE 👀 to
`done_emoji`. Without `answers` the eye stays 👀 and the request piles up → false
"NOBODY TO TAKE IT." ⚠ **Always name the request you're answering.**

## 3. Send a file

    {"chat_id": N, "file": "/absolute/path", "text": "caption"}

⚠ The key is **file**, not `path`; the caption is **text**, not `caption`. A wrong key
drops the message SILENTLY (not into sent/, not into the log). The arbiter of file delivery is the line
in `sent_by_rule.log`.

## 4. Close the eye (👀 → done)

The eye is a REACTION on the message. Closing it = CHANGING the reaction, not sending a like
next to it. Two ways:

    in the reply:  the "answers": ["<mid>-<chat>"] field   (see §2)
    by marker:     outbox/<mid>-<chat>.react.json
                   {"chat_id": N, "message_id": M, "emoji": "👍"}

⚠⚠ **The emoji must be from Telegram's reaction set** (`config.VALID_REACTIONS`).
`✅ ❌ 🟢 ✔` and most others are NOT reactions. An invalid emoji is now rejected loudly by the bridge
(`REACTION_INVALID` in the log). Before 2026-08-22 it fell back to
sending the emoji as a SEPARATE message — that's how ~20 "✅" got sent while the eyes never changed.
For "done" use **👍**. To remove the eye entirely: `*.unreact.json` (empty reaction).

Arbiter: `mark 👍 -> chat/mid: reaction` (good) versus `: message` (fell through).

## 5. Reminders

    reminders/<name>.json
    {"at": "2026-08-22T17:00:00+00:00", "chat_id": N, "text": "...",
     "ack": true, "every_min": 5, "max_tries": 24}   // ack fields are optional

`at` is exact UTC (parsing human time is your job, not the bridge's).
With `"ack": true` the bridge resends every `every_min` minutes UNTIL someone reacts
(any mark = "seen"), or until it hits `max_tries` (then it gives up
out loud). Without `ack` — once. To cancel: a curator's reaction, or remove the file.

## 6. Verify delivery — not by the absence of a line

    text sent   → file in sent/
    file sent   → line in sent_by_rule.log
    mark sent   → `mark ... reaction` in bridge.out

⚠ Diagnosing by a MISSING log line deceives you: silence also happens when the
message was swallowed by the schema. Look at the destination, not at its trace.

## 7. What NOT to do
- Don't leave a request without `answers` (eyes pile up).
- Don't set an invalid reaction (see §4).
- Don't edit the LIVE `LogicBridge/` tree; work on a clone, rollout is a separate
  curator decision, with fingerprint reconciliation and `drift.py --approve` afterward.

## 8. Control questions (against the assistant losing context)

Every 5th message addressed to the principal, the bridge drops a SEPARATE request
`control-<mid>-<chat>.json` (the watcher will announce it as "YOU'RE BEING CALLED" — you won't miss it).
Its text comes from `selfcheck present`: first a REVEAL of the truth about your previous
answer (from the code, not from your gut), then a NEW question. It's written AFTER the human's
request, so the self-check doesn't hold up their message. No eye is placed on a
control request and nudge won't touch it — it isn't a human one.

    see control_question -> answer the new one:
        ./selfcheck.py commit "your answer"
    you learn the truth about it on the NEXT control (you answer BEFORE the reveal —
    no cheating). Missed it -> go and reread what it named.

The judge is the code (ztl.py), not the assistant: a drifted you won't give yourself a pass.
Tool: `Projects/SelfCheck/` (cards.json, selfcheck.py).

Trigger safety (by the book): the command is a FIXED list
(`config.SELFCHECK_PRESENT`), no `shell=True`, no user input ->
no injection. It needs no secrets (the token isn't passed). A misfire/timeout (8s) ->
the field simply doesn't appear, delivery is NOT harmed. The one caveat: the run is
synchronous, so a hung selfcheck delays a single message by up to 8s (fail-safe).
