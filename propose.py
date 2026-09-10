#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Hang a proposal on the consent gate.

    ./propose.py "send Arkadiy the letter about the v05.2 acceptance"

The assistant does nothing outward on its own. It hangs ONE LINE, the
principal marks it 👍 or 👎, and only the mark is an order.

WHY THE BRIDGE DOES NOT EXECUTE. The gate records consent; the act is
performed by the assistant. A daemon that executes arbitrary actions on a
reaction is a far larger surface for harm, and there is nothing to gain: the
assistant only acts outward while it is awake anyway. The bridge is
responsible for CONSENT, not for EXECUTION.

ONE LINE, ONE ACTION. Three things to do means three proposals and three
marks. A mark under a list of five items becomes a rubber stamp within a week.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time

from pathlib import Path

import config as C

USAGE = ('usage: ./propose.py --file-rule <dir> --to <chat> [--glob "*.md"] [--why ...] [--until <iso>]\n       ./propose.py "the proposed action, or the exact text to post" '
         '[note to self] [--to <chat_id>]')


def _principal_chat() -> int:
    """Where to hang the proposal: the principal's own chat.

    A proposal is addressed to the person entitled to approve it, not to
    whichever allowed chat comes first. Hanging it in a group would mean
    outsiders see a decision that is not theirs to make.
    """
    for cid in C.all_chats():
        p = C.policy(cid)
        if p["principal"] and cid == p["principal"]:
            return cid
    raise SystemExit("no private chat with the principal in chats.json — run ./setup.py")


def _rule_proposal(argv: list[str], target: int | None) -> int:
    """Propose a STANDING RULE for sending files, rather than one send.

        ./propose.py --file-rule ~/Dropbox/.../Inbox-Arkadiy --to -1001234567890 \
                     --glob "*.md" --why "finished documents for the project"

    The confirmation moves from the instance to the CLASS: the operator marks
    it once, and from then on everything from that folder to that room goes out
    without a question. Everything else is still asked about one file at a time.

    A proposal only PROPOSES. The rule is written into the book by the bridge
    and only on a mark, together with the numeric id of whoever marked it. The
    assistant never writes the book.
    """
    i = argv.index("--file-rule")
    try:
        directory = Path(argv[i + 1]).expanduser()
    except IndexError:
        print(USAGE); return 2
    del argv[i:i + 2]
    glob = "*"
    if "--glob" in argv:
        j = argv.index("--glob"); glob = argv[j + 1]; del argv[j:j + 2]
    until = None
    if "--until" in argv:
        j = argv.index("--until"); until = argv[j + 1]; del argv[j:j + 2]
    why = ""
    if "--why" in argv:
        j = argv.index("--why"); why = argv[j + 1]; del argv[j:j + 2]
    if target is None:
        print("a rule needs a room: --to <chat_id>"); return 2
    if not directory.exists():
        print(f"no such directory: {directory}"); return 2

    room = C.policy(target).get("_") or target
    line = C.T("propose.rule_body", directory=directory, glob=glob, room=room,
               why=why or C.T("propose.not_said"),
               until=until or C.T("propose.no_deadline"))
    C.OUTBOX.mkdir(exist_ok=True)
    name = f"propose-rule-{int(time.time())}.json"
    tag = _tag(name + str(target))
    C.OUTBOX.joinpath(name).write_text(json.dumps({
        "chat_id": _principal_chat(),
        "text": C.T("propose.rule_offer", tag=tag, body=line,
                    hours=C.PROPOSAL_TTL_HOURS),
        "proposal": {"action": f"standing rule: {directory} -> {room}",
                     "one_line": line, "target_chat": target,
                     "rule": {"chat_id": target, "dir": str(directory),
                              "glob": glob, "expires_at": until,
                              "why": why}},
    }, ensure_ascii=False), encoding="utf-8")
    print(f"rule queued {tag}: {name}")
    return 0


def _tag(seed: str) -> str:
    """A short proposal tag that the human can SEE.

    Telegram assigns the message id itself and does NOT show it to the user: it
    exists in the API and in my log, and not on the screen. Referring to it in
    conversation means naming something the other person cannot see — exactly
    what the operator caught on 2026-08-22. So the tag goes INTO THE TEXT of the
    proposal: what I name and what they see are the same string.
    """
    return "P-" + hashlib.sha256(seed.encode()).hexdigest()[:4].upper()


def _batch_proposal(argv: list[str], target: int | None) -> int:
    """Queue a BATCH: one mark — one delivery into one room.

        ./propose.py --batch a.md b.pdf c.png --to -1001234567890 [--why ...]

    Three conditions, each closing its own hole:

    ONE recipient. Mixing rooms inside one batch is forbidden — that is exactly
    where the mistake hides: four files to the right place, one to the wrong
    one, and it will be the recipient who notices, not us.

    EVERY file is named: name, size, digest — right in the text of the proposal.
    The mark covers WHAT WAS SEEN, not "those files he gathered over there".

    A CEILING at C.BATCH_MAX. A list too long to read with your eyes is a rubber
    stamp, whatever it is called. The answer to "many files" is not a bigger
    batch but a rule on the folder.
    """
    i = argv.index("--batch")
    del argv[i]
    why = ""
    if "--why" in argv:
        j = argv.index("--why"); why = argv[j + 1]; del argv[j:j + 2]
    paths = [Path(a).expanduser() for a in argv if not a.startswith("--")]
    if target is None:
        print("a batch needs a room: --to <chat_id>"); return 2
    if not paths:
        print("the batch is empty"); return 2
    if len(paths) > C.BATCH_MAX:
        print(f"{len(paths)} files in the batch, the ceiling is {C.BATCH_MAX}. "
              f"A list too long to read with your eyes is a rubber stamp. "
              f"For a stream of files make a rule: --file-rule <folder>")
        return 2

    files, lines = [], []
    for p_ in paths:
        if not p_.exists():
            print(f"no such file: {p_}"); return 2
        raw = p_.read_bytes()
        d = hashlib.sha256(raw).hexdigest()
        files.append({"name": p_.name, "path": str(p_.resolve()),
                      "bytes": len(raw), "sha256": d})
        lines.append(f"    {p_.name}  —  {len(raw)} B  —  {d[:16]}…")

    room = C.policy(target).get("_") or target
    line = C.T("propose.batch_body", room=room,
               why=why or C.T("propose.not_said"), files="\n".join(lines))
    C.OUTBOX.mkdir(exist_ok=True)
    name = f"propose-batch-{int(time.time())}.json"
    tag = _tag(name + str(target))
    C.OUTBOX.joinpath(name).write_text(json.dumps({
        "chat_id": _principal_chat(),
        "text": C.T("propose.batch_offer", tag=tag, count=len(files), body=line),
        "proposal": {"action": f"batch of {len(files)} files -> {room}",
                     "one_line": line, "target_chat": target,
                     "batch": {"chat_id": target, "files": files, "why": why}},
    }, ensure_ascii=False), encoding="utf-8")
    print(f"batch queued {tag}: {name} — {len(files)} files")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    target = None
    if "--to" in argv:
        i = argv.index("--to")
        try:
            target = int(argv[i + 1])
        except (IndexError, ValueError):
            print(USAGE)
            return 2
        del argv[i:i + 2]
    if "--batch" in argv:
        return _batch_proposal(argv, target)
    if "--file-rule" in argv:
        return _rule_proposal(argv, target)
    if not argv or not argv[0].strip():
        print(USAGE)
        return 2
    line = argv[0].strip()
    note = argv[1].strip() if len(argv) > 1 else line
    # WHERE IT GOES BELONGS IN THE RECORD, not in the assistant's memory.
    # A proposal approved now may be acted on after a wake-up, and "which chat
    # was that for" is exactly the kind of thing remembered wrong. Posting a
    # private remark into a group cannot be taken back.
    where = ""
    if target is not None:
        where = f" — to post in: {C.policy(target).get('_') or target}"
    C.OUTBOX.mkdir(exist_ok=True)
    name = f"propose-{int(time.time())}.json"
    C.OUTBOX.joinpath(name).write_text(json.dumps({
        "chat_id": _principal_chat(),
        "text": (f"[{_tag(name + str(target))}] I PROPOSE{where}:\n\n{line}\n\n"
                 f"👍 — do it. 👎 — do not. Without a mark I do nothing; "
                 f"it clears itself after {C.PROPOSAL_TTL_HOURS}h."),
        "proposal": {"action": note, "one_line": line, "target_chat": target},
    }, ensure_ascii=False), encoding="utf-8")
    print(f"hung: {name} — {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
