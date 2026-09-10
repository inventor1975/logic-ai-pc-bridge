#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Tamper watch: refuse to run when what is on disk is not what was approved.

    ./drift.py --check     compare and return an exit code
    ./drift.py --approve   record the present state as the approved one

THE HONEST BOUNDARY, NAMED FIRST. This watch does NOT protect against anyone
with access to the bridge's directory: whoever can edit `tg_bridge.py` can also
edit `approved_manifest.json` and this file itself. The package has said from
day one that a compromised machine is a compromised bot, and nothing here
changes that.

What it DOES catch: an edit that bypassed the rollout. A file fixed on the live
tree "just for a minute"; a rollout that did not finish; a gap between what was
tested and what is running. That is exactly the kind of failure that caught us
on 2026-08-21, and it happens with no ill intent at all.

WHY A REFUSAL AND NOT A WARNING. A warning is addressed to a reader who may not
be there. A bridge that carries on with untested code is serving the consent
gate — that is, deciding what counts as permission. Such a thing had better not
run at all than run as something unknown.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import config as C

EXIT_DRIFT = 90          # its own code: a tamper refusal must not look like a crash
WATCHED = ("tg_bridge.py", "config.py", "propose.py", "pending.py", "react.py",
           "edit.py", "unreact.py", "seal.py", "gate_health.py", "drift.py",
           "rules.py", "test_gate.py", "test_attach.py")
APPROVED = C.ROOT / "approved_manifest.json"
REFUSALS = C.ROOT / "drift_refusals.jsonl"


def manifest() -> dict[str, str]:
    """Digests of what actually runs.

    A LIST OF NAMES IS NOT ENOUGH, and that was the hole. A watch that knows
    only its own list will not notice a NEW file — and Python itself picks some
    up by name (`sitecustomize.py`), while any new module alongside may be
    imported by tomorrow's edit. So we take both the list and EVERY .py in the
    directory: a file appearing is as much a divergence as a file changing.
    """
    out = {}
    names = set(WATCHED) | {p.name for p in C.ROOT.glob("*.py")}
    for name in sorted(names):
        p = C.ROOT / name
        if p.exists() and p.is_file():
            out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def check() -> tuple[bool, dict]:
    """(everything matches, details). A missing manifest is NOT a reason to pass."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = manifest()
    if not APPROVED.exists():
        return False, {"at": now, "reason": "NO_APPROVED_MANIFEST",
                       "note": "there is no approved state — nothing to compare "
                               "against, and that is a refusal, not a default allow"}
    old = json.loads(APPROVED.read_text(encoding="utf-8")).get("files", {})
    changed = {k: {"approved": old.get(k), "now": v}
               for k, v in cur.items() if old.get(k) != v}
    gone = [k for k in old if k not in cur]
    added = [k for k in cur if k not in old]
    if not (changed or gone or added):
        return True, {"at": now, "files": len(cur)}
    return False, {"at": now, "reason": "DRIFT", "changed": changed,
                   "removed": gone, "added": added}


def main(argv: list[str]) -> int:
    if "--approve" in argv:
        APPROVED.write_text(json.dumps(
            {"approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "note": "recorded during the move; see the move receipt",
             "files": manifest()}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"approved {len(manifest())} files -> {APPROVED.name}")
        return 0

    ok, detail = check()
    if ok:
        print(f"matches: {detail['files']} files")
        return 0
    with REFUSALS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(detail, ensure_ascii=False) + "\n")
    print(f"REFUSED: {detail['reason']}")
    for k, v in (detail.get("changed") or {}).items():
        print(f"    changed  {k}\n        approved {str(v['approved'])[:16]}…"
              f"\n        now      {str(v['now'])[:16]}…")
    for k in (detail.get("removed") or []):
        print(f"    MISSING  {k}")
    for k in (detail.get("added") or []):
        print(f"    appeared {k}")
    print(f"the refusal is recorded in {REFUSALS.name}")
    return EXIT_DRIFT


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
