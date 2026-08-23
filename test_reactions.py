#!/usr/bin/env python3
"""Страж реакций: невалидный эмодзи (✅) должен отвергаться, а не срываться
в сообщение. Промерено болью 2026-08-22."""
import config as C

def run():
    ok = True
    ok &= "✅" not in C.VALID_REACTIONS          # то, на чём обожглись
    ok &= "👍" in C.VALID_REACTIONS              # безопасная метка «готово»
    ok &= C.ACK_EMOJI in C.VALID_REACTIONS       # сам 👀 обязан быть валиден
    for bad in ("✅", "❌", "✔", "🟢", "🐝"):
        ok &= bad not in C.VALID_REACTIONS
    print("test_reactions:", "OK" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(run())
