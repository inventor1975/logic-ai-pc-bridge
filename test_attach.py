#!/usr/bin/env python3
"""v1.1.0 tests — attachments and the per-chat signature.

Offline: not a single network call. It checks what can be checked without
Telegram — parsing the message, sanitizing the filename, choosing the signature.

A separate reason this file exists: on 2026-08-21 an image from a third
party landed in the inbox with an EMPTY request and was closed as "nothing to answer".
The first two tests below are about making sure that does not happen again.
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

print("attachments — what the bridge even notices")
photo = {"photo": [{"file_id": "s", "file_size": 100},
                   {"file_id": "l", "file_size": 9000}]}
a = B.attachments_of(photo)
check("image noticed", len(a) == 1 and a[0]["kind"] == "photo")
check("the LARGEST of the size ladder is taken", a[0]["file_id"] == "l")
check("an empty message yields no attachments", B.attachments_of({}) == [])
check("a sticker is NOT downloaded", B.attachments_of({"sticker": {"file_id": "x"}}) == [])
doc = {"document": {"file_id": "d", "file_name": "a.pdf", "file_size": 10}}
check("document noticed", B.attachments_of(doc)[0]["kind"] == "document")
both = {**photo, **doc}
check("image and document together — both", len(B.attachments_of(both)) == 2)

print("\nthe filename is DATA, not a path")
check("directory traversal stripped", B.safe_name("../../config.py", "x") == "config.py")
check("absolute path stripped", B.safe_name("/etc/passwd", "x") == "passwd")
check("an empty name yields the default", B.safe_name("", "photo.jpg") == "photo.jpg")
check("None yields the default", B.safe_name(None, "photo.jpg") == "photo.jpg")
check("Cyrillic is preserved", B.safe_name("отчёт 2026.pdf", "x") == "отчёт 2026.pdf")
check("exotic characters are replaced", "$" not in B.safe_name("a$b;rm -rf.txt", "x"))
check("a name of only dots does not pass", B.safe_name("...", "d.bin") == "d.bin")
check("length is capped", len(B.safe_name("я" * 400, "x")) <= 120)

print("\nthe signature — an empty string is a CHOICE, not an omission")
DEF = C.REPLY_PREFIX
check("chat with no setting — the shared signature",
      B.outgoing_prefix({}, {}) == DEF)
check("chat with an EMPTY signature — empty, not the shared one",
      B.outgoing_prefix({"reply_prefix": ""}, {}) == "")
check("chat with its own signature — its own",
      B.outgoing_prefix({"reply_prefix": "Х:"}, {}) == "Х:")
check("text SENT OUTWARD is always signed, even in a chat with no signature",
      B.outgoing_prefix({"reply_prefix": ""}, {"no_marker": True}) == C.COPY_PREFIX)
check("a RELAY of someone else's words is always signed",
      B.outgoing_prefix({"reply_prefix": ""}, {"relay": True}) == C.RELAY_PREFIX)

print("\nassembling the body")
check("with a signature — separated by a space", B.compose("Л:", "текст") == "Л: текст")
check("without a signature — NO leading space", B.compose("", "текст") == "текст")
check("without a signature the text is untouched", B.compose("", " с краю ") == " с краю ")

print("\nthe size threshold is declared and sensible")
check("the ceiling is positive", C.MEDIA_MAX_BYTES > 0)
check("the ceiling is no higher than what the Bot API serves",
      C.MEDIA_MAX_BYTES <= 20 * 1024 * 1024)
check("attachments have their own directory", C.MEDIA.name == "media")

print("\nattachment cleanup — by overflow, not by age")
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
check("under budget — touches nothing", rm == [])
rm = B.sweep_media(root=tmp, budget=900, pending=set())
check("over budget — removes the OLD first", rm == ["1-100"])
check("the fresh one remains", (tmp / "3-100").exists())
check("after cleanup it fits within budget",
      sum(f.stat().st_size for f in tmp.rglob("*") if f.is_file()) <= 900)

tmp2 = Path(tempfile.mkdtemp())
for n in ("1-100", "2-100", "3-100"):
    d = tmp2 / n; d.mkdir(); (d / "f.bin").write_bytes(b"x" * 400)
    t = _t.time() - (400 - int(n[0]) * 100)
    os.utime(d, (t, t))
rm = B.sweep_media(root=tmp2, budget=900, pending={"1-100"})
check("something AWAITING A REPLY is not deleted, even if it is the oldest",
      (tmp2 / "1-100").exists() and rm == ["2-100"])
check("the next one by seniority is removed instead", not (tmp2 / "2-100").exists())

tmp3 = Path(tempfile.mkdtemp())
d = tmp3 / "9-100"; d.mkdir(); (d / "f.bin").write_bytes(b"x" * 5000)
rm = B.sweep_media(root=tmp3, budget=100, pending={"9-100"})
check("if everything is awaiting a reply — deletes NOTHING", rm == [] and d.exists())
check("cleanup on a nonexistent directory does not crash",
      B.sweep_media(root=tmp3 / "нет", budget=1, pending=set()) == [])
for t_ in (tmp, tmp2, tmp3): shutil.rmtree(t_, ignore_errors=True)

check("the attachment budget is declared", C.MEDIA_BUDGET_BYTES > C.MEDIA_MAX_BYTES)

print("\nsending a file outward — building the request, no network")
tmpf = Path(tempfile.mkdtemp()) / "отчёт.md"
tmpf.write_bytes("данные".encode())
r = B.send_file(1, Path("/нет/такого/файла.txt"))
check("a nonexistent file — an honest refusal, not an exception",
      r.get("ok") is False and "нет такого" in r.get("description", ""))
check("the send function exists and takes a path", callable(B.send_file))
import inspect
src = inspect.getsource(B.send_file)
check("the caption is trimmed to the Bot API limit (1024)", "1024" in src)
check("document and photo — different methods",
      "sendDocument" in src and "sendPhoto" in src)
check("the multipart boundary is derived from the content, not random",
      "sha256" in src and "boundary" in src)
import shutil as _sh; _sh.rmtree(tmpf.parent, ignore_errors=True)

print("\nthe gate on files — the rules log")
# The approvers of rules/grants in these tests must be REAL approvers
# (rule_for/grant_for now verify membership, not just a nonempty id).
C.all_approvers = lambda: {1, 7, 500600700}
base = Path(tempfile.mkdtemp())
(base / "ok.md").write_text("x"); (base / "ok.zip").write_text("x")
other = Path(tempfile.mkdtemp()); (other / "чужой.md").write_text("x")
APPROVED = [{"id": "R001", "chat_id": 42, "dir": str(base), "glob": "*.md",
             "added_by_user_id": 500600700}]

check("an empty log ALLOWS nothing",
      B.rule_for(42, base / "ok.md", []) is None)
check("a rule covers its own directory and pattern",
      (B.rule_for(42, base / "ok.md", APPROVED) or {}).get("id") == "R001")
check("a different PATTERN is not covered", B.rule_for(42, base / "ok.zip", APPROVED) is None)
check("a different ROOM is not covered", B.rule_for(99, base / "ok.md", APPROVED) is None)
check("a different DIRECTORY is not covered", B.rule_for(42, other / "чужой.md", APPROVED) is None)
check("traversal via .. does NOT pass",
      B.rule_for(42, base / ".." / other.name / "чужой.md", APPROVED) is None)

NOAPPROVER = [dict(APPROVED[0], added_by_user_id=None)]
check("a rule with NO approver has no effect — a forgery does not pass",
      B.rule_for(42, base / "ok.md", NOAPPROVER) is None)

# A nonempty but FOREIGN id (not an approver) also does not pass — corrupting a file
# with an arbitrary nonzero id used to be accepted.
NOTAPPROVER = [dict(APPROVED[0], added_by_user_id=999999)]
check("a rule from a NON-approver id is rejected (not just nonemptiness)",
      B.rule_for(42, base / "ok.md", NOTAPPROVER) is None)

EXPIRED = [dict(APPROVED[0], expires_at="2020-01-01T00:00:00+00:00")]
check("an expired rule has no effect", B.rule_for(42, base / "ok.md", EXPIRED) is None)
FUTURE = [dict(APPROVED[0], expires_at="2099-01-01T00:00:00+00:00")]
check("a non-expired one has effect", B.rule_for(42, base / "ok.md", FUTURE) is not None)
BROKEN = [dict(APPROVED[0], expires_at="позавчера")]
check("an unreadable expiry is treated AGAINST sending",
      B.rule_for(42, base / "ok.md", BROKEN) is None)
NODIR = [{"id": "R", "chat_id": 42, "added_by_user_id": 1}]
check("a rule with no directory has no effect (no 'anything, anywhere')",
      B.rule_for(42, base / "ok.md", NODIR) is None)
import shutil as _s
for t_ in (base, other): _s.rmtree(t_, ignore_errors=True)

print("\nstricter: exact paths, room list, project label")
b2 = Path(tempfile.mkdtemp())
(b2 / "названный.md").write_text("x"); (b2 / "новый.md").write_text("x")
EXACT = [{"id": "R010", "project": "work", "chats": [42, 43],
          "paths": [str(b2 / "названный.md")], "added_by_user_id": 7}]
check("an exact path is allowed",
      (B.rule_for(42, b2 / "названный.md", EXACT) or {}).get("id") == "R010")
check("a NEW file in the same folder is NOT allowed — that is the strictness",
      B.rule_for(42, b2 / "новый.md", EXACT) is None)
check("the second listed room is covered too",
      B.rule_for(43, b2 / "названный.md", EXACT) is not None)
check("an unlisted room is not covered",
      B.rule_for(44, b2 / "названный.md", EXACT) is None)

LABEL = [{"id": "R011", "project": "work", "chats": [42],
          "dirs": [{"dir": str(b2), "glob": "*.md"}], "added_by_user_id": 7}]
check("the whole folder — a new file is covered",
      B.rule_for(42, b2 / "новый.md", LABEL) is not None)
FAKE = [{"id": "R012", "project": "work", "chats": [42],
         "added_by_user_id": 7}]
check("the project LABEL does NOT grant permission on its own",
      B.rule_for(42, b2 / "новый.md", FAKE) is None)
OLD14 = [{"id": "R001", "chat_id": 42, "dir": str(b2), "glob": "*.md",
          "added_by_user_id": 7}]
check("the v1.4 form (chat_id/dir/glob) still works",
      B.rule_for(42, b2 / "новый.md", OLD14) is not None)
import shutil as _s3; _s3.rmtree(b2, ignore_errors=True)

print("\na rule travels from proposal to log")
import inspect
src = inspect.getsource(B.flush_outbox)
check("the rule field is placed into the pending proposal", '"rule": prop.get("rule")' in src)
# _close became a thin wrapper (lock + idempotency) over _close_locked;
# the log/rule-writing logic lives in the implementation, so that is what we inspect.
csrc = inspect.getsource(B._close) + inspect.getsource(B._close_locked)
check("the log is written only on APPROVED and only with a uid",
      'verdict == "APPROVED"' in csrc and 'and uid' in csrc)
check("the approver goes into the rule record", "added_by_user_id" in csrc)

import inspect as _i
_src = _i.getsource(B.flush_outbox)
check("a refused file LEAVES THE QUEUE rather than being renamed in place",
      "C.NEEDS_CONSENT / f.name" in _src and 'C.OUTBOX / f"needs-consent' not in _src)
check("the awaiting-consent directory is declared", C.NEEDS_CONSENT.name == "needs_consent")

print("\nthe batch — one-time grants by fingerprint")
bd = Path(tempfile.mkdtemp()); f1 = bd / "один.md"; f1.write_bytes(b"aaa")
import hashlib as _h
D1 = _h.sha256(b"aaa").hexdigest()
saved = C.GRANTS
C.GRANTS = bd / "grants.json"
import json as _j
def put(gs): C.GRANTS.write_text(_j.dumps(gs), encoding="utf-8")

put([{"id": "G001", "chat_id": 42, "sha256": D1,
      "added_by_user_id": 7, "used_at": None}])
check("a grant by fingerprint fires",
      (B.grant_for(42, f1) or {}).get("id") == "G001")
check("a foreign room is not covered", B.grant_for(43, f1) is None)

f1.write_bytes("ПОДМЕНА".encode())
check("TAMPERING with the content after the mark — does not pass", B.grant_for(42, f1) is None)
f1.write_bytes(b"aaa")

put([{"id": "G002", "chat_id": 42, "sha256": D1,
      "added_by_user_id": 7, "used_at": "2026-08-22T00:00:00+00:00"}])
check("a spent grant no longer has effect", B.grant_for(42, f1) is None)
put([{"id": "G003", "chat_id": 42, "sha256": D1,
      "added_by_user_id": None, "used_at": None}])
check("a grant with no approver has no effect", B.grant_for(42, f1) is None)

put([{"id": "G004", "chat_id": 42, "sha256": D1,
      "added_by_user_id": 7, "used_at": None}])
B.spend_grant("G004")
check("a spent one is marked and does not fire a second time",
      B.grant_for(42, f1) is None)
C.GRANTS = saved
check("the batch ceiling is declared and small enough that the list stays readable",
      0 < C.BATCH_MAX <= 20)
import shutil as _s4; _s4.rmtree(bd, ignore_errors=True)

print("\ndead end, marker, and the tampering watchdog")
import inspect as _i2
_fo = _i2.getsource(B.flush_outbox)
check("a refused file WAKES the assistant rather than lying silent",
      "needsfile-" in _fo and "./propose.py --batch" in _fo)
_nu = _i2.getsource(B.nudge_unanswered)
check("the reminder is sent ONCE per message", '"nudged"' in _nu)
check("one's own notes do not count as waiting on a human",
      '"verdict-"' in _nu and '"needsfile-"' in _nu)
check("the silence threshold is declared and reasonable", 5 <= C.NUDGE_AFTER_MIN <= 120)

import drift as _d
check("a tampering refusal has its OWN return code", _d.EXIT_DRIFT not in (0, 1, 2))
check("the watchdog watches itself", "drift.py" in _d.WATCHED)
check("the watchdog watches the consent gate", "tg_bridge.py" in _d.WATCHED)
_saved = _d.APPROVED
_d.APPROVED = Path(tempfile.mkdtemp()) / "нет.json"
_okd, _det = _d.check()
check("NO approved state — that is a REFUSAL, not a default allow",
      _okd is False and _det["reason"] == "NO_APPROVED_MANIFEST")
_d.APPROVED = _saved

print("\nsecurity: ceiling, header, new file")
import inspect as _i3
_ff = _i3.getsource(B.fetch_file)
check("the download goes in CHUNKS, not a single read()",
      "resp.read(" in _ff and "resp.read()" not in _ff)
check("the stream is cut off at the ceiling, the partial download is deleted",
      "got > cap" in _ff and "unlink" in _ff)
check("the size is asked of the API, not just taken from the update",
      'res.get("file_size")' in _ff)
_sf = _i3.getsource(B.send_file)
check("the filename is sanitized before the header",
      'replace(\'"\'' in _sf or "replace('\"'" in _sf)
check("a newline in the name is scrubbed too", '\\r' in _sf and '\\n' in _sf)
import drift as _d2
_dm = _i3.getsource(_d2.manifest)
check("the watchdog sees ALL .py files, not just its own list",
      'C.ROOT.glob("*.py")' in _dm)

print("\nthe write notice describes what it is ABOUT to do")
_a = C.announce_text(111111111)
check("it mentions writing the conversation to a file", "ПИШЕТСЯ В ФАЙЛ" in _a)
check("it mentions ATTACHMENTS — this was added in v1.1.0", "ВЛОЖЕНИЯ" in _a)
check("it mentions voice transcription", "расшифров" in _a)
check("it says nothing goes outward on its own initiative", "по своему почину" in _a)
_g = C.announce_text(-5101395964)
check("where a signature exists, it is mentioned", "ИИ(" in _g)
check("where there is no signature, it is not mentioned", "ИИ(" not in _a)
_an = _i3.getsource(B.announce)
check("the notice key includes the text FINGERPRINT, not just the chat number",
      "sha256" in _an and "key" in _an)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
