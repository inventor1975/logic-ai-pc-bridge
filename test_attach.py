#!/usr/bin/env python3
"""Tests for v1.1.0 — attachments and the per-chat signature.

Offline: not one call to the network. What is checked is what can be checked
without Telegram — parsing a message, sanitising a name, choosing a signature.

A separate reason this file exists: on 2026-08-21 an image from a third party
landed in the inbox as an EMPTY request and was closed as "nothing to answer".
The first two tests below are about that not happening again.
"""
import os, sys, json, tempfile
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

print("attachments — what the bridge notices at all")
photo = {"photo": [{"file_id": "s", "file_size": 100},
                   {"file_id": "l", "file_size": 9000}]}
a = B.attachments_of(photo)
check("an image is noticed", len(a) == 1 and a[0]["kind"] == "photo")
check("the LARGEST of the size ladder is taken", a[0]["file_id"] == "l")
check("an empty message yields no attachments", B.attachments_of({}) == [])
check("a sticker is NOT downloaded", B.attachments_of({"sticker": {"file_id": "x"}}) == [])
doc = {"document": {"file_id": "d", "file_name": "a.pdf", "file_size": 10}}
check("a document is noticed", B.attachments_of(doc)[0]["kind"] == "document")
both = {**photo, **doc}
check("an image and a document together — both", len(B.attachments_of(both)) == 2)

print("\na file name is DATA, not a path")
check("directory traversal is cut off", B.safe_name("../../config.py", "x") == "config.py")
check("an absolute path is cut off", B.safe_name("/etc/passwd", "x") == "passwd")
check("an empty name yields the default", B.safe_name("", "photo.jpg") == "photo.jpg")
check("None yields the default", B.safe_name(None, "photo.jpg") == "photo.jpg")
# non-latin-by-design: these samples ARE the subject of the check — a product
# that speaks seven languages must not mangle names written in them.
check("a non-Latin name survives", B.safe_name("отчёт 2026.pdf", "x") == "отчёт 2026.pdf")  # non-latin-by-design
check("Hebrew survives", B.safe_name("שלום.pdf", "x") == "שלום.pdf")            # non-latin-by-design
check("Chinese survives", B.safe_name("文档.txt", "x") == "文档.txt")             # non-latin-by-design
check("shell metacharacters are replaced", "$" not in B.safe_name("a$b;rm -rf.txt", "x"))
check("a name of nothing but dots does not pass", B.safe_name("...", "d.bin") == "d.bin")
check("the length is bounded", len(B.safe_name("a" * 400, "x")) <= 120)

print("\nthe signature — an empty string is a CHOICE, not an omission")
DEF = C.REPLY_PREFIX
check("a chat with no setting — the general signature",
      B.outgoing_prefix({}, {}) == DEF)
check("a chat with an EMPTY signature — empty, not the general one",
      B.outgoing_prefix({"reply_prefix": ""}, {}) == "")
check("a chat with its own signature — its own",
      B.outgoing_prefix({"reply_prefix": "X:"}, {}) == "X:")
check("text FOR SENDING ON is always signed, even in an unsigned chat",
      B.outgoing_prefix({"reply_prefix": ""}, {"no_marker": True}) == C.COPY_PREFIX)
check("a RELAY of someone else's words is always signed",
      B.outgoing_prefix({"reply_prefix": ""}, {"relay": True}) == C.RELAY_PREFIX)

print("\nassembling the body")
check("with a signature — separated by a space", B.compose("B:", "text") == "B: text")
check("without a signature — NO leading space", B.compose("", "text") == "text")
check("without a signature the text is untouched", B.compose("", " edges ") == " edges ")

print("\nthe size ceiling is declared and makes sense")
check("the ceiling is positive", C.MEDIA_MAX_BYTES > 0)
check("the ceiling is no higher than what the Bot API serves",
      C.MEDIA_MAX_BYTES <= 20 * 1024 * 1024)
check("attachments have their own directory", C.MEDIA.name == "media")

print("\nthe attachment sweep — by overflow, not by age")
import shutil, time as _t
tmp = Path(tempfile.mkdtemp())
def mk(name, size, age_s):
    d = tmp / name; d.mkdir()
    (d / "f.bin").write_bytes(b"x" * size)
    t = _t.time() - age_s
    os.utime(d, (t, t))
    return d
mk("1-100", 400, 300)      # the oldest
mk("2-100", 400, 200)
mk("3-100", 400, 100)      # the freshest
rm = B.sweep_media(root=tmp, budget=10_000, pending=set())
check("under budget — nothing is touched", rm == [])
rm = B.sweep_media(root=tmp, budget=900, pending=set())
check("over budget — the OLDEST goes first", rm == ["1-100"])
check("the fresh one stayed", (tmp / "3-100").exists())
check("after the sweep it fits the budget",
      sum(f.stat().st_size for f in tmp.rglob("*") if f.is_file()) <= 900)

tmp2 = Path(tempfile.mkdtemp())
for n in ("1-100", "2-100", "3-100"):
    d = tmp2 / n; d.mkdir(); (d / "f.bin").write_bytes(b"x" * 400)
    t = _t.time() - (400 - int(n[0]) * 100)
    os.utime(d, (t, t))
rm = B.sweep_media(root=tmp2, budget=900, pending={"1-100"})
check("WHAT AWAITS AN ANSWER is not deleted, even as the oldest",
      (tmp2 / "1-100").exists() and rm == ["2-100"])
check("the next-oldest is cleared instead", not (tmp2 / "2-100").exists())

tmp3 = Path(tempfile.mkdtemp())
d = tmp3 / "9-100"; d.mkdir(); (d / "f.bin").write_bytes(b"x" * 5000)
rm = B.sweep_media(root=tmp3, budget=100, pending={"9-100"})
check("when everything awaits an answer, NOTHING is deleted", rm == [] and d.exists())
check("a sweep over a missing directory does not crash",
      B.sweep_media(root=tmp3 / "none", budget=1, pending=set()) == [])
for t_ in (tmp, tmp2, tmp3): shutil.rmtree(t_, ignore_errors=True)

check("the attachment budget is declared", C.MEDIA_BUDGET_BYTES > C.MEDIA_MAX_BYTES)

print("\nsending a file out — assembling the request, no network")
tmpf = Path(tempfile.mkdtemp()) / "report.md"
tmpf.write_bytes("data".encode())
r = B.send_file(1, Path("/no/such/file.txt"))
check("a missing file gives an honest refusal, not an exception",
      r.get("ok") is False and "no such file" in r.get("description", ""))
check("the send function exists and takes a path", callable(B.send_file))
import inspect
src = inspect.getsource(B.send_file)
check("the caption is cut at the Bot API limit (1024)", "1024" in src)
check("a document and a photo use different methods",
      "sendDocument" in src and "sendPhoto" in src)
check("the multipart boundary is derived from the content, not random",
      "sha256" in src and "boundary" in src)
import shutil as _sh; _sh.rmtree(tmpf.parent, ignore_errors=True)

print("\nthe gate on files — the rule book")
# The approvers of rules and grants in these tests must be REAL approvers
# (rule_for/grant_for now check membership, not merely that the id is non-empty).
C.all_approvers = lambda: {1, 7, 500600700}
base = Path(tempfile.mkdtemp())
(base / "ok.md").write_text("x"); (base / "ok.zip").write_text("x")
other = Path(tempfile.mkdtemp()); (other / "foreign.md").write_text("x")
APPROVED = [{"id": "R001", "chat_id": 42, "dir": str(base), "glob": "*.md",
             "added_by_user_id": 500600700}]

check("an empty book ALLOWS nothing",
      B.rule_for(42, base / "ok.md", []) is None)
check("a rule covers its own directory and pattern",
      (B.rule_for(42, base / "ok.md", APPROVED) or {}).get("id") == "R001")
check("a different PATTERN is not covered", B.rule_for(42, base / "ok.zip", APPROVED) is None)
check("a different ROOM is not covered", B.rule_for(99, base / "ok.md", APPROVED) is None)
check("a different DIRECTORY is not covered", B.rule_for(42, other / "foreign.md", APPROVED) is None)
check("traversal through .. does NOT pass",
      B.rule_for(42, base / ".." / other.name / "foreign.md", APPROVED) is None)

NOAPPROVER = [dict(APPROVED[0], added_by_user_id=None)]
check("a rule with NO approver does not hold — a forgery does not pass",
      B.rule_for(42, base / "ok.md", NOAPPROVER) is None)

# NEW (R8/G7): a non-empty but FOREIGN id (not an approver) does not pass
# either — corrupting the file with an arbitrary non-zero id used to be accepted.
NOTAPPROVER = [dict(APPROVED[0], added_by_user_id=999999)]
check("a rule from a NON-approver id is refused (not merely non-empty)",
      B.rule_for(42, base / "ok.md", NOTAPPROVER) is None)

EXPIRED = [dict(APPROVED[0], expires_at="2020-01-01T00:00:00+00:00")]
check("an expired rule does not hold", B.rule_for(42, base / "ok.md", EXPIRED) is None)
FUTURE = [dict(APPROVED[0], expires_at="2099-01-01T00:00:00+00:00")]
check("an unexpired one holds", B.rule_for(42, base / "ok.md", FUTURE) is not None)
BROKEN = [dict(APPROVED[0], expires_at="the day before yesterday")]
check("an unreadable deadline is read AGAINST sending",
      B.rule_for(42, base / "ok.md", BROKEN) is None)
NODIR = [{"id": "R", "chat_id": 42, "added_by_user_id": 1}]
check("a rule with no directory does not hold (no \"anything anywhere\")",
      B.rule_for(42, base / "ok.md", NODIR) is None)
import shutil as _s
for t_ in (base, other): _s.rmtree(t_, ignore_errors=True)

print("\nstricter: exact paths, a list of rooms, the project label")
b2 = Path(tempfile.mkdtemp())
(b2 / "named.md").write_text("x"); (b2 / "new.md").write_text("x")
EXACT = [{"id": "R010", "project": "SomeProject", "chats": [42, 43],
          "paths": [str(b2 / "named.md")], "added_by_user_id": 7}]
check("an exact path is allowed",
      (B.rule_for(42, b2 / "named.md", EXACT) or {}).get("id") == "R010")
check("a NEW file in the same folder is NOT allowed — that is the strictness",
      B.rule_for(42, b2 / "new.md", EXACT) is None)
check("the second listed room is covered too",
      B.rule_for(43, b2 / "named.md", EXACT) is not None)
check("a room that is not listed is not covered",
      B.rule_for(44, b2 / "named.md", EXACT) is None)

LABEL = [{"id": "R011", "project": "SomeProject", "chats": [42],
          "dirs": [{"dir": str(b2), "glob": "*.md"}], "added_by_user_id": 7}]
check("a whole folder — a new file is covered",
      B.rule_for(42, b2 / "new.md", LABEL) is not None)
FAKE = [{"id": "R012", "project": "SomeProject", "chats": [42],
         "added_by_user_id": 7}]
check("the project LABEL grants nothing by itself",
      B.rule_for(42, b2 / "new.md", FAKE) is None)
OLD14 = [{"id": "R001", "chat_id": 42, "dir": str(b2), "glob": "*.md",
          "added_by_user_id": 7}]
check("the v1.4 shape (chat_id/dir/glob) still works",
      B.rule_for(42, b2 / "new.md", OLD14) is not None)
import shutil as _s3; _s3.rmtree(b2, ignore_errors=True)

print("\na rule travels from the proposal all the way to the book")
import inspect
src = inspect.getsource(B.flush_outbox)
check("the rule field is put into the pending proposal", '"rule": prop.get("rule")' in src)
# _close is now a thin wrapper (lock + idempotence) over _close_locked; the
# logic that writes the book and the rule lives in the implementation, and that
# is what we inspect.
csrc = inspect.getsource(B._close) + inspect.getsource(B._close_locked)
check("the book is written only on APPROVED and only with a uid",
      'verdict == "APPROVED"' in csrc and 'and uid' in csrc)
check("the rule record carries who approved it", "added_by_user_id" in csrc)

import inspect as _i
_src = _i.getsource(B.flush_outbox)
check("a refused file LEAVES THE QUEUE instead of being renamed in place",
      "C.NEEDS_CONSENT / f.name" in _src and 'C.OUTBOX / f"needs-consent' not in _src)
check("the awaiting-consent directory is declared", C.NEEDS_CONSENT.name == "needs_consent")

print("\na batch — one-off grants bound by digest")
bd = Path(tempfile.mkdtemp()); f1 = bd / "one.md"; f1.write_bytes(b"aaa")
import hashlib as _h
D1 = _h.sha256(b"aaa").hexdigest()
saved = C.GRANTS
C.GRANTS = bd / "grants.json"
import json as _j
def put(gs): C.GRANTS.write_text(_j.dumps(gs), encoding="utf-8")

put([{"id": "G001", "chat_id": 42, "sha256": D1,
      "added_by_user_id": 7, "used_at": None}])
check("a grant bound by digest fires",
      (B.grant_for(42, f1) or {}).get("id") == "G001")
check("another room is not covered", B.grant_for(43, f1) is None)

f1.write_bytes("SWAPPED".encode())
check("SWAPPING the content after the mark does not pass", B.grant_for(42, f1) is None)
f1.write_bytes(b"aaa")

put([{"id": "G002", "chat_id": 42, "sha256": D1,
      "added_by_user_id": 7, "used_at": "2026-08-22T00:00:00+00:00"}])
check("a spent grant no longer holds", B.grant_for(42, f1) is None)
put([{"id": "G003", "chat_id": 42, "sha256": D1,
      "added_by_user_id": None, "used_at": None}])
check("a grant with no approver does not hold", B.grant_for(42, f1) is None)

put([{"id": "G004", "chat_id": 42, "sha256": D1,
      "added_by_user_id": 7, "used_at": None}])
B.spend_grant("G004")
check("a spent one is marked and does not fire again",
      B.grant_for(42, f1) is None)
C.GRANTS = saved
check("the batch ceiling is declared and small enough for the list to be read",
      0 < C.BATCH_MAX <= 20)
import shutil as _s4; _s4.rmtree(bd, ignore_errors=True)

print("\nthe dead end, the mark and the tamper watch")
import inspect as _i2
_fo = _i2.getsource(B.flush_outbox)
check("a refused file WAKES the assistant instead of lying silent",
      "needsfile-" in _fo and "./propose.py --batch" in _fo)
_nu = _i2.getsource(B.nudge_unanswered)
check("the nudge is sent ONCE per message", '"nudged"' in _nu)
check("our own notes do not count as a person waiting",
      '"verdict-"' in _nu and '"needsfile-"' in _nu)
check("the silence threshold is declared and sane", 5 <= C.NUDGE_AFTER_MIN <= 120)

import drift as _d
check("a tamper refusal has ITS OWN exit code", _d.EXIT_DRIFT not in (0, 1, 2))
check("the watch watches itself", "drift.py" in _d.WATCHED)
check("the watch watches the consent gate", "tg_bridge.py" in _d.WATCHED)
_saved = _d.APPROVED
_d.APPROVED = Path(tempfile.mkdtemp()) / "none.json"
_okd, _det = _d.check()
check("NO approved state is a REFUSAL, not a default allow",
      _okd is False and _det["reason"] == "NO_APPROVED_MANIFEST")
_d.APPROVED = _saved

print("\nsafety: the ceiling, the header, a new file")
import inspect as _i3
_ff = _i3.getsource(B.fetch_file)
check("the download goes in CHUNKS, not one read()",
      "resp.read(" in _ff and "resp.read()" not in _ff)
check("the stream is aborted at the ceiling and the partial file deleted",
      "got > cap" in _ff and "unlink" in _ff)
check("the size is asked of the API, not only taken from the update",
      'res.get("file_size")' in _ff)
_sf = _i3.getsource(B.send_file)
check("the file name is sanitised before the header",
      'replace(\'"\'' in _sf or "replace('\"'" in _sf)
check("a newline in the name is cleaned too", '\\r' in _sf and '\\n' in _sf)
import drift as _d2
_dm = _i3.getsource(_d2.manifest)
check("the watch sees EVERY .py, not only its own list",
      'C.ROOT.glob("*.py")' in _dm)

print("\nthe recording notice describes what is ACTUALLY collected")
# THE CHAT'S POLICY DECIDES THE SIGNATURE, not which numbers sit in OUR
# installation. There used to be live ids here, and the stand was green only on
# this machine: for a stranger the policy differs and half the checks silently
# changed meaning. We set the policy directly — what is checked is the
# PROPERTY of the notice, not our configuration.
_pol = C.policy
C.policy = lambda cid: {"reply_prefix": cid != 500600700}
# THE ENGLISH IS FORCED HERE, not merely hoped for. The checks below read English
# words, and until now they relied on this installation happening to be set to
# English — so the stand was green for us and RED for anyone whose lang is ru or
# he. Found 2026-09-10 by running the whole stand in three languages after a live
# test. A stand must not depend on a setting.
_lc = C._LC
C._LC = {}
try:
    _a = C.announce_text(500600700)          # a chat with no signature
    # WE CHECK THE ENGLISH — that is the PRODUCT's language. The recording
    # notice is the one text with legal weight; checking it in the language ONE
    # installation happens to have chosen is not checking the product. The
    # completeness of the other languages is the locale guard's business, not
    # this stand's.
    check("it says the conversation is recorded", "WRITTEN TO A FILE" in _a)
    check("it says ATTACHMENTS are kept — added in v1.1.0", "ATTACHMENTS ARE KEPT" in _a)
    check("it says voice is transcribed", "transcribed" in _a)
    check("it says nothing leaves on its own", "my own initiative" in _a)
    _g = C.announce_text(-1001234567890)     # a chat with a signature
    check("where there is a signature, it is mentioned", "AI(" in _g)
    check("where there is none, it is NOT mentioned", "AI(" not in _a)
finally:
    C.policy = _pol
    C._LC = _lc
_an = _i3.getsource(B.announce)
check("the notice key includes a DIGEST of the text, not only the chat id",
      "sha256" in _an and "key" in _an)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
