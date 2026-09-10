#!/usr/bin/env python3
"""Tests for the "eyes": a request goes out exactly when the answer really
landed.

The eye (👀) is the only indicator of "not done". These tests are about the
record and the truth not drifting apart: a file answer CLOSES the named request
just as a text one does; a mark that failed does NOT put the request out; ack is
set BEFORE the move into served; a broken or foreign outbox item is quarantined
rather than storming for ever.

Offline: the network is mocked out entirely.
"""
import os, sys, json, tempfile, time
from pathlib import Path

os.environ.setdefault("BRIDGE_BOT_TOKEN", "0:test")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tg_bridge as B
import config as C

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond: ok += 1;  print(f"  ok   {name}")
    else:    fail += 1; print(f"  FAIL {name}")


def fresh_dirs(tmp):
    """Point every one of the bridge's directories at a temporary tree."""
    for attr in ("ROOT", "REQUESTS", "SERVED", "OUTBOX", "SENT",
                 "NEEDS_CONSENT", "PROPOSALS", "DECIDED"):
        d = tmp if attr == "ROOT" else tmp / attr.lower()
        d.mkdir(exist_ok=True)
        setattr(C, attr, d)
    C.LOG = tmp / "tg_log.jsonl"


def run():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        fresh_dirs(tmp)
        C.DRY_RUN = True                      # ack() -> "dry-run", no network
        C.allowed = lambda cid: True          # the chat is allowed
        acks = []
        B.ack = lambda cid, mid, e=None: (acks.append((cid, mid, e)) or "reaction")

        # --- 1. clear_inbox(mark_done): request -> served, ack called ---
        (C.REQUESTS / "123-456.json").write_text("{}", encoding="utf-8")
        B.clear_inbox({"answers": ["123-456"]}, mark_done=True)
        check("clear_inbox: the request moved to served",
              not (C.REQUESTS / "123-456.json").exists()
              and (C.SERVED / "123-456.json").exists())
        check("clear_inbox: the mark was set (ack called)", acks == [(456, 123, "👍")])

        # --- 2. clear_inbox on a worded id (verdict-...) does not crash, but moves ---
        (C.REQUESTS / "verdict-9-9.json").write_text("{}", encoding="utf-8")
        B.clear_inbox({"answers": ["verdict-9-9"]}, mark_done=True)
        check("clear_inbox: a worded id is moved without crashing",
              (C.SERVED / "verdict-9-9.json").exists())

        # --- 3. A3: ack BEFORE the move. If ack throws, the request must NOT be
        #        left in limbo; we catch the order: at ack time the file is still
        #        in requests. ---
        seen_state = {}
        def spy_ack(cid, mid, e=None):
            seen_state["in_requests_at_ack"] = (C.REQUESTS / "77-88.json").exists()
            return "reaction"
        B.ack = spy_ack
        (C.REQUESTS / "77-88.json").write_text("{}", encoding="utf-8")
        B.clear_inbox({"answers": ["77-88"]}, mark_done=True)
        check("A3: ack is set WHILE the request is still in requests",
              seen_state.get("in_requests_at_ack") is True)
        B.ack = lambda cid, mid, e=None: (acks.append((cid, mid, e)) or "reaction")

        # --- 4. FIX A: a file answer with answers CLOSES the request ---
        acks.clear()
        (C.REQUESTS / "200-300.json").write_text("{}", encoding="utf-8")
        payload = tmp / "payload.txt"; payload.write_text("hi", encoding="utf-8")
        (C.OUTBOX / "reply.json").write_text(json.dumps({
            "chat_id": 300, "file": str(payload), "text": "here is the file",
            "answers": ["200-300"]}), encoding="utf-8")
        B.rule_for = lambda cid, fp: {"id": "R1"}          # covered by a rule
        B.grant_for = lambda cid, fp: None
        B.send_file = lambda cid, fp, cap, as_photo=False: {"ok": True}
        B.flush_outbox()
        check("A: the file answer closed the request (the eye went out)",
              not (C.REQUESTS / "200-300.json").exists()
              and (C.SERVED / "200-300.json").exists())
        check("A: the outbox item moved to sent",
              (C.SENT / "reply.json").exists()
              and not (C.OUTBOX / "reply.json").exists())

        # --- 5. FIX A2: a .react.json whose mark did NOT land does not close it ---
        (C.REQUESTS / "1-2.json").write_text("{}", encoding="utf-8")
        (C.OUTBOX / "m.react.json").write_text(json.dumps({
            "chat_id": 2, "message_id": 2, "emoji": "👍",
            "answers": ["1-2"]}), encoding="utf-8")
        B.ack = lambda cid, mid, e=None: "invalid-emoji"   # the mark did NOT land
        B.flush_outbox()
        check("A2: the mark did not land -> the request STAYS open",
              (C.REQUESTS / "1-2.json").exists()
              and not (C.SERVED / "1-2.json").exists())
        check("A2: the .react.json is removed from the queue anyway",
              not (C.OUTBOX / "m.react.json").exists())

        # --- 6. FIX A2 (the converse): the mark LANDED -> the request closes ---
        (C.REQUESTS / "3-4.json").write_text("{}", encoding="utf-8")
        (C.OUTBOX / "ok.react.json").write_text(json.dumps({
            "chat_id": 4, "message_id": 4, "emoji": "👍",
            "answers": ["3-4"]}), encoding="utf-8")
        B.ack = lambda cid, mid, e=None: "reaction"        # it landed
        B.flush_outbox()
        check("A2: the mark landed -> the request is closed",
              (C.SERVED / "3-4.json").exists())

        # --- 7. D-storm: a foreign chat in a text outbox item -> rejected (list intact) ---
        C.allowed = lambda cid: False
        C._chats = lambda: {"999": {}}                     # the config IS loaded
        (C.OUTBOX / "bad.json").write_text(json.dumps({
            "chat_id": 111, "text": "somewhere it should not go"}), encoding="utf-8")
        B.flush_outbox()
        check("D-storm: a forbidden chat goes to rejected/, no storm",
              (C.OUTBOX / "rejected" / "bad.json").exists()
              and not (C.OUTBOX / "bad.json").exists())

        # --- 8. D-storm (the safeguard): with a BROKEN config we do NOT quarantine ---
        C._chats = lambda: {}                              # empty = broken or absent
        (C.OUTBOX / "wait.json").write_text(json.dumps({
            "chat_id": 111, "text": "wait for the fix"}), encoding="utf-8")
        B.flush_outbox()
        check("D-storm: a broken chats.json -> we do NOT quarantine, we wait",
              (C.OUTBOX / "wait.json").exists()
              and not (C.OUTBOX / "rejected" / "wait.json").exists())

        # --- 9. D-storm: broken JSON older than 5 s -> rejected; fresh -> wait ---
        C.allowed = lambda cid: True
        old = C.OUTBOX / "broken.json"; old.write_text("{not json", encoding="utf-8")
        os.utime(old, (time.time() - 30, time.time() - 30))
        B.flush_outbox()
        check("D-storm: old broken JSON -> rejected/",
              (C.OUTBOX / "rejected" / "broken.json").exists())
        fresh = C.OUTBOX / "fresh.json"; fresh.write_text("{not json", encoding="utf-8")
        B.flush_outbox()
        check("D-storm: fresh broken JSON stays (it may be a half-write)",
              (C.OUTBOX / "fresh.json").exists())

    print("test_eyes:", "OK" if fail == 0 else "FAIL", f"({ok} ok, {fail} fail)")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
