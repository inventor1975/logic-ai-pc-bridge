# LogicBridge — how versions are kept

Started 2026-08-22 by the operator's word: "leave what exists untouched and keep
developing on a clone of it. All that is needed is to start keeping versions,
with 1.0.0 frozen."

## Two trees, and they must not be confused

    the live tree        SERVING. It runs and answers people. NOT EDITED.
    the dev tree         THIS ONE. Work happens here. It serves nobody.

The serving tree changes in exactly one way: a finished version is placed there,
its digests are compared, and the restart is a SEPARATE decision of the
operator's. There will be no edits on the live tree: that is the first of the six
kinds of failure we were caught by on 2026-08-21.

## Two numbering lines, and one map between them

**`v1.0.0` — our line.** An EXACT copy of the serving tree as of 2026-08-22, byte
for byte across every `.py` (verified when it was created, not asserted). From
here grow `1.1.0`, `1.2.0` and onward.

**`v0.2` — the owner's line.** The package handed to an external reviewer and
reviewed by them. That, and not our 1.0.0, is the baseline under their control
regime.

**The map between them is already drawn and is not rewritten:** a baseline
manifest of the delivered archive's 21 files, of which two had diverged from the
live tree (`tg_bridge.py`, `test_gate.py`); since the freeze of 2026-08-21
20:05:23 there has been no drift.

**A new label does NOT cancel an old fact.** `v1.0.0` is a name for our work, not
a whitewash of a divergence. Whoever reads the history must still see that the
live tree differed from the reviewed package by two files.

## What lives where

Secrets and state never enter the repository at all: the token, `settings.json`,
`chats.json`, the conversation, voice and the queues are all in `.gitignore`, and
the clone was created WITHOUT them (checked at creation, not promised).

The dev tree should be exercised against a TEST bot with its own token. A test
bot already exists — it was left over from the run of 2026-08-21.

## The version rule

    1.x.0   a new capability (files and images, a per-chat signature)
    1.x.y   a repair with no new capability
    2.0.0   an incompatible change to the request format, the settings or the protocol

Every version is a git tag and a line in `CHANGELOG.md` carrying the digest of
what was actually delivered. The digest is taken from the file, not from the
intention.

## v1.12.0 — control questions on a trigger (every 5th message)

The operator: "hang it on the bot, trigger it on every fifth message." Against
the assistant losing its context (it drifts back to the classical reading; the
operator used to catch that by hand).

  * `config.SELFCHECK_EVERY=5`, `SELFCHECK_PRESENT` (the checker's command),
    `SELFCHECK_COUNT` (a counter of the principal's messages).
  * `control_question()` — on every 5th addressed message from the principal the
    bridge runs the checker as a SEPARATE process (it does not pull the checker
    into itself) and puts the question plus the disclosure of the previous answer
    into the request's `control_question` field. Fail-safe: a timeout or a
    misfire → None, and delivery does NOT suffer. The judge is code, not the
    assistant.
  * The split between present (the bot fetches the truth) and commit (the
    assistant writes an answer): the answer comes BEFORE the truth is seen, so
    there is no copying.
  * `test_autocheck` (the 5th yields a question, a misfire is swallowed). gate
    20, attach 90, reminders 4, reactions OK.

---

## v1.11.0 — a guard against invalid reactions + AI-facing documentation

The operator (2026-08-22): "you keep setting ✅ — nothing will come of that, the
eye icon has to change", and "are you documenting how the AI itself uses the
bot?"

  * `config.VALID_REACTIONS` — the fixed set of Telegram's reactions. `ack()` now
    refuses an invalid emoji LOUDLY (REACTION_INVALID in the log) instead of
    falling through into sending the emoji as a separate message. Measured: ✅ is
    not a reaction, which is why about twenty "✅" messages went out while no eye
    changed. `test_reactions`.
  * `ASSISTANT.md` — the operational contract for ANY AI driving the bot:
    incoming, answering (+answers, closing the eyes), files (file/text), valid
    reactions with the ✅ trap, reminders, verifying delivery. PROTOCOL.md is
    about rights; this one is about HOW to use it.

gate 20/20, attach 90/90, reminders 4/4, reactions OK.

---

## v1.10.0 — a reminder that keeps knocking until it is seen

By the operator's word (2026-08-22): "remind me in an hour — you reminded me, but
did I see it? then it has to be sent again, and if I react then I saw it."

A reminder with `"ack": true` no longer leaves after a single send. The bridge
sends it again every `every_min` minutes UNTIL the operator reacts to it (any
mark means "seen"), and only then goes quiet. Three ways it avoids becoming an
endless nag:

  - the operator's reaction stops it immediately (a one-touch cancel from a phone);
  - the `max_tries` fuse (24 by default, about 2 hours) — it gives up by itself
    and says so out loud rather than in silence;
  - "cancel the reminder" — the file is removed.

The reaction is read from `reactions.jsonl` (the message_id of the latest copy).
Ordinary reminders without `ack` behave as before, once. Test:
`test_reminders.py`, 4 scenarios. `test_gate` 20/20, `test_attach` 90/90 —
untouched.

---
