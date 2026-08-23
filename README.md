# Telegram bridge for an AI assistant

A small bridge that lets you reach your AI assistant from any device through
Telegram, and lets it reach you — with boundaries that hold when nobody is
watching.

Python standard library only. No dependencies, no framework, no server.
Linux, macOS and Windows.

## What it actually does

    Telegram → tg_bridge.py → tg_log.jsonl      the whole allowed chat
                    ↓
                requests/*.json                  messages addressed to it
                    ↓
    Telegram ← outbox/*.json  ← the assistant

**The bridge holds the token; the assistant never sees it.** The assistant
reads files and writes files. If it gets something wrong, it gets it wrong in
a file rather than in someone else's chat.

Three things run whether or not the assistant is awake: receiving and logging,
the 👀 "recognised" mark, and **reminders**. Replies need the assistant.

## Install

1. **Create a bot.** Open `@BotFather` in Telegram → `/newbot` → pick a name →
   it gives you a token.

2. **Run setup.**

       python3 setup.py

   It asks for the token, asks **what the assistant should be called** and
   whose it is, then asks you to write a message so it can find your `chat_id`
   itself — that is the one number no client shows you. It writes
   `settings.json`, `chats.json` and `token.txt`. It does not edit any Python.

   **The name you choose here is how you reach it.** In a shared chat you
   address the assistant by starting a message with that name (e.g. `Logic, …`);
   in your own private chat every message counts. See **How to address it**
   below for the exact rules.

3. **Watch it before it speaks.** Setup leaves `dry_run` on: the bridge reads,
   filters and logs but sends nothing. Run it, write a few messages, look at
   `tg_log.jsonl` and `requests/`.

       python3 tg_bridge.py

4. **Let it speak.** Set `"dry_run": false` in `settings.json`.

5. **Autostart** (Linux). The bridge is needed when your assistant's session
   is closed — reminders in particular.

       cp logic-bridge.service ~/.config/systemd/user/
       # fix the paths inside it if the project lives elsewhere
       systemctl --user daemon-reload
       systemctl --user enable --now logic-bridge
       loginctl enable-linger $USER

   `enable-linger` is not optional: without it user services stop when you log
   out, and a reminder scheduled for the evening never arrives.

       systemctl --user status  logic-bridge
       systemctl --user restart logic-bridge     # after editing the code

   **Stop the service before running the bridge by hand** — two processes
   polling one token conflict.

### For groups

- `@BotFather` → `/mybots` → your bot → Bot Settings → **Group Privacy: off**,
  otherwise the bot only sees messages starting with a command.
- To receive **reactions** in a group the bot must additionally be an
  **administrator** there. In a private chat no rights are needed (measured).
  If admin is not possible, approve with a word instead of a mark.

## How to address it

In a **one-to-one chat** with the bot, nothing is required: there is nobody
else to be talking to, so every message is addressed to it. Set
`"all_addressed": true` for that chat.

In a **room**, three things count as addressing it — the name is only one:

Start the message with the assistant's **name**, and only at the start:

    Logic, what did we decide about the deadline?
    Logic remind me at 15:30 that I need to leave

Case is ignored. Whatever follows the name and its punctuation is the
question. A name in the middle is not an address: "we should ask Logic" is
talk about it, not to it, and neither is "logically speaking" — the name must
end where it ends, with no letter or hyphen following.

**Replying** to one of its messages also counts, with no name needed. A reply
points at a specific message and says "I am talking to you" more exactly than
a name at the front of a sentence.

**A voice note** in the principal's private chat always counts, and the name
need not be spoken: a transcript spells a name however it pleases, and relying
on that would drop real messages.

A 👀 appears — placed by the bridge, not by the assistant — **once the request
is written to disk**, never before. It therefore means "stored, and it will be
answered", not "bytes seen". A mark that fires before delivery is a documented
failure of at least one shipped Telegram bridge: the user sees the eyes and
believes the message landed when it did not.

If the assistant wakes and judges that the message was not addressed to it
after all, it **withdraws** the mark (`./unreact.py`). The bridge is fast and
cannot judge; the assistant can judge and is slow. Neither has to be both. Telegram's own delivery tick
appears on every message including "this one is not for you"; the mark appears
only on a real address, so its absence tells you something too.

Replies are signed so a shared chat always shows who is speaking:

    Logic AI(Your Name): ...

## Voice notes

Send a voice message and it is transcribed and treated exactly like text. This
is **optional**: transcription runs as a subprocess under an interpreter named
in `settings.json` (`whisper_python`), so the bridge itself keeps no
dependencies, and the model never occupies the daemon's memory.

    pip install faster-whisper        # in whatever environment you prefer

`setup.py` checks this and records which interpreter can do it. The bridge
prints the answer **at startup** — a capability the user discovers is missing
mid-conversation is a capability nobody checked.

Without it, audio is saved and the sender is told plainly that it cannot be
read. Two marks appear, and both are true when placed: 🤔 "heard you, working
on it", then 👀 "transcribed, stored, will be answered".

Measured on this hardware: about 3.5 s for a short note with the `small` model
on the CPU. **The GPU was measured six times slower** (13.5 s versus 2.2 s) —
each call loads the model afresh, and for short clips that load costs more than
the recognition. Do not "improve" this without measuring it.

## Reminders

You ask in words; the assistant converts that to an exact time and drops a
file in `reminders/`. **The bridge waits and sends it** — not the assistant.

That is deliberate. A reminder that depends on the assistant waking up dies
with its session, while a person was counting on it. The bridge survives a
closed window and a reboot.

## Marks as answers

Not every message deserves a paragraph. "Understood", "agreed", "thank you"
cost the reader nothing as a mark and real attention as prose.

    ./react.py last 👍
    ./react.py <message_id> 🤝

The assistant's chosen mark **replaces** the bridge's automatic 👀 — a bot
holds one reaction per message. That separation is useful rather than
limiting: 👀 means "received and stored", placed by the bridge; anything else
means "read, and here is what I think", placed by the assistant.

**A reply takes the eyes off by itself.** When an outbox file names the
request it answers (`"answers": [...]`), the bridge clears it from the inbox
**and** replaces 👀 with a completion mark — 👍 by default, or whatever
`done_emoji` says. This is automatic because the manual version failed: the
rule was written and broken one message later. Anything that depends on
remembering will eventually not be remembered.

**The mark means DONE, not doing.** 👀 stays for as long as the work lasts;
replacing it says the work is finished, and nothing else replaces it. An
earlier vocabulary mixed the two — "accepted, will do" sat beside "understood"
and from the outside they were the same picture. A mark that might mean either
is worse than no mark, because the reader stops checking: he sees a mark,
assumes it is done, and finds out otherwise later. If something will take a
while, say so **in words**; a mark cannot carry "still working" without
ruining what every other mark means.

`./react.py` with no arguments prints the working vocabulary. One rule is not
negotiable: **disagreement is not a mark.** A 👎 with no words is a refusal
pretending to be an answer.

When the principal reacts to one of the assistant's messages, the bridge marks
it seen at once **and wakes the assistant** — a reaction is an act, and 👍 on a
claim is agreement, not noise. Deciding not to answer is then part of the job:
a mark that closes an exchange must not reopen it.

## The inbox

`requests/` is an inbox, not a pile. A request leaves it only when a reply
**names** it — an outbox file carrying `"answers": ["<request_id>"]`. So what
is still owed is a fact on disk rather than something the assistant believes.

    ./pending.py
    ./pending.py --close <id> "why"

The second form closes a request **without** answering it, and the reason is
required. Deciding not to answer is a real decision — a 👍 that ends an
exchange should not be met with a paragraph — but without a way to record that
decision, a deliberately unanswered request looks exactly like a forgotten one,
and the inbox starts lying in the other direction. "Closed" with no reason is
indistinguishable from "lost", which is the failure this inbox exists to
prevent.

This exists because belief failed. Two requests arrived in the same moment, one
was answered, the other silently dropped, and the sender had to ask whether he
had been heard. Attention is the wrong place to keep that record — it fails
precisely when two things arrive at once, which is exactly when it matters.

## Editing what was already sent

    ./edit.py last "the corrected text"

Telegram lets a bot edit only its own messages; a message written by a person
is untouchable from any bot, at any price.

**A proposal is never editable.** If the text behind a mark could change after
the mark was placed, the mark would certify nothing — approve version A, act on
version B. The bridge refuses such an edit itself rather than trusting whoever
asked to remember the rule.

## Boundaries: who may do what

Full account in **`PROTOCOL.md`**. In short: **the gate stands on the action,
not on the sender.** Anyone in an allowed chat may talk to the assistant,
including someone else's human and someone else's AI. An act with consequences
**outside the chat** happens only on the principal's mark, no matter who asked.

Splitting by sender — "an order from an AI needs a mark, from a human it does
not" — is tempting and leaky: a guest human then commands freely although they
are not the principal. The right to direct is not conferred by the sender
being human; that is the provenance of the message, not the authority to issue
it.

Per-chat exceptions go in `chats.json` (see `chats.json.example`); defaults are
`CHAT_DEFAULTS` in `config.py`.

## The consent gate

    ./propose.py "email Sam the signed contract"

    → the bridge sends "I PROPOSE: ..." and remembers it by message id
    → 👍  the bridge instantly places 👀 ("mark received"), records the
          verdict and wakes the assistant
    → 👎  refused
    → 24 hours of silence  expired

**The bridge records consent; it does not execute.** A daemon that performs
arbitrary actions on a reaction is a far larger surface for harm, and there is
nothing to gain: the assistant only acts outward while it is awake anyway.

Rules without which this rots — the reasoning is in `PROTOCOL.md`:

- **one mark, one bounded action.** A mark under a list of five items becomes
  a rubber stamp within a week, the known fate of every "approve in one click";
- **the mark goes on the assistant's line**, not on someone else's prose, so a
  misunderstanding is visible before the act;
- **no mark means no.** Expired means no;
- **approvers are matched by numeric id**, never by name — people choose their
  own display names. In a private chat that hardly matters; in a **group** it
  decides everything. An anonymous admin arrives with no `user` field: nobody
  to identify, so no approval;
- **a mark transfers responsibility to the human who placed it.** That is the
  point, and it is also the cost. An unread mark is worse than no mark;
  `./gate_health.py` measures whether that is happening instead of trusting
  that it is not.

## Security, and what it does not cover

**What holds.** The token lives in one file, tightened to owner-only on every
start; the assistant never sees it. Chats not in `chats.json` are never read,
and the filter sits before the write to disk. Approvers are matched by numeric
id. Nothing is executed on anyone's say-so — the bridge records consent and
performs no action.

**Rate limits are obeyed rather than fought.** A 429 carries the number of
seconds to wait; the bridge waits exactly that and tries once more. The earlier
version treated 429 as an ordinary failure and left the message in the queue,
so it went out again a second later — one refusal became a storm. Sends to the
same chat are also spaced, because nobody reads five messages in one second.

**What does NOT hold, stated plainly:**

- **Anyone who can write to `outbox/` can speak as the bot.** That is the
  filesystem's boundary, not this program's; whoever has that access has the
  token too.
- **The topic boundary is not enforceable by machine.** The bridge puts each
  room's subject into every request; keeping to it is the assistant's own
  discipline, and that is the weakest link here. A guest's message is data,
  but it is data the assistant reads.
- **The consent gate constrains the artifact, not the reader.** It ensures the
  assistant does nothing unapproved; it cannot control what a person does with
  an answer.
- **A compromised machine is a compromised bot.** No part of this defends
  against someone who already has your files.

**Sealing old history (optional, off by default).** `./seal.py --days 30 --do`
encrypts conversation older than N days to your own GPG **public** key and
removes the plaintext. Public-key, because the bridge must read the live log on
every message: a key that has to sit beside the data protects against nobody.
The private half is never needed here and does not have to be on this machine.

It covers a stolen disk, a leaked backup, a machine sold or repaired. It does
not cover malware running as you — that reads the live log and needs no key.
Your key needs an **encryption** capability; a sign-only key cannot do it.

Read the warning in the file first: sealing deletes the plaintext, so a lost
key is lost history. Encryption is also a way to destroy data. Nothing runs on
a schedule and nothing runs without `--do`.

**Encrypting anything is pointless on an unencrypted disk.** Check that first.

**What is kept, and for how long.** The conversation log is never pruned — it
is the record. Saved audio and sent/served bookkeeping are deleted after
`keep_days` (30 by default), because a minute of voice is a hundred kilobytes
and a bridge that quietly fills a disk over a year stops one morning for a
reason nobody connects to voice messages.

## Privacy

The bridge logs **the whole** allowed chat, not only messages addressed to the
assistant — context is what makes the answers worth anything. Therefore every
new chat receives a **one-time notice** saying so, before anything from it is
stored. Edit the wording in `config.py`; do not remove it.

Chats that are not in `chats.json` are ignored entirely — the filter sits
**before** the write to disk, so they never reach the log.

## What it does not do

- does not write to chats outside `chats.json`;
- does not start conversations — it answers when addressed;
- does not keep the token in any file that belongs in a repository;
- **does not execute actions** — it records consent to them;
- does not create a direct channel between two AIs.

## Files

    setup.py              first-run setup; writes the JSON, edits no Python
    LICENSE               Apache License 2.0
    config.py             defaults and paths
    tg_bridge.py          the bridge
    propose.py            hang a proposal on the consent gate
    react.py              answer with a mark instead of words
    edit.py               rewrite one of the assistant's own messages
    unreact.py            withdraw a mark from a message that was not an address
    gate_health.py        is the gate still a decision, or a reflex?
    pending.py            what is still owed an answer
    seal.py               seal old history under your own GPG public key
    test_gate.py          test the gate without Telegram (9 checks)
    PROTOCOL.md           who may do what, and why
    logic-bridge.service  systemd unit for autostart

    settings.json         name, operator, signatures, triggers,
                          dry-run, whisper interpreter          (yours)
    chats.json            allowed chats and their boundaries  (yours)
    token.txt             the bot token                       (yours)

    tg_log.jsonl          the log of allowed chats
    requests/             THE INBOX — addressed messages awaiting an answer
    served/               requests a reply has named, cleared from the inbox
    outbox/ sent/         replies waiting to be sent / already sent
    reminders/            schedule; the BRIDGE sends these
    proposals/ decided/   pending and settled proposals
    reactions.jsonl       every reaction, with the id of who placed it
    voice/                voice notes, kept beside their transcripts

## Do not commit

`settings.json`, `chats.json`, `token.txt`, `tg_log.jsonl`, `reactions.jsonl`,
`requests/`, `outbox/`, `sent/`, `proposals/`, `decided/`, `reminders/`.
These are your conversations, your identifiers and your credentials. The
supplied `.gitignore` already covers them.

## Tests

    python3 test_gate.py

Nine checks on the consent gate with the network stubbed out. It exists
because the expiry branch guards "no mark means no" and had never once
executed in live use — a day had not yet passed. A branch that guards a safety
property and has never run cannot be called working.

## Provenance

Built by Vitaly Reznik with AI assistance (Claude Opus 5), August 2026.

The comments in the code are part of what is being handed over, not decoration.
Most of them record **why** something is shaped the way it is, and several
record a mistake that shaped it — a single timeout sized for the long poll that
froze the sending thread, a mark placed by the assistant instead of the bridge
so that "seen" arrived late, an approver matched by display name instead of
numeric id. Deleting them leaves code that looks arbitrary and invites the same
mistakes back.

## Licence

Apache License 2.0 — full text in `LICENSE`.

    Copyright 2026 Vitaly Reznik

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.
