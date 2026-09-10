#!/usr/bin/env python3
"""A guard against the SILENT SHADOWING OF NAMES in tg_bridge.

Written 2026-08-28. The occasion: the module held TWO functions called
`file_job` — the handler for incoming attachments (5 arguments) and the one that
served a source file (2 arguments). The second shadowed the first, and every
image or file sent to the bot died with
`TypeError: file_job() takes 2 positional arguments but 5 were given`.

The bridge kept working all the while: text flowed, answers went out, nothing
looked "broken". What stayed silent was EXACTLY what had stopped working. The
operator sent an image, it never arrived, and only then did the traceback in
bridge.out — which nobody reads — come to light.

Measured against the snapshot of 2026-08-25: there `def file_job` appears ONCE.
So attachments were not being accepted FOR TWO DAYS.

This guard catches the kind, not the instance: any repeated top-level function
or class name is a refusal. Python allows such shadowing silently, so the
prohibition has to come from outside.
"""
import ast
import pathlib
import sys


def main() -> int:
    ok = fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        print(f"  {'OK ' if cond else 'FAIL'} {name}{(' — ' + detail) if detail and not cond else ''}")
        ok += bool(cond); fail += (not cond)

    here = pathlib.Path(__file__).resolve().parent
    for src in sorted(here.glob("*.py")):
        if src.name.startswith("test_"):
            continue
        tree = ast.parse(src.read_text(encoding="utf-8"))
        names = [n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        dup = sorted({n for n in names if names.count(n) > 1})
        check(f"{src.name}: no shadowed names", not dup, f"repeated: {dup}")

    # CONTROL: the guard must actually CATCH, or it is decoration. We feed it a
    # deliberately shadowed name and require the check to see it.
    bad = ast.parse("def f():\n    pass\ndef f():\n    pass\n")
    names = [n.name for n in bad.body if isinstance(n, ast.FunctionDef)]
    check("CONTROL: a planted duplicate is caught",
          sorted({n for n in names if names.count(n) > 1}) == ["f"])

    print(f"\ntest_no_shadowing: {'OK' if fail == 0 else 'FAIL'} ({ok} ok, {fail} fail)")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
