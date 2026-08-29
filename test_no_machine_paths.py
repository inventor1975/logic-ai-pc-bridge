#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: nothing in the package points at one particular machine.

Why this exists. v1.15.0 shipped an absolute path into one developer's home
directory — in a test AND in a shipped default. It was inert and it was still
wrong twice over: it carried a stranger's directory layout into a public package,
and it made one stand pass on that machine and fail on every other.

A fresh clone could not catch it. The dependency was MACHINE-wide, not
directory-wide, so cloning into a new folder reproduced nothing. Only a reader on
another computer saw it — which is the whole argument for this file: the check
has to live in the package, because the failure is invisible from inside.

The scan is a rule about the package, not a habit of whoever last edited it.
"""
import pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
# Absolute paths into a user's world. /usr, /etc, /tmp and the like are fine —
# they exist on every machine and carry nobody's name.
MACHINE = re.compile(r"(?:/home/[A-Za-z0-9._-]+|/Users/[A-Za-z0-9._-]+"
                     r"|/media/[A-Za-z0-9._-]+|/mnt/[A-Za-z0-9._-]+"
                     r"|[A-Za-z]:\\\\Users\\\\)")

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")

def scan(text):
    return [m.group(0) for m in MACHINE.finditer(text)]

files = sorted(p for p in HERE.glob("*.py")) + sorted(HERE.glob("*.md")) \
        + sorted(HERE.glob("*.json")) + sorted(HERE.glob("*.service"))
hits = []
for f in files:
    if f.name == pathlib.Path(__file__).name:
        continue                       # this file names the patterns on purpose
    for h in scan(f.read_text(encoding="utf-8", errors="replace")):
        hits.append(f"{f.name}: {h}")

check(f"no machine-specific absolute path in {len(files)} shipped files",
      not hits, "; ".join(hits[:6]))

check("CONTROL: the scanner really detects one when it is there",
      scan("SELFCHECK = ['python3', '/home/someone/tool.py']") != [],
      "the scan matches nothing at all — a green here would mean nothing")
check("CONTROL: an ordinary system path is NOT flagged",
      scan("/usr/bin/python3 and /tmp/work and /etc/hosts") == [],
      "the rule is so wide it would forbid writing any path at all")

print(f"\nNO-MACHINE-PATHS {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
