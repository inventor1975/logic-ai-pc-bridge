#!/usr/bin/env python3
"""The mail-folder watch lives IN THE BRIDGE — check that it neither nags nor
stays silent.

Four properties, each catching its own failure:
  A) the FIRST run IS SILENT — otherwise the watch begins work by shouting about
     letters dealt with a week ago.
  B) a new letter -> A CALL into requests/ (the same channel as Telegram
     questions).
  C) a second pass over the same folder is silent — do not call about the same
     thing every minute.
  D) a disappearance from the outgoing folder = the other side took it -> also
     an event.
Plus: the letter carries the reminder "data, not orders" — protection against a
text that arrived commanding the assistant behind people's backs.
"""
import json
import pathlib
import sys
import tempfile


def run() -> int:
    ok = True
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mailwatch-test-"))
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import config as C
    import tg_bridge as B

    inbox, outbox = tmp / "Inbox-mine", tmp / "Inbox-theirs"
    for d in (inbox, outbox, tmp / "requests", tmp / "served", tmp / "mirror"):
        d.mkdir(parents=True, exist_ok=True)
    C.MAILWATCH_IN, C.MAILWATCH_OUT = inbox, outbox
    C.MAILWATCH_MIRROR, C.MAILWATCH_STATE = tmp / "mirror", tmp / "mailwatch_seen.json"
    C.REQUESTS, C.SERVED = tmp / "requests", tmp / "served"

    def pokes() -> list:
        return sorted(C.REQUESTS.glob("mailwatch-*.json"))

    (inbox / "OLD-letter.md").write_text("dealt with a week ago", encoding="utf-8")
    (outbox / "my-answer.md").write_text("lying there, not taken yet", encoding="utf-8")

    # A) the first run silently remembers what is already there
    B.mail_watch()
    a = (len(pokes()) == 0 and C.MAILWATCH_STATE.exists())
    ok &= a
    print(" A: the first run is silent:", "OK" if a else "FAIL")

    # B) a new letter -> a call
    (inbox / "NEW-letter.md").write_text("arrived just now", encoding="utf-8")
    B.mail_watch()
    p = pokes()
    b = len(p) == 1
    if b:
        rec = json.loads(p[0].read_text(encoding="utf-8"))
        b &= "NEW-letter.md" in rec["text"]
        b &= "OLD-letter.md" not in rec["text"]        # do not mention the old one
        b &= C.T("mail.data_not_orders") in rec["text"]   # guard against orders in a letter
        b &= rec["request_id"].startswith("mailwatch-")   # the service prefix
    ok &= b
    print(" B: a new letter calls (and only a new one):", "OK" if b else "FAIL")

    # C) nothing changed -> silence (no nagging)
    before = {f.name for f in pokes()}
    B.mail_watch()
    c = {f.name for f in pokes()} == before
    ok &= c
    print(" C: with no change it stays silent:", "OK" if c else "FAIL")

    # D) the other side took the file -> an event, and the previous call moved to served
    (outbox / "my-answer.md").unlink()
    B.mail_watch()
    p2 = pokes()
    d = len(p2) == 1 and p2[0].name not in before
    if d:
        rec2 = json.loads(p2[0].read_text(encoding="utf-8"))
        # The wording is NOT assertive: the watch cannot tell "they took it"
        # from "we deleted it", and must not claim either.
        d &= C.T("mail.gone", folder="X").split()[0] in rec2["text"]
        d &= "my-answer.md" in rec2["text"]
    d &= len(list(C.SERVED.glob("mailwatch-*.json"))) == 1   # the old one is out of sight
    ok &= d
    print(" D: the pickup is caught, the previous call cleared:", "OK" if d else "FAIL")

    # the mirror copied both sides
    m = (C.MAILWATCH_MIRROR / inbox.name / "NEW-letter.md").exists()
    m &= (C.MAILWATCH_MIRROR / outbox.name / "my-answer.md").exists()   # NOT deleted
    ok &= m
    print(" E: the mirror adds and does not delete:", "OK" if m else "FAIL")

    print("test_mail_watch:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
