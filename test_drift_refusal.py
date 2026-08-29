#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: the tamper guard actually REFUSES, and refuses for the right reason.

Why this exists, stated plainly. Until now the suite checked the guard's SHAPE —
that its exit code is distinct, that it watches itself, that the manifest globs
every .py. Nothing ever tampered with a tree and asserted that the guard says no.
The one branch the guard exists for had never fired in a test.

An outside reviewer asked exactly that question — whether the refusal branches of
the guard, the allow-list and the consent gate are exercised by the public
artifacts. For the allow-list and the gate the answer was yes. For the guard it
was no. This file is the answer being made true rather than argued.

A safety branch that has never fired cannot be called working.

The guard is driven as a subprocess against a THROWAWAY TREE, so the stand can
tamper freely without touching the real bridge — and so the exit code, not just
the return value, is what gets asserted.
"""
import json, os, pathlib, shutil, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
EXPECTED_DRIFT_CODE = 90

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")

def tree():
    """A minimal throwaway bridge directory the guard can be pointed at."""
    d = pathlib.Path(tempfile.mkdtemp())
    for name in ("drift.py", "config.py"):
        shutil.copy2(HERE / name, d / name)
    (d / "tg_bridge.py").write_text("# stand-in for the bridge\n", encoding="utf-8")
    (d / "settings.json").write_text('{"bot_name": "Logic", "operator": "op"}\n',
                                     encoding="utf-8")
    (d / "token.txt").write_text("0:test\n", encoding="utf-8")
    return d

def run(d, *args):
    r = subprocess.run([sys.executable, str(d / "drift.py"), *args],
                       capture_output=True, text=True, cwd=str(d),
                       env={**os.environ, "BRIDGE_BOT_TOKEN": "0:test"})
    return r.returncode, (r.stdout + r.stderr)

d = tree()

# --- 1. No approved state at all is a REFUSAL, not a default allow ---
code, out = run(d)
check("with no manifest the guard REFUSES", code == EXPECTED_DRIFT_CODE,
      f"exit {code}: a missing approved state waved the tree through")
check("and names the reason", "NO_APPROVED_MANIFEST" in out, out.strip()[:120])

# --- 2. CONTROL: an approved, untouched tree PASSES ---
code, out = run(d, "--approve")
check("approving records a state", code == 0 and (d / "approved_manifest.json").exists())
code, out = run(d)
check("CONTROL: the untouched approved tree passes", code == 0,
      f"exit {code} — the guard refuses everything, so a refusal proves nothing")

# --- 3. A WATCHED file changed by one byte is a refusal ---
p = d / "tg_bridge.py"
p.write_text(p.read_text(encoding="utf-8") + "# one byte of drift\n", encoding="utf-8")
code, out = run(d)
check("a changed watched file REFUSES", code == EXPECTED_DRIFT_CODE, f"exit {code}")
check("the reason is DRIFT", "DRIFT" in out and "NO_APPROVED_MANIFEST" not in out)
check("the refusal names the file that moved", "tg_bridge.py" in out, out.strip()[:160])

# --- 4. The refusal leaves a RECORD, not just a message on a screen ---
rec = d / "drift_refusals.jsonl"
check("the refusal is written down", rec.exists() and rec.read_text(encoding="utf-8").strip(),
      "a refusal nobody can read afterwards is a refusal that did not happen")
if rec.exists() and rec.read_text(encoding="utf-8").strip():
    last = json.loads(rec.read_text(encoding="utf-8").strip().splitlines()[-1])
    check("the record carries the reason and the changed file",
          last.get("reason") == "DRIFT" and "tg_bridge.py" in (last.get("changed") or {}))

# --- 5. A NEW file appearing is drift too — the roster is not the whole story ---
code, out = run(d, "--approve")
(d / "sitecustomize.py").write_text("# arrived from nowhere\n", encoding="utf-8")
code, out = run(d)
check("a file that APPEARS is drift as well", code == EXPECTED_DRIFT_CODE and "sitecustomize" in out,
      f"exit {code}: a watchdog that knows only its roster misses a new module")

# --- 6. A file REMOVED is drift too ---
code, out = run(d, "--approve")
(d / "sitecustomize.py").unlink()
code, out = run(d)
check("a file that DISAPPEARS is drift as well", code == EXPECTED_DRIFT_CODE, f"exit {code}")

# --- 7. CONTROL: something the guard does not watch must NOT trigger it ---
code, out = run(d, "--approve")
(d / "notes.txt").write_text("a human note, not code\n", encoding="utf-8")
code, out = run(d)
check("CONTROL: an unwatched file does NOT trigger a refusal", code == 0,
      "the guard fires on any noise, so operators will learn to ignore it")

# --- 8. CONTROL: the refusal code is its own, not a crash and not a failure ---
check("CONTROL: the refusal code is distinct from 0, 1 and 2",
      EXPECTED_DRIFT_CODE not in (0, 1, 2),
      "a tamper refusal is indistinguishable from an ordinary error")

shutil.rmtree(d, ignore_errors=True)
print(f"\nDRIFT-REFUSAL {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
