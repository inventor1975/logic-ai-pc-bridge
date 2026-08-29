#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Control-question trigger: every SELFCHECK_EVERY-th call yields a question, a
misfire is swallowed, and delivery is unaffected.

NO EXTERNAL PATH. This stand used to invoke a script by absolute path into one
developer's home directory. It passed there and failed on every other machine —
a fresh clone on the SAME machine could not catch it, because the dependency was
machine-wide, not directory-wide. Found by an outside reader, not by us.
The stub below is written into a temp directory, so the stand carries its own
world and the same run happens everywhere.
"""
import re, subprocess, sys, tempfile, types, pathlib

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")

def load():
    src = pathlib.Path(__file__).resolve().parent.joinpath("tg_bridge.py").read_text(encoding="utf-8")
    m = re.search(r"def control_question\(.*?\n\n\n", src, re.S)
    assert m, "control_question not found — fail loudly, do not pass on nothing"
    ns = {"subprocess": subprocess, "now": lambda: "T", "int": int}
    exec(compile(m.group(0), "<autocheck>", "exec"), ns)
    return ns["control_question"], ns

tmp = pathlib.Path(tempfile.mkdtemp())
stub = tmp / "stub_present.py"
stub.write_text("print('CONTROL QUESTION')\n", encoding="utf-8")

cq, ns = load()
ns["C"] = types.SimpleNamespace(
    SELFCHECK_COUNT=tmp / "cnt", SELFCHECK_EVERY=5,
    SELFCHECK_PRESENT=[sys.executable, str(stub)])

got = [bool(cq()) for _ in range(10)]
check("a question only on the 5th and the 10th call",
      got == [False, False, False, False, True, False, False, False, False, True],
      f"got {got}")

ns["C"].SELFCHECK_PRESENT = [sys.executable, str(tmp / "no-such.py")]
ns["C"].SELFCHECK_COUNT.write_text("4")
check("CONTROL: a misfire returns None and does not crash", cq() is None,
      "a broken command takes the message down with it")

ns["C"].SELFCHECK_PRESENT = []
ns["C"].SELFCHECK_COUNT.write_text("4")
check("CONTROL: no command configured is OFF, not broken", cq() is None,
      "an empty command must mean 'no questions', not an exception")

ns["C"].SELFCHECK_PRESENT = [sys.executable, str(stub)]
ns["C"].SELFCHECK_EVERY = 5
ns["C"].SELFCHECK_COUNT.write_text("4")
check("CONTROL: the stub really does produce a question",
      (cq() or "").strip() == "CONTROL QUESTION",
      "the checks above would pass even with the whole mechanism removed")

print(f"\nAUTOCHECK {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
raise SystemExit(1 if fail else 0)
