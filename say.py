#!/usr/bin/env python3
"""Write into the BRIDGE's outbox with the checks applied — instead of
remembering the rules.

Written 2026-08-26 after the NINTH case in one day of "knew the rule and did not
apply it": I had noted for myself that done_emoji may only come from
config.VALID_REACTIONS, and an hour later sent 🧊 again. The bridge rejected it,
the message arrived, the mark did not, and two needless items landed in the inbox.

The cure is the same one we applied that day to the watchdog vocabulary, to
mixed models and to the save check at the gate: A RULE THAT LIVES IN MEMORY IS
NOT A RULE. The check has to stand where it cannot be walked around.

  ./say.py <file-with-text> [--chat N] [--emoji 👌] [--answers id1,id2]
           [--wait SECONDS | --no-wait]
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as C   # noqa: E402

MAX = 4096           # Telegram's ceiling; longer and the bridge cuts or drops it
WAIT = 45.0          # seconds to wait for the bridge; it looks at the outbox every second
                     # MEASURED 2026-09-10: one reaction call alone took 20.3 s, so the
                     # first choice of 20 s would have timed out on a message that went out


# "QUEUED" IS NOT "SENT". Until 2026-09-10 say.py stopped at "queued", and after
# every message the operator had to go and look for the file in sent/ by hand —
# or did not look. Queued, sent and read are three different facts. The first is
# known here at once; the second shows up a second later as sent/<name> or
# outbox/rejected/<name>; the third nobody can know from here — Telegram
# accepting a message is not someone reading it. So say.py waits for the second
# fact and says which it was. A timeout is not a verdict: the file stays queued
# and goes out whenever the bridge takes it.
#
# One trap: sent/ may already hold a file of the same name from an earlier
# message. Only a file written after this one was queued counts.
def outcome(name: str, t0: float):
    """What the bridge has done with outbox/<name>: ('sent', None),
    ('rejected', reason), ('retrying', tries), ('waiting', None) or ('gone', None)."""
    def fresh(p: pathlib.Path) -> bool:
        try:
            return p.stat().st_mtime >= t0 - 1
        except OSError:
            return False
    if fresh(C.SENT / name):
        return "sent", None
    rej = C.OUTBOX / "rejected" / name
    if fresh(rej):
        try:
            why = json.loads(rej.read_text(encoding="utf-8")).get("_rejected")
        except Exception:
            why = None
        return "rejected", why or "no reason recorded"
    q = C.OUTBOX / name
    if not q.exists():
        return "gone", None
    try:
        tries = int(json.loads(q.read_text(encoding="utf-8")).get("_tries", 0))
    except Exception:    # caught half-written by the bridge; look again next time
        tries = 0
    return ("retrying", tries) if tries else ("waiting", None)


def wait_for(name: str, t0: float, limit: float) -> int:
    deadline = time.time() + limit
    gone_before = False
    while True:
        state, info = outcome(name, t0)
        if state == "sent":
            print(f"SENT: Telegram accepted it (sent/{name}). Accepted is not read.")
            return 0
        if state == "rejected":
            print(f"REJECTED by the bridge: {info}\n  The message is in outbox/rejected/{name}.")
            return 1
        # The bridge writes sent/ first and removes the queued file second, so
        # one look can fall between the two. "Gone" counts only when seen twice.
        if state == "gone" and gone_before:
            print(f"LEFT THE QUEUE, but it is neither in sent/ nor in outbox/rejected/. "
                  f"See bridge.out.")
            return 1
        gone_before = state == "gone"
        if time.time() >= deadline:
            break
        time.sleep(0.25)
    if state == "retrying":
        print(f"NOT SENT YET: Telegram refused it {info} time(s); the bridge keeps "
              f"trying and moves it to outbox/rejected/ when it gives up. See bridge.out.")
    else:
        # SAY WHAT IS SEEN, NOT WHAT IT PROBABLY MEANS. A file still in the queue
        # is either not taken yet or taken and being sent right now — the bridge
        # leaves it in place until Telegram answers, and on 2026-09-10 Telegram
        # took 20.3 s over one reaction. Telling those apart needs a "claimed"
        # mark from the bridge itself; until it has one, "the bridge is not
        # running" would be a guess.
        print(f"STILL QUEUED after {limit:g} s in {C.ROOT.name}/outbox: not taken yet, "
              f"or Telegram is slow — see bridge.out. If this tree's bridge is not "
              f"running, it will go out when it starts.")
    return 2


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--chat", type=int, default=None)
    ap.add_argument("--emoji", default="👌")
    ap.add_argument("--answers", default="")
    ap.add_argument("--name", default=None)
    ap.add_argument("--wait", type=float, default=WAIT, metavar="SECONDS")
    ap.add_argument("--no-wait", action="store_true",
                    help="only queue it, as before; do not wait for the bridge")
    a = ap.parse_args(argv)

    text = pathlib.Path(a.file).read_text(encoding="utf-8").strip()
    if not text:
        print("REFUSED: the text is empty"); return 1
    if len(text) > MAX:
        print(f"REFUSED: {len(text)} characters, Telegram's ceiling is {MAX}. "
              f"Split it into two messages."); return 1

    valid = getattr(C, "VALID_REACTIONS", None)
    if valid and a.emoji not in valid:
        print(f"REFUSED: {a.emoji!r} is NOT among the allowed reactions.\n"
              f"  The bridge will reject it, the mark will not appear, and the "
              f"inbox gets one more needless item.\n"
              f"  Take one from: {''.join(sorted(valid))[:120]}…")
        return 1

    chat = a.chat if a.chat is not None else getattr(C, "PRINCIPAL", None) \
        or C.policy(0).get("principal")
    # DO NOT PUT INTO THE OUTBOX WHAT THE BRIDGE WILL CERTAINLY REJECT.
    # `C.policy(0)` knows no principal, so without --chat this produced None; the
    # file was written, say.py printed "queued", and the bridge refused with a
    # line in bridge.out that nobody read. 2026-09-10: THREE messages in a row
    # failed to go out that way, in silence. The refusal belongs here, where it
    # cannot be missed.
    if chat is None:
        known = ", ".join(sorted(C.CHATS)) if getattr(C, "CHATS", None) else "see chats.json"
        print("REFUSED: no chat given and none can be inferred — the bridge would "
              "reject such a file.\n"
              f"  Name it explicitly: --chat <id>.  Known chats: {known}")
        return 1
    rec = {"chat_id": chat, "text": text, "done_emoji": a.emoji}
    ans = [x.strip() for x in a.answers.split(",") if x.strip()]
    if ans:
        rec["answers"] = ans
    name = a.name or pathlib.Path(a.file).stem
    out = C.OUTBOX / f"{name}.json"
    t0 = time.time()
    out.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    # NAME THE TREE. With a development tree and an installation side by side,
    # "queued" is true for whichever outbox this copy of say.py belongs to — and
    # on 2026-09-10 a report was queued into the dev tree, whose bridge was shut
    # down, while the operator waited. It printed "queued" honestly and went
    # nowhere. The tree's name costs nothing to print and makes that visible.
    print(f"queued into {C.ROOT.name}: {out.name} · {len(text)} chars · {a.emoji} · "
          f"closes {len(ans)} request(s).")
    if a.no_wait:
        return 0
    return wait_for(out.name, t0, a.wait)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
