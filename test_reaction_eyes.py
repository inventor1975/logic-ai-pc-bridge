#!/usr/bin/env python3
"""Variant 1 (the operator, 2026-08-24): a 👀 on MY message
(reaction-<chat>-<mid>) enters open_eye_backlog and is closed through answers,
like any other eye."""
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

    # A) a reaction eye on my message 1208 + an ordinary request 1300
    (req/f"reaction-{CH}-1208.json").write_text('{"reaction":["👍"]}', encoding="utf-8")
    (req/f"1300-{CH}.json").write_text('{"text":"q"}', encoding="utf-8")
    reset(); got = fn(CH)
    ok &= (got == [1208, 1300]); print(" A got:", got, "want [1208,1300]", "OK" if got==[1208,1300] else "FAIL")

    # B) the reaction eye closed through answers -> leaves the list, 1300 stays
    (out/"r1.json").write_text(json.dumps({"answers":[f"reaction-{CH}-1208"]}), encoding="utf-8")
    reset(); got = fn(CH)
    ok &= (got == [1300]); print(" B got:", got, "want [1300]", "OK" if got==[1300] else "FAIL")

    # C) the ordinary request closed -> empty
    (out/"r2.json").write_text(json.dumps({"answers":[f"1300-{CH}"]}), encoding="utf-8")
    reset(); got = fn(CH)
    ok &= (got == []); print(" C got:", got, "want []", "OK" if got==[] else "FAIL")

    # D) a reaction file may sit in served/ too — still visible until closed
    (srv/f"reaction-{CH}-1409.json").write_text('{"reaction":["🔥"]}', encoding="utf-8")
    reset(); got = fn(CH)
    ok &= (got == [1409]); print(" D got:", got, "want [1409]", "OK" if got==[1409] else "FAIL")

    print("test_reaction_eyes:", "OK" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(run())
