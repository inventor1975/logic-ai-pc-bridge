#!/usr/bin/env python3
"""Anti-flood of the "against a fool" kind: going over the limit mutes the
sender for a pause, with ONE notification, and the principal is NOT an
exception. The operator's design, 2026-08-23."""
import re, time, types, pathlib

def _load():
    src = pathlib.Path("tg_bridge.py").read_text(encoding="utf-8")
    m = re.search(r"_FLOOD_TIMES.*?\ndef flood_muted\(.*?\n\n\n", src, re.S)
    calls = []
    import config as _C
    # T comes from the real config: the notice's text lives in the locale, and
    # slipping a stub in here would test something other than what people get.
    ns = {"time": time, "now": lambda: "T", "Any": object, "T": _C.T,
          "call": lambda method, **kw: (calls.append(kw.get("text", "")) or {"ok": True}),
          "C": types.SimpleNamespace(FLOOD_N=10, FLOOD_T=20, FLOOD_K=5,
                                     DRY_RUN=False, REPLY_PREFIX="BOT")}
    exec(compile(m.group(0), "<x>", "exec"), ns)
    return ns["flood_muted"], calls

def run():
    fm, calls = _load()
    ok = True
    for _ in range(10):                       # 10 in the window: not a flood yet
        ok &= fm(777, -1, "guest") is False
    ok &= fm(777, -1, "guest") is True        # the 11th: muted
    import config as _C
    ok &= len(calls) == 1 and _C.T("flood.muted", who="guest", minutes=5)[-20:] in calls[0]
    ok &= fm(777, -1, "guest") is True and len(calls) == 1  # after that, silently
    calls.clear()
    for _ in range(10):
        fm(500, -1, "principal")
    ok &= fm(500, -1, "principal") is True and len(calls) == 1   # principal is NO exception
    ok &= fm(999, -1, "other") is False       # someone else is untouched
    print("test_flood:", "OK" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(run())
