#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: queue_watch.py — who takes the folder, and how the watch ends.

WHY THIS EXISTS. Three things changed at once and each fails in silence:

  --mail          the correspondent's folder carries no chat, so by the general
                  rule it fell to the private session. An installation whose
                  folder belongs to the ROOM operator could not say so, and ran
                  a second watcher of its own. A routing change that drops the
                  folder for everyone looks, from outside, exactly like a quiet
                  day — so the table below is checked row by row, and the union
                  of the two zones must still cover every request.
  --until-called  a host now expires monitors after thirty minutes; a plain
                  background command wakes the session by ENDING. A watch that
                  ends without a call wakes the session for nothing, and one
                  that never ends on a call wakes no one at all.
  --doorbell      the bridge touches a file when a request appears. A bell
                  heard as "already rung" costs the whole pause.

Nothing here touches the real queue: every run works on a copy in a temporary
directory, with the queue report replaced by a fixed text.
"""
import json, os, pathlib, shutil, subprocess, sys, tempfile, time

ok = fail = 0
HERE = pathlib.Path(__file__).resolve().parent


def check(name, cond, why=""):
    global ok, fail
    if cond: print(f"  OK   {name}"); ok += 1
    else: print(f"  FAIL {name} — {why}"); fail += 1


PRIVATE, ROOM = "500", "777"
REQUESTS = {
    "100-500":        {"chat_id": 500, "text": "a private question"},
    "200-777":        {"chat_id": 777, "text": "a room question"},
    "mailwatch-1":    {"chat_id": None, "text": "MAIL\\nnew letter"},
    "pending-eyes-1": {"chat_id": None, "text": "OPEN EYES\\n mailwatch-1  12m"},
    "pending-eyes-2": {"chat_id": None, "text": "OPEN EYES\\n 100-500  9m\\n mailwatch-1  12m"},
    "emoji-notice-1": {"chat_id": None, "text": "a rejected mark"},
}
# What pending.py prints: two fields, [kind], the name; the preview on the next line.
REPORT = "\\n".join(f"  12:00 1m [req] {n}\\n      preview of {n}" for n in REQUESTS)

DRIVER = r'''
import json, sys, subprocess, types
sys.argv = ["queue_watch.py"] + json.loads(sys.argv[1])
mode = sys.argv.pop()          # the last element says what to do
import queue_watch as Q
report = open("report.txt", encoding="utf-8").read()
real_run = subprocess.run
def fake_run(cmd, **kw):
    if cmd[-1] == "pending.py":
        return types.SimpleNamespace(stdout=report, returncode=0)
    return real_run(cmd, **kw)
Q.subprocess.run = fake_run
if mode == "route":
    _, entries, trouble = Q.queue()
    print(json.dumps(sorted(e["name"] for e in entries)))
elif mode == "main":
    Q.PAUSE = 0.3
    print("RC", Q.main(), flush=True)
elif mode == "bellrace":
    import time
    calls = [0]
    def fake_run2(cmd, **kw):
        if cmd[-1] == "pending.py":
            calls[0] += 1
            if calls[0] == 1:
                Q.DOORBELL.touch()     # the bell rings WHILE the poll is running
                return types.SimpleNamespace(stdout="", returncode=0)
            return types.SimpleNamespace(stdout=report, returncode=0)
        return real_run(cmd, **kw)
    Q.subprocess.run = fake_run2
    Q.PAUSE = 8.0
    t0 = time.time(); rc = Q.main()
    print("RC", rc, "TOOK", round(time.time() - t0, 2), flush=True)
'''


def sandbox():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="qwatch-"))
    for f in ("queue_watch.py", "config.py"):
        shutil.copy2(HERE / f, tmp / f)
    shutil.copytree(HERE / "locale", tmp / "locale")
    (tmp / "requests").mkdir()
    for n, d in REQUESTS.items():
        (tmp / "requests" / f"{n}.json").write_text(
            json.dumps(dict(d, text=d["text"].replace("\\n", "\n"))), encoding="utf-8")
    (tmp / "report.txt").write_text(REPORT.replace("\\n", "\n"), encoding="utf-8")
    (tmp / "driver.py").write_text(DRIVER, encoding="utf-8")
    return tmp


ENV = dict(os.environ, BRIDGE_BOT_TOKEN="0:test")


def route(tmp, flags):
    p = subprocess.run([sys.executable, "driver.py", json.dumps(flags + ["route"])],
                       cwd=tmp, env=ENV, capture_output=True, text=True, timeout=60)
    try:
        return set(json.loads(p.stdout.strip().splitlines()[-1]))
    except Exception:
        return {"<crash> " + p.stderr[-200:]}


def run() -> int:
    tmp = sandbox()

    # ── THE ROUTING TABLE ──────────────────────────────────────────────────
    me = route(tmp, ["--only", PRIVATE, "--no-mail"])
    check("--only --no-mail takes the private chat, its eye list and service notices",
          me == {"100-500", "pending-eyes-2", "emoji-notice-1"}, str(sorted(me)))
    rooms = route(tmp, ["--except", PRIVATE, "--mail"])
    check("--except --mail takes the rooms AND the folder, and every eye list naming it",
          rooms == {"200-777", "mailwatch-1", "pending-eyes-1", "pending-eyes-2"}, str(sorted(rooms)))
    check("  the two zones together leave NOTHING unwatched",
          set(REQUESTS) <= (me | rooms), str(sorted(set(REQUESTS) - (me | rooms))))
    check("  and the folder itself goes to exactly one of them",
          ("mailwatch-1" in me) + ("mailwatch-1" in rooms) == 1, f"me={sorted(me)} rooms={sorted(rooms)}")
    old_rooms = route(tmp, ["--except", PRIVATE])
    check("without --mail the room zone is unchanged: no folder",
          old_rooms == {"200-777"}, str(sorted(old_rooms)))
    old_me = route(tmp, ["--only", PRIVATE])
    check("without any flag the folder still falls to the private session, as before",
          "mailwatch-1" in old_me and "pending-eyes-1" in old_me, str(sorted(old_me)))

    # ── --watch-peer ───────────────────────────────────────────────────────
    # Two requests the bridge has already called unpicked ("nudged"), one in each
    # zone, beside the plain ones. Each watch must call about the OTHER zone's
    # nudged request, never about a plain one, and without the flag nothing moves.
    extra = {"300-777": {"chat_id": 777, "text": "a room question nobody took", "nudged": "2026-09-30T22:33:23+00:00"},
             "400-500": {"chat_id": 500, "text": "a private question nobody took", "nudged": "2026-09-30T22:58:51+00:00"}}
    for n, d in extra.items():
        (tmp / "requests" / f"{n}.json").write_text(json.dumps(d), encoding="utf-8")
    full = REPORT + "".join(f"\\n  12:00 1m [req] {n}\\n      preview of {n}" for n in extra)
    (tmp / "report.txt").write_text(full.replace("\\n", "\n"), encoding="utf-8")
    me = route(tmp, ["--only", PRIVATE, "--no-mail", "--watch-peer"])
    check("--watch-peer: the private watch calls about the room request the bridge nudged",
          "peer:300-777" in me and "peer:200-777" not in me, str(sorted(me)))
    check("  and still takes its own nudged request as its own, not as a peer's",
          "400-500" in me and "peer:400-500" not in me, str(sorted(me)))
    rooms = route(tmp, ["--except", PRIVATE, "--mail", "--watch-peer"])
    check("  the room watch calls about the private request the bridge nudged",
          "peer:400-500" in rooms and "peer:100-500" not in rooms, str(sorted(rooms)))
    # The folder's calls are never nudged by the bridge: their age decides,
    # against the same threshold (default 20 min). A fresh one must stay quiet.
    (tmp / "requests" / "mailwatch-1.json").touch()
    old_mail = {"mailwatch-9": {"chat_id": None, "text": "MAIL\\nan old letter nobody took"}}
    (tmp / "requests" / "mailwatch-9.json").write_text(json.dumps(old_mail["mailwatch-9"]), encoding="utf-8")
    os.utime(tmp / "requests" / "mailwatch-9.json", (time.time() - 3600, time.time() - 3600))
    full2 = full + "\\n  12:00 1m [req] mailwatch-9\\n      preview of mailwatch-9"
    (tmp / "report.txt").write_text(full2.replace("\\n", "\n"), encoding="utf-8")
    me = route(tmp, ["--only", PRIVATE, "--no-mail", "--watch-peer"])
    check("  a mail call waiting an hour outside the zone is called about (never nudged by the bridge)",
          "peer:mailwatch-9" in me, str(sorted(me)))
    check("  a fresh mail call outside the zone is not",
          "peer:mailwatch-1" not in me, str(sorted(me)))
    rooms = route(tmp, ["--except", PRIVATE, "--mail", "--watch-peer"])
    check("  and the zone that owns the mail takes it as its own, not as a peer's",
          "mailwatch-9" in rooms and "peer:mailwatch-9" not in rooms, str(sorted(rooms)))
    (tmp / "requests" / "mailwatch-9.json").unlink()
    plain = route(tmp, ["--only", PRIVATE, "--no-mail"])
    check("  without the flag no peer call at all",
          not any(n.startswith("peer:") for n in plain), str(sorted(plain)))
    for n in extra:
        (tmp / "requests" / f"{n}.json").unlink()
    (tmp / "report.txt").write_text(REPORT.replace("\\n", "\n"), encoding="utf-8")

    # ── THE CONTRADICTION ──────────────────────────────────────────────────
    p = subprocess.run([sys.executable, "driver.py",
                        json.dumps(["--except", PRIVATE, "--mail", "--no-mail", "main"])],
                       cwd=tmp, env=ENV, capture_output=True, text=True, timeout=30)
    check("--mail with --no-mail is refused aloud, not guessed",
          "RC 2" in p.stdout and "contradict" in p.stdout, p.stdout[-200:] + p.stderr[-200:])

    # ── --until-called ─────────────────────────────────────────────────────
    seen = tmp / ".queue-watch-seen-except-500.json"
    seen.unlink(missing_ok=True)
    t0 = time.time()
    p = subprocess.run([sys.executable, "driver.py",
                        json.dumps(["--except", PRIVATE, "--mail", "--until-called", "main"])],
                       cwd=tmp, env=ENV, capture_output=True, text=True, timeout=30)
    took = time.time() - t0
    check("--until-called ends at the first call", "RC 0" in p.stdout and took < 15,
          f"{took:.1f}s {p.stdout[-200:]}")
    called = p.stdout.count("200-777") >= 1 and p.stdout.count("mailwatch-1") >= 1
    check("  having named everything new in that pass", called, p.stdout[-400:])
    check("  and SEEN is written BEFORE it ends",
          seen.exists() and "mailwatch-1" in json.loads(seen.read_text()), seen.read_text() if seen.exists() else "no SEEN")

    try:
        p = subprocess.run([sys.executable, "driver.py",
                            json.dumps(["--except", PRIVATE, "--mail", "--until-called", "main"])],
                           cwd=tmp, env=ENV, capture_output=True, text=True, timeout=3)
        still = False
    except subprocess.TimeoutExpired as e:
        still, p = True, e
    out = (p.stdout or b"").decode() if isinstance(p.stdout, bytes) else (p.stdout or "")
    check("  with nothing new it does NOT end — an ending with no call wakes the session for nothing",
          still and "200-777" not in out, out[-200:])

    # A problem is a call: the pending report breaks.
    (tmp / "report.txt").write_text("", encoding="utf-8")
    drv = (tmp / "driver.py").read_text(encoding="utf-8")
    (tmp / "driver.py").write_text(drv.replace(
        'return types.SimpleNamespace(stdout=report, returncode=0)',
        'raise OSError("the report is broken")'), encoding="utf-8")
    try:
        p = subprocess.run([sys.executable, "driver.py",
                            json.dumps(["--only", PRIVATE, "--until-called", "main"])],
                           cwd=tmp, env=ENV, capture_output=True, text=True, timeout=10)
        ended = "RC 0" in p.stdout
    except subprocess.TimeoutExpired:
        ended = False
    check("  and a PROBLEM ends it too — in this mode a line that does not end the process wakes no one",
          ended, "it kept running on a broken report")
    (tmp / "driver.py").write_text(drv, encoding="utf-8")
    # EACH CASE LEAVES THE SANDBOX AS IT FOUND IT. The first version of this
    # stand emptied the report here and never put it back, and the next case
    # hung for thirty seconds on correct code, waiting for a call that its own
    # previous case had deleted.
    (tmp / "report.txt").write_text(REPORT.replace("\\n", "\n"), encoding="utf-8")

    # ── --doorbell ─────────────────────────────────────────────────────────
    bell = tmp / ".doorbell"
    probe = (
        "import sys, time, threading, pathlib\n"
        f"sys.argv = ['queue_watch.py', '--only', '{PRIVATE}', '--doorbell', {str(bell)!r}]\n"
        "import queue_watch as Q\n"
        f"bell = pathlib.Path({str(bell)!r})\n"
        "mode = sys.argv_mode = __import__('os').environ['MODE']\n"
        "if mode == 'ring':\n"
        "    mark = Q._bell()\n"
        "    threading.Timer(0.8, lambda: bell.touch()).start()\n"
        "elif mode == 'race':\n"
        "    mark = Q._bell(); bell.touch()        # rings between the mark and the wait\n"
        "else:\n"
        "    mark = Q._bell()\n"
        "t0 = time.time(); Q.wait_for_bell(mark, 6.0); print(round(time.time() - t0, 2))\n")
    (tmp / "probe.py").write_text(probe, encoding="utf-8")
    def waited(mode):
        p = subprocess.run([sys.executable, "probe.py"], cwd=tmp, env=dict(ENV, MODE=mode),
                           capture_output=True, text=True, timeout=30)
        try: return float(p.stdout.strip().splitlines()[-1])
        except Exception: return -1.0
    bell.touch()
    w = waited("ring")
    check("a ring during the wait ends it early", 0.5 < w < 2.5, f"waited {w}s")
    w = waited("race")
    check("wait_for_bell compares against the mark it is GIVEN, not a fresh one",
          0 <= w < 1.0, f"waited {w}s")
    # AND main() MUST GIVE IT THE MARK FROM BEFORE THE POLL. The check above
    # cannot see that ordering — a mutation moving the mark after the poll left
    # it green. So: the bell rings during the first poll; the second poll must
    # follow at once, not after the full eight-second pause.
    (tmp / ".queue-watch-seen-only-500.json").unlink(missing_ok=True)
    p = subprocess.run([sys.executable, "driver.py",
                        json.dumps(["--only", PRIVATE, "--until-called", "--doorbell", str(bell), "bellrace"])],
                       cwd=tmp, env=ENV, capture_output=True, text=True, timeout=30)
    took = -1.0
    for line in p.stdout.splitlines():
        if line.startswith("RC 0 TOOK"):
            took = float(line.split()[-1])
    check("a ring DURING the poll is heard: main() takes the mark before polling",
          0 <= took < 3.0, f"took {took}s (8s = the ring was lost) {p.stderr[-200:]}")
    w = waited("silent")
    check("no ring -> the full pause, the fallback poll stays", w >= 5.5, f"waited {w}s")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nQUEUE-WATCH-MODES {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(run())
