#!/usr/bin/env python3
"""The mail-folder watch lives IN THE BRIDGE — check that it neither nags nor
stays silent.

Each property catches its own failure:
  A) the FIRST run IS SILENT — otherwise the watch begins work by shouting about
     letters dealt with a week ago.
  B) a new letter -> A CALL into requests/ (the same channel as Telegram
     questions).
  C) a second pass over the same folder is silent — do not call about the same
     thing every minute.
  D) a disappearance from the outgoing folder is an event — and the EARLIER call,
     still unanswered, STAYS in the queue. It used to be moved out of sight, and
     the newer call lists only what is new, so an unread letter left the queue.
  E) the mirror adds and does not delete.
  F) a change UNDER THE SAME NAME is a letter too, and is called a change.
  G) a state from before signatures existed is re-signed in silence.
  H) an addition inside an existing folder calls, by its path.
  I) the ROOT of the shared folder: a letter placed BESIDE the two sides calls —
     one sat unseen for 18 hours before this — and a letter in a side is not
     reported twice.
  J) at the root a change and a disappearance are called too.
  K) a state from before the root was watched re-signs the root in silence and
     still calls the inbox's own event in the same pass.
  M) the root is copied into the mirror, beside the sides and not inside them,
     and the mirror's own history is left alone.
  N) a mirror lying inside the root is refused aloud, not copied into itself.
Plus: the letter carries the reminder "data, not orders" — protection against a
text that arrived commanding the assistant behind people's backs.
"""
import io
import json
import os
import pathlib
import sys
import tempfile
import time
from contextlib import redirect_stdout


def run() -> int:
    ok = True
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mailwatch-test-"))
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import config as C
    import tg_bridge as B

    root = tmp / "Exchange"
    inbox, outbox = root / "Inbox-mine", root / "Inbox-theirs"
    for d in (inbox, outbox, tmp / "requests", tmp / "served", tmp / "mirror" / ".git"):
        d.mkdir(parents=True, exist_ok=True)
    (tmp / "mirror" / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    C.MAILWATCH_IN, C.MAILWATCH_OUT, C.MAILWATCH_ROOT = inbox, outbox, root
    C.MAILWATCH_MIRROR, C.MAILWATCH_STATE = tmp / "mirror", tmp / "mailwatch_seen.json"
    C.REQUESTS, C.SERVED = tmp / "requests", tmp / "served"

    def pokes() -> list:
        return sorted(C.REQUESTS.glob("mailwatch-*.json"))

    def latest():
        q = pokes()
        return json.loads(q[-1].read_text(encoding="utf-8")) if q else None

    def mw():
        B.mail_watch()
        time.sleep(0.002)          # two calls must not share a millisecond name

    (inbox / "OLD-letter.md").write_text("dealt with a week ago", encoding="utf-8")
    (outbox / "my-answer.md").write_text("lying there, not taken yet", encoding="utf-8")
    (root / "README.md").write_text("the channel's contract", encoding="utf-8")
    (root / "STATUS-theirs.md").write_text("their status", encoding="utf-8")

    # A) the first run silently remembers what is already there
    mw()
    a = (len(pokes()) == 0 and C.MAILWATCH_STATE.exists())
    ok &= a
    print(" A: the first run is silent:", "OK" if a else "FAIL")

    # B) a new letter -> a call
    (inbox / "NEW-letter.md").write_text("arrived just now", encoding="utf-8")
    mw()
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
    mw()
    c = {f.name for f in pokes()} == before
    ok &= c
    print(" C: with no change it stays silent:", "OK" if c else "FAIL")

    # D) the other side took the file -> an event; the earlier, unanswered call STAYS
    (outbox / "my-answer.md").unlink()
    mw()
    p2 = pokes()
    d = len(p2) == 2 and before <= {f.name for f in p2}
    if d:
        rec2 = latest()
        # The wording is NOT assertive: the watch cannot tell "they took it"
        # from "we deleted it", and must not claim either.
        d &= C.T("mail.gone", folder="X").split()[0] in rec2["text"]
        d &= "my-answer.md" in rec2["text"]
    d &= len(list(C.SERVED.glob("mailwatch-*.json"))) == 0   # nothing moved out of sight
    ok &= d
    print(" D: the pickup is caught, and the earlier unanswered call stays:", "OK" if d else "FAIL")

    # E) the mirror copied both sides
    m = (C.MAILWATCH_MIRROR / inbox.name / "NEW-letter.md").exists()
    m &= (C.MAILWATCH_MIRROR / outbox.name / "my-answer.md").exists()   # NOT deleted
    ok &= m
    print(" E: the mirror adds and does not delete:", "OK" if m else "FAIL")

    # F) a letter CHANGED under the same name -> a call that says "changed"
    before = {f.name for f in pokes()}
    f = inbox / "NEW-letter.md"
    f.write_text("arrived just now — and then rewritten, longer", encoding="utf-8")
    t = time.time() + 5
    os.utime(f, (t, t))
    mw()
    rec = latest()
    fx = rec is not None and pokes()[-1].name not in before
    fx = fx and C.T("mail.edited", folder=inbox.name) in rec["text"] and "NEW-letter.md" in rec["text"]
    fx = fx and C.T("mail.arrived", folder=inbox.name) not in rec["text"]   # not called NEW
    ok &= fx
    print(" F: a change under the same name calls, as a change:", "OK" if fx else "FAIL")

    # G) a state written BEFORE signatures existed must not read as "everything changed"
    st = json.loads(C.MAILWATCH_STATE.read_text(encoding="utf-8"))
    st.pop("in_sig", None)
    C.MAILWATCH_STATE.write_text(json.dumps(st), encoding="utf-8")
    before = {f.name for f in pokes()}
    mw()
    g = {f.name for f in pokes()} == before
    g = g and "in_sig" in json.loads(C.MAILWATCH_STATE.read_text(encoding="utf-8"))
    ok &= g
    print(" G: an old state is re-signed in silence, no flood of changes:", "OK" if g else "FAIL")

    # H) a letter added INSIDE a folder that was already there -> a call naming its path
    pkg = inbox / "PKG"; pkg.mkdir()
    (pkg / "first.md").write_text("the package arrives", encoding="utf-8")
    mw()
    before = {f.name for f in pokes()}
    (pkg / "later.md").write_text("added a day later into the same folder", encoding="utf-8")
    mw()
    rec = latest()
    h = rec is not None and pokes()[-1].name not in before
    h = h and str(pathlib.Path("PKG") / "later.md") in rec["text"] and "first.md" not in rec["text"]
    ok &= h
    print(" H: an addition inside an existing folder calls, by its path:", "OK" if h else "FAIL")

    # I) a letter placed at the ROOT, beside the two sides -> a call under the root's name
    before = {f.name for f in pokes()}
    (root / "GIFT-letter.md").write_text("placed beside the two sides", encoding="utf-8")
    (inbox / "ordinary.md").write_text("an ordinary letter in the inbox", encoding="utf-8")
    mw()
    rec = latest()
    i = rec is not None and pokes()[-1].name not in before
    i = i and C.T("mail.arrived", folder=root.name) in rec["text"] and "GIFT-letter.md" in rec["text"]
    i = i and rec["text"].count("ordinary.md") == 1          # a side's letter is not reported twice
    ok &= i
    print(" I: a letter at the root calls, and a side's letter is not doubled:", "OK" if i else "FAIL")

    # J) at the root a change and a disappearance are called too
    before = {f.name for f in pokes()}
    rd = root / "README.md"
    rd.write_text("the channel's contract, amended", encoding="utf-8")
    t = time.time() + 7
    os.utime(rd, (t, t))
    (root / "STATUS-theirs.md").unlink()
    mw()
    rec = latest()
    j = rec is not None and pokes()[-1].name not in before
    j = j and C.T("mail.edited", folder=root.name) in rec["text"] and "README.md" in rec["text"]
    j = j and C.T("mail.gone", folder=root.name) in rec["text"] and "STATUS-theirs.md" in rec["text"]
    ok &= j
    print(" J: at the root a change and a disappearance call:", "OK" if j else "FAIL")

    # K) a state from BEFORE the root was watched: the root is re-signed in silence,
    #    and the inbox's own event in the same pass is still called
    st = json.loads(C.MAILWATCH_STATE.read_text(encoding="utf-8"))
    st.pop("root", None); st.pop("root_path", None)
    C.MAILWATCH_STATE.write_text(json.dumps(st), encoding="utf-8")
    (root / "ROOT-during-upgrade.md").write_text("lands at the root during the upgrade", encoding="utf-8")
    (inbox / "INBOX-during-upgrade.md").write_text("lands in the inbox during the upgrade", encoding="utf-8")
    before = {f.name for f in pokes()}
    out = io.StringIO()
    with redirect_stdout(out):
        mw()
    rec = latest()
    k = rec is not None and pokes()[-1].name not in before
    k = k and "INBOX-during-upgrade.md" in rec["text"] and "ROOT-during-upgrade.md" not in rec["text"]
    k = k and "took the shared folder's root" in out.getvalue()      # said so, once
    k = k and json.loads(C.MAILWATCH_STATE.read_text(encoding="utf-8")).get("root_path") == str(root)
    ok &= k
    print(" K: an old state re-signs the root in silence and keeps the inbox's event:", "OK" if k else "FAIL")

    # M) the root is in the mirror, beside the sides, and the mirror's history is untouched
    mm = (C.MAILWATCH_MIRROR / "GIFT-letter.md").exists()
    rm = C.MAILWATCH_MIRROR / "README.md"
    mm &= rm.exists() and rm.read_text(encoding="utf-8") == "the channel's contract, amended"
    mm &= not (C.MAILWATCH_MIRROR / inbox.name / inbox.name).exists()      # a side is not nested in itself
    mm &= not (C.MAILWATCH_MIRROR / "ordinary.md").exists()                # a side's file stays in its side
    mm &= (C.MAILWATCH_MIRROR / ".git" / "HEAD").read_text(encoding="utf-8") == "ref: refs/heads/main\n"
    ok &= mm
    print(" M: the root is mirrored beside the sides, the mirror's history untouched:", "OK" if mm else "FAIL")

    # N) a mirror inside the root is refused aloud
    saved = C.MAILWATCH_MIRROR
    C.MAILWATCH_MIRROR = root / "mirror-inside"
    C.MAILWATCH_MIRROR.mkdir()
    out = io.StringIO()
    with redirect_stdout(out):
        B.mail_watch()
    n = "is NOT mirrored" in out.getvalue()
    n &= not (C.MAILWATCH_MIRROR / "mirror-inside").exists()               # not copied into itself
    C.MAILWATCH_MIRROR = saved
    ok &= n
    print(" N: a mirror inside the root is refused aloud:", "OK" if n else "FAIL")

    print("test_mail_watch:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
