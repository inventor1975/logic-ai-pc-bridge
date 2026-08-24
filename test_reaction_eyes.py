#!/usr/bin/env python3
"""Eyes on MY messages (reaction-<chat>-<mid>) join open_eye_backlog and close
through `answers`, like any other eye."""
import re, json, time, types, tempfile, pathlib

def _load(name):
    src = pathlib.Path("tg_bridge.py").read_text(encoding="utf-8")
    m = re.search(rf"def {name}\(.*?\n\n\n", src, re.S)
    ns = {"re": re, "json": json, "time": time, "_EYE_CACHE": {}}
    exec(compile(m.group(0), "<x>", "exec"), ns)
    return ns

def run():
    ok = True
    ns = _load("open_eye_backlog")
    fn = ns["open_eye_backlog"]
    tmp = pathlib.Path(tempfile.mkdtemp())
    req, srv, sent, out = (tmp/"req", tmp/"srv", tmp/"sent", tmp/"out")
    for d in (req, srv, sent, out): d.mkdir()
    ns["C"] = types.SimpleNamespace(REQUESTS=req, SERVED=srv, SENT=sent, OUTBOX=out)
    CH = 9
    def reset(): ns["_EYE_CACHE"].clear()

    (req/f"reaction-{CH}-1208.json").write_text('{"reaction":["👍"]}', encoding="utf-8")
    (req/f"1300-{CH}.json").write_text('{"text":"q"}', encoding="utf-8")
    reset(); ok &= (fn(CH) == [1208, 1300])

    (out/"r1.json").write_text(json.dumps({"answers":[f"reaction-{CH}-1208"]}), encoding="utf-8")
    reset(); ok &= (fn(CH) == [1300])

    (out/"r2.json").write_text(json.dumps({"answers":[f"1300-{CH}"]}), encoding="utf-8")
    reset(); ok &= (fn(CH) == [])

    (srv/f"reaction-{CH}-1409.json").write_text('{"reaction":["🔥"]}', encoding="utf-8")
    reset(); ok &= (fn(CH) == [1409])

    print("test_reaction_eyes:", "OK" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(run())
