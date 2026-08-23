#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Withdraw the 👀 from a message that was not addressed to the assistant.

    ./unreact.py <chat_id> <message_id>

The bridge marks anything beginning with the name, because telling a real
address from a coincidence takes judgement and judgement is slow. This is the
second stage: once awake, the assistant takes the mark back.

Worth doing precisely because the ABSENCE of the mark is a signal people rely
on. A mark left on a message nobody will answer turns that signal into noise.
"""
from __future__ import annotations

import json
import sys

import config as C


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: ./unreact.py <chat_id> <message_id>")
        return 2
    chat_id, message_id = int(sys.argv[1]), int(sys.argv[2])
    C.OUTBOX.mkdir(exist_ok=True)
    C.OUTBOX.joinpath(f"{message_id}-{chat_id}.unreact.json").write_text(
        json.dumps({"chat_id": chat_id, "message_id": message_id}),
        encoding="utf-8")
    print(f"withdrawing the mark from {chat_id}/{message_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
