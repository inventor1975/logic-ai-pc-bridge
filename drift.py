#!/usr/bin/env python3
# Copyright 2026 Vitaly Reznik
# SPDX-License-Identifier: Apache-2.0
"""Сторож подмены: отказаться работать, если на диске не то, что одобрено.

    ./drift.py --check     сверить и вернуть код возврата
    ./drift.py --approve   записать нынешнее состояние как одобренное

ЧЕСТНАЯ ГРАНИЦА, И ЕЁ НАДО НАЗВАТЬ ПЕРВОЙ. Этот сторож НЕ защищает от того, у
кого есть доступ к каталогу моста: кто может править `tg_bridge.py`, тот может
править и `approved_manifest.json`, и сам этот файл. Пакет с первого дня
говорит, что скомпрометированная машина — это скомпрометированный бот, и здесь
ничего не изменилось.

Что он ЛОВИТ: правку, которая прошла мимо переноса. Файл, поправленный на живом
дереве «на минутку»; недокатившийся перенос; расхождение между тем, что
испытано, и тем, что работает. Именно от этой породы отказов нас и поймали
2026-08-21, и она случается без всякого злого умысла.

ПОЧЕМУ ОТКАЗ, А НЕ ПРЕДУПРЕЖДЕНИЕ. Предупреждение адресовано читателю, которого
может не быть. Мост, поехавший дальше с непроверенным кодом, обслуживает ворота
согласия — то есть решает, что считать разрешением. Такому лучше не работать
вовсе, чем работать неизвестно чем.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import config as C

EXIT_DRIFT = 90          # свой код: отказ по подмене НЕ должен путаться с падением
WATCHED = ("tg_bridge.py", "config.py", "propose.py", "pending.py", "react.py",
           "edit.py", "unreact.py", "seal.py", "gate_health.py", "drift.py",
           "rules.py", "test_gate.py", "test_attach.py")
APPROVED = C.ROOT / "approved_manifest.json"
REFUSALS = C.ROOT / "drift_refusals.jsonl"


def manifest() -> dict[str, str]:
    """Отпечатки того, что исполняется.

    СПИСКА ИМЁН НЕДОСТАТОЧНО, и это была дыра. Сторож, знающий только свой
    перечень, не заметит НОВЫЙ файл — а Python сам подхватывает кое-что по
    имени (`sitecustomize.py`), и любой новый модуль рядом может быть
    импортирован завтрашней правкой. Поэтому берём и перечень, и ВСЕ .py в
    каталоге: появление файла — такое же расхождение, как изменение.
    """
    out = {}
    names = set(WATCHED) | {p.name for p in C.ROOT.glob("*.py")}
    for name in sorted(names):
        p = C.ROOT / name
        if p.exists() and p.is_file():
            out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def check() -> tuple[bool, dict]:
    """(всё сходится, подробности). Отсутствие манифеста — НЕ повод пропустить."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = manifest()
    if not APPROVED.exists():
        return False, {"at": now, "reason": "NO_APPROVED_MANIFEST",
                       "note": "одобренного состояния нет — сверять не с чем, "
                               "и это отказ, а не разрешение по умолчанию"}
    old = json.loads(APPROVED.read_text(encoding="utf-8")).get("files", {})
    changed = {k: {"approved": old.get(k), "now": v}
               for k, v in cur.items() if old.get(k) != v}
    gone = [k for k in old if k not in cur]
    added = [k for k in cur if k not in old]
    if not (changed or gone or added):
        return True, {"at": now, "files": len(cur)}
    return False, {"at": now, "reason": "DRIFT", "changed": changed,
                   "removed": gone, "added": added}


def main(argv: list[str]) -> int:
    if "--approve" in argv:
        APPROVED.write_text(json.dumps(
            {"approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "note": "записано при переносе; см. квитанцию переноса",
             "files": manifest()}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"одобрено {len(manifest())} файлов -> {APPROVED.name}")
        return 0

    ok, detail = check()
    if ok:
        print(f"сходится: {detail['files']} файлов")
        return 0
    with REFUSALS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(detail, ensure_ascii=False) + "\n")
    print(f"ОТКАЗ: {detail['reason']}")
    for k, v in (detail.get("changed") or {}).items():
        print(f"    изменён  {k}\n        одобрено {str(v['approved'])[:16]}…"
              f"\n        сейчас   {str(v['now'])[:16]}…")
    for k in (detail.get("removed") or []):
        print(f"    ПРОПАЛ   {k}")
    for k in (detail.get("added") or []):
        print(f"    появился {k}")
    print(f"отказ записан в {REFUSALS.name}")
    return EXIT_DRIFT


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
