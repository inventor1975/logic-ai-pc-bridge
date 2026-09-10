#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""QUEUE WATCH — one shout per new entry in the inbox, and none of them twice.

Written 2026-09-02 to replace a pattern buried inside the monitor command. The
old one recognised only names shaped NUMBER-CHAT and silently lost reaction-*,
needsfile-*, emoji-notice-* and pending-eyes-*. It did complain that its
"pattern is out of date" — but a complaint is not a recognition: with a single
failed file delivery waiting in the queue it would have said "recognised 0" and
never named WHAT was waiting.

    A WATCH COMPLAINING ABOUT ITSELF DOES NOT REPLACE WHAT IT FAILED TO SEE.

The parsing lives here rather than in the monitor command so the pattern can be
edited without a restart.
"""
import json, re, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as C

T = C.T
PAUSE = 20.0

# ZONE. Two sessions may watch one bridge: one for the operator's private chat,
# one for every other room. A request's file is named <message>-<chat>, so a
# zone is expressed as a filter and the bridge itself needed no change.
#
#   --only 500600700     take ONLY this chat
#   --except 500600700   take everything EXCEPT it
#
# THE MEMORY IS PER ZONE, and that is not a detail. One "already seen" file
# shared by two processes would let the room watch mark a private request as
# shown — and the private session would never be woken at all. A silent failure
# that looks from outside like "it says nothing".
def _zone(argv):
    only = other = None
    for flag in ("--only", "--except"):
        if flag in argv:
            value = argv[argv.index(flag) + 1]
            if flag == "--only": only = value
            else: other = value
    return only, other

ONLY, EXCEPT = _zone(sys.argv)
_tag = f"only-{ONLY}" if ONLY else (f"except-{EXCEPT}" if EXCEPT else "all")
SEEN = HERE / f".queue-watch-seen-{_tag}.json"


def in_zone(chat) -> bool:
    """Is this request mine?

    THE CHAT COMES FROM THE FIELD, NOT FROM THE NAME. Parsing the name would
    already have failed once: an ordinary request is <message>-<chat>, but
    reaction-<chat>-<message> holds the chat IN THE MIDDLE, and
    pending-eyes-<time>, emoji-notice-<time> and needsfile-<name> do not hold it
    at all. The tail of a reaction's name would give the message id instead of
    the chat — and the request would go to the wrong session in silence. That is
    exactly the kind of miss this watch exists for: a list of kinds goes stale, a
    field does not.

    AN UNKNOWN CHAT GOES TO THE PRIVATE SESSION, not the room one. Service
    notices (open eyes, a rejected mark, a self-check) carry chat_id = None and
    are addressed to whoever answers. A refusal must fall towards the one who
    is on the hook.
    """
    if chat is None:
        return EXCEPT is None          # the private watch takes it; the room one does not
    chat = str(chat)
    if ONLY is not None: return chat == ONLY
    if EXCEPT is not None: return chat != EXCEPT
    return True


def request_chat(name: str):
    """A request's chat_id, from its file. None when there is no file or no field."""
    for folder in ("requests", "served"):
        f = HERE / folder / f"{name}.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8")).get("chat_id")
            except (ValueError, OSError):
                return None
    return None


def eyes_in_my_zone(text: str):
    """For the "OPEN EYES" notice: is at least one of the listed eyes mine?

    The notice carries chat_id = None and by the general rule falls to the
    private session — while listing the eyes of EVERY room. Measured 2026-09-07:
    while someone else's eye hung open in a room, the notice woke the private
    session every five minutes. That is the kind of noise that eventually gets
    switched off wholesale, taking the useful part with it.

    We parse the LIST, not the name: for each listed eye we take the chat_id
    from its own file. Names are not parsed — that lesson is already paid for
    (reaction-<chat>-<message> holds the chat in the middle).

    True when at least one eye is mine; False when all are someone else's; None
    when not one line could be resolved — then the general rule decides and the
    notice goes to the private session. The refusal falls towards the answerer.
    """
    resolved = mine = 0
    for line in text.split("\n"):
        fields = line.split()
        if not fields or not line.startswith(" "):
            continue
        chat = request_chat(fields[0])
        if chat is None:
            continue
        resolved += 1
        if in_zone(chat): mine += 1
    if resolved == 0:
        return None
    return mine > 0


# The entry's name is any non-blank run after "] ". The KIND is deliberately not
# enumerated: a list of kinds is exactly what went stale last time.
PATTERN = re.compile(r"^\s*\S+\s+\S+\s+\[([^\]]+)\]\s+(\S+)")


def queue():
    try:
        out = subprocess.run([sys.executable, "pending.py"], cwd=HERE,
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError) as e:
        return None, [], T("watch.poll_failed", error=str(e))
    lines = out.splitlines()
    entries, headers = [], 0
    for i, s in enumerate(lines):
        m = PATTERN.match(s)
        if not m: continue
        headers += 1
        name = m.group(2)
        # THE WHOLE TEXT FROM THE REQUEST, not the queue's truncated preview:
        # the old watch did it this way and was right — a preview does not say
        # what you are being called about. The preview stays as the fallback for
        # when the request file is missing.
        text, raw, chat = "", "", None
        rf = HERE / "requests" / f"{name}.json"
        if rf.exists():
            try:
                d = json.loads(rf.read_text(encoding="utf-8"))
                raw = d.get("text") or ""
                # THE FLATTENED text is fine to shout, but NOT to parse: the
                # lines of an eyes list are recognised by their indent, and
                # flattening removes it. Caught 2026-09-07 by the first run —
                # the patch had been dead.
                text = raw.replace("\n", " ")
                chat = d.get("chat_id")
            except (ValueError, OSError):
                pass
        if not text:
            text = lines[i+1].strip() if i+1 < len(lines) else ""
        if name.startswith("pending-eyes-"):
            if eyes_in_my_zone(raw) is False:   # every listed eye belongs elsewhere
                continue
        elif not in_zone(chat):
            continue
        entries.append({"kind": m.group(1), "name": name, "text": text[:200]})
    # A WATCH OVER THE WATCH: compare what was recognised with what was claimed.
    claimed = re.search(r"^(\d+)\s+awaiting", out, re.M)
    mismatch = None
    if (claimed and ONLY is None and EXCEPT is None
            and int(claimed.group(1)) != len(entries)):
        mismatch = T("watch.pattern_blind", claimed=claimed.group(1),
                     recognised=len(entries), file=Path(__file__).name)
    return headers, entries, mismatch


def main():
    seen = set(json.loads(SEEN.read_text())) if SEEN.exists() else set()
    while True:
        _, entries, trouble = queue()
        if trouble: print(trouble, flush=True)
        for e in entries:
            if e["name"] in seen: continue
            seen.add(e["name"])
            print(T("watch.you_are_called", name=e["name"], text=e["text"]), flush=True)
        alive = {e["name"] for e in entries}
        # forget what has gone, or the memory grows for ever and a repeated
        # name would never be shouted again
        seen &= alive
        SEEN.write_text(json.dumps(sorted(seen), ensure_ascii=False))
        time.sleep(PAUSE)


if __name__ == "__main__":
    if "--once" in sys.argv:
        h, e, t = queue()
        print(f"headers {h}, entries {len(e)}, mismatch: {t or 'none'}")
        for x in e: print("   ", x["kind"], x["name"], "|", x["text"][:60])
    else:
        main()
