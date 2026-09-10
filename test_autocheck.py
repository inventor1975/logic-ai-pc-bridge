#!/usr/bin/env python3
"""The control-question trigger: every SELFCHECK_EVERY-th message yields a
question, a misfire is swallowed, delivery does not suffer. It lifts
control_question() out of the module with C replaced — no network, and without
starting the whole bridge."""
import re, subprocess, tempfile, types, pathlib
import config as _C          # the texts live in the locale, not in the stand

def load():
    src = pathlib.Path("tg_bridge.py").read_text(encoding="utf-8")
    m = re.search(r"def control_question\(.*?\n\n\n", src, re.S)
    import config as _C
    ns = {"subprocess": subprocess, "now": lambda: "T", "int": int, "T": _C.T}
    exec(compile(m.group(0), "<x>", "exec"), ns)
    return ns["control_question"], ns

def _sandbox_selfcheck(tmp):
    """A sandbox copy of the checker. The live one must not be touched: it not
    only KEEPS a history, it also SPENDS cards from its deck — running the tests
    used to eat real questions and move the position round the circle (measured
    2026-08-25)."""
    import shutil
    # WHERE THE COPY COMES FROM. From the installation's settings, not from a
    # hard-coded path: on a stranger's machine no such directory exists, and the
    # stand would be green only here.
    import config as _C
    _cmd = getattr(_C, "SELFCHECK_PRESENT", None) or []
    _exe = next((a for a in _cmd if str(a).endswith(".py")), None)
    if not _exe:
        return ["python3", "-c", "print('present: no checker configured')"]
    src = pathlib.Path(_exe).parent
    dst = pathlib.Path(tmp) / "SelfCheck"
    if src.exists() and not dst.exists():
        shutil.copytree(src, dst)
    return ["python3", str(dst / "selfcheck.py"), "present"]


SANDBOX_SELFCHECK = True


def run():
    ok = True
    tmp = pathlib.Path(tempfile.mkdtemp())
    cq, ns = load()
    ns["C"] = types.SimpleNamespace(
        SELFCHECK_COUNT=tmp / "cnt", SELFCHECK_EVERY=5,
        # A SANDBOX copy: the live checker SPENDS cards from its deck and moves
        # the circle on, and a test has no right to spend real questions.
        SELFCHECK_PRESENT=_sandbox_selfcheck(tmp))
    # DO NOT TOUCH THE LIVE FILE. There used to be an absolute path here to the
    # working state file — and every test run ERASED the checker's history.
    # Measured 2026-08-25: after a day's work the live state held two answers out
    # of fifteen. The checker looked healthy while its record was being destroyed
    # by routine, and there was no way to see it: the file is outside git and
    # carries no timestamps.
    pass  # the checker's state does not belong to the test
    got = [bool(cq()) for _ in range(10)]
    # a question only on the 5th and the 10th
    ok &= got == [False, False, False, False, True, False, False, False, False, True]
    # A MISFIRE MUST BE LOUD. This used to be `cq() is None` with the comment
    # "does not crash" — that is, the silence of a broken checker was FIXED IN
    # PLACE as correct behaviour, and anyone repairing it would break the test. A
    # checker that died soundlessly is indistinguishable from one whose turn has
    # simply not come round. Now we expect a shout.
    ns["C"].SELFCHECK_PRESENT = ["python3", "/no/such.py"]
    ns["C"].SELFCHECK_COUNT.write_text("4")
    said = cq()
    ok &= (said is not None and _C.T("selfcheck.silent", code=2, error="x")[:24] in said)
    # DO NOT TOUCH THE LIVE FILE. There used to be an absolute path here to the
    # working state file — and every test run ERASED the checker's history.
    # Measured 2026-08-25: after a day's work the live state held two answers out
    # of fifteen. The checker looked healthy while its record was being destroyed
    # by routine, and there was no way to see it: the file is outside git and
    # carries no timestamps.
    pass  # the checker's state does not belong to the test
    print("test_autocheck:", "OK" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(run())
