#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Stand: the contact-form watch lives IN THE BRIDGE — no message missed, none
filed twice, and the token never shown.

A real HTTP server on 127.0.0.1 plays the site, so the request the bridge sends
(the bearer header, the refusal of a redirect) is the one urllib really makes.

Each property catches its own failure:
  A) no contact_watch key -> silent: no file, no line, no request to the site.
  B) the FIRST run files EVERY message already there — unlike the mail watch,
     whose silent first run here would mark as read exactly the messages the
     watch exists to deliver. One call in requests/ and one chat notice each.
  C) the call is DATA FROM THE PUBLIC: chat_id None, not from the principal,
     the warning in its text; the notice carries name, email, time, message.
  D) a second pass with nothing new files nothing.
  E) one new id -> exactly one call and one notice.
  F) 401: nothing filed, nothing marked, and said ONCE over two passes.
  G) a network error (the site down): nothing filed, nothing marked — and the
     message arrives once the site is back.
  H) write-then-mark: when the chat notice cannot be written, the id is NOT
     recorded, and the next pass delivers it.
  I) a long message is cut in the chat with a note naming the call; the call
     keeps the whole text.
  J) at most CONTACT_PER_SCAN per pass; the rest on the next pass, none lost.
  K) a redirect is refused (urllib would carry the token to wherever it points);
     plain http to a remote host is refused without a request.
  L) the token appears in no log line, call, notice or state file.
"""
import http.server
import io
import json
import pathlib
import shutil
import socket
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout

TOKEN = "tok-" + "7f3a9c" * 8          # synthetic, long enough to be unmistakable
CHAT = 500600700                        # synthetic (test_no_private_names SYNTHETIC)

ok = fail = 0
def check(name, cond, why=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {name}")
    else: fail += 1; print(f"  FAIL {name} — {why}")


SITE = {"messages": [], "hits": [], "down": False}


class Site(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        SITE["hits"].append((self.path, self.headers.get("Authorization")))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/contact/inbox")
            self.end_headers()
            return
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            body, code = {"ok": False, "error": "unauthorized"}, 401
        else:
            body, code = {"ok": True, "messages": list(SITE["messages"])}, 200
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def msg(i, text=None):
    return {"id": f"m{i:03d}", "time": f"2026-10-30T10:{i % 60:02d}:00Z",
            "name": f"Writer {i}", "email": f"w{i}@example.org",
            "message": text if text is not None else f"hello number {i}"}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    import config as C
    import tg_bridge as B

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="contactwatch-test-"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    tokf = tmp / "contact.token"
    tokf.write_text(TOKEN + "\n", encoding="utf-8")
    log = io.StringIO()

    def setup(url=base + "/contact/inbox", fresh_state=True):
        for d in ("requests", "outbox"):
            shutil.rmtree(tmp / d, ignore_errors=True)
            (tmp / d).mkdir()
        C.REQUESTS, C.OUTBOX = tmp / "requests", tmp / "outbox"
        C.CONTACTWATCH_URL, C.CONTACTWATCH_TOKEN_FILE = url, tokf
        C.CONTACTWATCH_CHAT, C.CONTACTWATCH_STATE = CHAT, tmp / "contact_watch_seen.json"
        if fresh_state:
            C.CONTACTWATCH_STATE.unlink(missing_ok=True)
        B._CONTACT_COND[0] = None

    def scan() -> str:
        out = io.StringIO()
        with redirect_stdout(out):
            B.contact_watch()
        log.write(out.getvalue())
        time.sleep(0.003)
        return out.getvalue()

    calls = lambda: sorted(C.REQUESTS.glob("contact-*.json"))
    notes = lambda: sorted(C.OUTBOX.glob("contact-*.json"))
    seen = lambda: (json.loads(C.CONTACTWATCH_STATE.read_text(encoding="utf-8"))["seen"]
                    if C.CONTACTWATCH_STATE.exists() else [])
    rd = lambda p: json.loads(p.read_text(encoding="utf-8"))

    # A) no key -> silent
    setup()
    C.CONTACTWATCH_URL = ""
    SITE["hits"].clear()
    out = scan()
    check("A: no contact_watch key — no file, no line, no request to the site",
          not calls() and not notes() and not out and not SITE["hits"]
          and not C.CONTACTWATCH_STATE.exists(),
          f"calls={len(calls())} out={out!r} hits={SITE['hits']}")

    # B) first run files everything
    setup()
    SITE["messages"] = [msg(1), msg(2)]
    scan()
    c, n = calls(), notes()
    check("B: the first run files EVERY message already there (2 calls, 2 notices)",
          len(c) == 2 and len(n) == 2, f"calls={len(c)} notices={len(n)}")
    check("B: both ids recorded only after delivery", seen() == ["m001", "m002"], str(seen()))
    check("B: the bearer token was sent", (
        "/contact/inbox", f"Bearer {TOKEN}") in SITE["hits"], "no authorised hit")

    # C) the shape
    r0 = rd(c[0]) if c else {}
    check("C: a call is a service call: chat_id None, not from the principal",
          r0.get("chat_id") is None and r0.get("from_principal") is False
          and r0.get("selfcheck") is False and r0.get("request_id") == c[0].stem
          and c[0].stem.startswith("contact-"), str(r0)[:200])
    check("C: the call says it is DATA FROM THE PUBLIC, before and after the text",
          r0.get("text", "").count(C.T("contact.public_data")) == 2
          and r0["text"].index(C.T("contact.public_data")) < r0["text"].index("hello number 1")
          < r0["text"].rindex(C.T("contact.public_data")), r0.get("text", "")[:200])
    n0 = rd(n[0]) if n else {}
    t0 = n0.get("text", "")
    check("C: the notice goes to chat_id with name, email, time and message",
          n0.get("chat_id") == CHAT and "Writer 1" in t0 and "w1@example.org" in t0
          and "2026-10-30T10:01:00Z" in t0 and "hello number 1" in t0, str(n0)[:200])
    check("C: the notice and the call share one stem (one message, one name)",
          [p.name for p in c] == [p.name for p in n], f"{[p.name for p in c]} vs {[p.name for p in n]}")

    # D) nothing new
    scan()
    check("D: a second pass with nothing new files nothing",
          len(calls()) == 2 and len(notes()) == 2, f"calls={len(calls())}")

    # E) one new id
    SITE["messages"].append(msg(3))
    scan()
    check("E: one new id -> one call and one notice",
          len(calls()) == 3 and len(notes()) == 3 and seen()[-1] == "m003"
          and "hello number 3" in rd(calls()[-1])["text"], f"calls={len(calls())} seen={seen()}")

    # F) 401
    tokf.write_text("a-wrong-token", encoding="utf-8")
    SITE["messages"].append(msg(4))
    o1, o2 = scan(), scan()
    check("F: 401 files nothing and marks nothing",
          len(calls()) == 3 and "m004" not in seen(), f"calls={len(calls())} seen={seen()}")
    check("F: 401 is said once over two passes",
          "401" in o1 and o2 == "", f"first={o1!r} second={o2!r}")
    tokf.write_text(TOKEN + "\n", encoding="utf-8")
    scan()
    check("F: with the right token back, the held message arrives",
          len(calls()) == 4 and seen()[-1] == "m004", f"calls={len(calls())} seen={seen()}")

    # G) network error
    C.CONTACTWATCH_URL = f"http://127.0.0.1:{free_port()}/contact/inbox"   # nobody listens
    SITE["messages"].append(msg(5))
    o1, o2 = scan(), scan()
    check("G: a network error files nothing and marks nothing",
          len(calls()) == 4 and "m005" not in seen(), f"calls={len(calls())}")
    check("G: the error is said once over two passes", o1 != "" and o2 == "",
          f"first={o1!r} second={o2!r}")
    C.CONTACTWATCH_URL = base + "/contact/inbox"
    scan()
    check("G: the site back -> the message arrives", seen()[-1] == "m005" and len(calls()) == 5,
          f"seen={seen()}")

    # H) write-then-mark
    SITE["messages"].append(msg(6))
    good_outbox = C.OUTBOX
    C.OUTBOX = tmp / "no-such-dir" / "outbox"
    out = scan()
    check("H: the notice could not be written -> the id is NOT recorded",
          "m006" not in seen() and "not marked" in out, f"seen={seen()} out={out!r}")
    C.OUTBOX = good_outbox
    scan()
    check("H: the next pass delivers it (re-delivered, not lost)",
          seen()[-1] == "m006" and any("hello number 6" in rd(p)["text"] for p in notes()),
          f"seen={seen()}")

    # I) a long message
    setup()
    long = "x" * (B.CONTACT_TEXT_MAX + 1500)
    SITE["messages"] = [msg(7, long)]
    scan()
    c, n = calls(), notes()
    nt = rd(n[0])["text"] if n else ""
    check("I: the chat notice is cut, with a note naming the call",
          n and len(nt) < B.CONTACT_TEXT_MAX + 600 and c[0].stem in nt
          and str(len(long)) in nt, f"len={len(nt)}")
    check("I: the call keeps the whole text", c and long in rd(c[0])["text"])

    # J) the per-pass cap
    setup()
    SITE["messages"] = [msg(i) for i in range(100, 100 + B.CONTACT_PER_SCAN + 2)]
    scan()
    first = len(calls())
    scan()
    check("J: at most CONTACT_PER_SCAN per pass, the rest on the next, none lost",
          first == B.CONTACT_PER_SCAN and len(calls()) == B.CONTACT_PER_SCAN + 2
          and seen() == [m["id"] for m in SITE["messages"]],
          f"first={first} total={len(calls())}")

    # K) a redirect is refused; plain http to a remote host is refused
    setup(url=base + "/redirect")
    SITE["messages"] = [msg(8)]
    SITE["hits"].clear()
    scan()
    check("K: a redirect is not followed — nothing filed, the token not carried on",
          not calls() and not seen() and [h[0] for h in SITE["hits"]] == ["/redirect"],
          f"hits={[h[0] for h in SITE['hits']]}")
    setup(url="http://example.org/contact/inbox")
    out = scan()
    check("K: plain http to a remote host is refused before any request",
          "not https" in out and not calls(), out)
    check("K: CONTROL — https and local http are accepted",
          B.contact_url_refusal("https://example.org/x") is None
          and B.contact_url_refusal("http://127.0.0.1:8/x") is None
          and B.contact_url_refusal("http://localhost/x") is None)

    # L) the token is nowhere
    everywhere = log.getvalue()
    for d in (C.REQUESTS, C.OUTBOX, good_outbox, tmp):
        for p in d.rglob("*"):
            if p.is_file() and p != tokf:
                everywhere += p.read_text(encoding="utf-8", errors="replace")
    check("L: the token appears in no log line, call, notice or state file",
          TOKEN not in everywhere and "7f3a9c7f3a9c" not in everywhere)
    check("L: CONTROL — the log was really collected", "contact watch" in log.getvalue())

    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nCONTACT-WATCH {'GREEN' if not fail else 'RED'}: {ok} OK, {fail} FAIL")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
