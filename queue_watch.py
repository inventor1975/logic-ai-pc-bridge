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
NO_MAIL = "--no-mail" in sys.argv   # an operator told not to watch the
# correspondent's folder at all (mailwatch-*), by the principal's word.

# --mail IS THE OTHER HALF OF --no-mail. The folder's requests carry no chat, so
# by the general rule they fall to the private session; an installation whose
# folder belongs to the ROOM operator had no way to say so, and that operator
# ran a second watcher of its own beside the bridge's. With --mail this zone
# takes the correspondent's folder whatever its chat — and nobody else needs a
# second process for it. Both flags at once is a contradiction, refused aloud.
MAIL = "--mail" in sys.argv

# --until-called: EXIT AT THE FIRST CALL. A host that runs this under a monitor
# with a lifetime (thirty minutes, then silence) turns every expiry into a
# wake-up that carries nothing. Run instead as a plain background command that
# ends when it has something to say: the session is woken by the END of the
# process, exactly once per call, and starts it again when it is done. A problem
# is a call too — in this mode a line that does not end the process wakes no one.
UNTIL_CALLED = "--until-called" in sys.argv

# --doorbell <file>: a file the bridge touches when a request appears (see the
# on_request hook). Between polls the watch waits for the bell instead of
# sleeping blind; the poll every PAUSE seconds stays as the fallback, so a bell
# that never rings costs latency, never a request.
DOORBELL = (Path(sys.argv[sys.argv.index("--doorbell") + 1]).expanduser()
            if "--doorbell" in sys.argv else None)
# --watch-peer: TWO OPERATORS WATCH EACH OTHER. Measured 2026-09-30: a room
# request waited seven hours. The bridge did see that nobody took it, and said
# so in the chat after twenty minutes - but that line woke no one, because the
# room session had no watch running at night while the private one did. With
# this flag a watch also calls about a request OUTSIDE its zone once the bridge
# has marked it "nudged" (nobody picked it up) and it is still waiting. The
# signal is the bridge's own mark, so no second clock is kept here. The limit,
# stated: if NEITHER session has a watch running, nobody is woken.
WATCH_PEER = "--watch-peer" in sys.argv
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


def eyes_all_mail(text: str) -> bool:
    """True when EVERY listed eye is a mailwatch-* (the correspondent's folder).

    Added 2026-09-17: --no-mail filtered the mailwatch entries themselves, but
    the OPEN-EYES notice that merely LISTS them still woke this session. A flag
    that stops at half the path is a flag that is not in force.
    """
    names = [l.split()[0] for l in text.split("\n") if l.startswith(" ") and l.split()]
    return bool(names) and all(n.startswith("mailwatch-") for n in names)


def eyes_any_mail(text: str) -> bool:
    """True when at least one listed eye is a mailwatch-* — for the --mail zone."""
    names = [l.split()[0] for l in text.split("\n") if l.startswith(" ") and l.split()]
    return any(n.startswith("mailwatch-") for n in names)


# The entry's name is any non-blank run after "] ". The KIND is deliberately not
# enumerated: a list of kinds is exactly what went stale last time.
PATTERN = re.compile(r"^\s*\S+\s+\S+\s+\[([^\]]+)\]\s+(\S+)")


def peer_missed(name, rf, text, entries, kind):
    """--watch-peer: a request outside this zone that the bridge has already
    called unpicked ("nudged"), or a mail call older than the nudge threshold,
    becomes a call here, under its own name with a
    "peer:" prefix - the other zone's memory of what it has seen is not touched."""
    if not WATCH_PEER or not rf.exists():
        return
    try:
        nudged = json.loads(rf.read_text(encoding="utf-8")).get("nudged")
    except (ValueError, OSError):
        return
    if nudged:
        entries.append({"kind": kind, "name": f"peer:{name}",
                        "text": T("watch.peer_missed", name=name, nudged=nudged, text=text[:300])})
        return
    # THE FOLDER'S CALLS ARE NEVER NUDGED: they carry no chat to say it in, and
    # the bridge skips them (nudge_unanswered). Measured 2026-09-30/10-01: twelve
    # mail calls waited from 18:26 to 08:14 with nobody taking them, and a watch
    # keyed only to "nudged" would have stayed silent through all of it. So for
    # them the age is read the way the bridge reads it for a nudge - the file's
    # time against the same NUDGE_AFTER_MIN - and no new setting is invented.
    if name.startswith("mailwatch-"):
        mins = int((time.time() - rf.stat().st_mtime) // 60)
        if mins >= C.NUDGE_AFTER_MIN:
            entries.append({"kind": kind, "name": f"peer:{name}",
                            "text": T("watch.peer_mail_waiting", name=name, mins=mins, text=text[:300])})


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
        if name.startswith("pending-eyes-") and MAIL and eyes_any_mail(raw):
            pass   # it lists an eye of the correspondent's folder: this zone's
        elif name.startswith("pending-eyes-"):
            mine_eyes = eyes_in_my_zone(raw)
            # None = not one line could be resolved -> the GENERAL rule
            # decides, exactly as the docstring promises. Only False used to be
            # filtered, so on None the notice woke BOTH operators. Found by the
            # second operator and measured, not argued.
            if mine_eyes is False or (mine_eyes is None and not in_zone(None)):
                continue
            if NO_MAIL and eyes_all_mail(raw):
                continue   # the notice speaks only of the correspondent's
                # folder, which is outside this operator's zone
        elif MAIL and name.startswith("mailwatch-"):
            pass   # the correspondent's folder is this zone, whatever its chat
        elif not in_zone(chat):
            peer_missed(name, rf, text, entries, m.group(1))
            continue
        if NO_MAIL and name.startswith("mailwatch-"):
            peer_missed(name, rf, text, entries, m.group(1))
            continue   # the correspondent's folder is outside this zone
        # THE TRUNCATION WAS SILENT, and that is worse than its length. The
        # wake-up line stopped at 200 characters with no sign of it, so a cut
        # message looked EXACTLY like a whole one. The assistant then answered
        # four times by reconstructing the missing end from sense, while the
        # full text sat in the store one command away. All four guesses were
        # right, and that was luck: the next tail could have inverted the ask.
        # The cap is now 2000 — beyond almost every real message — AND THE
        # TAIL IS NAMED whenever it is cut.
        cap = 2000
        shown = text[:cap]
        if len(text) > cap:
            shown += (f" …[TRUNCATED, {len(text) - cap} more characters; "
                      f"the full text is in requests/ or served/ under {name}]")
        entries.append({"kind": m.group(1), "name": name, "text": shown})
    # A WATCH OVER THE WATCH: compare what was recognised with what was claimed.
    claimed = re.search(r"^(\d+)\s+awaiting", out, re.M)
    mismatch = None
    if (claimed and ONLY is None and EXCEPT is None
            and int(claimed.group(1)) != len(entries)):
        mismatch = T("watch.pattern_blind", claimed=claimed.group(1),
                     recognised=len(entries), file=Path(__file__).name)
    return headers, entries, mismatch


def _bell():
    """The doorbell's mark, or None when there is no bell or it is not there."""
    try:
        return DOORBELL.stat().st_mtime_ns if DOORBELL else None
    except OSError:
        return None


def wait_for_bell(mark, seconds: float) -> None:
    """Sleep up to `seconds`, returning early once the bell differs from `mark`.

    THE MARK IS TAKEN BEFORE THE POLL, not after it. A bell that rings while the
    poll is running would otherwise be counted as already heard, and that
    request would wait the full pause for nothing."""
    if DOORBELL is None:
        time.sleep(seconds)
        return
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _bell() != mark:
            return
        time.sleep(0.5)


def main():
    if MAIL and NO_MAIL:
        print("queue_watch: --mail and --no-mail contradict each other; refusing "
              "to guess which one was meant", flush=True)
        return 2
    seen = set(json.loads(SEEN.read_text())) if SEEN.exists() else set()
    while True:
        mark = _bell()
        _, entries, trouble = queue()
        if trouble: print(trouble, flush=True)
        called = False
        for e in entries:
            if e["name"] in seen: continue
            seen.add(e["name"])
            print(T("watch.you_are_called", name=e["name"], text=e["text"]), flush=True)
            called = True
        alive = {e["name"] for e in entries}
        # forget what has gone, or the memory grows for ever and a repeated
        # name would never be shouted again
        seen &= alive
        SEEN.write_text(json.dumps(sorted(seen), ensure_ascii=False))
        if UNTIL_CALLED and (called or trouble):
            return 0   # written SEEN first: the next start must not shout it again
        wait_for_bell(mark, PAUSE)


if __name__ == "__main__":
    if "--once" in sys.argv:
        h, e, t = queue()
        print(f"headers {h}, entries {len(e)}, mismatch: {t or 'none'}")
        for x in e: print("   ", x["kind"], x["name"], "|", x["text"][:60])
    else:
        raise SystemExit(main())
