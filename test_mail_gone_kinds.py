#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: a file that left the watched folder is told apart ONLY where the folder itself says why.

A correspondent, 2026-10-04: six files reported GONE had been replaced by v0.2 and moved to _Archive. Now:
superseded (a sibling differs only by a version token) and archived (same name under an *archive* folder)
are named as such; everything else stays GONE with the cautious wording.
The CONTROLS: a sibling with a DIFFERENT stem is not a successor; a same-named file outside any archive
folder is not "archived"; an unversioned rename stays GONE.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tg_bridge as B             # noqa: E402

ok = fail = 0
def check(name, got, want):
    global ok, fail
    if got == want: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name}: got {got!r}, want {want!r}")

sup, arc, gone = B.explain_gone(
    ["ERIS/LEGION_A.md", "ERIS/LEGION_B.md", "plan_v1.pdf", "ERIS/notes.txt", "ERIS/C.md", "D.md", "E_v2.md"],
    ["ERIS/LEGION_A_v0.2.md", "_Archive/ERIS/LEGION_B.md", "plan_v2.pdf", "ERIS/notes-final.txt",
     "other/C.md", "E_v3.md"])
check("superseded by a version token", set(sup), {("E_v2.md", "E_v3.md"), ("ERIS/LEGION_A.md", "ERIS/LEGION_A_v0.2.md"), ("plan_v1.pdf", "plan_v2.pdf")})
check("archived under *archive*", arc, [("ERIS/LEGION_B.md", "_Archive/ERIS/LEGION_B.md")])
check("CONTROLS stay gone (other stem, same name outside archive, plain loss)", sorted(gone), ["D.md", "ERIS/C.md", "ERIS/notes.txt"])
check("nothing gone -> nothing said", B.explain_gone([], ["a"]), ([], [], []))
print(f"mail_gone_kinds: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
