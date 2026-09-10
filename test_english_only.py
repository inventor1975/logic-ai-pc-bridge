#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: the product's own source is English, and only the locales are not.

WHY. This bridge was written by a Russian-speaking author for himself, and for
months that was invisible from inside: 2015 lines of Cyrillic across 31 files —
comments carrying the reasons, variable names, even a file name. None of it
broke anything here, and all of it shut out every reader who does not read
Russian. A product "for the whole world" that can only be maintained by one
household is not a product.

WHAT IS ALLOWED AND WHY. locale/*.json is where every other language lives, so
it is not scanned at all — that is the whole point of having it. Beyond that
there is ONE exemption below, written out in full with its reason, because an
exemption nobody can read is how the rule comes back undone.

The check is on the SOURCE, not on behaviour: the bridge speaks whatever
language its locale says. This is about who can read and repair it.
"""
import pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
CYR = re.compile(r"[А-Яа-яЁё]")
SELF = pathlib.Path(__file__).name

# THE EXEMPTION IS PER LINE, NOT PER FILE. Two places legitimately hold non-Latin
# text: a stand that proves safe_name() does not mangle foreign file names, and a
# guard whose search patterns are themselves foreign words. In both, the non-Latin
# text IS THE SUBJECT of the check rather than something said to a reader.
#
# Exempting the whole file would have been easier and much worse: everything else
# in it would drift back unwatched. A line must be marked deliberately, and the
# marker is greppable, so the exemptions can be counted at any moment.
MARKER = "non-latin-by-design"

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")


def scan(paths):
    hits = []
    for p in paths:
        if p.name == SELF:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if CYR.search(line) and MARKER not in line:
                hits.append(f"{p.name}:{i}")
    return hits


product = sorted(p for p in HERE.glob("*.py") if not p.name.startswith("test_"))
stands = sorted(HERE.glob("test_*.py"))
docs = sorted(HERE.glob("*.md"))

for label, paths in (("the bridge's own code", product),
                     ("the stands", stands),
                     ("the documents", docs)):
    hits = scan(paths)
    check(f"no Russian in {label}", not hits,
          f"{len(hits)} lines in {len({h.split(':')[0] for h in hits})} files: "
          f"{', '.join(hits[:6])}{' …' if len(hits) > 6 else ''}")

check("file names are Latin", not [p.name for p in HERE.iterdir() if CYR.search(p.name)],
      "a Cyrillic file name is silently mangled by git ls-files and by some tools")

# The locales are the exception that makes the rule usable — prove they are there.
loc = sorted((HERE / "locale").glob("*.json"))
check("the locale directory carries the other languages", len(loc) >= 2,
      f"only {len(loc)} locale file(s)")
check("at least one locale really is not English",
      any(CYR.search(p.read_text(encoding="utf-8")) for p in loc),
      "no locale contains anything but Latin — the mechanism is unused")

# CONTROL: the scanner must be able to see what it is looking for.
check("CONTROL: the scanner recognises Cyrillic", bool(CYR.search("да")))
check("CONTROL: the scanner does not flag plain English", not CYR.search("plain english"))

# The exemptions are few enough to be read at a glance, and that is the point:
# a count that grows quietly is how a rule dies.
marked = [f"{p.name}:{i}" for p in sorted(HERE.glob("*.py")) if p.name != SELF
          for i, l in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
          if MARKER in l]
check("the exemptions stay countable", len(marked) <= 5,
      f"{len(marked)} marked lines: {', '.join(marked)}")
print(f"       exempt lines: {', '.join(marked) or 'none'}")

print(f"\nENGLISH-ONLY {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
