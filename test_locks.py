#!/usr/bin/env python3
"""Tests for the state lock: a one-off consent does not come back to life, and
a decision is made once.

The race this closes: grants.json/rules.json are edited read-modify-write from
two threads (the main _close, the pump's spend_grant/sweep_proposals). Without a
shared lock and an atomic write an edit was lost — worst of all the used_at of a
one-off grant, and the file could go out a second time without a new "yes".

Offline: the network is not touched.
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


def run():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for attr in ("ROOT", "PROPOSALS", "DECIDED", "REQUESTS"):
            d = tmp if attr == "ROOT" else tmp / attr.lower()
            d.mkdir(exist_ok=True); setattr(C, attr, d)
        C.GRANTS = tmp / "grants.json"
        C.RULES = tmp / "rules.json"

        # --- _atomic_write: a whole file, with no .tmp left behind ---
        B._atomic_write(tmp / "x.json", '{"a":1}')
        check("_atomic_write: the file is written whole",
              (tmp / "x.json").read_text() == '{"a":1}')
        check("_atomic_write: no temporary file is left",
              not (tmp / "x.json.tmp").exists())

        # --- _close APPROVED with a batch -> one grant, verdict APPROVED ---
        pf = C.PROPOSALS / "100-200.json"
        prop = {"chat_id": 200, "message_id": 100, "one_line": "send a",
                "batch": {"chat_id": 200,
                          "files": [{"name": "a", "sha256": "hh", "bytes": 1}]}}
        pf.write_text(json.dumps(prop), encoding="utf-8")
        B._close(pf, dict(prop), "APPROVED", uid=7)
        gs = json.loads(C.GRANTS.read_text())
        check("_close APPROVED: exactly one grant", len(gs) == 1)
        check("_close APPROVED: used_at is empty (not spent)",
              gs and gs[0].get("used_at") is None)
        dec = json.loads((C.DECIDED / "100-200.json").read_text())
        check("_close APPROVED: the decision is recorded as APPROVED",
              dec.get("verdict") == "APPROVED")
        check("_close: pf is removed from the pending set", not pf.exists())

        # --- IDEMPOTENCE: a repeated _close (EXPIRED) neither duplicates nor
        #     overwrites. This is how the decide vs sweep_proposals race is
        #     settled. ---
        gid = gs[0]["id"]
        B._close(pf, dict(prop), "EXPIRED", uid=None)
        gs2 = json.loads(C.GRANTS.read_text())
        check("idempotence: the grant is NOT duplicated", len(gs2) == 1)
        dec2 = json.loads((C.DECIDED / "100-200.json").read_text())
        check("idempotence: the APPROVED verdict is not overwritten by EXPIRED",
              dec2.get("verdict") == "APPROVED")

        # --- spend_grant: spends the one-off, sets used_at ---
        B.spend_grant(gid)
        gs3 = json.loads(C.GRANTS.read_text())
        check("spend_grant: used_at is set",
              gs3[0].get("used_at") is not None)
        # a repeated spend neither revives nor changes anything
        before = gs3[0]["used_at"]
        B.spend_grant(gid)
        gs4 = json.loads(C.GRANTS.read_text())
        check("spend_grant: a repeat does not change what is already spent",
              gs4[0]["used_at"] == before)

    print("test_locks:", "OK" if fail == 0 else "FAIL", f"({ok} ok, {fail} fail)")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
