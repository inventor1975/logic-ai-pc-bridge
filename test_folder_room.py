#!/usr/bin/env python3
"""BINDING A FOLDER TO A ROOM — check that it separates rather than smears.

A correspondent, 2026-09-01: messages of ONE topic falling into the shared room
were breaking their working channel. So the cost of a mistake here is NOT "not
delivered" but "delivered TO THE WRONG PLACE" — and the negative half of the
trial matters more than the positive one.

  A) an event whose name matches the pattern -> a message INTO ITS OWN room;
  B) an event with NO match -> goes into no room at all (the main property);
  C) a disappearance is reported too, and the wording does NOT claim who took it;
  D) the call to the assistant stays where it was — the binding does not replace it.
"""
import json, pathlib, sys, tempfile


def run() -> int:
    ok = True
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="folder-room-"))
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import config as C
    import tg_bridge as B

    inbox, outbox = tmp / "Inbox-mine", tmp / "Inbox-theirs"
    for d in (inbox, outbox, tmp / "requests", tmp / "served", tmp / "mirror", tmp / "outbox"):
        d.mkdir(parents=True, exist_ok=True)
    C.MAILWATCH_IN, C.MAILWATCH_OUT = inbox, outbox
    C.MAILWATCH_MIRROR, C.MAILWATCH_STATE = tmp / "mirror", tmp / "seen.json"
    C.REQUESTS, C.SERVED, C.OUTBOX = tmp / "requests", tmp / "served", tmp / "outbox"
    C.FOLDER_ROOMS = [{"match": "TOPIC", "chat_id": -1001234567890, "name": "TOPIC"}]

    def to_room() -> list:
        return [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(C.OUTBOX.glob("folder-*.json"))]

    (inbox / "old.md").write_text("already there", encoding="utf-8")
    B.mail_watch()                      # the silent first acquaintance

    # A) an event of ours reaches its own room
    (outbox / "TOPIC-DRAFTS").mkdir()
    (outbox / "TOPIC-DRAFTS" / "CONCEPT.md").write_text("x", encoding="utf-8")
    (inbox / "2026-09-01_TOPIC-owner-disposition.md").write_text("y", encoding="utf-8")
    B.mail_watch()
    m = to_room()
    a = len(m) == 1 and m[0]["chat_id"] == -1001234567890 and "TOPIC" in m[0]["text"]
    ok &= a; print(" A: a matching event goes to its own room:", "OK" if a else "FAIL")

    # B) a FOREIGN event does NOT go to the room — the main property
    (inbox / "OTHER-PROJECT-CONTRACT-002.md").write_text("another topic", encoding="utf-8")
    before = len(to_room())
    B.mail_watch()
    b = len(to_room()) == before
    ok &= b; print(" B: an unrelated event does NOT reach the room:", "OK" if b else "FAIL")

    # C) a disappearance is reported and does NOT claim who took it
    (outbox / "TOPIC-DRAFTS" / "CONCEPT.md").unlink()
    B.mail_watch()
    m = to_room()
    # TWO DIFFERENT THINGS, CHECKED IN TWO DIFFERENT PLACES. That the right key
    # was used is a property of the MECHANISM and is checked against T() itself,
    # in whatever language this installation speaks. That the wording does not
    # accuse anybody is a property of the TEXT, and it is checked in ENGLISH,
    # which is the product's own language — the other translations are the locale
    # guard's business.
    #
    # Nailing both to one language cost this stand twice in one day: first it was
    # red for a stranger because it demanded Russian words, then red for us
    # because it demanded English ones. A stand must not depend on a setting.
    _gone = C.T("mail.gone_yours", folder=outbox.name)
    _en = json.loads((pathlib.Path(__file__).resolve().parent
                      / "locale" / "en.json").read_text(encoding="utf-8"))
    c = (len(m) >= 2 and _gone.split("\n")[0][:20] in m[-1]["text"]
         and "cannot tell" in _en["mail.gone_yours"])
    ok &= c; print(" C: the disappearance is reported, nobody is blamed:", "OK" if c else "FAIL")

    # D) the call to the assistant is in place — the binding did not replace it
    d = len(list(C.REQUESTS.glob("mailwatch-*.json"))) >= 1
    ok &= d; print(" D: the call to the assistant is still there:", "OK" if d else "FAIL")

    print("test_folder_room:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
