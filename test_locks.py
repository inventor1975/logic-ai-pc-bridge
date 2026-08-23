#!/usr/bin/env python3
"""State-lock tests: one-time consent does not resurrect, a decision is final.

The race this closes: grants.json/rules.json are edited read-modify-write
from two threads (main _close, pump spend_grant/sweep_proposals). Without a shared
lock and an atomic write, an edit was lost — worst of all the used_at of a one-time
grant — and the file could be sent again without a fresh "yes".

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

        # --- _atomic_write: the whole file, no .tmp leftover ---
        B._atomic_write(tmp / "x.json", '{"a":1}')
        check("_atomic_write: file written in full",
              (tmp / "x.json").read_text() == '{"a":1}')
        check("_atomic_write: temp file not left behind",
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
        check("_close APPROVED: used_at empty (not spent)",
              gs and gs[0].get("used_at") is None)
        dec = json.loads((C.DECIDED / "100-200.json").read_text())
        check("_close APPROVED: decision recorded as APPROVED",
              dec.get("verdict") == "APPROVED")
        check("_close: pf removed from the pending set", not pf.exists())

        # --- IDEMPOTENCE: a repeated _close (EXPIRED) does NOT duplicate and does NOT
        #     overwrite. This is exactly how the decide vs sweep_proposals race is quenched. ---
        gid = gs[0]["id"]
        B._close(pf, dict(prop), "EXPIRED", uid=None)
        gs2 = json.loads(C.GRANTS.read_text())
        check("idempotence: grant NOT duplicated", len(gs2) == 1)
        dec2 = json.loads((C.DECIDED / "100-200.json").read_text())
        check("idempotence: APPROVED verdict not overwritten with EXPIRED",
              dec2.get("verdict") == "APPROVED")

        # --- spend_grant: spends the one-time grant, sets used_at ---
        B.spend_grant(gid)
        gs3 = json.loads(C.GRANTS.read_text())
        check("spend_grant: used_at set",
              gs3[0].get("used_at") is not None)
        # a repeated spend neither resurrects nor changes anything
        before = gs3[0]["used_at"]
        B.spend_grant(gid)
        gs4 = json.loads(C.GRANTS.read_text())
        check("spend_grant: a repeat does not change what was already spent",
              gs4[0]["used_at"] == before)

    print("test_locks:", "OK" if fail == 0 else "FAIL", f"({ok} ok, {fail} fail)")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
