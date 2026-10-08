#!/usr/bin/env python3
"""Write into the BRIDGE's outbox with the checks applied — instead of
remembering the rules.

Written 2026-08-26 after the NINTH case in one day of "knew the rule and did not
apply it": I had noted for myself that done_emoji may only come from
config.VALID_REACTIONS, and an hour later sent 🧊 again. The bridge rejected it,
the message arrived, the mark did not, and two needless items landed in the inbox.

The cure is the same one we applied that day to the watchdog vocabulary, to
mixed models and to the save check at the gate: A RULE THAT LIVES IN MEMORY IS
NOT A RULE. The check has to stand where it cannot be walked around.

  ./say.py <file-with-text> [--chat N] [--emoji 👌] [--answers id1,id2]
           [--attach PATH] [--wait SECONDS | --no-wait]

  --attach PATH sends that file, the text becoming its caption (at most 1024
  characters, Telegram's ceiling for captions).
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as C   # noqa: E402

MAX = 4096           # Telegram's ceiling; longer and the bridge cuts or drops it
CAPTION_MAX = 1024   # Telegram's ceiling for a file's caption; the bridge cuts at it
WAIT = 45.0          # seconds to wait for the bridge; it looks at the outbox every second
                     # MEASURED 2026-09-10: one reaction call alone took 20.3 s, so the
                     # first choice of 20 s would have timed out on a message that went out


# "QUEUED" IS NOT "SENT". Until 2026-09-10 say.py stopped at "queued", and after
# every message the operator had to go and look for the file in sent/ by hand —
# or did not look. Queued, sent and read are three different facts. The first is
# known here at once; the second shows up a second later as sent/<name> or
# outbox/rejected/<name>; the third nobody can know from here — Telegram
# accepting a message is not someone reading it. So say.py waits for the second
# fact and says which it was. A timeout is not a verdict: the file stays queued
# and goes out whenever the bridge takes it.
#
# One trap: sent/ may already hold a file of the same name from an earlier
# message. Only a file written after this one was queued counts.
def outcome(name: str, t0: float):
    """What the bridge has done with outbox/<name>: ('sent', None),
    ('rejected', reason), ('retrying', tries), ('waiting', None) or ('gone', None)."""
    def fresh(p: pathlib.Path) -> bool:
        try:
            return p.stat().st_mtime >= t0 - 1
        except OSError:
            return False
    if fresh(C.SENT / name):
        return "sent", None
    if fresh(getattr(C, "NEEDS_CONSENT", C.ROOT / "needs_consent") / name):
        return "needs_consent", None
    rej = C.OUTBOX / "rejected" / name
    if fresh(rej):
        try:
            why = json.loads(rej.read_text(encoding="utf-8")).get("_rejected")
        except Exception:
            why = None
        return "rejected", why or "no reason recorded"
    q = C.OUTBOX / name
    if not q.exists():
        return "gone", None
    try:
        tries = int(json.loads(q.read_text(encoding="utf-8")).get("_tries", 0))
    except Exception:    # caught half-written by the bridge; look again next time
        tries = 0
    return ("retrying", tries) if tries else ("waiting", None)


def wait_for(name: str, t0: float, limit: float) -> int:
    deadline = time.time() + limit
    gone_before = False
    while True:
        state, info = outcome(name, t0)
        if state == "sent":
            print(f"SENT: Telegram accepted it (sent/{name}). Accepted is not read.")
            return 0
        if state == "rejected":
            print(f"REJECTED by the bridge: {info}\n  The message is in outbox/rejected/{name}.")
            return 1
        if state == "needs_consent":
            print(f"NOT SENT: no standing rule covers this file; the bridge parked it in "
                  f"needs_consent/{name} and opened a request for the principal's decision.")
            return 1
        # The bridge writes sent/ first and removes the queued file second, so
        # one look can fall between the two. "Gone" counts only when seen twice.
        if state == "gone" and gone_before:
            print(f"LEFT THE QUEUE, but it is neither in sent/ nor in outbox/rejected/. "
                  f"See bridge.out.")
            return 1
        gone_before = state == "gone"
        if time.time() >= deadline:
            break
        time.sleep(0.25)
    if state == "retrying":
        print(f"NOT SENT YET: Telegram refused it {info} time(s); the bridge keeps "
              f"trying and moves it to outbox/rejected/ when it gives up. See bridge.out.")
    else:
        # SAY WHAT IS SEEN, NOT WHAT IT PROBABLY MEANS. A file still in the queue
        # is either not taken yet or taken and being sent right now — the bridge
        # leaves it in place until Telegram answers, and on 2026-09-10 Telegram
        # took 20.3 s over one reaction. Telling those apart needs a "claimed"
        # mark from the bridge itself; until it has one, "the bridge is not
        # running" would be a guess.
        print(f"STILL QUEUED after {limit:g} s in {C.ROOT.name}/outbox: not taken yet, "
              f"or Telegram is slow — see bridge.out. If this tree's bridge is not "
              f"running, it will go out when it starts.")
    return 2


_GUARD_SAID = False


def _guard_unreadable(what, exc):
    """Say, once, that the zone guard could not be read.

    FAIL-OPEN IS A DECISION AND IT STAYS: a guard that refuses when it cannot
    read itself stops all work, and the comment below it was written on
    purpose. The defect is not that it lets the message through — it is that
    it lets it through IN SILENCE. An operator sees an ordinary send and has
    no way to tell that the zone was never consulted.

    Measured 2026-09-23 on a copy, with `pending` made to raise on import:
    `_zone()` returns None, `_chat_in_zone()` returns True, the author stamp
    disappears, and because the call site reads `if mine is not None`, the
    check is not merely permissive — it does not run at all. Three silent
    defaults and one skipped branch, none of them visible.

    Printed once per process: three helpers failing would otherwise shout
    three times about one cause."""
    global _GUARD_SAID
    if not _GUARD_SAID:
        _GUARD_SAID = True
        print(f"\n  THE ZONE GUARD COULD NOT BE READ ({type(exc).__name__}:"
              f" {exc}).\n"
              f"  This send goes out with NO zone check and NO operator"
              f" stamp.\n"
              f"  Not a refusal — a warning: the guard is ABSENT, not"
              f" permitting.", file=sys.stderr)
    return None


def _zone():
    """This session's declared zone, or None. Shares pending.py's single answer
    rather than adding a second place to keep in step."""
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import pending
        return pending.zone()
    except Exception as e:
        return _guard_unreadable("zone", e)


def _chat_in_zone(chat, mine):
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import pending
        return pending.in_zone(chat, mine)
    except Exception as e:
        _guard_unreadable("in_zone", e)
        return True          # unreadable guard never refuses — but says so


def _operator_from_zone():
    """The operator this session declared, or None. Shares pending.py's single
    answer to "who am I" rather than adding a second place to keep in step."""
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import pending
        return pending.operator()
    except Exception:
        return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--by", default="",
                    help="operator this message is sent as; taken from the "
                         "session's declared zone when omitted")
    ap.add_argument("file")
    ap.add_argument("--chat", type=int, default=None)
    ap.add_argument("--emoji", default="👌")
    ap.add_argument("--answers", default="")
    ap.add_argument("--attach", default=None, metavar="PATH",
                    help="send this file; the text becomes its caption")
    ap.add_argument("--name", default=None)
    ap.add_argument("--wait", type=float, default=WAIT, metavar="SECONDS")
    ap.add_argument("--no-wait", action="store_true",
                    help="only queue it, as before; do not wait for the bridge")
    a = ap.parse_args(argv)

    text = pathlib.Path(a.file).read_text(encoding="utf-8").strip()
    if not text:
        print("REFUSED: the text is empty"); return 1
    if len(text) > MAX:
        print(f"REFUSED: {len(text)} characters, Telegram's ceiling is {MAX}. "
              f"Split it into two messages."); return 1

    # A FILE GOES THROUGH HERE TOO (2026-09-27). Until now a file could be sent
    # only by writing its JSON into the outbox by hand — which skipped every
    # check below, the zone gate and the author stamp included. Measured the
    # same day: a translated report went out that way, and the first attempt
    # was parked because no rule covered the folder it lay in.
    attach = None
    if a.attach:
        attach = pathlib.Path(a.attach).expanduser().resolve()
        if not attach.is_file():
            print(f"REFUSED: no such file to attach: {attach}"); return 1
        if len(text) > CAPTION_MAX:
            print(f"REFUSED: a caption is {len(text)} characters; Telegram's ceiling "
                  f"for captions is {CAPTION_MAX}. Shorten it or send the text first."); return 1

    valid = getattr(C, "VALID_REACTIONS", None)
    if valid and a.emoji not in valid:
        print(f"REFUSED: {a.emoji!r} is NOT among the allowed reactions.\n"
              f"  The bridge will reject it, the mark will not appear, and the "
              f"inbox gets one more needless item.\n"
              f"  Take one from: {''.join(sorted(valid))[:120]}…")
        return 1

    chat = a.chat if a.chat is not None else getattr(C, "PRINCIPAL", None) \
        or C.policy(0).get("principal")
    # DO NOT PUT INTO THE OUTBOX WHAT THE BRIDGE WILL CERTAINLY REJECT.
    # `C.policy(0)` knows no principal, so without --chat this produced None; the
    # file was written, say.py printed "queued", and the bridge refused with a
    # line in bridge.out that nobody read. 2026-09-10: THREE messages in a row
    # failed to go out that way, in silence. The refusal belongs here, where it
    # cannot be missed.
    if chat is None:
        known = ", ".join(sorted(C.CHATS)) if getattr(C, "CHATS", None) else "see chats.json"
        print("REFUSED: no chat given and none can be inferred — the bridge would "
              "reject such a file.\n"
              f"  Name it explicitly: --chat <id>.  Known chats: {known}")
        return 1
    if attach is not None:
        # DO NOT QUEUE WHAT THE BRIDGE WILL PARK. Its own rule_for decides; it is
        # imported, not copied — a rule written twice drifts.
        try:
            from tg_bridge import rule_for, grant_for
            covered = rule_for(chat, attach) or grant_for(chat, attach)
        except Exception as exc:
            covered = True
            print(f"  (the file rule could not be read here: {exc!r} — "
                  f"the bridge will decide)", file=sys.stderr)
        if not covered:
            print(f"REFUSED: no standing rule covers sending {attach} to chat {chat}.\n"
                  f"  The bridge would park it and ask the principal. Put the file where\n"
                  f"  a rule covers it (see rules.json), or propose one:\n"
                  f"    ./propose.py --batch '{attach}' --to {chat} --why '<why>'")
            return 1
    rec = {"chat_id": chat, "text": text, "done_emoji": a.emoji}
    if attach is not None:
        rec["file"] = str(attach)
    ans = [x.strip() for x in a.answers.split(",") if x.strip()]
    # AN ANSWER MUST NAME A REQUEST THAT EXISTS. The bridge closes an eye by
    # opening requests/<id>.json; an id that names no file closes nothing and
    # nothing says so. Measured 2026-10-03: --answers 8726 (the message id
    # alone, the request is 8726-<chat>) went out, this script printed "closes
    # 1 request(s)", and the eye stayed until a watcher raised it. The short
    # form is what a person naturally types, so it is completed from --chat;
    # anything still unknown is refused HERE, before Telegram is touched.
    fixed, unknown = [], []
    for rid in ans:
        if (C.REQUESTS / f"{rid}.json").exists():
            fixed.append(rid)
        elif rid.isdigit() and (C.REQUESTS / f"{rid}-{chat}.json").exists():
            fixed.append(f"{rid}-{chat}")
        elif (C.SERVED / f"{rid}.json").exists() or \
                (rid.isdigit() and (C.SERVED / f"{rid}-{chat}.json").exists()):
            fixed.append(rid if (C.SERVED / f"{rid}.json").exists() else f"{rid}-{chat}")
            print(f"  note: {fixed[-1]} was already answered (it is in served/)")
        else:
            unknown.append(rid)
    if unknown:
        print(f"REFUSED: --answers names no request: {', '.join(unknown)}.\n"
              f"  A request id is <message id>-<chat id>, e.g. 8726-{chat}; the open\n"
              f"  ones are listed by ./pending.py. Nothing was sent.")
        return 1
    ans = fixed
    if ans:
        rec["answers"] = ans
    # WHO PROPOSED THIS. The journal records what was sent and, until now, never
    # WHO SENT IT — two operators share one bridge, so a shared log with no
    # author cannot answer the first question anyone asks of it. Measured
    # 2026-09-21: an audit of 129 outbound actions could establish the author of
    # four, and reporting the rest as one operator's would have charged the
    # other with work that was rightfully theirs.
    #
    # THE STAMP BELONGS HERE, NOT IN A RULE. Asking the operator to remember a
    # field is a rule that holds only while the reader is careful; this builds
    # it into the one place every message of theirs passes through.
    #
    # AND IT IS NEVER GUESSED. No declared operator -> no key -> the record says
    # AUTHOR NOT ESTABLISHED, which is a finding. A guess would be an accusation.
    who = a.by or _operator_from_zone()
    if who:
        rec["by"] = who

    # THE GATE: AUTHORIZATION PRECEDES EXECUTION.
    #
    # Until now every check here asked whether the message was WELL FORMED —
    # short enough, a reaction the bridge can set, a chat that exists. None
    # asked whether THIS OPERATOR MAY WRITE TO THIS CHAT. Measured 2026-09-21:
    # one operator answered three chats belonging to the other and stated that
    # side's work as not started while it was being delivered; one of those
    # statements was false at the instant of sending, by twenty-two seconds.
    # The rule existed and was written down. It held for eight hours and then
    # did not.
    #
    # IT CANNOT CLOSE THE CHANNEL TO THE PRINCIPAL. The zone of the operator
    # who holds the private chat CONTAINS that chat, so a message to the
    # principal is always inside it. A gate that could silence the one channel
    # back to the person would be a worse failure than the one it prevents.
    #
    # NO DECLARED ZONE -> NO GATE. An installation that never declared zones
    # behaves exactly as before; the check appears only for an operator who
    # asked for it. Refusing on an undeclared zone would mean guessing an
    # authority, and a guessed authority is the thing this whole line exists
    # to refuse.
    mine = _zone()
    if mine is None:
        # THE BRANCH THAT DOES NOT RUN. With no zone the condition below is
        # skipped entirely, so a session with an unreadable guard may write
        # into the other operator's rooms and nothing marks it. Said out loud
        # because a check that did not happen looks exactly like one that
        # passed.
        print("  no zone declared or readable — THE ZONE CHECK DID NOT RUN",
              file=sys.stderr)
    if mine is not None and not _chat_in_zone(chat, mine):
        kind, chats = mine
        print(f"REFUSED BY ZONE: chat {chat} is outside this operator's zone "
              f"({kind} {' '.join(sorted(chats))}).\n"
              f"  Nothing was queued. The message would have gone to a chat\n"
              f"  another operator answers, and the journal would have recorded\n"
              f"  it without saying who wrote it.\n"
              f"  If this chat IS yours, declare it: "
              f"./pending.py --zone only|except <chat id> [as <operator>]")
        return 1
    name = a.name or pathlib.Path(a.file).stem
    out = C.OUTBOX / f"{name}.json"
    t0 = time.time()
    out.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    # NAME THE TREE. With a development tree and an installation side by side,
    # "queued" is true for whichever outbox this copy of say.py belongs to — and
    # on 2026-09-10 a report was queued into the dev tree, whose bridge was shut
    # down, while the operator waited. It printed "queued" honestly and went
    # nowhere. The tree's name costs nothing to print and makes that visible.
    print(f"queued into {C.ROOT.name}: {out.name} · {len(text)} chars · {a.emoji} · "
          f"closes {len(ans)} request(s).")
    if a.no_wait:
        return 0
    return wait_for(out.name, t0, a.wait)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
