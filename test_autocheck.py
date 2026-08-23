#!/usr/bin/env python3
"""Триггер контрольных вопросов: каждое SELFCHECK_EVERY-е даёт вопрос, осечка
глотается, доставка не страдает. Вытаскивает control_question() из модуля с
подменённым C — без сети и без запуска всего моста."""
import re, subprocess, tempfile, types, pathlib

def load():
    src = pathlib.Path("tg_bridge.py").read_text(encoding="utf-8")
    m = re.search(r"def control_question\(.*?\n\n\n", src, re.S)
    ns = {"subprocess": subprocess, "now": lambda: "T", "int": int}
    exec(compile(m.group(0), "<x>", "exec"), ns)
    return ns["control_question"], ns

def run():
    ok = True
    tmp = pathlib.Path(tempfile.mkdtemp())
    cq, ns = load()
    ns["C"] = types.SimpleNamespace(
        SELFCHECK_COUNT=tmp / "cnt", SELFCHECK_EVERY=5,
        SELFCHECK_PRESENT=["python3",
            "/media/vitaly/SSD_1000GB/Projects/SelfCheck/selfcheck.py", "present"])
    pathlib.Path("/media/vitaly/SSD_1000GB/Projects/SelfCheck/state.json").unlink(missing_ok=True)
    got = [bool(cq()) for _ in range(10)]
    # вопрос только на 5-м и 10-м
    ok &= got == [False, False, False, False, True, False, False, False, False, True]
    # осечка -> None, не падает
    ns["C"].SELFCHECK_PRESENT = ["python3", "/no/such.py"]
    ns["C"].SELFCHECK_COUNT.write_text("4")
    ok &= cq() is None
    pathlib.Path("/media/vitaly/SSD_1000GB/Projects/SelfCheck/state.json").unlink(missing_ok=True)
    print("test_autocheck:", "OK" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(run())
