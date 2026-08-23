#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Показать журнал правил: что разрешено, кем одобрено, и что по нему ушло.

    ./rules.py

РАЗРЕШЕНИЕ, КОТОРОГО НЕ ВИДНО, через месяц перестаёт быть решением и становится
привычкой. Правило снимает вопрос ЗАРАНЕЕ — значит единственная оставшаяся
проверка идёт ПОСЛЕ, и она обязана быть под рукой, а не в логе на 40 тысяч строк.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import config as C


def main() -> int:
    rules = C.file_rules()
    if not rules:
        print("журнал пуст — не разрешено НИЧЕГО, спрашивается каждый файл")
        return 0

    log = C.ROOT / "sent_by_rule.log"
    used: Counter = Counter()
    last: dict[str, str] = {}
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                used[parts[1]] += 1
                last[parts[1]] = parts[0]

    for r in rules:
        rid = r.get("id", "?")
        rooms = r.get("chats") or ([r["chat_id"]] if r.get("chat_id") else [])
        names = []
        for c in rooms:
            pol = C.policy(c)
            names.append(f"{pol.get('_') or c} [{c}]")
        print(f"\n{rid}  «{r.get('project') or '—'}»")
        for d in (r.get("dirs") or []):
            print(f"    папка    {d.get('dir')}  ({d.get('glob') or '*'})")
        for pth in (r.get("paths") or []):
            print(f"    файл     {pth}")
        if r.get("dir"):                       # форма v1.4
            print(f"    папка    {r['dir']}  ({r.get('glob') or '*'})")
        for n in names:
            print(f"    кому     {n}")
        print(f"    срок     {r.get('expires_at') or 'без срока'}")
        # КТО одобрил — числом, а не именем: имя человек выбирает себе сам.
        who = r.get("added_by_user_id")
        print(f"    одобрил  {who if who else 'НИКТО — правило недействительно'}"
              f"  {r.get('decision_reaction') or ''}  {r.get('added_at') or ''}")
        print(f"    ушло     {used.get(rid, 0)}"
              + (f", последнее {last[rid]}" if rid in last else ""))

    total = sum(used.values())
    print(f"\nвсего правил {len(rules)}, отправок по ним {total}")
    if total and not log.exists():
        print("НЕСХОДИМОСТЬ: счёт есть, журнала отправок нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
