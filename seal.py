#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Seal old conversation history under your own GPG key.

    ./seal.py --days 7            what would be sealed (shows, changes nothing)
    ./seal.py --days 7 --do       actually seal it

WHY PUBLIC-KEY, AND WHY ONLY THE OLD PART. Encrypting the live log would be
theatre: the bridge must read it on every message, so the key would have to sit
beside the data, and a key beside the data protects against nobody. Sealing to
a PUBLIC key is different — the bridge never needs the private half, so the
private half does not have to be on this machine at all. That is what makes it
worth doing.

WHAT IT PROTECTS AND WHAT IT DOES NOT. It covers a stolen disk, a leaked
backup, a machine sold or repaired. It does NOT cover malware running as you:
that reads the live log directly and needs no key.

READ THIS BEFORE USING IT. Sealing DELETES the plaintext. If the private key is
lost, the history is lost with it — encryption is also a way to destroy data.
Nothing here runs on a schedule, and nothing runs without --do, deliberately.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import config as C

import os
RECIPIENT = os.environ.get("SEAL_RECIPIENT", "")  # email of the GPG key that seals your history; set it before use


def main() -> int:
    days = 30
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    do = "--do" in sys.argv
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    if not C.LOG.exists():
        print("no log yet.")
        return 0
    old, live = [], []
    for line in C.LOG.read_text(encoding="utf-8").splitlines():
        try:
            when = datetime.fromisoformat(json.loads(line)["at"])
        except Exception:
            live.append(line); continue
        (old if when < cutoff else live).append(line)

    print(f"older than {days} days: {len(old)} lines")
    print(f"staying live:           {len(live)} lines")
    if not old:
        return 0
    if not do:
        print("\nnothing changed. Add --do to seal, and read the warning in this "
              "file first: sealing deletes the plaintext.")
        return 0

    sealed = C.ROOT / "sealed"
    sealed.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = sealed / f"log-until-{stamp}.jsonl.gpg"
    r = subprocess.run(["gpg", "--yes", "--batch", "--encrypt",
                        "--recipient", RECIPIENT, "--output", str(dest)],
                       input="\n".join(old).encode(), capture_output=True)
    if r.returncode != 0 or not dest.exists():
        print(f"gpg refused, nothing removed: {r.stderr.decode()[:300]}")
        return 1
    # Only now, with the sealed file on disk and verified non-empty, does the
    # plaintext go. The other order loses data on any failure.
    if dest.stat().st_size == 0:
        print("sealed file is empty — refusing to delete the original.")
        return 1
    C.LOG.write_text("\n".join(live) + ("\n" if live else ""), encoding="utf-8")
    dest.chmod(0o600)
    print(f"sealed -> {dest.name} ({dest.stat().st_size // 1024} KB)")
    print(f"read it with:  gpg -d {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
