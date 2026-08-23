#!/usr/bin/env python3
"""Тесты замка состояния: разовое согласие не воскресает, решение — одно.

Гонка, которую это закрывает: grants.json/rules.json правятся read-modify-write
из двух потоков (главный _close, pump spend_grant/sweep_proposals). Без общего
замка и атомарной записи терялась правка — худшее — used_at разового
разрешения, и файл мог уйти повторно без нового «да».

Offline: сеть не трогается.
"""
import os, sys, json, tempfile
from pathlib import Path

os.environ.setdefault("BRIDGE_BOT_TOKEN", "0:test")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tg_bridge as B
import config as C

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond: ok += 1;  print(f"  ok   {name}")
    else:    fail += 1; print(f"  FAIL {name}")


def run():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for attr in ("ROOT", "PROPOSALS", "DECIDED", "REQUESTS"):
            d = tmp if attr == "ROOT" else tmp / attr.lower()
            d.mkdir(exist_ok=True); setattr(C, attr, d)
        C.GRANTS = tmp / "grants.json"
        C.RULES = tmp / "rules.json"

        # --- _atomic_write: целый файл, без хвоста .tmp ---
        B._atomic_write(tmp / "x.json", '{"a":1}')
        check("_atomic_write: файл записан целиком",
              (tmp / "x.json").read_text() == '{"a":1}')
        check("_atomic_write: временный файл не оставлен",
              not (tmp / "x.json.tmp").exists())

        # --- _close APPROVED с пачкой -> одно разрешение, вердикт APPROVED ---
        pf = C.PROPOSALS / "100-200.json"
        prop = {"chat_id": 200, "message_id": 100, "one_line": "send a",
                "batch": {"chat_id": 200,
                          "files": [{"name": "a", "sha256": "hh", "bytes": 1}]}}
        pf.write_text(json.dumps(prop), encoding="utf-8")
        B._close(pf, dict(prop), "APPROVED", uid=7)
        gs = json.loads(C.GRANTS.read_text())
        check("_close APPROVED: ровно одно разрешение", len(gs) == 1)
        check("_close APPROVED: used_at пусто (не потрачено)",
              gs and gs[0].get("used_at") is None)
        dec = json.loads((C.DECIDED / "100-200.json").read_text())
        check("_close APPROVED: решение записано APPROVED",
              dec.get("verdict") == "APPROVED")
        check("_close: pf убран из ожидающих", not pf.exists())

        # --- ИДЕМПОТЕНТНОСТЬ: повторный _close (EXPIRED) НЕ дублирует и НЕ
        #     затирает. Именно так гасится гонка decide vs sweep_proposals. ---
        gid = gs[0]["id"]
        B._close(pf, dict(prop), "EXPIRED", uid=None)
        gs2 = json.loads(C.GRANTS.read_text())
        check("идемпотентность: разрешение НЕ продублировано", len(gs2) == 1)
        dec2 = json.loads((C.DECIDED / "100-200.json").read_text())
        check("идемпотентность: вердикт APPROVED не затёрт на EXPIRED",
              dec2.get("verdict") == "APPROVED")

        # --- spend_grant: тратит разовое, ставит used_at ---
        B.spend_grant(gid)
        gs3 = json.loads(C.GRANTS.read_text())
        check("spend_grant: used_at проставлен",
              gs3[0].get("used_at") is not None)
        # повторный spend не воскрешает и не меняет
        before = gs3[0]["used_at"]
        B.spend_grant(gid)
        gs4 = json.loads(C.GRANTS.read_text())
        check("spend_grant: повторный не меняет уже потраченное",
              gs4[0]["used_at"] == before)

    print("test_locks:", "OK" if fail == 0 else "FAIL", f"({ok} ok, {fail} fail)")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
