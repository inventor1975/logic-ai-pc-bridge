#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: the product installs FOR A STRANGER — from what git ships, plus the
examples.

WHY. We develop the bot and merely use it here, and our installation grew things
a stranger does not have. Measured 2026-09-10: on a clean install the requests/
directory does not exist and the bridge died with FileNotFoundError on the FIRST
incoming message. From our own folder that is invisible — our directories have
existed for ages. This stand plays the stranger: it takes EXACTLY what the
repository ships, puts the example settings beside it instead of ours, and looks
whether the thing starts.

WHAT THIS STAND DOES NOT PROVE. It touches neither Telegram, nor a token, nor
the network. It answers one question: "does what a stranger unpacks run?"
Anything past the first start is not here.
"""
import json, pathlib, shutil, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")

def tracked():
    """Exactly what the repository ships outward."""
    # -z IS REQUIRED. A plain ls-files returns non-Latin names escaped
    # ("\321\201\321\202..."), and a file with such a name is silently not
    # copied — caught by a run on 2026-09-10. The NUL separator gives the bytes
    # as they are.
    r = subprocess.run(["git", "ls-files", "-z"], cwd=HERE, capture_output=True)
    if r.returncode != 0:
        return []
    return [n.decode("utf-8") for n in r.stdout.split(b"\0") if n]

names = tracked()
if not names:
    print("  SKIPPED: not a git tree, nothing to play the stranger with")
    print("\nFRESH-INSTALL SKIPPED")
    sys.exit(0)

with tempfile.TemporaryDirectory(prefix="fresh-") as tmp:
    dst = pathlib.Path(tmp) / "clone"
    # A NAME GIT KNOWS BUT THE DISK DOES NOT is a working-tree deletion that has
    # not been committed yet — legitimate, and no reason for a guard to crash.
    # The first version died on it with FileNotFoundError (found 2026-09-10 on a
    # tree whose git still listed a removed file). A guard that falls over reports
    # nothing; one that says "skipped N" reports everything.
    missing = [n for n in names if not (HERE / n).is_file()]
    for n in names:
        if n in missing:
            continue
        p = dst / n
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / n, p)
    if missing:
        print(f"  NOTE: {len(missing)} tracked name(s) are not on disk and were skipped: "
              f"{', '.join(missing[:3])}{' …' if len(missing) > 3 else ''}")

    check("the repository ships settings examples, not only sources",
          (dst / "settings.json.example").exists() and (dst / "chats.json.example").exists(),
          "a stranger has nothing to start from")
    check("NOT ONE of our own settings files is shipped",
          not (dst / "settings.json").exists() and not (dst / "chats.json").exists()
          and not (dst / "token.txt").exists(),
          "private data would travel into a public repository")

    shutil.copy2(dst / "settings.json.example", dst / "settings.json")
    shutil.copy2(dst / "chats.json.example", dst / "chats.json")

    r = subprocess.run([sys.executable, "-c", "import config as C; print(C.BOT_NAME)"],
                       cwd=dst, capture_output=True, text=True)
    check("the example settings load with no edit to the code", r.returncode == 0,
          (r.stderr or "").strip().splitlines()[-1:] or "")

    # THE FIRST INCOMING MESSAGE. Exactly what used to die: the bridge puts a
    # request into requests/.
    r = subprocess.run([sys.executable, "-c",
        "import config as C, pathlib\n"
        "(C.REQUESTS / 'first.json').write_text('{}', encoding='utf-8')\n"
        "print('ok')"], cwd=dst, capture_output=True, text=True)
    check("the first incoming message does not kill the bridge", r.returncode == 0,
          (r.stderr or "").strip().splitlines()[-1:] or "")

    r = subprocess.run([sys.executable, "-c",
        "import config as C\n"
        "missing = [d.name for d in (C.REQUESTS, C.SERVED, C.OUTBOX, C.SENT, C.MEDIA,\n"
        "        C.PROPOSALS, C.DECIDED, C.VOICE) if not d.is_dir()]\n"
        "print(','.join(missing))"], cwd=dst, capture_output=True, text=True)
    check("the bridge created all its own directories", r.returncode == 0 and not r.stdout.strip(),
          f"not created: {r.stdout.strip()}")

    check("by default the installation IS SILENT (dry_run)",
          json.loads((dst / "settings.json.example").read_text(encoding="utf-8"))
              .get("dry_run") is True,
          "a stranger's first act would be to send messages out")

print(f"\nFRESH-INSTALL {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
