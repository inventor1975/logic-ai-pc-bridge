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
import sys
from datetime import datetime, timezone

import config as C


def main() -> int:
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
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(d["at"])).total_seconds() / 60
        rows.append((age, f.stem, d.get("chat_id"), (d.get("ask") or "")[:56]))
    if not rows:
        print("nothing owed — the inbox is empty.")
        return 0
    print(f"{len(rows)} awaiting an answer (oldest first):\n")
    for age, rid, chat, ask in sorted(rows, reverse=True):
        print(f"  {age:6.0f} min  {rid:32} chat {chat}\n              {ask}")
    print("\nTo clear one, put \"answers\": [\"<id>\"] in the outbox file that replies to it,")
    print("or close it without replying:  ./pending.py --close <id> \"why\" [emoji]")
    return 0


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
    C.OUTBOX.mkdir(exist_ok=True)
    C.OUTBOX.joinpath(f"{d['message_id']}-{d['chat_id']}.react.json").write_text(
        json.dumps({"chat_id": d["chat_id"], "message_id": d["message_id"],
                    "emoji": emoji}, ensure_ascii=False), encoding="utf-8")
    print(f"closed without answering: {rid}\n  reason: {why}\n  mark: {emoji}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
