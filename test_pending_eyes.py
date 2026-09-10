#!/usr/bin/env python3
"""Open eyes are shown as a list (never put out automatically), and a malformed
outbox item is refused LOUDLY. The operator's design, 2026-08-23."""
import re, json, time, os, types, tempfile, pathlib

def _load(name):
    src = pathlib.Path("tg_bridge.py").read_text(encoding="utf-8")
    m = re.search(rf"def {name}\(.*?\n\n\n", src, re.S)
    import config as _C
    ns = {"json": json, "time": time, "now": lambda: "T", "T": _C.T}
    exec(compile(m.group(0), "<x>", "exec"), ns)
    return ns

def run():
    ok = True
    ns = _load("pending_eyes")
    tmp = pathlib.Path(tempfile.mkdtemp()); req = tmp/"req"; srv = tmp/"srv"
    req.mkdir(); srv.mkdir()
    ns["C"] = types.SimpleNamespace(REQUESTS=req, SERVED=srv, EYES_AFTER_MIN=0)
    pe = ns["pending_eyes"]
    def mk(n, t="hi"):
        p = req/n; p.write_text(json.dumps({"text": t}), encoding="utf-8")
        os.utime(p, (time.time()-3600, time.time()-3600))
    mk("677-1.json", "hello"); mk("882-1.json", "a question")
    mk("control-9-1.json"); mk("reaction-9-1.json")   # must be excluded
    pe()
    pf = list(req.glob("pending-eyes-*.json")); ok &= len(pf) == 1
    lst = json.loads(pf[0].read_text())["text"]
    ok &= ("677-1" in lst and "882-1" in lst
           and "control-9-1" not in lst and "reaction-9-1" not in lst)
    before = set(req.glob("pending-eyes-*.json")); pe()          # the same set
    ok &= set(req.glob("pending-eyes-*.json")) == before         # -> no new poke
    (req/"677-1.json").unlink(); (req/"882-1.json").unlink(); pe()
    ok &= (not list(req.glob("pending-eyes-*.json"))
           and bool(list(srv.glob("pending-eyes-*.json"))))      # cleared into served

    # Fix A: an item with neither text nor file is refused
    def bad(item): return (not (item.get("text") or "").strip()) and not item.get("file")
    ok &= bad({"chat_id": 1, "path": "/x", "caption": "y"})      # wrong keys
    ok &= not bad({"chat_id": 1, "file": "/x", "text": "ok"})
    ok &= not bad({"chat_id": 1, "text": "hi"})
    print("test_pending_eyes:", "OK" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(run())
