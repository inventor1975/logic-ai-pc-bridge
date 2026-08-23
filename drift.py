#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Tamper watchdog: refuse to run if what's on disk isn't what was approved.

    ./drift.py --check     compare and return an exit code
    ./drift.py --approve   record the current state as approved

THE HONEST BOUNDARY, AND IT MUST BE STATED FIRST. This watchdog does NOT protect
against anyone with access to the bridge's directory: whoever can edit
`tg_bridge.py` can also edit `approved_manifest.json` and this very file. From day
one the package has said that a compromised machine is a compromised bot, and
nothing has changed here.

What it DOES CATCH: an edit that slipped past a deployment. A file patched on the
live tree "just for a minute"; a deployment that didn't fully land; a divergence
between what was tested and what is running. This is exactly the kind of failure
that caught us out on 2026-08-21, and it happens with no ill intent at all.

WHY REFUSE RATHER THAN WARN. A warning is addressed to a reader who may not be
there. A bridge that rolls on with unverified code is serving the gates of
consent — that is, it decides what counts as permission. Something like that is
better off not running at all than running as who-knows-what.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import config as C

EXIT_DRIFT = 90          # our own code: a tamper refusal must NOT be confused with a crash
WATCHED = ("tg_bridge.py", "config.py", "propose.py", "pending.py", "react.py",
           "edit.py", "unreact.py", "seal.py", "gate_health.py", "drift.py",
           "rules.py", "test_gate.py", "test_attach.py")
APPROVED = C.ROOT / "approved_manifest.json"
REFUSALS = C.ROOT / "drift_refusals.jsonl"


def manifest() -> dict[str, str]:
    """Fingerprints of what is actually running.

    A LIST OF NAMES IS NOT ENOUGH, and that was a hole. A watchdog that knows only
    its own roster won't notice a NEW file — and Python itself picks up certain
    things by name (`sitecustomize.py`), and any new module alongside it could be
    imported by tomorrow's edit. So we take both the roster AND every .py in the
    directory: a file appearing is just as much a divergence as one changing.
    """
    out = {}
    names = set(WATCHED) | {p.name for p in C.ROOT.glob("*.py")}
    for name in sorted(names):
        p = C.ROOT / name
        if p.exists() and p.is_file():
            out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def check() -> tuple[bool, dict]:
    """(everything matches, details). A missing manifest is NOT a reason to wave it through."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = manifest()
    if not APPROVED.exists():
        return False, {"at": now, "reason": "NO_APPROVED_MANIFEST",
                       "note": "there is no approved state — nothing to compare against, "
                               "and that is a refusal, not a default allow"}
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
             "note": "recorded at deployment; see the deployment receipt",
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
        print(f"    GONE     {k}")
    for k in (detail.get("added") or []):
        print(f"    appeared {k}")
    print(f"refusal recorded in {REFUSALS.name}")
    return EXIT_DRIFT


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
