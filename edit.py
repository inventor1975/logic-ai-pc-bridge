#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Rewrite one of the assistant's own messages in place.

    ./edit.py last "the corrected text"
    ./edit.py <message_id> "the corrected text"

Telegram lets a bot edit only what the bot itself sent. A message written by a
person is untouchable — "rewrite my text in place" is not available at any
price, from any bot.

What this is for: a draft that needs another pass updates itself instead of
growing a thread of near-identical versions.

A PROPOSAL IS NEVER EDITABLE. If the text behind a mark could change after the
mark was placed, the mark would certify nothing: approve version A, act on
version B. A changed text needs a new proposal and a new mark. The bridge
refuses such an edit rather than trusting whoever asked to remember the rule.
"""
from __future__ import annotations

import json
import sys

import config as C


def last_sent() -> tuple[int, int]:
    best = None
    for f in C.SENT.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("sent_message_id") and d.get("sent_at"):
            if best is None or d["sent_at"] > best["sent_at"]:
                best = d
    if not best:
        raise SystemExit("nothing sent yet that carries a message id")
    return best["chat_id"], best["sent_message_id"]


def _chat_of(message_id: int) -> int:
    """Which chat this message id belongs to. Guessing is not an option."""
    for f in list(C.SENT.glob("*.json")) + list(C.SERVED.glob("*.json")) + \
             list(C.REQUESTS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if message_id in (d.get("sent_message_id"), d.get("message_id")):
            return d["chat_id"]
    chats = C.all_chats()
    if len(chats) == 1:
        return chats[0]
    raise SystemExit(f"cannot tell which chat message {message_id} is in — "
                     f"name it explicitly rather than let me guess")


def main() -> int:
    if len(sys.argv) != 3:
        print('usage: ./edit.py <message_id|last> "the corrected text"')
        return 2
    if sys.argv[1] == "last":
        chat_id, mid = last_sent()
    else:
        mid = int(sys.argv[1])
        # NOT "whichever chat comes first". With more than one allowed chat
        # that picks an arbitrary room, and a mark or an edit landing in the
        # wrong one is visible to people it was never meant for. The message
        # id is looked up instead: it belongs to exactly one chat.
        chat_id = _chat_of(mid)
    C.OUTBOX.mkdir(exist_ok=True)
    C.OUTBOX.joinpath(f"{mid}-{chat_id}.edit.json").write_text(
        json.dumps({"chat_id": chat_id, "message_id": mid, "text": sys.argv[2]},
                   ensure_ascii=False), encoding="utf-8")
    print(f"rewriting {chat_id}/{mid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
