# LogicBridge — changelog

The fingerprint in every line is taken from the file, not from intent.


## v1.1.0 — 2026-08-22

First version of its own line after `v1.0.0` (an exact copy of the serving tree).
Work happened in `LogicBridge-dev`; the serving tree stayed untouched throughout.

**Attachments — files and images.** The bridge read only `text` and `caption`, so
an image without a caption arrived as an EMPTY request. This already cost us a loss:
on 2026-08-21 a third-party photo landed in the inbox as emptiness and was closed as
"nothing to answer." Now images, documents, video, and audio are downloaded into
`media/<request>/`, enter the request via the `files` field with name, size, type,
and fingerprint, and if there's no caption the request describes itself and is never
empty.

The trust boundary shifted from text to bytes; how that's held is in `PROTOCOL.md`,
including the rule "reading is allowed, executing is not" and an explanation of why a
blocklist of forbidden extensions was considered and rejected.

**The signature is configurable per chat, and an empty signature works.** Previously
`pol.get("reply_prefix") or C.REPLY_PREFIX` silently returned the name: an empty string
is falsy in Python. Now the PRESENCE of the key is checked, and "configured to empty"
is distinct from "not configured." Both outward signatures — outbound text and the
relay of someone else's words in a translation — are chosen earlier and left untouched:
text bound for the outside must say whose it is.

Two functions were extracted so the decision can be tested rather than eyeballed:
`outgoing_prefix(pol, item)` and `compose(prefix, text)`.

**Tested offline, no network:**

    test_gate.py     20 passed, 0 failed   (consent gate, untouched)
    test_attach.py   25 passed, 0 failed   (attachments, name as data, signature)

`test_attach.py` was created by this version.

## v1.2.0 — 2026-08-22

**Attachment cleanup by OVERFLOW, not by age** (the curator's word: "not by age, but
by overflow; allot however many bytes you need yourself"). Budget 2 GiB: a per-file
ceiling of 20 MB, so a hundred of the largest attachments or on the order of seventeen
thousand images at the current size. Normal use will never hit the wall; a runaway
sender hits it fast and won't eat the disk.

Three cleanup rules: a request's directory is deleted whole (one message's attachments
are one thing); **a request directory that hasn't been answered yet is never touched**;
every deletion is printed with its size, because silent cleanup is indistinguishable
from loss. If there's nothing to clean up and space has run out, the bridge says so out
loud rather than resigning itself in silence.

**Found along the way and fixed: `sweep_old_files` was written and NEVER CALLED.** Its
docstring promised that voice doesn't pile up forever; the promise held only because the
bridge is young and hasn't yet lived thirty days. Now both cleanups are called on the
same tick as proposal expiry.

    test_gate.py     20 passed, 0 failed
    test_attach.py   34 passed, 0 failed   (+9 for cleanup)

## v1.3.0 — 2026-08-22

**The bridge learned to SEND files.** Since v1.1.0 it received them but didn't send;
to the request "send a file to the chat" the honest answer was "I can't." Now both
directions.

`send_file(chat_id, path, caption, as_photo)` — its own multipart assembly, no
third-party libraries; a separate function rather than a parameter to `call`, because
an ordinary call encodes fields urlencoded and a file can't be passed that way. Mixing
two ways of talking to one API means hiding a difference that will bite later.

The caption is truncated to 1024 characters UP FRONT — that's what the Bot API allows.
Otherwise the server would reject the whole thing, and the file wouldn't go out because
of an extra line of text.

The outgoing queue gained a `file` field; a failure renames the queue file to `failed-*`
rather than staying silent.

    test_gate.py     20 passed, 0 failed
    test_attach.py   39 passed, 0 failed   (+5)

## v1.4.0 — 2026-08-22

**A gate on sending files, and confirmation moves from the instance to the RULE.**
The curator's word: "files aren't just little letters anymore, we need to guard against
a fool… but confirming every single time is a pain. Go by a rule log: send a familiar
class, ask about something new, and don't ask at all about what was agreed before."

How it works. An empty log permits NOTHING — by default everything is asked. A rule
binds three things, all three required: the recipient room, the source directory, and
a name pattern. A rule of "anything anywhere" simply CAN'T BE EXPRESSED in this format —
the field is mandatory, and a prohibition that can't be bypassed through forgetfulness
is more reliable than one you have to remember.

**A rule cannot originate from the assistant.** It is written by the bridge and only on
the curator's mark, together with his numeric identifier, the mark itself, and the
proposal number. A rule without an approver is skipped with a scandal in the log. The
same one produces the object that constrains it.

The path is collapsed to its real form before comparison, so
`allowed-folder/../../anything` doesn't pass. An unreadable expiry date is interpreted
NOT in favor of sending.

A rule removes the question UP FRONT — which means the check remains only AFTER, and it
must exist: every send by a rule writes a line to `sent_by_rule.log` with the rule
number. Otherwise a standing permission becomes a blind spot.

`./propose.py --file-rule <directory> --to <room> [--glob] [--why] [--until]`

    test_gate.py     20 passed, 0 failed
    test_attach.py   50 passed, 0 failed   (+11 for the gate, including the bypass via ..)

## v1.7.0 — 2026-08-22

**Batch: one mark — one parcel.** The curator: "if you need to send someone five files,
will you ask once or for all five?" It asked five times, and that's torment.

But "one mark per list" couldn't just be done: this very file has recorded since day one
that a mark under a list of five tasks becomes a rubber stamp within a week. The
difference that decides everything: five DIFFERENT tasks under one mark is a rubber
stamp; five files of ONE parcel to ONE room is one task with five parts. The unit of
consent is the one a person thinks about, not a byte count.

Three conditions, each closing its own hole:

    one recipient per batch     mixing rooms is forbidden — that's where the error hides
    every file named            name, size, fingerprint right in the proposal;
                                the mark covers WHAT WAS SEEN
    one-time and by fingerprint swapping the file after the mark doesn't pass,
                                the same permission won't fire a second time

The ceiling `batch_max` = 10. A list you can't read with your eyes is a rubber stamp,
whatever you call it; for a stream you set up a RULE on a folder, not a bigger batch.

One-time permissions live in `grants.json` SEPARATELY from rules by design: a rule
describes a class and acts henceforth, a permission is named by fingerprint and is spent
once. In one file you couldn't tell them apart a month later.

`./propose.py --batch f1 f2 … --to <room> [--why ...]`

    test_gate.py     20 passed, 0 failed
    test_attach.py   69 passed, 0 failed   (+7 for the batch, including swap and replay)

## v1.8.0 — 2026-08-22

Three things, on the curator's word "all three."

**A dead end I built myself this morning.** A refused file landed in `needs_consent/`
and just sat there: not a line to the inbox, no way back. A dead end no one knows about
is indistinguishable from loss. Now a refusal WAKES the assistant — the request in the
inbox names the file, the room, and a ready-made command to hang it on a mark.

**The badge no longer lies.** 👀 means "saved, and will be answered" — that's a promise,
and if the assistant isn't running, there's no one to keep it, while a person on the
outside can't tell "being read" from "forgotten." The bridge, the only one here that's
definitely alive, speaks for itself: "received, but in N minutes no one has picked it
up." ONCE per message — otherwise it's a racket that gets muted. Threshold 20 minutes.

**The tamper watchdog refuses rather than warns** (`drift.py`, §7 of the owner's
decision). The bridge checks the fingerprints of its thirteen files against the approved
state BEFORE the first network call and won't come up on a mismatch: its own return code
90, a record in `drift_refusals.jsonl`. The absence of an approved state is also a
refusal, not a permit by default. A broken watchdog is a refusal (code 91): a watchdog
that lets things through when it's itself broken guards only in good weather. The
watchdog watches itself too.

The honest boundary is named in the file itself: it does NOT protect against someone who
has access to the directory. It catches an edit that slipped past the transfer — exactly
the breed of failure we got caught on 2026-08-21.

    test_gate.py     20 passed, 0 failed
    test_attach.py   77 passed, 0 failed   (+8)

## v1.9.0 — 2026-08-23

A pass over the code through several lenses (races, silent failures, correctness).
Eleven fixes of the "did ≠ recorded" and "silent loss" class.

**The badge lies even less.** A file reply with `answers` now closes the named request
(the file branch of `flush_outbox` had no `clear_inbox` — the file went out but the 👀
stayed hanging). `.react.json` no longer clears a request if the mark DIDN'T land
(invalid emoji/network): "answered" on top of emptiness is inadmissible. `clear_inbox`
sets the mark BEFORE moving to `served`, not after.

**A reminder's receipt counts only from an approver** (`_seen`). Previously ANY reaction
cleared the escalation — in a group an outsider could silently remove it. Now an
`approver` is required; the bridge's own marks are cut off at the same time.

**Dispatch doesn't crash on a naive date.** `rule_for` caught only `ValueError`, but a
deadline without a timezone raises `TypeError` — it aborted ALL sends every pass. We
normalize to UTC.

**Silent losses — out loud.** A failed voice download is no longer a bare `return`: a
log entry plus a word to the sender. A worker-thread crash prints a traceback
(`_guarded`) rather than carrying the message off silently. A corrupt/foreign `outbox`
goes to `outbox/rejected/` instead of retrying forever — with a safeguard that a broken
`chats.json` (empty list) is NOT penalized. A broken `chats.json`/`settings.json` now
names the reason.

**Small but important.** `log_line` is under a lock — long lines from threads no longer
interleave into corrupt JSONL. `from_principal` doesn't elevate privileges on a message
without a sender (`is not None` first).

## v1.10.0 — 2026-08-23

**One lock and atomic writes on `grants.json` / `rules.json`.** These lists are edited
read-modify-write from TWO threads: the main one (`_close` via `decide`) and the pump
(`spend_grant`, and also `sweep_proposals`→`_close`). Without a shared lock, two threads
read the same list, each appended its own and wrote over the top — an edit was lost. The
worst consequence: `spend_grant` sets `used_at`, while a parallel `_close` overwrites the
list without it — a one-time consent came back to life, the file could go out again
without a new "yes." Now `_STATE_LOCK` (RLock) serializes edits, and `_atomic_write`
(tmp → `os.replace`) keeps a reader from seeing a half-file.

**Exactly one decision.** The mark (`decide`) and expiry (`sweep_proposals`) race to
close one proposal; whoever takes the lock first decides, the loser sees the
already-written `decided/` and exits. There's no mixed state where the log says EXPIRED
but a permission was created. `test_locks.py` locks this in.

## v1.11.0 — 2026-08-23

**The approver of a rule/permission is a REAL approver, not just a non-empty field.**
`rule_for`/`grant_for` checked only the NON-EMPTINESS of `added_by_user_id`; an arbitrary
nonzero id (corruption of `grants.json`/`rules.json`, a manual edit past the gate) used
to pass. Now the id must be an approver of at least one chat (`config.all_approvers()`).
Backward-compatible: live rules from the principal pass; a "folder→group" rule approved
in a private chat doesn't break. `test_attach` locks it in: an id not among the approvers
is rejected.

## v1.12.0 — 2026-08-23

**A list of open eyes on EVERY request (`open_eyes`).** 👀 = not handled; the principal
navigates by them. The pending report saw only the fresh ones in `requests/`, while those
moved to `served` after 6h fell out of sight — over a long session more than a hundred
unclosed ones piled up that way. Now `open_eye_backlog(chat_id)` counts the WHOLE open
set (addressed, given 👀, MINUS those closed via `answers`), from files, with a 10s cache,
and the `open_eyes=[id…]` field is placed in every request to the assistant — the one that
fired is before your eyes on the next message and gets closed rather than lost. The
close-path is untouched.

## v1.13.0 — 2026-08-23

**An invalid `done_emoji` no longer leaves 👀 hanging — falls back to 👍 and
notifies the assistant.** Telegram accepts reactions only from
`config.VALID_REACTIONS`; on anything else `ack()` refused and returned without
touching the reaction, so a close moved the request to `served/` (the assistant
read it as answered) while 👀 stayed on the phone — 26 piled up unseen in one
session. Now an invalid `done_emoji` on an eye-close is replaced with 👍 (the
eye always closes) and the bridge writes `requests/emoji-notice-*.json` so the
assistant sees, in a file (it never reads the stdout log), that its emoji was
invalid and 👍 was used instead.

## v1.14.0 — 2026-08-24

**Eyes 👀 on MY OWN messages (from the principal's reactions) now join the list
and can be closed, like any other eye.** When the principal reacts to one of my
messages, `handle_reaction` puts `ack()` = 👀 on it and files
`reaction-<chat>-<mid>.json`. But `open_eye_backlog` matched only `<mid>-<chat>`
names — so that eye was invisible to the list and hung forever. Now `got` also
counts `reaction-<chat>-<mid>` (keyed by mid); closing through `answers`
recognises that id (mid parsed off the END via `rsplit`, so a negative group
chat in the middle stays intact) and places `done_emoji` on my message; the
`closed` set understands the reaction id. Adds `test_reaction_eyes.py`.
