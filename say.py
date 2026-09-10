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
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as C   # noqa: E402

MAX = 4096           # Telegram's ceiling; longer and the bridge cuts or drops it


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--chat", type=int, default=None)
    ap.add_argument("--emoji", default="👌")
    ap.add_argument("--answers", default="")
    ap.add_argument("--name", default=None)
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
    out = C.ROOT / "outbox" / f"{name}.json"
    out.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    # NAME THE TREE. With a development tree and an installation side by side,
    # "queued" is true for whichever outbox this copy of say.py belongs to — and
    # on 2026-09-10 a report was queued into the dev tree, whose bridge was shut
    # down, while the operator waited. It printed "queued" honestly and went
    # nowhere. The tree's name costs nothing to print and makes that visible.
    print(f"queued into {C.ROOT.name}: {out.name} · {len(text)} chars · {a.emoji} · "
          f"closes {len(ans)} request(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
