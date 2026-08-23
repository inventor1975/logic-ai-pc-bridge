#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Answer with a mark instead of words.

    ./react.py <message_id> 👍
    ./react.py last 🤝

The bridge places 👀 on arrival, meaning "received and stored". Once the
assistant has actually read the message it may replace that with a mark of its
own — a bot holds only one reaction per message, so the new one takes the
place of the eyes.

WHY THIS EARNS ITS KEEP. Not every message deserves a paragraph. "Understood",
"agreed", "thank you" cost the reader nothing as a mark and cost real attention
as prose. A channel where every trivial exchange grows two more paragraphs is
one nobody can end — the same failure as two assistants talking politely
forever, one step smaller.

Telegram allows a fixed set of reactions; anything outside it is refused by the
server. The list below is the working subset, chosen for what actually needs
saying.
"""
from __future__ import annotations

import json
import sys

import config as C

# THE MARK MEANS DONE, NOT DOING. This is the whole discipline of the file.
#
# 👀 is placed by the bridge on arrival and means "accepted, not yet done". It
# stays there for as long as the work lasts. Replacing it says the work is
# FINISHED — nothing else replaces it, ever.
#
# The earlier vocabulary mixed the two: 🤝 "accepted, will do" sat beside 👍
# "understood", and from the outside they were indistinguishable. A mark that
# might mean either is worse than no mark, because the reader stops checking:
# he sees a mark, assumes it is done, and finds out otherwise later.
#
# If something is going to take a while, say so IN WORDS. A mark cannot carry
# "still working" without ruining what the other marks mean.
MEANINGS = {
    "👍": "done — understood, nothing further needed",
    "🤝": "done — carried out as asked",
    "🫡": "done — the instruction is executed",
    "🔥": "done, and it turned out well",
    "👏": "done — and you were right to ask for it",
    "🤯": "done — and it changed something worth telling you about",
    "🙏": "thank you (nothing was asked, so nothing is owed)",
    "😢": "done, but the news is bad — words follow",
    "👎": "NOT done, and never only a mark — words must say why",
}

# Placed by the bridge, not by hand. Listed so the vocabulary is complete.
BRIDGE_MARKS = {
    "👀": "accepted and stored — NOT done yet",
    "🤔": "voice note heard, being transcribed",
}


def last_incoming() -> tuple[int, int]:
    best = None
    for line in C.LOG.read_text(encoding="utf-8").splitlines()[-200:]:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("message_id"):
            best = r
    if not best:
        raise SystemExit("no incoming message in the log yet")
    return best["chat_id"], best["message_id"]


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
        print('usage: ./react.py <message_id|last> <emoji>\n')
        print("  a mark REPLACES the eyes only when the work is finished\n")
        for e, m in MEANINGS.items():
            print(f"  {e}  {m}")
        print("\n  placed by the bridge, meaning NOT done yet:")
        for e, m in BRIDGE_MARKS.items():
            print(f"  {e}  {m}")
        return 2
    emoji = sys.argv[2]
    if emoji in BRIDGE_MARKS:
        print(f"{emoji} belongs to the bridge — it means 'not done yet'. "
              f"Use it only to put a mark back, never to report progress.")
    elif emoji not in MEANINGS:
        print(f"{emoji} is not in the working set — Telegram may refuse it. "
              f"Sending anyway; watch the log for REACTION_INVALID.")
    if sys.argv[1] == "last":
        chat_id, mid = last_incoming()
    else:
        mid = int(sys.argv[1])
        # NOT "whichever chat comes first". With more than one allowed chat
        # that picks an arbitrary room, and a mark or an edit landing in the
        # wrong one is visible to people it was never meant for. The message
        # id is looked up instead: it belongs to exactly one chat.
        chat_id = _chat_of(mid)
    C.OUTBOX.mkdir(exist_ok=True)
    C.OUTBOX.joinpath(f"{mid}-{chat_id}.react.json").write_text(
        json.dumps({"chat_id": chat_id, "message_id": mid, "emoji": emoji,
                    # Answering with a mark clears the request the same way a
                    # reply in words does. Otherwise the inbox would show a
                    # debt that has already been paid.
                    "answers": [f"{mid}-{chat_id}"]},
                   ensure_ascii=False), encoding="utf-8")
    print(f"{emoji} -> {chat_id}/{mid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
