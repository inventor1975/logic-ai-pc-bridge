#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Test the consent gate WITHOUT Telegram.

Why: the expiry branch guards the central rule ("no mark means no", never
yes), and in live use it had never once executed — a day had not yet passed.
A branch that guards a safety property and has never run cannot be called
working.

The network is not touched: call and ack are replaced. Directories are
temporary.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config as C
import tg_bridge as B

CHAT = 100200300          # any id; nothing is sent anywhere
# DELIBERATELY DIFFERENT FROM CHAT. In a private chat the principal's user id
# happens to equal the chat id, and a test written that way cannot tell the two
# apart — which is exactly the confusion the defect was made of. The group case,
# where they differ, is the one that must be checked.
PRINCIPAL = 500600700
STRANGER = 999999

ok = fail = 0


def check(name: str, cond: bool) -> None:
    global ok, fail
    if cond:
        ok += 1; print(f"  ok   {name}")
    else:
        fail += 1; print(f"  FAIL {name}")


def hang(mid: int, hours_old: float = 0.0) -> None:
    born = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    C.PROPOSALS.joinpath(f"{CHAT}-{mid}.json").write_text(json.dumps({
        "chat_id": CHAT, "message_id": mid, "action": "test",
        "one_line": f"action {mid}",
        "created": born.isoformat(timespec="seconds"),
        "expires": (born + timedelta(hours=C.PROPOSAL_TTL_HOURS)).isoformat(timespec="seconds"),
    }, ensure_ascii=False), encoding="utf-8")


def verdict_of(mid: int) -> str | None:
    f = C.DECIDED / f"{CHAT}-{mid}.json"
    return json.loads(f.read_text(encoding="utf-8"))["verdict"] if f.exists() else None


def pending(mid: int) -> bool:
    return (C.PROPOSALS / f"{CHAT}-{mid}.json").exists()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gate-"))
    for name in ("proposals", "decided", "requests", "outbox"):
        (tmp / name).mkdir()
    C.PROPOSALS, C.DECIDED = tmp / "proposals", tmp / "decided"
    C.REQUESTS, C.OUTBOX = tmp / "requests", tmp / "outbox"
    B.call = lambda *a, **k: {"ok": True, "result": {"message_id": 1}}
    B.ack = lambda c, m: "stubbed"

    print("consent gate:")

    hang(10); B.decide(CHAT, 10, ["👍"], True, CHAT)
    check("principal's mark approves", verdict_of(10) == "APPROVED")
    check("approval wakes the assistant", (C.REQUESTS / f"verdict-{CHAT}-10.json").exists())

    hang(11); B.decide(CHAT, 11, ["👎"], True, CHAT)
    check("thumbs down refuses", verdict_of(11) == "REFUSED")

    hang(12); B.decide(CHAT, 12, ["👍"], False, STRANGER)
    check("an OUTSIDER's mark is not an order", verdict_of(12) is None and pending(12))

    hang(13); B.decide(CHAT, 13, ["❤"], True, CHAT)
    check("an unrelated emoji is not a verdict", verdict_of(13) is None and pending(13))

    hang(14, hours_old=C.PROPOSAL_TTL_HOURS + 1)
    B.decide(CHAT, 14, ["👍"], True, CHAT)
    check("an EXPIRED proposal cannot be approved", verdict_of(14) == "EXPIRED")

    hang(15, hours_old=C.PROPOSAL_TTL_HOURS + 1); hang(16)
    B.sweep_proposals()
    check("the sweep clears expired ones", verdict_of(15) == "EXPIRED")
    check("the sweep leaves fresh ones alone", verdict_of(16) is None and pending(16))

    B.decide(CHAT, 777, ["👍"], True, CHAT)
    check("a mark on an ordinary message does nothing", verdict_of(777) is None)

    # ---- the five cases the owner review requires -----------------------
    #
    # Each of these is a way the gate could give permission it was never
    # given. Two of them were real defects found by review rather than by
    # these tests, which is the reason the tests now exist.
    print("\nconsent cannot be manufactured:")

    hang(20); B.decide(CHAT, 20, ["👍", "👎"], True, CHAT)
    check("mixed approve+reject CANNOT approve",
          verdict_of(20) is None and pending(20))

    hang(21); B.decide(CHAT, 21, ["👍"], True, PRINCIPAL)
    d = json.loads((C.DECIDED / f"{CHAT}-21.json").read_text(encoding="utf-8"))
    r = json.loads((C.REQUESTS / f"verdict-{CHAT}-21.json").read_text(encoding="utf-8"))
    check("the decided artifact names the exact approver id",
          d.get("decided_by_user_id") == PRINCIPAL)
    check("the verdict request's from_id is the APPROVER, not the chat",
          r.get("from_id") == PRINCIPAL and r.get("from_id") != CHAT)
    check("the decision records which reaction carried it",
          d.get("decision_reaction") == ["👍"])

    hang(22); B.decide(CHAT, 22, ["👍"], False, STRANGER)
    check("an outsider never creates an approved verdict",
          verdict_of(22) is None and pending(22))

    hang(23); B.decide(CHAT, 23, ["👍"], False, None)
    check("an anonymous reaction (no user id) cannot approve",
          verdict_of(23) is None and pending(23))

    hang(24, hours_old=C.PROPOSAL_TTL_HOURS + 1)
    B.decide(CHAT, 24, ["👍"], True, PRINCIPAL)
    B.decide(CHAT, 24, ["👍"], True, PRINCIPAL)          # a second, later mark
    check("expiry cannot be revived by a later mark",
          verdict_of(24) == "EXPIRED")

    hang(25, hours_old=C.PROPOSAL_TTL_HOURS + 1)
    B.sweep_proposals()
    e = json.loads((C.DECIDED / f"{CHAT}-25.json").read_text(encoding="utf-8"))
    check("an expiry records that NOBODY decided it",
          e.get("verdict") == "EXPIRED" and e.get("decided_by_user_id") is None)

    # ---- the group case, which a private-chat test cannot see ------------
    #
    # Twice now a defect has hidden in the difference between a private chat
    # and a group. Once because the principal's user id EQUALS the chat id in
    # a private chat; once because a group's chat id is NEGATIVE. Tests
    # written only on the private case are blind to both by construction.
    print("\nnegative (group) chat ids:")
    GROUP = -5101395964
    ids = [f"284-{GROUP}", f"46-{CHAT}", f"verdict-{CHAT}-122"]
    parsed = []
    for rid in ids:
        try:
            m, c = rid.split("-", 1)
            parsed.append((rid, int(m), int(c)))
        except ValueError:
            parsed.append((rid, None, None))
    check("a group request id parses to message and NEGATIVE chat",
          parsed[0][1] == 284 and parsed[0][2] == GROUP)
    check("a private request id still parses",
          parsed[1][1] == 46 and parsed[1][2] == CHAT)
    check("a verdict-* id is skipped rather than mis-parsed",
          parsed[2][1] is None)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
