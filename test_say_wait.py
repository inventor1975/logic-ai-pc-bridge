#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: say.py must report what the bridge DID with a message, not only that
it was queued.

Each outcome is driven by a fake bridge in a thread that does to the queue
exactly what the real one does: writes sent/<name>, moves to outbox/rejected/
with a reason, or counts _tries in place.

The CONTROL: a file of the same name already in sent/ from an earlier message
must NOT pass for a delivery. Without it the stand is satisfied by a say.py that
reports "sent" whenever sent/<name> exists.
"""
import contextlib, io, json, os, pathlib, shutil, sys, tempfile, threading, time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as C            # noqa: E402
import say as S               # noqa: E402

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else:    fail += 1; print(f"  FAIL {name}: {why}")

tmp = pathlib.Path(tempfile.mkdtemp(prefix="say-wait-"))
C.OUTBOX, C.SENT = tmp / "outbox", tmp / "sent"
C.OUTBOX.mkdir(); C.SENT.mkdir()
msg = tmp / "m.txt"
msg.write_text("hello", encoding="utf-8")

def run(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = S.main([str(msg), "--chat", "1", *args])
    return rc, buf.getvalue()

def bridge(delay, act):
    t = threading.Thread(target=lambda: (time.sleep(delay), act()))
    t.start()
    return t

def queued(name):
    return C.OUTBOX / f"{name}.json"

def deliver(name):          # the text branch: write sent/, then remove from the queue
    def act():
        item = json.loads(queued(name).read_text(encoding="utf-8"))
        (C.SENT / f"{name}.json").write_text(json.dumps(item), encoding="utf-8")
        queued(name).unlink()
    return act

def reject(name, why):
    def act():
        item = json.loads(queued(name).read_text(encoding="utf-8"))
        item["_rejected"] = why
        (C.OUTBOX / "rejected").mkdir(exist_ok=True)
        (C.OUTBOX / "rejected" / f"{name}.json").write_text(json.dumps(item), encoding="utf-8")
        queued(name).unlink()
    return act

def retry(name, tries):
    def act():
        item = json.loads(queued(name).read_text(encoding="utf-8"))
        item["_tries"] = tries
        queued(name).write_text(json.dumps(item), encoding="utf-8")
    return act

# --- 1. delivered ---
t = bridge(0.3, deliver("s1")); rc, out = run("--name", "s1", "--wait", "5"); t.join()
check("sent: exit 0, says SENT", rc == 0 and out.count("SENT:") == 1 and "NOT SENT" not in out, out)

# --- 2. rejected, with the bridge's reason ---
t = bridge(0.3, reject("r1", "chat 1 is not on the allow list"))
rc, out = run("--name", "r1", "--wait", "5"); t.join()
check("rejected: exit 1, carries the reason", rc == 1 and "not on the allow list" in out, out)

# --- 3. Telegram refused, the bridge keeps trying ---
t = bridge(0.3, retry("t1", 2)); rc, out = run("--name", "t1", "--wait", "1.5"); t.join()
check("retrying: exit 2, says how many refusals",
      rc == 2 and "refused it 2 time" in out and queued("t1").exists(), out)

# --- 4. no bridge at all ---
rc, out = run("--name", "n1", "--wait", "1")
check("still queued: exit 2, file stays queued", rc == 2 and "STILL QUEUED" in out and queued("n1").exists(), out)

# --- 5. CONTROL: a stale sent/ file of the same name is not a delivery ---
stale = C.SENT / "c1.json"
stale.write_text("{}", encoding="utf-8")
old = time.time() - 3600
os.utime(stale, (old, old))
rc, out = run("--name", "c1", "--wait", "1")
check("CONTROL: stale sent/<name> does not count", rc == 2 and "STILL QUEUED" in out, out)

# --- 6. left the queue for nowhere ---
t = bridge(0.3, lambda: queued("g1").unlink()); rc, out = run("--name", "g1", "--wait", "5"); t.join()
check("gone: exit 1, says so", rc == 1 and "LEFT THE QUEUE" in out, out)

# --- 7. --no-wait keeps the old behaviour ---
t0 = time.time(); rc, out = run("--name", "w1", "--no-wait")
check("--no-wait: exit 0 at once", rc == 0 and "queued into" in out and time.time() - t0 < 0.5, out)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nSAY-WAIT {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
