#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: every language says everything, and says it about the same things.

WHY. A translation rots differently from code: nothing breaks when a key is
missing, the reader simply gets a foreign sentence in the middle of their own
language — and the author, who does not read that language, never finds out.
So the check cannot be reading. It has to be mechanical:

  1. every key the code asks for exists in English (the fallback of last resort);
  2. every translation carries exactly the keys English carries;
  3. every translation keeps the SAME {placeholders} — a lost {name} is not a
     wording problem, it is a KeyError in front of a stranger;
  4. no translation is left as a copy of the English (that is not a translation,
     it is a promise of one).

English itself is exempt from 4: it is the original.
"""
import ast, json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
LOC = HERE / "locale"
PLACE = re.compile(r"\{([a-z_][a-z_0-9]*)\}")

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")


def keys_asked_by_code():
    """Every T("...") the product asks for, found by parsing, not by grep."""
    asked = set()
    for p in sorted(HERE.glob("*.py")):
        if p.name.startswith("test_"):
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call):
                fn = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                if fn == "T" and n.args and isinstance(n.args[0], ast.Constant) \
                        and isinstance(n.args[0].value, str):
                    asked.add(n.args[0].value)
    return asked


def load(code):
    return {k: v for k, v in json.loads((LOC / f"{code}.json").read_text(encoding="utf-8")).items()
            if not k.startswith("_")}


en = load("en")
others = sorted(p.stem for p in LOC.glob("*.json") if p.stem != "en")

asked = keys_asked_by_code()
missing = sorted(asked - set(en))
check("every key the code asks for exists in English", not missing,
      f"{len(missing)} missing: {', '.join(missing[:6])}")
unused = sorted(set(en) - asked)
check("English carries no key the code never asks for", not unused,
      f"{len(unused)} unused: {', '.join(unused[:6])}")

check("there is more than one language", len(others) >= 1, "only English is present")

for code in others:
    tr = load(code)
    miss = sorted(set(en) - set(tr))
    check(f"{code}: nothing left untranslated", not miss,
          f"{len(miss)} missing: {', '.join(miss[:5])}")
    extra = sorted(set(tr) - set(en))
    check(f"{code}: no key English does not have", not extra, f"{', '.join(extra[:5])}")
    bad = [k for k in set(tr) & set(en)
           if set(PLACE.findall(en[k])) != set(PLACE.findall(tr[k]))]
    check(f"{code}: placeholders kept exactly", not bad,
          f"{len(bad)} differ: {', '.join(bad[:5])}")
    same = [k for k in set(tr) & set(en) if tr[k] == en[k] and len(en[k]) > 24]
    check(f"{code}: not simply a copy of English", not same,
          f"{len(same)} left in English: {', '.join(same[:5])}")

# A LITERAL BACKSLASH-N IS ALWAYS A MISTAKE HERE. JSON writes a real newline as
# \n itself, so a value that CONTAINS those two characters was written by an
# author who escaped once too often — and the reader sees "\n" in the middle of a
# sentence. Caught 2026-09-10 by a live run against the test bot, while this very
# stand was green: six keys in two languages carried it. A guard that cannot see
# the fault it was built for is decoration.
literal = [(code, k) for code in ["en"] + others
           for k, v in load(code).items() if "\\n" in v]
check("no value carries a literal backslash-n", not literal,
      f"{len(literal)}: {', '.join(f'{c}:{k}' for c, k in literal[:6])}")

# CONTROL: the checks must be able to see a fault, or their green means nothing.
check("CONTROL: a missing placeholder is noticed",
      set(PLACE.findall("hi {name}")) != set(PLACE.findall("hi")))
check("CONTROL: an identical placeholder set is accepted",
      set(PLACE.findall("{a} and {b}")) == set(PLACE.findall("{b}/{a}")))
check("CONTROL: a literal backslash-n is recognised", "\\n" in "a\\\\nb")
check("CONTROL: a real newline is NOT flagged", "\\n" not in "a\nb")
check("CONTROL: the parser really finds T() calls", "handler.timeout" in asked,
      "the parse found nothing, so every check above is vacuous")

print(f"\nLOCALES {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
