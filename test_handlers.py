#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: external handlers — the product's extension point.

WHY THIS EXISTS. The bridge must carry no feature of its operator's own. Until
2026-09-10 it carried 309 lines of one installation's private search, wired to
three absolute paths on one machine. The cure is not deleting that code but
giving the product a place for such things OUTSIDE itself, so that the same
command survives deleting the bridge and installing it again.

The half that matters is the negative one. A handler reaches private material,
so a declaration that says nothing about WHERE must run in the principal's
private chat and nowhere else — a group is exactly where one wrong word
publishes a private index to third parties.

Nothing here talks to Telegram: `call` and `send_file` are intercepted.
"""
import json, os, pathlib, stat, sys, tempfile

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: print(f"  OK   {name}"); ok += 1
    else: print(f"  FAIL {name} — {why}"); fail += 1


def make_handler(tmp, name, body):
    p = tmp / name
    p.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def run() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="handlers-"))
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import config as C, tg_bridge as B

    for d in ("requests", "served", "outbox"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    C.REQUESTS, C.SERVED, C.OUTBOX = tmp / "requests", tmp / "served", tmp / "outbox"

    PRINCIPAL, GROUP = 500600700, -1001234567890
    C.policy = lambda cid: {"principal": PRINCIPAL}

    said, files = [], []
    B.call = lambda method, **kw: said.append(kw.get("text", "")) or {"ok": True}
    B.send_file = lambda cid, path, caption="", as_photo=False: files.append(path.name)

    # A handler that echoes what it was told, so the CONTRACT itself is tested.
    echo = make_handler(tmp, "echo.py",
        "import json,sys\n"
        "d=json.load(sys.stdin)\n"
        "print(json.dumps({'text': 'arg=' + d['arg'] + ' cmd=' + d['command']\n"
        "                          + ' from=' + str(d['from']['id'])}))\n")
    boom = make_handler(tmp, "boom.py", "import sys\nsys.stderr.write('on fire\\n')\nsys.exit(3)\n")
    junk = make_handler(tmp, "junk.py", "print('not json at all')\n")
    slow = make_handler(tmp, "slow.py", "import time\ntime.sleep(5)\n")
    doc = tmp / "answer.txt"; doc.write_text("hello", encoding="utf-8")
    giver = make_handler(tmp, "giver.py",
        "import json\nprint(json.dumps({'text':'here','files':[%r,'/no/such/file']}))\n" % str(doc))
    digits = make_handler(tmp, "digits.py",
        "import json,sys\nd=json.load(sys.stdin)\nprint(json.dumps({'text':'n=' + d['groups'][0]}))\n")

    def declare(entries):
        C.HANDLERS = []
        import re
        for e in entries:
            pat = e.get("pattern") or (r"^\s*" + re.escape(e["command"]) + r"(?:[\s:]+(?P<arg>.+))?\s*$")
            C.HANDLERS.append({"command": e.get("command") or e["pattern"],
                               "re": re.compile(pat, re.I | re.U | re.S),
                               "run": e["run"], "where": e.get("where", "principal_private"),
                               "help": "", "timeout": e.get("timeout", 30)})

    def deliver(text, chat_id=PRINCIPAL, chat_type="private"):
        said.clear(); files.clear()
        chat = {"id": chat_id, "type": chat_type}
        msg = {"message_id": 1, "chat": chat, "from": {"id": chat_id, "first_name": "T"}}
        h, m = B.handler_for(text, chat_id, chat)
        if h: B.handler_job(h, chat_id, msg, m, text)
        return h, (said[0] if said else "")

    print("\nthe contract: what goes in, what comes back")
    declare([{"command": "/ac", "run": [sys.executable, str(echo)]}])
    h, out = deliver("/ac what did I say about paradox")
    check("a declared command is matched", h is not None, "not matched at all")
    check("the argument reaches the handler", "arg=what did I say about paradox" in out, out)
    check("the command name reaches the handler", "cmd=/ac" in out, out)
    check("the sender reaches the handler", f"from={PRINCIPAL}" in out, out)
    h, out = deliver("/ac: colon form works")
    check("colon separates the argument too", "arg=colon form works" in out, out)
    h, _ = deliver("please /ac in the middle of a line")
    check("a command inside a sentence is NOT a command", h is None, "matched mid-sentence")
    h, _ = deliver("just a message")
    check("an ordinary message reaches the assistant, not a handler", h is None)

    print("\nwhere: silence is default-deny")
    h, _ = deliver("/ac secret", chat_id=GROUP, chat_type="group")
    check("without an explicit where a handler does NOT run in a group", h is None,
          "a private index would have been published to a group")
    declare([{"command": "/ac", "run": [sys.executable, str(echo)], "where": "anywhere"}])
    h, _ = deliver("/ac public", chat_id=GROUP, chat_type="group")
    check("where=anywhere does run in a group", h is not None)
    declare([{"command": "/ac", "run": [sys.executable, str(echo)], "where": "principal_private"}])
    h, _ = deliver("/ac not mine", chat_id=111222333, chat_type="private")
    check("someone else's private chat is not the principal's", h is None)

    print("\nfailure is reported, never swallowed")
    declare([{"command": "/x", "run": [sys.executable, str(boom)]}])
    _, out = deliver("/x")
    check("a failing handler says so", "exit 3" in out or "/x" in out, out)
    check("the handler's own stderr is quoted", "on fire" in out, out)
    declare([{"command": "/x", "run": [sys.executable, str(junk)]}])
    _, out = deliver("/x")
    check("unreadable output is reported",
          C.T("handler.bad_output", command="/x", error="e", tail="t")[:12] in out, out)
    declare([{"command": "/x", "run": [sys.executable, "/no/such/program.py"]}])
    _, out = deliver("/x")
    check("a handler that cannot even start is reported", bool(out), "silence")
    declare([{"command": "/x", "run": [sys.executable, str(slow)], "timeout": 1}])
    _, out = deliver("/x")
    # Against T() itself, not against English words: this line was green for us
    # and red for an installation set to another language — the same trap as in
    # the folder-room stand. What is checked is that the TIMEOUT KEY was used.
    check("a hanging handler is stopped and reported",
          C.T("handler.timeout", command="/x", seconds=1)[:12] in out, out)

    print("\nfiles and groups")
    declare([{"command": "/give", "run": [sys.executable, str(giver)]}])
    said.clear(); files.clear()
    deliver("/give")
    check("a file the handler names is sent", "answer.txt" in files, str(files))
    declare([{"pattern": r"^\s*/f([1-9])\s*$", "run": [sys.executable, str(digits)]}])
    _, out = deliver("/f7")
    check("a pattern's groups reach the handler", "n=7" in out, out)
    h, _ = deliver("/f0")
    check("what the pattern does not match is not a command", h is None)

    print("\nlanguage")
    check("failure text comes from the locale, not from a bare sentence",
          not C.T("handler.timeout", command="/x", seconds=1).startswith("?"),
          "the key is missing from locale/en.json")

    print(f"\nHANDLERS {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(run())
