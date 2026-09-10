# LogicBridge — changelog

The digest in every line is taken from the file, not from the intention.

## v2.0.0 — 2026-09-10

**Incompatible.** By the rule in VERSIONS.md: the request format, the settings and
a command-line tool changed.

The product and an installation are now separate things. Everything specific to
one installation has left the code; an installation is settings and data only.

- **External handlers** (`settings.json → handlers`). A command maps to an
  external program: one JSON object on stdin, one back on stdout. `where` defaults
  to the principal's private chat — an extension usually reaches private material.
  A private search tool that lived inside the bridge (383 lines, three absolute
  paths) was removed and now runs outside it as a handler. *Incompatible:* its
  commands no longer exist in the product.
- **Seven languages**: `locale/{en,ru,uk,he,de,fr,es}.json`, chosen by
  `settings.lang`. The English action marker is accepted in every language.
  uk, he, de, fr and es have not yet been reviewed by native speakers.
- **Renamed** (*incompatible*). The mail watch: `mail_watch()`, `MAILWATCH_*`,
  `FOLDER_ROOMS`, `mail_watch.label`, and its requests are prefixed `mailwatch-`
  instead of an installation-specific prefix. The queue watch:
  `queue_watch.py --only / --except / --once`.
- **Install in two steps.** Create a bot at `@BotFather`, then `python3 setup.py`:
  it asks only for the token and waits for your first message. The principal, the
  language (Telegram's `language_code`) and the name come from that message; the
  bridge answers at once. On Linux it writes a service with this directory's real
  paths — and never overwrites a service that serves another directory. It ends by
  running `doctor.py` and prints `READY` or what to fix. The full questionnaire is
  `setup.py --advanced`. `doctor.py` joins the package.
- **The bridge creates its own directories.** A clean install used to die on the
  very first incoming message.
- **File names in any script are kept.** Only characters dangerous in a path or a
  header are replaced; Hebrew or Chinese names no longer arrive as underscores.
- **The mail watch's state knows its folders.** Changing a folder in settings
  re-baselines silently instead of announcing everything as gone.
- **An allow-list `.gitignore`.** An installation's data — chats, settings, grants,
  rules, the token, logs, queues — is never admitted.
- **New guards**: no private name, chat id or machine path in anything git ships;
  every settings key documented in the example; a clean checkout installs and
  survives its first message; every locale complete, with identical placeholders
  and no literal `\n`; English-only source; the setup plan decides correctly.
- The source is in English throughout.

Stand: 26 stands. One (`test_other_bot`) is **skipped** with its reason: the
feature it specifies is not in this product, and whether to restore it is an open
decision.

## v1.21.0 — 2026-08-24

**Eyes 👀 on MY OWN messages (from the principal's reactions) now enter the list
and are closed like any other eye (variant 1).** When the principal reacts to one
of my messages, `handle_reaction` sets `ack()` = 👀 on it and files
`reaction-<chat>-<mid>.json`. But `open_eye_backlog` counted only names shaped
`<mid>-<chat>` — that eye was invisible to the list and hung for ever (found by
the operator). Now `got` counts `reaction-<chat>-<mid>` as well (keyed by mid);
closing through `answers` recognises that id (the mid is cut from the END with
`rsplit`, so a negative group chat id in the middle stays intact) and sets
`done_emoji` on my message; the `closed` set accounts for such ids. Added
`test_reaction_eyes.py`.

## v1.20.0 — 2026-08-23

**An invalid `done_emoji` no longer leaves 👀 hanging — it falls back to 👍 and
notifies the AI.** Telegram accepts reactions only from `config.VALID_REACTIONS`;
for anything else `ack()` REFUSED and returned without replacing the reaction —
the request went to served (the assistant read "answered") while the 👀 on the
phone STAYED. Twenty-six stuck that way in one session. Now, when an eye is
closed, an invalid `done_emoji` is REPLACED by 👍 (the eye always goes out), and
the bridge writes `requests/emoji-notice-*.json` — the assistant sees, in a file
(it does not read the stdout log), that the emoji was invalid and 👍 was
substituted. `pending_eyes` skips `emoji-notice-`.

## v1.19.0 — 2026-08-23

**A list of open eyes on EVERY request (`open_eyes`).** 👀 = not handled, and the
operator navigates by it. `pending_eyes` saw only the fresh ones in `requests/`,
while those moved to `served` after 6 h dropped out of the report and became
invisible — 115 unclosed eyes accumulated that way in one session. Now
`open_eye_backlog(chat_id)` counts the WHOLE open set (addressed, given a 👀,
MINUS those closed through `answers`), from files, with a 10 s cache, and the
`open_eyes=[id…]` field is put into every request to me. Nothing is lost that
way, and the ones that fired do get closed. The operator's design. The close path
is untouched.

## v1.18.0 — 2026-08-23

**The approver of a rule or grant must be a REAL approver, not merely a non-empty
field.** `rule_for`/`grant_for` checked only that `added_by_user_id` was NON-EMPTY;
an arbitrary non-zero id (a corrupted `grants.json`/`rules.json`, a hand edit
around the gate) used to pass and the file went out. Now the id must be an
approver of at least one chat (`config.all_approvers()` — the union across chats).
Backward compatible: live rules from the principal pass (they are an approver of
both chats); a "folder→group" rule approved in a private chat still works.
`test_attach` pins it: an id outside the approvers is refused.

The finding came from TWO independent methods — a security lens (#2, deferred as
defence in depth) and a blind atomic decomposition of the same code (R8/G7: "the
code checks non-emptiness but not the authenticity of the approval"). They agreed,
so it was closed.

## v1.17.0 — 2026-08-23

Closes the race on the state books deferred in v1.16 (a finding of the "races"
lens).

**One lock and an atomic write for grants.json / rules.json.** These lists are
edited read-modify-write from TWO threads: the main one (`_close` via `decide`)
and the pump (`spend_grant`, and `sweep_proposals`→`_close`). Without a shared
lock two threads read the same list, each appended its own entry and wrote over
the other — an edit was lost. The worst consequence: `spend_grant` sets `used_at`
while a concurrent `_close` overwrites the list without it — **a one-off consent
came back to life**, and the file could go out again without a new "yes". Now
`_STATE_LOCK` (an RLock) serialises every edit, and `_atomic_write` (tmp →
`os.replace`) prevents a reader (`rule_for`/`grant_for` in the pump) from seeing
half a file.

**A decision is made exactly once.** Two paths race to close one proposal: the
mark (`decide`, main thread) and expiry (`sweep_proposals`, pump). Whoever takes
the lock first decides; the loser finds the `decided/` record already written and
leaves. There is no more mixed state in which the consent book says EXPIRED while
a grant has nonetheless been created. `test_locks.py` pins it: a repeated `_close`
neither duplicates the grant nor overwrites the verdict.

## v1.16.0 — 2026-08-23

A pass over the code through five lenses (races, resources, correctness,
security, silent failures). Thirteen real bugs found and closed; 8/8 tests green,
`test_eyes.py` added (13 checks).

**The mark lies less.** Three repairs of one class, "did it ≠ recorded it". A file
answer carrying `answers` silently did NOT close the request (the file branch of
`flush_outbox` had no `clear_inbox`) — the eye hung, and twenty minutes later a
false "nobody picked it up" flew. A `.react.json` cleared the inbox even when the
mark had NOT landed (it did not look at `how`) — "answered" written over
emptiness. And `clear_inbox` now sets the mark BEFORE the move into `served`
rather than after: a failed ack no longer leaves an empty inbox under a burning 👀.

**A reminder's receipt counts only from an approver** (`_seen`). The docstring
promised "the principal reacted" while the code accepted ANY reaction — in a group
a stranger could silently cancel an escalation. Three lenses found it separately.
We now require an `approver`, which also cuts out the bridge's own marks.

**Delivery no longer dies on a naive date.** `rule_for` caught only `ValueError`,
while a deadline without a timezone raises `TypeError` — it escaped `flush_outbox`
and cut off EVERY send on every pass. We normalise to UTC.

**Silent losses, spoken aloud.** A voice note that failed to download used to be a
bare `return` (leaving the sender on 🤔 for ever): now a log line and a word to
them. A job thread died silently and took the message with it: the `_guarded`
wrapper prints the traceback. A broken or foreign outbox item went into an endless
retry: it is quarantined in `outbox/rejected/` — with the safeguard that a broken
`chats.json` (an empty list) is NOT quarantined, or the whole outbox would be
poured away. A broken `chats.json`/`settings.json` now shouts its reason instead
of going mute.

**Less leaking, less breaking.** The anti-flood dictionaries are cleaned (they
grew without bound). `log_line` runs under a lock — long lines from threads no
longer interleave into broken JSONL. Service wake-up requests
(`reaction-`/`control-`/`verdict-`/`pending-eyes-`) are swept out of `requests/`
by age (`SERVICE_REQUEST_KEEP_HOURS`; `needsfile-` is NOT touched — that is an
open request).

**An honest calibration:** the lens reported "service requests accumulate" as
HIGH; measured, `pending_eyes`/`nudge` already skip them and there are no false
eyes → in fact LOW.

## v1.1.0 — 2026-08-22

The first version of our own line after `v1.0.0` (an exact copy of the serving
tree). The work happened in the dev tree; the serving tree was not changed.

**Attachments — files and images.** The bridge read only `text` and `caption`, so
an image without a caption arrived as an EMPTY request. That had already cost a
loss: on 2026-08-21 a screenshot from a third party landed in the inbox as
emptiness and was closed as "nothing to answer". Now images, documents, video and
audio are downloaded into `media/<request>/`, enter the request through a `files`
field carrying name, size, type and digest, and when there is no caption the
request describes itself and is never empty.

The trust boundary moved from text to bytes; what holds it is in `PROTOCOL.md`,
including the rule "reading is allowed, executing never is" and the explanation of
why a list of forbidden extensions was considered and rejected.

**The signature is configurable per chat, and an empty signature works.**
Previously `pol.get("reply_prefix") or C.REPLY_PREFIX` silently returned the name:
an empty string is falsy in Python. Now the PRESENCE of the key is checked, and
"configured to empty" differs from "not configured". Both outward signatures — text
to be sent on, and a relay of someone else's words in translation — are chosen
earlier and are untouched: text that will travel outward must say whose it is.

Two functions were extracted so the decision could be tested rather than
contemplated: `outgoing_prefix(pol, item)` and `compose(prefix, text)`.

**Tested offline, with no network:**

    test_gate.py     20 passed, 0 failed   (the consent gate, untouched)
    test_attach.py   25 passed, 0 failed   (attachments, a name as data, the signature)

`test_attach.py` was created by this version.

## v1.2.0 — 2026-08-22

**The attachment sweep goes by OVERFLOW, not by age** (the operator's word: "not
by age but by overflow, allot however many bytes you need yourself"). A budget of
2 GiB: with a 20 MB ceiling per file that is a hundred of the largest attachments
or some seventeen thousand screenshots at their present size. Ordinary use will
never reach it; a runaway sender reaches it quickly and eats no disk.

Three rules for the sweep: a request's directory is deleted whole (the
attachments of one message are one thing); **a request's directory that has not
been answered yet is never touched**; and every deletion is printed with its size,
because a silent sweep is indistinguishable from a loss. If there is nothing to
clear and the space has run out, the bridge says so out loud rather than
accepting it in silence.

**Found along the way and fixed: `sweep_old_files` had been written and NEVER
CALLED.** Its docstring promised that voice would not pile up for ever; the
promise held only because the bridge was young and had not lived thirty days yet.
Both sweeps are now called on the same tick as the expiry of proposals.

    test_gate.py     20 passed, 0 failed
    test_attach.py   34 passed, 0 failed   (+9 for the sweep)

## v1.3.0 — 2026-08-22

**The bridge learned to GIVE files back.** Since v1.1.0 it accepted them but did
not send them; to "send the file into the chat" the honest answer was "I cannot".
Now both directions work.

`send_file(chat_id, path, caption, as_photo)` — multipart assembled by hand, with
no third-party libraries; a separate function rather than a parameter to `call`,
because an ordinary call encodes its fields as urlencoded and a file cannot
travel that way. Mixing two ways of talking to one API would hide a difference
that bites later.

The caption is cut to 1024 characters IN ADVANCE — that is what the Bot API
allows. Otherwise the server would refuse the whole request and the file would
not go out because of one extra line of text.

The outgoing queue gained a `file` field; a failure renames the queue file to
`failed-*` rather than staying silent.

    test_gate.py     20 passed, 0 failed
    test_attach.py   39 passed, 0 failed   (+5)

## v1.4.0 — 2026-08-22

**A gate on sending files, and the confirmation moves from the instance to the
RULE.** The operator's word: "files are not letters any more, there has to be
protection against a fool… but a confirmation every single time is a pain. It
should go by a book of rules: for this project just send, ask about something
new, and about what was agreed earlier and is ready in the folder do not ask at
all."

The design. An empty book allows NOTHING — by default everything is asked about.
A rule binds three things, all of them required: the receiving room, the source
directory and a name pattern. A rule of the "anything anywhere" kind simply
CANNOT BE EXPRESSED in this format — the field is mandatory, and a prohibition
that cannot be walked around by forgetfulness is sturdier than one that has to be
remembered.

**A rule cannot come from the assistant.** It is written by the bridge and only
on the operator's mark, together with their numeric id, the mark itself and the
proposal's number. A rule with no approver is skipped with a scandal in the log.
The same prohibition stated for warrants: the constrained party does not
manufacture the object that constrains it.

The path is resolved to its real form before comparison, so
`allowed-folder/../../anything` does not pass. An unreadable expiry date is read
AGAINST sending.

A rule settles the question IN ADVANCE — so the only check left is AFTERWARDS,
and it must exist: every send under a rule writes a line into `sent_by_rule.log`
with the rule's number. Otherwise a standing permission becomes a blind spot.

`./propose.py --file-rule <directory> --to <room> [--glob] [--why] [--until]`

    test_gate.py     20 passed, 0 failed
    test_attach.py   50 passed, 0 failed   (+11 on the gate, including .. traversal)

## v1.7.0 — 2026-08-22

**A batch: one mark — one delivery.** The operator: "if five files have to go to
someone, will you ask once or all five times?" It asked five times, and that is a
mockery.

But "one mark for a list" could not simply be built: this very file has said from
day one that a mark under a list of five items becomes a rubber stamp within a
week. The difference that settles it: five DIFFERENT matters under one mark is a
stamp; five files of ONE delivery into ONE room are one matter with five parts.
The unit of consent is the one a person thinks in, not a number of bytes.

Three conditions, each closing its own hole:

    one recipient per batch    mixing rooms is forbidden — that is where the
                               mistake hides
    every file is named        name, size, digest right in the proposal;
                               the mark covers WHAT WAS SEEN
    one-off and by digest      swapping a file after the mark does not pass,
                               and the same grant will not fire twice

The ceiling `batch_max` = 10. A list too long to read with your eyes is a stamp,
whatever it is called; for a stream of files one makes a RULE on the folder, not a
bigger batch.

One-off grants live in `grants.json` SEPARATELY from rules on purpose: a rule
describes a class and holds from now on, a grant is named by a digest and is
spent once. In one file, a month later, the two would be indistinguishable.

`./propose.py --batch f1 f2 … --to <room> [--why ...]`

    test_gate.py     20 passed, 0 failed
    test_attach.py   69 passed, 0 failed   (+7 on batches, including a swap and a repeat)

## v1.8.0 — 2026-08-22

Three things, by the operator's word "all three".

**A dead end I built myself that morning.** A refused file landed in
`needs_consent/` and stayed there: no line in the inbox, no way back. A dead end
nobody knows about is indistinguishable from a loss. Now a refusal WAKES the
assistant — a request in the inbox names the file, the room, and the ready command
to hang it on a mark.

**The mark no longer lies.** 👀 means "stored, and it will be answered" — that is
a promise, and if the assistant is not running there is nobody to keep it, while
from outside a person cannot tell "being read" from "forgotten". The bridge, the
one party here that is certainly alive, speaks for itself: "received, but for N
minutes nobody has picked it up". ONCE per message — otherwise it is a nuisance
that gets switched off. The threshold is 20 minutes.

**The tamper watch refuses rather than warns** (`drift.py`, §7 of the owner's
decision). The bridge compares the digests of thirteen of its files against the
approved state BEFORE the first network call and does not start on a divergence:
its own exit code 90, a record in `drift_refusals.jsonl`. The absence of an
approved state is also a refusal, not a default allow. A broken watch is a refusal
too (code 91): a watch that lets things through when it is itself broken guards
only in fair weather. The watch watches itself as well.

The honest boundary is named in the file itself: it does NOT protect against
anyone with access to the directory. It catches an edit that bypassed the
rollout — exactly the kind of failure we were caught by on 2026-08-21.

    test_gate.py     20 passed, 0 failed
    test_attach.py   77 passed, 0 failed   (+8)
