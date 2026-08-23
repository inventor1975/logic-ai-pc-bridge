#!/usr/bin/env python3
"""Reminder escalation: keeps sending until seen (a reaction), then goes quiet.

Offline harness: config C and call() are stubbed out. Checks the four branches
the curator worried about — "how do I cancel it, won't it nag forever?"
"""
import json, re, sys, tempfile, types, pathlib
from datetime import datetime, timezone, timedelta


def load_funcs():
    src = pathlib.Path("tg_bridge.py").read_text(encoding="utf-8")
    ns = {"json": json, "datetime": datetime, "timezone": timezone,
          "timedelta": timedelta, "pathlib": pathlib}
    for fn in ("def now(", "def _seen(", "def due_reminders("):
        start = re.search(re.escape(fn), src).start()
        rest = src[start:]
        nxt = re.search(r"\n(def |class )", rest[3:])
        exec(compile(rest[:nxt.start() + 3] if nxt else rest, "<x>", "exec"), ns)
    return ns


def run():
    tmp = pathlib.Path(tempfile.mkdtemp())
    rem, sent = tmp / "reminders", tmp / "sent_reminders"
    rem.mkdir(); sent.mkdir()
    (tmp / "reactions.jsonl").write_text("", encoding="utf-8")
    ns = load_funcs()
    log = []
    ns["C"] = types.SimpleNamespace(ROOT=tmp, REMINDERS=rem, SENT_REMINDERS=sent,
                                    REPLY_PREFIX="ЛОГИК", DRY_RUN=False,
                                    allowed=lambda cid: cid == 111)
    ns["call"] = lambda method, **kw: (log.append(kw.get("text", "")),
                                       {"ok": True, "result": {"message_id": 1000 + len(log)}})[1]
    due = ns["due_reminders"]
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    def put(name, **kw):
        (rem / name).write_text(json.dumps(kw, ensure_ascii=False), encoding="utf-8")

    ok = True

    # 1. ack: sends, tries=1, stays waiting
    put("r1.json", at=past, chat_id=111, text="воды", ack=True, every_min=5, max_tries=3)
    due()
    r = json.loads((rem / "r1.json").read_text())
    ok &= r["tries"] == 1 and r["last_msg_id"] is not None and not (sent / "r1.json").exists()

    # 2a. an OUTSIDER's reaction (approver=false) does NOT silence it — otherwise a
    #     bystander in the group could quietly cancel an escalation the principal
    #     never saw.
    (rem / "r1.json").write_text(json.dumps({**r, "at": past}, ensure_ascii=False))
    (tmp / "reactions.jsonl").write_text(
        json.dumps({"chat_id": 111, "message_id": r["last_msg_id"],
                    "emoji": ["👍"], "approver": False}) + "\n",
        encoding="utf-8")
    n = len(log); due()
    ok &= len(log) > n and not (sent / "r1.json").exists()   # sends again, doesn't go quiet

    # 2b. the PRINCIPAL's reaction (approver=true) -> goes quiet
    r = json.loads((rem / "r1.json").read_text())
    (rem / "r1.json").write_text(json.dumps({**r, "at": past}, ensure_ascii=False))
    (tmp / "reactions.jsonl").write_text(
        json.dumps({"chat_id": 111, "message_id": r["last_msg_id"],
                    "emoji": ["👍"], "approver": True}) + "\n",
        encoding="utf-8")
    n = len(log); due()
    ok &= len(log) == n and (sent / "r1.json").exists()

    # 3. safety fuse
    log.clear()
    put("r2.json", at=past, chat_id=111, text="важное", ack=True, max_tries=2, tries=2)
    due()
    ok &= (sent / "r2.json").exists() and log and "giving up" in log[-1]

    # 4. plain — one-shot
    log.clear()
    put("r3.json", at=past, chat_id=111, text="разово")
    due()
    ok &= len(log) == 1 and (sent / "r3.json").exists()

    print("test_reminders:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
