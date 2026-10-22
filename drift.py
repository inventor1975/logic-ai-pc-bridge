#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Tamper watch: refuse to run when what is on disk is not what was approved.

    ./drift.py --check     compare and return an exit code
    ./drift.py --approve   record the present state as the approved one
    ./drift.py --approve --receipt PACK.json      (with an approval policy, below)
    ./drift.py --approve --without-receipt "why"  (an override, written down)

APPROVAL BOUND TO A DEPLOYMENT RECEIPT (since 2026-10-12). Catching an edit that
bypassed the rollout only works if APPROVING it also needs the rollout: a hand
copy followed by --approve was a bypass the watch could not see, and it happened
at least five times between 2026-09-27 and 2026-10-09 on the author's own
installation. An installation that puts `approve_policy.json` beside this file,
    {"receipts": "/path/to/deploy/receipts", "max_age_s": 3600}
gets an --approve that refuses unless --receipt names a deployment receipt from
that folder: a JSON record whose decision is ALLOW, made within max_age_s, that
lists "manifest-sha256:<digest>" for EXACTLY the tree now on disk (any VEIP
evidence pack written by a deployment gate has this shape). Without the policy
file, --approve behaves as before. --without-receipt still approves, and writes
the reason to drift_overrides.jsonl: a bypass that is recorded, not a silent one.

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
POLICY = C.ROOT / "approve_policy.json"
OVERRIDES = C.ROOT / "drift_overrides.jsonl"
EXIT_NO_RECEIPT = 91     # an approval refused for want of a deployment receipt


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


def manifest_digest(files: dict[str, str]) -> str:
    """One digest for a whole manifest: what a deployment receipt names."""
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()


def receipt_problem(path: str | None, now: datetime) -> str | None:
    """None when the receipt allows approving the tree now on disk, else why not."""
    try:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        folder = Path(policy["receipts"]).resolve()
        max_age = float(policy.get("max_age_s", 3600))
    except Exception as e:                       # noqa: BLE001 — a broken policy refuses
        return f"approve_policy.json is unreadable ({type(e).__name__}): fix it, do not delete it"
    if not path:
        return "this installation approves only with --receipt (a deployment receipt)"
    p = Path(path).resolve()
    if p.parent != folder:
        return f"the receipt is not in the receipts folder named by the policy ({folder})"
    try:
        r = json.loads(p.read_text(encoding="utf-8"))
        decision = r["decision"]["classification"]
        made = datetime.fromisoformat(r["created_at"])
        refs = r["action"].get("context_refs") or []
    except Exception as e:                       # noqa: BLE001
        return f"the receipt is unreadable ({type(e).__name__})"
    if decision != "ALLOW":
        return f"the receipt's decision is {decision}, not ALLOW"
    age = (now - made).total_seconds()
    if not 0 <= age <= max_age:
        return f"the receipt is {int(age)} s old (the policy allows {int(max_age)} s)"
    want = "manifest-sha256:" + manifest_digest(manifest())
    if want not in refs:
        return "the receipt names a different tree than the one on disk (a file changed after the deployment)"
    return None


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
        now = datetime.now(timezone.utc)
        note = "recorded during the move; see the move receipt"
        if POLICY.exists():
            receipt = argv[argv.index("--receipt") + 1] if "--receipt" in argv[:-1] else None
            if "--without-receipt" in argv:
                i = argv.index("--without-receipt")
                why = argv[i + 1] if i + 1 < len(argv) else ""
                if not why.strip():
                    print("REFUSED: --without-receipt needs a reason (it is written down)")
                    return EXIT_NO_RECEIPT
                with OVERRIDES.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"at": now.isoformat(timespec="seconds"), "reason": why,
                                        "manifest-sha256": manifest_digest(manifest())},
                                       ensure_ascii=False) + "\n")
                note = f"OVERRIDE without a receipt: {why}"
            else:
                problem = receipt_problem(receipt, now)
                if problem:
                    print(f"REFUSED TO APPROVE: {problem}")
                    return EXIT_NO_RECEIPT
                note = f"approved against the deployment receipt {Path(receipt).name}"
        APPROVED.write_text(json.dumps(
            {"approved_at": now.isoformat(timespec="seconds"), "note": note,
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
