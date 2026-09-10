# LogicBridge — deferred (the bridge is FROZEN; build nothing without a word)

The bridge is frozen pending a decision on its warrant. Requests are collected
here so they are not lost. **Do not implement anything without the operator's
word.**

## 1. Attachments: files and images (the operator, 2026-08-21 23:37 — "this matters, to be of real use")

**As it stands.** `handle()` takes only `msg["text"] or msg["caption"]`. An
image with no caption arrives as an EMPTY request — and that has already caused
a failure: request 364 (an image from a correspondent) was closed as "emptiness".
The bridge does have `getFile`, but it was built for voice and for voice only.

**The shape, if it is to be built.** Download `photo` / `document` /
`video_note` through the same `getFile` into `media/<request_id>/`, put a
`files: [paths]` field into the request and leave the caption in `ask`. The
assistant then reads the file from disk by ordinary reading.

**What must be decided BEFORE any code (this is not a detail):**
- **The trust boundary.** Downloading turns the bridge from a receiver of TEXT
  into a receiver of ARBITRARY BYTES from someone else's machine. It needs a
  size ceiling, an allow list of types and an explicit refusal for executables.
- **Who sent it.** In a group chat a file comes from any admitted person; at
  present that is not distinguished at all.
- **What the assistant may do with it.** Read — yes. Execute — never. That must
  be written into PROTOCOL.md rather than left implied.

The workaround for today: the operator saves the file to disk and names the
directory.

## A silently swallowed outbox message (found 2026-08-22)

An item was put into `outbox/` with the keys `path` + `caption` instead of
`file` + `text`. The message **vanished without a trace**: it did not go out, it
did not stay in the outbox, it reached neither `sent/` nor `needs_consent/`, and
**no line appeared in `bridge.out`**. It only came to light because someone went
looking in `sent_by_rule.log` on purpose.

This is exactly the class of failure the bridge must not allow: a silent refusal
with no reason. The cure is to move an unrecognised item into `outbox/rejected/`
with a `reason` field and write a line in the log. The shape is simple and worth
checking explicitly:

    text:  {"chat_id": N, "text": "..."}
    file:  {"chat_id": N, "file": "/absolute/path", "text": "caption"}

The keys `path` and `caption` are NOT recognised.

## Requests not marked answered -> false "nobody picked it up" (2026-08-22)

The bridge keeps requests/*.json until someone clears them, and
nudge_unanswered() sends "received, but nobody picked it up" after 20 minutes.
Answers were written as outbox files with arbitrary names WITHOUT clearing the
original request — so the operator kept getting false reminders about messages
that had already been answered (689, 690, 698, 700, 703...). They were cleared
by hand, moved into served/.

The durable fix (needs the operator's word, it changes behaviour): either the
outbox answer carries an "answers": [stem] field and the bridge moves exactly
those requests into served/, or flush_outbox, on answering into chat X, clears
that chat's requests older than the answer. The first is precise, the second
does not depend on anyone's discipline. Do not build it in silence.
