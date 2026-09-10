#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: the product holds not one PRIVATE name — of a person, a machine or a
chat.

WHY. We DEVELOP the bot and merely USE it here. The line got rubbed out: all the
work between 2026-08-24 and 2026-09-10 happened in the LIVE tree rather than
here, and one installation grew into the product — the code called an outside
person by name, paths led to ONE machine, a private chat's id sat in the source.

WHY A GUARD AND NOT MEMORY. The operator's word, 2026-09-10: "and somehow not
forget". Anything that rests on memory can be forgotten; a stand that turns red
cannot. The same argument as for the machine-path guard from which the path
pattern here is taken: from inside one's own machine this trouble is invisible,
and only a stranger sees it.

WHAT IS NOT A VIOLATION. The copyright line — the product's author is named by
right. Data files (chats.json, settings.json, grants.json, token.txt,
*_seen.json) are not shipped and never enter git, so they are not scanned.
"""
import pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
SELF = pathlib.Path(__file__).name

# An installation's data, not the product: private things belong there.
# rules.json is the rule book: it holds real chat ids BY DESIGN, exactly like
# chats.json. arkady_seen.json is the watch state under its OLD name, still lying
# in installations that predate the rename. Both are an installation's data. They
# were missing from this list and the guard turned red on the live tree for
# holding what it is supposed to hold — found 2026-09-10 rehearsing a rollout.
DATA = {"chats.json", "settings.json", "grants.json", "rules.json", "token.txt",
        "mailwatch_seen.json", "mail_watch_seen.json", "arkady_seen.json",
        "approved_manifest.json", "drift_refusals.jsonl"}

COPYRIGHT = re.compile(r"Copyright \d{4} Vitaly Reznik")

RULES = [
    # (the rule's name, what we look for, how it is cured)
    ("a machine path",
     re.compile(r"/home/[A-Za-z0-9._-]+|/Users/[A-Za-z0-9._-]+"
                r"|/media/[A-Za-z0-9._-]+|/mnt/[A-Za-z0-9._-]+"
                r"|[A-Za-z]:\\Users\\"),
     "an installation's path belongs in settings.json, not in the code"),
    ("a person's name",
     # re.I IS REQUIRED. Without it the same name in capitals slipped past, and
     # the guard reported 18 lines where there were more. Caught by a run on
     # 2026-09-10. The patterns below are non-Latin BY DESIGN: they are what is
     # being searched for, not text addressed to a reader.
     re.compile(r"ARKADY_|аркад|Arkady|Адриан|Adrian|Виталий|Vitaliy", re.U | re.I),  # non-latin-by-design
     "call people by their ROLE (principal, correspondent), not by name"),
]

# A CHAT ID IS AN ALLOW LIST, NOT A DENY LIST. Forbidding "these three real
# ones" means missing the fourth that appears tomorrow. So the other way round:
# ONLY invented numbers may be shipped, and they are listed here by name. A new
# stand that needs a number has its author write it in DELIBERATELY, and a live
# id will not wander by accident into a list called "synthetic". The form of the
# rule is the operator's (the allow-list .gitignore of 2026-08-29): err TOWARDS
# REFUSAL.
SYNTHETIC = {"123456789", "500600700", "100200300", "555000111", "-9999000111",
             "111222333", "-1001234567890",
             "-100987654321",   # the invented group id in chats.json.example
             "2147483648"}      # NOT an id: media_budget_bytes = 2 GiB in the settings
                                # example — a ten-digit number the id pattern cannot
                                # tell apart from a chat. Listed so, not ignored so.
ID = re.compile(r"(?<![0-9A-Za-z._-])(-?\d{9,})(?![0-9A-Za-z._-])")

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond:
        ok += 1; print(f"  OK   {name}")
    else:
        fail += 1; print(f"  FAIL {name} — {why}")

# WHAT THE PRODUCT SHIPS, NOT WHAT HAPPENS TO LIE IN THE DIRECTORY. The first
# version walked the directory and then needed an ever-growing list of data files
# to ignore — patched twice within one hour on 2026-09-10 (rules.json, then a
# stale state file). Patching the same list twice means the FORM of the rule is
# wrong. The question this guard answers is "does the product carry a private
# name", and the product is exactly what git ships. The directory walk remains
# only as a fallback outside a git tree, where DATA still filters it.
import subprocess
_r = subprocess.run(["git", "ls-files", "-z"], cwd=HERE, capture_output=True)
if _r.returncode == 0 and _r.stdout:
    _names = [n.decode("utf-8") for n in _r.stdout.split(b"\0") if n]
    # EVERY tracked file, not four extensions. With the extension filter a runtime
    # log (dev.out, tracked since 2026-08-22) carried two live chat ids past this
    # guard unseen — found 2026-09-10 while measuring what a public release would
    # carry. "What git ships" means all of it; binary files are skipped below.
    files = sorted(HERE / n for n in _names)
else:
    files = sorted(p for p in HERE.glob("*.py")) + sorted(HERE.glob("*.md")) \
            + sorted(HERE.glob("*.json")) + sorted(HERE.glob("*.service"))
files = [p for p in files if p.name != SELF and p.name not in DATA and p.is_file()]

for rule, pat, cure in RULES:
    hits = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if COPYRIGHT.search(line) or "guard-fixture" in line:
                continue
            m = pat.search(line)
            if m:
                hits.append(f"{f.name}:{i}: {m.group(0)[:40]}")
    check(f"no such thing: {rule}", not hits,
          f"{len(hits)} lines in {len({h.split(':')[0] for h in hits})} files — {cure}")
    for h in hits[:6]:
        print(f"         {h}")
    if len(hits) > 6:
        print(f"         … and {len(hits) - 6} more")

hits = []
for f in files:
    try:
        text = f.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if "guard-fixture" in line:
            continue
        for m in ID.finditer(line):
            if m.group(1) not in SYNTHETIC:
                hits.append(f"{f.name}:{i}: {m.group(1)}")
check("no such thing: a live chat id", not hits,
      f"{len(hits)} lines in {len({h.split(':')[0] for h in hits})} files — "
      f"a live chat id belongs in chats.json; a stand uses one from SYNTHETIC")
for h in hits[:6]:
    print(f"         {h}")
if len(hits) > 6:
    print(f"         … and {len(hits) - 6} more")

# CONTROL: the guard must STAY SILENT on what is legitimate, or its green means
# nothing.
check("CONTROL: /usr/bin is not a machine path",
      not RULES[0][1].search("shutil.which('python3') or '/usr/bin/python3'"))
check("CONTROL: the author's copyright is not a violation",
      bool(COPYRIGHT.search("# Copyright 2026 Vitaly Reznik")))
check("CONTROL: a short number is not a chat id",
      not ID.search("timeout = 20260910"))
check("CONTROL: digits inside a digest are not a chat id",
      not ID.search("digest db2902819408774e"))
check("CONTROL: a synthetic id from the list is not a violation",
      all(m.group(1) in SYNTHETIC for m in ID.finditer("PRINCIPAL = 500600700")))
check("CONTROL: a live id is caught",
      any(m.group(1) not in SYNTHETIC for m in ID.finditer("chat = -5101395964")))

print(f"\nNO-PRIVATE-NAMES {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
