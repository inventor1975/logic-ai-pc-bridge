#!/usr/bin/env python3
"""Is the patch alive? Close a request WITHOUT a message and one WITH one."""
import json, subprocess, pathlib, sys
R = pathlib.Path("requests"); S = pathlib.Path("served"); O = pathlib.Path("outbox")
# WE MAKE OUR OWN DIRECTORIES. This stand used to be green only because
# another stand had imported config BEFORE it and the directories appeared as a
# side effect; run alone on a clean install it died with FileNotFoundError.
# Greenness that depends on the order of the run is not greenness. Caught
# 2026-09-10.
for _d in (R, S, O): _d.mkdir(parents=True, exist_ok=True)
ok = True

def run(rid, payload):
    (R/f"{rid}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, "pending.py", "--close", rid, "probe", "🗿"],
                       capture_output=True, text=True)
    return p

# 1. without a message — this used to raise KeyError AFTER the unlink
p = run("t-chatless", {"request_id": "t-chatless", "chat_id": None,
                       "selfcheck": True, "text": "self-check"})
if p.returncode != 0 or "closed without answering" not in p.stdout:
    ok = False; print("FAIL without a message:", p.returncode, p.stdout[-200:], p.stderr[-300:])
elif not (S/"t-chatless.json").exists():
    ok = False; print("FAIL: the served record did not land")
else:
    print("without a message: OK, sets no mark —", p.stdout.strip().splitlines()[-1])
(S/"t-chatless.json").unlink(missing_ok=True)

# 2. with a message — the old behaviour is intact, the mark is set
p = run("t-normal", {"request_id": "t-normal", "chat_id": 111, "message_id": 222,
                     "text": "ordinary"})
mark = O/"222-111.react.json"
if p.returncode != 0 or not mark.exists():
    ok = False; print("FAIL of the ordinary case:", p.returncode, p.stderr[-300:])
else:
    print("with a message: OK, the mark landed —", json.loads(mark.read_text())["emoji"])
mark.unlink(missing_ok=True); (S/"t-normal.json").unlink(missing_ok=True)

print("t_close:", "OK" if ok else "THERE ARE FAILURES")
sys.exit(0 if ok else 1)
