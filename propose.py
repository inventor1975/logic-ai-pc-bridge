#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Hang a proposal on the consent gate.

    ./propose.py "email Sam the signed contract"

The assistant does nothing outward on its own. It hangs ONE LINE, the
principal marks it 👍 or 👎, and only the mark is an order.

WHY THE BRIDGE DOES NOT EXECUTE. The gate records consent; the act is
performed by the assistant. A daemon that executes arbitrary actions on a
reaction is a far larger surface for harm, and there is nothing to gain: the
assistant only acts outward while it is awake anyway. The bridge is
responsible for CONSENT, not for EXECUTION.

ONE LINE, ONE ACTION. Three things to do means three proposals and three
marks. A mark under a list of five items becomes a rubber stamp within a week.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time

from pathlib import Path

import config as C

USAGE = ('usage: ./propose.py --file-rule <dir> --to <chat> [--glob "*.md"] [--why ...] [--until <iso>]\n       ./propose.py "the proposed action, or the exact text to post" '
         '[note to self] [--to <chat_id>]')


def _principal_chat() -> int:
    """Where to hang the proposal: the principal's own chat.

    A proposal is addressed to the person entitled to approve it, not to
    whichever allowed chat comes first. Hanging it in a group would mean
    outsiders see a decision that is not theirs to make.
    """
    for cid in C.all_chats():
        p = C.policy(cid)
        if p["principal"] and cid == p["principal"]:
            return cid
    raise SystemExit("no private chat with the principal in chats.json — run ./setup.py")


def _rule_proposal(argv: list[str], target: int | None) -> int:
    """Предложить СТОЯЧЕЕ ПРАВИЛО на отправку файлов, а не одну отправку.

        ./propose.py --file-rule ~/Dropbox/Outbox --to -100200300 \
                     --glob "*.md" --why "approved documents for the review room"

    Подтверждение переезжает с экземпляра на КЛАСС: куратор помечает один раз,
    и дальше всё из этой папки в эту комнату уходит без вопроса. Всё прочее
    по-прежнему спрашивается поштучно.

    Предложение только ПРЕДЛАГАЕТ. В журнал правило вписывает мост и только по
    метке, вместе с числовым идентификатором пометившего. Ассистент журнал не
    пишет никогда.
    """
    i = argv.index("--file-rule")
    try:
        directory = Path(argv[i + 1]).expanduser()
    except IndexError:
        print(USAGE); return 2
    del argv[i:i + 2]
    glob = "*"
    if "--glob" in argv:
        j = argv.index("--glob"); glob = argv[j + 1]; del argv[j:j + 2]
    until = None
    if "--until" in argv:
        j = argv.index("--until"); until = argv[j + 1]; del argv[j:j + 2]
    why = ""
    if "--why" in argv:
        j = argv.index("--why"); why = argv[j + 1]; del argv[j:j + 2]
    if target is None:
        print("правилу обязательна комната: --to <chat_id>"); return 2
    if not directory.exists():
        print(f"нет такого каталога: {directory}"); return 2

    room = C.policy(target).get("_") or target
    line = (f"РАЗРЕШИТЬ отправку файлов БЕЗ отдельного вопроса:\n"
            f"    откуда:  {directory}\n"
            f"    образец: {glob}\n"
            f"    куда:    {room}\n"
            f"    зачем:   {why or 'не сказано'}\n"
            f"    до:      {until or 'без срока'}\n"
            f"Это правило на КЛАСС отправок, а не на один файл. "
            f"Всё, что в него не попадает, я по-прежнему спрошу.")
    C.OUTBOX.mkdir(exist_ok=True)
    name = f"propose-rule-{int(time.time())}.json"
    tag = _tag(name + str(target))
    C.OUTBOX.joinpath(name).write_text(json.dumps({
        "chat_id": _principal_chat(),
        "text": (f"[{tag}] ПРЕДЛАГАЮ ПРАВИЛО:\n\n{line}\n\n"
                 f"👍 — разрешить. 👎 — нет. Без метки не разрешено ничего; "
                 f"предложение само истечёт через {C.PROPOSAL_TTL_HOURS} ч."),
        "proposal": {"action": f"стоячее правило: {directory} -> {room}",
                     "one_line": line, "target_chat": target,
                     "rule": {"chat_id": target, "dir": str(directory),
                              "glob": glob, "expires_at": until,
                              "why": why}},
    }, ensure_ascii=False), encoding="utf-8")
    print(f"повешено правило {tag}: {name}")
    return 0


def _tag(seed: str) -> str:
    """Короткая метка предложения, ВИДИМАЯ человеку.

    Номер сообщения Телеграм присваивает сам и НЕ ПОКАЗЫВАЕТ пользователю: он
    есть в API и в моём логе, и его нет на экране. Ссылаться на него в разговоре
    значит называть то, чего собеседник не видит, — ровно то, за что куратор и
    поймал 2026-08-22. Поэтому метка кладётся В ТЕКСТ предложения: то, что я
    называю, и то, что он видит, — одна и та же строка.
    """
    return "П-" + hashlib.sha256(seed.encode()).hexdigest()[:4].upper()


def _batch_proposal(argv: list[str], target: int | None) -> int:
    """Повесить ПАЧКУ: одна метка — одна посылка в одну комнату.

        ./propose.py --batch a.md b.pdf c.png --to -5101395964 [--why ...]

    Три условия, и каждое закрывает свою дыру:

    ОДИН получатель. Смешивать комнаты в одной пачке запрещено — именно там
    ошибка и прячется: четыре файла туда, один не туда, и заметно это будет
    у получателя, а не у нас.

    КАЖДЫЙ файл назван: имя, размер, отпечаток — прямо в тексте предложения.
    Метка покрывает УВИДЕННОЕ, а не «те файлы, что он там собрал».

    ПОТОЛОК в C.BATCH_MAX. Список, который нельзя прочесть глазами, есть штамп,
    как его ни назови. Ответ на «много файлов» — не пачка побольше, а правило
    на папку.
    """
    i = argv.index("--batch")
    del argv[i]
    why = ""
    if "--why" in argv:
        j = argv.index("--why"); why = argv[j + 1]; del argv[j:j + 2]
    paths = [Path(a).expanduser() for a in argv if not a.startswith("--")]
    if target is None:
        print("пачке обязательна комната: --to <chat_id>"); return 2
    if not paths:
        print("пачка пуста"); return 2
    if len(paths) > C.BATCH_MAX:
        print(f"в пачке {len(paths)} файлов, потолок {C.BATCH_MAX}. "
              f"Список, который не прочесть глазами, — это штамп. "
              f"На поток заводите правило: --file-rule <папка>")
        return 2

    files, lines = [], []
    for p_ in paths:
        if not p_.exists():
            print(f"нет такого файла: {p_}"); return 2
        raw = p_.read_bytes()
        d = hashlib.sha256(raw).hexdigest()
        files.append({"name": p_.name, "path": str(p_.resolve()),
                      "bytes": len(raw), "sha256": d})
        lines.append(f"    {p_.name}  —  {len(raw)} байт  —  {d[:16]}…")

    room = C.policy(target).get("_") or target
    line = (f"ОТПРАВИТЬ ПАЧКОЙ в: {room}\n"
            f"    зачем: {why or 'не сказано'}\n\n" + "\n".join(lines) +
            f"\n\nОдобрено будет ИМЕННО ЭТО: отпечатки записаны, подмена "
            f"файла после метки не пройдёт. Разрешение РАЗОВОЕ.")
    C.OUTBOX.mkdir(exist_ok=True)
    name = f"propose-batch-{int(time.time())}.json"
    tag = _tag(name + str(target))
    C.OUTBOX.joinpath(name).write_text(json.dumps({
        "chat_id": _principal_chat(),
        "text": (f"[{tag}] ПРЕДЛАГАЮ ПАЧКУ ({len(files)}):\n\n{line}\n\n"
                 f"👍 — отправить. 👎 — нет. Без метки не уйдёт ничего."),
        "proposal": {"action": f"пачка {len(files)} файлов -> {room}",
                     "one_line": line, "target_chat": target,
                     "batch": {"chat_id": target, "files": files, "why": why}},
    }, ensure_ascii=False), encoding="utf-8")
    print(f"повешена пачка {tag}: {name} — {len(files)} файлов")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    target = None
    if "--to" in argv:
        i = argv.index("--to")
        try:
            target = int(argv[i + 1])
        except (IndexError, ValueError):
            print(USAGE)
            return 2
        del argv[i:i + 2]
    if "--batch" in argv:
        return _batch_proposal(argv, target)
    if "--file-rule" in argv:
        return _rule_proposal(argv, target)
    if not argv or not argv[0].strip():
        print(USAGE)
        return 2
    line = argv[0].strip()
    note = argv[1].strip() if len(argv) > 1 else line
    # WHERE IT GOES BELONGS IN THE RECORD, not in the assistant's memory.
    # A proposal approved now may be acted on after a wake-up, and "which chat
    # was that for" is exactly the kind of thing remembered wrong. Posting a
    # private remark into a group cannot be taken back.
    where = ""
    if target is not None:
        where = f" — to post in: {C.policy(target).get('_') or target}"
    C.OUTBOX.mkdir(exist_ok=True)
    name = f"propose-{int(time.time())}.json"
    C.OUTBOX.joinpath(name).write_text(json.dumps({
        "chat_id": _principal_chat(),
        "text": (f"[{_tag(name + str(target))}] I PROPOSE{where}:\n\n{line}\n\n"
                 f"👍 — do it. 👎 — do not. Without a mark I do nothing; "
                 f"it clears itself after {C.PROPOSAL_TTL_HOURS}h."),
        "proposal": {"action": note, "one_line": line, "target_chat": target},
    }, ensure_ascii=False), encoding="utf-8")
    print(f"hung: {name} — {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
