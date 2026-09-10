#!/usr/bin/env python3
"""The reaction guard: an invalid emoji (✅) must be refused rather than fall
through into a message. Learned the painful way on 2026-08-22."""
import config as C

def run():
    ok = True
    ok &= "✅" not in C.VALID_REACTIONS          # the one we were burned by
    ok &= "👍" in C.VALID_REACTIONS              # the safe "done" mark
    ok &= C.ACK_EMOJI in C.VALID_REACTIONS       # 👀 itself must be valid
    for bad in ("✅", "❌", "✔", "🟢", "🐝"):
        ok &= bad not in C.VALID_REACTIONS
    print("test_reactions:", "OK" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(run())
