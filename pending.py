#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""What is still owed an answer.

    ./pending.py

requests/ is the inbox: a file leaves it only when a reply names it. So this
lists what has actually been left unanswered, rather than what the assistant
believes it has dealt with.

It exists because belief failed. Two requests arrived in the same moment, one
was answered, the other was silently dropped, and the sender had to ask whether
he had been heard at all. Attention is the wrong place to keep that record.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, timezone

import config as C


def main() -> int:
    if "--zone" in sys.argv:
        i = sys.argv.index("--zone")
        rest = sys.argv[i + 1:]
        return declare(rest[0], rest[1:]) if rest else declare("", [])
    if "--close" in sys.argv:
        i = sys.argv.index("--close")
        if len(sys.argv) < i + 3:
            print('usage: ./pending.py --close <request_id> "why"')
            return 2
        emoji = sys.argv[i + 3] if len(sys.argv) > i + 3 else "👍"
        return close(sys.argv[i + 1], sys.argv[i + 2], emoji)
    rows = []
    for f in sorted(C.REQUESTS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        # A real request carries "at"; the bridge's own synthetic files
        # (control-*, pending-eyes-*) do not. d["at"] on those used to bring
        # down the WHOLE report, blinding the watch exactly when something was
        # waiting in the queue.
        at = d.get("at")
        try:
            age = ((datetime.now(timezone.utc) - datetime.fromisoformat(at))
                   .total_seconds() / 60) if at else None
        except Exception:
            age = None
        name = f.stem
        kind = ("eyes" if name.startswith("pending-eyes")
                else "control" if name.startswith("control-") else "request")
        summary = (d.get("ask") or d.get("text") or "")[:56].replace("\n", " ")
        rows.append((age, kind, name, d.get("chat_id"), summary))
    if not rows:
        print("nothing owed — the inbox is empty.")
        channel_watch()
        return 0
    mine = zone()
    print(f"{len(rows)} awaiting an answer (oldest first):\n")
    for age, kind, rid, chat, summary in sorted(
            rows, key=lambda r: (r[0] is not None, r[0] or 0.0), reverse=True):
        age_s = f"{age:6.0f} min" if age is not None else "   ?   min"
        tag = "" if in_zone(chat, mine) else "  << NOT YOUR ZONE"
        print(f"  {age_s}  [{kind}] {rid:30} chat {chat}{tag}\n"
              f"              {summary}")
    print("\nTo clear one, put \"answers\": [\"<id>\"] in the outbox file that replies to it,")
    print("or close it without replying:  ./pending.py --close <id> \"why\" [emoji]")
    channel_watch()
    return 0


def channel_watch() -> None:
    """One line about the correspondent's channel, in the report I already read.

    NOT A SECOND WATCHER. A watcher already runs on that folder — the other
    operator's, four days old — and two writers into one mirror was the thing
    to avoid. This adds no process and writes nothing: it asks the placement
    tool for its numbers at the moment I am already looking at this report.

    IT SPEAKS ON ZERO TOO. Silence would be indistinguishable from the call
    having been deleted, and from the tool being unimportable — three very
    different states reading as one all-clear. So the clean case prints the
    baseline's date: a check pinned to a stale baseline then says so itself,
    instead of shining green at a subject that has moved on."""
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent
                              / "veip-use"))
        import place_outward
        st = place_outward.state()
    except Exception as e:                      # never break the real report
        print(f"\n  channel: NOT CHECKED ({type(e).__name__}) — "
              f"veip-use/place_outward.py did not answer")
        return
    if not st["taken"]:
        print("\n  channel: no baseline taken — run "
              "veip-use/place_outward.py --baseline")
        return
    # THE ALARM IS ONLY ABOUT US. "Appeared", never "placed" — the folder
    # syncs with the correspondent's machine and he writes into it himself:
    # the first two files this line ever reported were his own superseding
    # revisions. And he does it constantly — 117 files in one day, measured by
    # the channel's operator. An alarm that cannot tell his normal work from
    # our unrecorded placement fires daily on another person's correspondence
    # and is switched off within a week, leaving the real case unwatched.
    #
    # Ours are the ones whose original exists in our own trees, which is the
    # exchange contract's own clause: "the sender keeps the original outside
    # the folder". His are counted on the same line, quietly.
    # THE SUMMARY NAMES EVERY AREA AND PRINTS EVERY ZERO. The old one read
    # "clean (1641 files, baseline 2026-09-22)" and the channel's operator
    # could not tell from it what 1641 counted, where the two known arrivals
    # sat, or whether an absent figure meant zero or meant unprinted. That is
    # the defect this instrument exists against, reproduced in its own status
    # line — the numbers are separated inside the tool and run together in the
    # report, which leaves the reader exactly where they started.
    ours = len(st.get("ours", []))
    head = (f"{ours} OF OURS placed since the baseline with no record"
            if ours else "nothing of ours placed without a record")
    print(f"\n  channel: {head}")
    # TWO AXES, NOT ONE: whose a file is, and whether anyone recorded that.
    # The first version printed "0 his" beside "2 identified" where those two
    # were his — a contradiction on its face, because one bucket was named by
    # side and the other by record.
    print(f"    {st['total']} scanned = {len(st['old'])} predate the baseline"
          f" · {st['authorized']} authorized · since then — his:"
          f" {len(st.get('theirs_named', []))} on record,"
          f" {len(st.get('theirs', []))} not · ours:"
          f" {len(st.get('ours_named', []))} on record, {ours} NOT")
    if not st.get("sums", True):
        print(f"    parts total {st['parts']}, which does NOT match the scan")
    for rel in st.get("ours", [])[:3]:
        print(f"      {rel}")
    if ours > 3:
        print(f"      … and {ours - 3} more")


def owner():
    """(pid, start-time) of the session process that owns this invocation.

    WHY NOT JUST A FILE NEXT TO THE SCRIPT. The first version of the zone
    label kept `.zone` beside this module — one path for a tree that TWO
    operators share. Whatever it held was therefore true for one of them and
    INVERTED for the other: with `only <private chat>` in place, the room
    operator's own rooms came up marked "not yours" and the other operator's
    private chat came up as theirs. A label is read, not re-verified, so a
    wrong label is worse than none. Found the same day it shipped, by the
    other operator, before it misled anyone twice.

    The owner is the nearest ancestor whose executable is `claude` itself —
    not the shell wrapper, and not `claude-desktop`, which is one process for
    every session and so cannot tell them apart.

    Returns None wherever this cannot be established. Every unknown answers
    "no zone", never a guessed one: see zone().
    """
    try:
        pid = os.getpid()
        for _ in range(12):
            stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
            after = stat.rsplit(")", 1)[1].split()
            ppid, start = int(after[1]), after[19]
            if os.path.basename(os.path.realpath(f"/proc/{pid}/exe")) == "claude":
                return str(pid), start
            pid = ppid
            if pid <= 1:
                return None
    except Exception:
        return None
    return None


def zone():
    """Which chats this operator owns, or None when nothing is declared.

    WHY THIS EXISTS. The queue is shared but the DUTY is not: two operators
    split it with `queue_watch.py --only/--except`. That split decides who is
    WOKEN. It never decided who is LISTED, so this report showed the whole
    queue with no owner on any row — and on 2026-09-21 one operator read four
    rows as four duties, answered three chats belonging to the other, and
    stated that side's work as undone while it was in fact being delivered.

    The chat id was on the row the whole time. That is the argument for a
    label rather than a reminder: the information was present and still read
    wrong, so the guard belongs where the reading happens.

    Declared per OPERATOR, never per tree — `.zone-<pid>`, written by
    `--zone only <chat>` / `--zone except <chat>`, in the same two words the
    watcher already uses. The file also records the owner's start time, so a
    reused pid cannot inherit a dead session's zone — that would recreate the
    inverted label this keying exists to prevent.

    NO FILE, NO CHANGE: without one, every row is unmarked exactly as before.
    Anything unreadable, malformed or mismatched answers None for the same
    reason — a guessed zone marks real duties as someone else's.
    """
    own = owner()
    if own is None:
        return None
    pid, start = own
    try:
        parts = (pathlib.Path(__file__).resolve().parent / f".zone-{pid}"
                 ).read_text(encoding="utf-8").split()
    except Exception:
        return None
    if len(parts) < 3 or parts[0] != start or parts[1] not in ("only", "except"):
        return None
    chats = parts[2:]
    if "as" in chats:                      # trailing `as <operator>` is optional
        chats = chats[:chats.index("as")]
    return (parts[1], {c.strip() for c in chats if c.strip()})


def operator():
    """The name this session acts under, or None when it has not declared one.

    ONE PLACE FOR "WHO AM I". The zone file already answers "which chats are
    mine"; the author of an outbound action is the same question asked the
    other way round, and a second config would be a second thing to get out of
    sync. Declared by `--zone only <chat> as <name>`.

    None is a real answer and must stay one: an action with no declared author
    is recorded as AUTHOR NOT ESTABLISHED rather than attributed by guess. The
    guess is what turns a record into an accusation."""
    own = owner()
    if own is None:
        return None
    pid, start = own
    try:
        parts = (pathlib.Path(__file__).resolve().parent / f".zone-{pid}"
                 ).read_text(encoding="utf-8").split()
    except Exception:
        return None
    if len(parts) < 2 or parts[0] != start or "as" not in parts:
        return None
    tail = parts[parts.index("as") + 1:]
    return tail[0] if tail else None


def declare(kind: str, chats) -> int:
    """Write this operator's zone. One command, so it cannot be placed wrongly.

    A trailing `as <name>` also declares WHO this session acts as, which is
    what stamps the author on an outbound action. Optional: without it the
    author stays undeclared rather than guessed."""
    own = owner()
    if own is None:
        print("cannot tell which session this is — zone not declared")
        return 1
    if kind not in ("only", "except") or not chats:
        print('usage: ./pending.py --zone only|except <chat id> [...] '
              '[as <operator>]')
        return 2
    pid, start = own
    f = pathlib.Path(__file__).resolve().parent / f".zone-{pid}"
    f.write_text(" ".join([start, kind, *chats]) + "\n", encoding="utf-8")
    who = chats[chats.index("as") + 1:] if "as" in chats else []
    print(f"zone declared for this session: {kind} "
          f"{' '.join(chats)}\n  {f.name}"
          + (f"\n  acting as: {who[0]}" if who else
             "\n  no operator declared — outbound actions stay "
             "AUTHOR NOT ESTABLISHED"))
    return 0


def in_zone(chat, mine) -> bool:
    """A row with no zone declared, or no chat at all, is never marked.

    `pending-eyes-*` and the other synthetic rows carry `chat_id = null` and
    speak for EVERY room; marking them would be a lie whichever way it fell."""
    if mine is None or chat is None:
        return True
    kind, chats = mine
    return (str(chat) in chats) if kind == "only" else (str(chat) not in chats)


def close(rid: str, why: str, emoji: str = "👍") -> int:
    """Close a request WITHOUT answering it, and say why.

    Deciding not to answer is a real decision — a 👍 that ends an exchange
    should not be met with a paragraph. But without this the inbox has no way
    to record that decision, so a deliberately unanswered request looks exactly
    like a forgotten one, and the inbox starts lying in the other direction.

    The reason is required. "Closed" with no reason is indistinguishable from
    "lost", which is the whole failure this inbox exists to prevent.
    """
    req = C.REQUESTS / f"{rid}.json"
    if not req.exists():
        print(f"no such request: {rid}")
        return 1
    d = json.loads(req.read_text(encoding="utf-8"))
    d["closed_without_answer"] = why
    d["closed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (C.SERVED / req.name).write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    req.unlink()

    # AND THE EYES COME OFF HERE TOO. Closing without an answer is still
    # closing: leaving 👀 on the message would say "not yet done" about
    # something already decided. The first version of this function moved the
    # file and left the mark, which made the record and the picture disagree —
    # exactly the split this inbox exists to prevent, reintroduced one level
    # down.
    # Not every request has a message to take the eye off: the self-check about
    # open eyes arrives with no chat_id and no message_id. This used to raise
    # KeyError AFTER the unlink — the request was closed, the closing was never
    # printed, and on screen it looked as if the command had failed.
    if d.get("message_id") is None or d.get("chat_id") is None:
        print(f"closed without answering: {rid}\n  reason: {why}\n"
              f"  no mark: a request without a message (self-check)")
        return 0

    C.OUTBOX.mkdir(exist_ok=True)
    C.OUTBOX.joinpath(f"{d['message_id']}-{d['chat_id']}.react.json").write_text(
        json.dumps({"chat_id": d["chat_id"], "message_id": d["message_id"],
                    "emoji": emoji}, ensure_ascii=False), encoding="utf-8")
    print(f"closed without answering: {rid}\n  reason: {why}\n  mark: {emoji}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
