#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: request hooks — the second extension point (settings.json -> on_request).

WHY THIS EXISTS. A session that waits for the bridge used to be woken only by a
watcher it ran itself, polling requests/ every twenty seconds under a monitor
that the host now expires every thirty minutes. The bridge is a service and
outlives every session, so the ring belongs in the bridge: it TELLS a declared
program that a request appeared, and the program decides whom to wake.

The half that matters is what a hook may NOT do. It never speaks in the chat,
its failure never takes the bridge down and never loses a request — the request
stays in requests/ whatever the hook does. And the watch covers every writer,
not a list of them: requests are written from eight places, and a ninth must
ring without anyone remembering to wire it.

Nothing here talks to Telegram: `call` is intercepted and must stay silent.
"""
import json, os, pathlib, stat, subprocess, sys, tempfile, time

ok = fail = 0


def check(name, cond, why=""):
    global ok, fail
    if cond: print(f"  OK   {name}"); ok += 1
    else: print(f"  FAIL {name} — {why}"); fail += 1


def make(tmp, name, body):
    p = tmp / name
    p.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def put(req, name, body):
    (req / f"{name}.json").write_text(body, encoding="utf-8")


def run() -> int:
    here = pathlib.Path(__file__).resolve().parent
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="reqhooks-"))
    sys.path.insert(0, str(here))
    import config as C, tg_bridge as B
    req = tmp / "requests"; req.mkdir()
    C.REQUESTS = req
    said = []
    B.call = lambda method, **kw: said.append((method, kw)) or {"ok": True}

    rings = tmp / "rings.jsonl"
    record = make(tmp, "record.py",
        "import sys\n"
        f"open({str(rings)!r}, 'a', encoding='utf-8').write(sys.stdin.read().strip() + '\\n')\n")
    boom = make(tmp, "boom.py", "import sys\nsys.stderr.write('on fire\\n')\nsys.exit(3)\n")
    slow = make(tmp, "slow.py", "import time\ntime.sleep(5)\n")

    def got():
        if not rings.exists():
            return []
        return [json.loads(x) for x in rings.read_text(encoding="utf-8").splitlines() if x]

    # A failing hook stands FIRST: the ones after it must still be told.
    C.REQUEST_HOOKS = [
        {"run": [str(boom)], "timeout": 5.0},
        {"run": [str(tmp / "no-such-program")], "timeout": 5.0},
        {"run": [str(record)], "timeout": 5.0},
    ]

    put(req, "old-request", '{"chat_id": 1}')
    seen = B.request_hooks_tick(None)
    r = got()
    check("the first pass rings once", len(r) == 1, f"{len(r)} rings")
    check("  as bridge_started", r and r[0]["event"] == "bridge_started", str(r[:1]))
    check("  with no names — what was already there is not announced",
          r and r[0]["requests"] == [], str(r[:1]))

    seen = B.request_hooks_tick(seen)
    check("nothing new -> no ring", len(got()) == 1, f"{len(got())} rings")

    put(req, "12345-500", '{"chat_id": 500, "text": "hello"}')
    seen = B.request_hooks_tick(seen)
    r = got()
    check("a new request rings", len(r) == 2, f"{len(r)} rings")
    last = r[-1] if r else {}
    check("  as new_requests", last.get("event") == "new_requests", str(last))
    item = (last.get("requests") or [{}])[0]
    check("  with its name, its chat and its file",
          item.get("name") == "12345-500" and item.get("chat_id") == 500
          and item.get("file") == str(req / "12345-500.json"), str(item))
    check("  and the bridge it came from",
          (last.get("bridge") or {}).get("root") == str(C.ROOT), str(last.get("bridge")))

    put(req, "b-two", '{"chat_id": 7}'); put(req, "a-one", "not json at all")
    seen = B.request_hooks_tick(seen)
    r = got(); last = r[-1] if r else {}
    names = [x["name"] for x in last.get("requests", [])]
    check("two at once -> ONE ring, both named, sorted", len(r) == 3 and names == ["a-one", "b-two"],
          f"{len(r)} rings, names {names}")
    unreadable = [x for x in last.get("requests", []) if x["name"] == "a-one"]
    check("  an unreadable request still rings, with chat_id None",
          unreadable and unreadable[0]["chat_id"] is None, str(unreadable))

    (req / "12345-500.json").unlink()
    seen = B.request_hooks_tick(seen)
    check("a request that LEAVES does not ring", len(got()) == 3, f"{len(got())} rings")
    put(req, "12345-500", '{"chat_id": 500}')
    seen = B.request_hooks_tick(seen)
    check("  and rings again when it comes back — the watcher forgets the same way",
          len(got()) == 4 and got()[-1]["requests"][0]["name"] == "12345-500", f"{len(got())} rings")

    C.REQUEST_HOOKS = [{"run": [str(slow)], "timeout": 0.5}, {"run": [str(record)], "timeout": 5.0}]
    put(req, "after-slow", '{"chat_id": 9}')
    t0 = time.time()
    seen = B.request_hooks_tick(seen)
    took = time.time() - t0
    check("a hanging hook is cut at its timeout", took < 3.0, f"took {took:.1f}s")
    check("  and the next hook is still told", got()[-1]["requests"][0]["name"] == "after-slow",
          str(got()[-1:]))

    check("the hooks never spoke in the chat", said == [], str(said[:2]))
    left = sorted(p.stem for p in req.glob("*.json"))
    check("every request is still in requests/ — a hook loses the ring, never the request",
          left == ["12345-500", "a-one", "after-slow", "b-two", "old-request"], str(left))

    # THE THREAD STARTS AFTER THE TAMPER WATCH: a bridge that refuses to run
    # must not ring "started".
    src = (here / "tg_bridge.py").read_text(encoding="utf-8")
    main = src[src.index("def main() -> int:"):]
    check("the hook thread starts after the tamper watch",
          main.index("drift.check()") < main.index("target=request_hooks_loop"),
          "request_hooks_loop is started before drift.check()")
    check("  and only when a hook is declared",
          "if not whoami and C.REQUEST_HOOKS:" in main, "no guard on C.REQUEST_HOOKS")

    # THE DECLARATION, read by the real config.py from a real settings.json.
    inst = tmp / "install"; inst.mkdir()
    (inst / "config.py").write_text((here / "config.py").read_text(encoding="utf-8"), encoding="utf-8")
    (inst / "settings.json").write_text(json.dumps({"on_request": [
        {"run": ["touch", "~/bridge/.doorbell"], "timeout_seconds": 3},
        {"timeout_seconds": 3},
        "not an object",
    ]}), encoding="utf-8")
    env = dict(os.environ, BRIDGE_BOT_TOKEN="0:test")
    p = subprocess.run([sys.executable, "-c",
                        "import json, config; print(json.dumps(config.REQUEST_HOOKS))"],
                       cwd=inst, env=env, capture_output=True, text=True, timeout=60)
    try:
        hooks = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        hooks = None
    check("settings: one valid hook is read", hooks is not None and len(hooks) == 1,
          f"{hooks!r} / {p.stderr[-300:]}")
    check("  its ~ is expanded and its timeout kept",
          bool(hooks) and hooks[0]["run"][1] == str(pathlib.Path("~/bridge/.doorbell").expanduser())
          and hooks[0]["timeout"] == 3.0, str(hooks))
    check("  an entry without run, or not an object, is refused ALOUD",
          p.stdout.count("WARNING: on_request entry without run") == 2, p.stdout[-300:])

    print(f"\nREQUEST-HOOKS {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(run())
