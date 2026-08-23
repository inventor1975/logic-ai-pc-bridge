#!/usr/bin/env python3
"""Тесты v1.1.0 — вложения и подпись по чату.

Offline: ни одного обращения к сети. Проверяется то, что можно проверить без
Телеграма — разбор сообщения, обеззараживание имени, выбор подписи.

Отдельная причина существования этого файла: 2026-08-21 картинка от третьего
лица легла в ящик ПУСТЫМ запросом и была закрыта как «отвечать нечего».
Первые два теста ниже — про то, чтобы это не повторилось.
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

print("вложения — что мост вообще замечает")
photo = {"photo": [{"file_id": "s", "file_size": 100},
                   {"file_id": "l", "file_size": 9000}]}
a = B.attachments_of(photo)
check("картинка замечена", len(a) == 1 and a[0]["kind"] == "photo")
check("берётся САМАЯ БОЛЬШАЯ из лестницы размеров", a[0]["file_id"] == "l")
check("пустое сообщение не даёт вложений", B.attachments_of({}) == [])
check("наклейка НЕ качается", B.attachments_of({"sticker": {"file_id": "x"}}) == [])
doc = {"document": {"file_id": "d", "file_name": "a.pdf", "file_size": 10}}
check("документ замечен", B.attachments_of(doc)[0]["kind"] == "document")
both = {**photo, **doc}
check("картинка и документ вместе — оба", len(B.attachments_of(both)) == 2)

print("\nимя файла — это ДАННЫЕ, а не путь")
check("обход каталога срезан", B.safe_name("../../config.py", "x") == "config.py")
check("абсолютный путь срезан", B.safe_name("/etc/passwd", "x") == "passwd")
check("пустое имя даёт умолчание", B.safe_name("", "photo.jpg") == "photo.jpg")
check("None даёт умолчание", B.safe_name(None, "photo.jpg") == "photo.jpg")
check("кириллица сохраняется", B.safe_name("отчёт 2026.pdf", "x") == "отчёт 2026.pdf")
check("экзотика заменяется", "$" not in B.safe_name("a$b;rm -rf.txt", "x"))
check("имя из одних точек не проходит", B.safe_name("...", "d.bin") == "d.bin")
check("длина ограничена", len(B.safe_name("я" * 400, "x")) <= 120)

print("\nподпись — пустая строка есть ВЫБОР, а не пропуск")
DEF = C.REPLY_PREFIX
check("чат без настройки — общая подпись",
      B.outgoing_prefix({}, {}) == DEF)
check("чат с ПУСТОЙ подписью — пусто, а не общая",
      B.outgoing_prefix({"reply_prefix": ""}, {}) == "")
check("чат со своей подписью — своя",
      B.outgoing_prefix({"reply_prefix": "Х:"}, {}) == "Х:")
check("текст НА ВЫНОС подписан всегда, даже в чате без подписи",
      B.outgoing_prefix({"reply_prefix": ""}, {"no_marker": True}) == C.COPY_PREFIX)
check("ПЕРЕСКАЗ чужих слов подписан всегда",
      B.outgoing_prefix({"reply_prefix": ""}, {"relay": True}) == C.RELAY_PREFIX)

print("\nсборка тела")
check("с подписью — через пробел", B.compose("Л:", "текст") == "Л: текст")
check("без подписи — БЕЗ ведущего пробела", B.compose("", "текст") == "текст")
check("без подписи текст не тронут", B.compose("", " с краю ") == " с краю ")

print("\nпорог размера объявлен и осмыслен")
check("потолок положителен", C.MEDIA_MAX_BYTES > 0)
check("потолок не выше того, что отдаёт Bot API",
      C.MEDIA_MAX_BYTES <= 20 * 1024 * 1024)
check("каталог вложений отдельный", C.MEDIA.name == "media")

print("\nуборка вложений — по переполнению, не по сроку")
import shutil, time as _t
tmp = Path(tempfile.mkdtemp())
def mk(name, size, age_s):
    d = tmp / name; d.mkdir()
    (d / "f.bin").write_bytes(b"x" * size)
    t = _t.time() - age_s
    os.utime(d, (t, t))
    return d
mk("1-100", 400, 300)      # самый старый
mk("2-100", 400, 200)
mk("3-100", 400, 100)      # самый свежий
rm = B.sweep_media(root=tmp, budget=10_000, pending=set())
check("под бюджетом — не трогает ничего", rm == [])
rm = B.sweep_media(root=tmp, budget=900, pending=set())
check("над бюджетом — убирает СТАРОЕ первым", rm == ["1-100"])
check("свежее осталось", (tmp / "3-100").exists())
check("после уборки укладывается в бюджет",
      sum(f.stat().st_size for f in tmp.rglob("*") if f.is_file()) <= 900)

tmp2 = Path(tempfile.mkdtemp())
for n in ("1-100", "2-100", "3-100"):
    d = tmp2 / n; d.mkdir(); (d / "f.bin").write_bytes(b"x" * 400)
    t = _t.time() - (400 - int(n[0]) * 100)
    os.utime(d, (t, t))
rm = B.sweep_media(root=tmp2, budget=900, pending={"1-100"})
check("ЖДУЩЕЕ ОТВЕТА не удаляется, даже будучи самым старым",
      (tmp2 / "1-100").exists() and rm == ["2-100"])
check("вместо него убрано следующее по старшинству", not (tmp2 / "2-100").exists())

tmp3 = Path(tempfile.mkdtemp())
d = tmp3 / "9-100"; d.mkdir(); (d / "f.bin").write_bytes(b"x" * 5000)
rm = B.sweep_media(root=tmp3, budget=100, pending={"9-100"})
check("если всё ждёт ответа — не удаляет НИЧЕГО", rm == [] and d.exists())
check("уборка на несуществующем каталоге не падает",
      B.sweep_media(root=tmp3 / "нет", budget=1, pending=set()) == [])
for t_ in (tmp, tmp2, tmp3): shutil.rmtree(t_, ignore_errors=True)

check("бюджет вложений объявлен", C.MEDIA_BUDGET_BYTES > C.MEDIA_MAX_BYTES)

print("\nотправка файла наружу — сборка запроса, без сети")
tmpf = Path(tempfile.mkdtemp()) / "отчёт.md"
tmpf.write_bytes("данные".encode())
r = B.send_file(1, Path("/нет/такого/файла.txt"))
check("несуществующий файл — честный отказ, не исключение",
      r.get("ok") is False and "нет такого" in r.get("description", ""))
check("функция отправки существует и берёт путь", callable(B.send_file))
import inspect
src = inspect.getsource(B.send_file)
check("подпись режется по пределу Bot API (1024)", "1024" in src)
check("документ и фото — разные методы",
      "sendDocument" in src and "sendPhoto" in src)
check("граница multipart выводится из содержимого, не случайна",
      "sha256" in src and "boundary" in src)
import shutil as _sh; _sh.rmtree(tmpf.parent, ignore_errors=True)

print("\nворота на файлы — журнал правил")
base = Path(tempfile.mkdtemp())
(base / "ok.md").write_text("x"); (base / "ok.zip").write_text("x")
other = Path(tempfile.mkdtemp()); (other / "чужой.md").write_text("x")
APPROVED = [{"id": "R001", "chat_id": 42, "dir": str(base), "glob": "*.md",
             "added_by_user_id": 500600700}]

check("пустой журнал НЕ РАЗРЕШАЕТ ничего",
      B.rule_for(42, base / "ok.md", []) is None)
check("правило покрывает свой каталог и образец",
      (B.rule_for(42, base / "ok.md", APPROVED) or {}).get("id") == "R001")
check("другой ОБРАЗЕЦ не покрыт", B.rule_for(42, base / "ok.zip", APPROVED) is None)
check("другая КОМНАТА не покрыта", B.rule_for(99, base / "ok.md", APPROVED) is None)
check("другой КАТАЛОГ не покрыт", B.rule_for(42, other / "чужой.md", APPROVED) is None)
check("обход через .. НЕ проходит",
      B.rule_for(42, base / ".." / other.name / "чужой.md", APPROVED) is None)

NOAPPROVER = [dict(APPROVED[0], added_by_user_id=None)]
check("правило БЕЗ одобрившего не действует — подделка не проходит",
      B.rule_for(42, base / "ok.md", NOAPPROVER) is None)

EXPIRED = [dict(APPROVED[0], expires_at="2020-01-01T00:00:00+00:00")]
check("истёкшее правило не действует", B.rule_for(42, base / "ok.md", EXPIRED) is None)
FUTURE = [dict(APPROVED[0], expires_at="2099-01-01T00:00:00+00:00")]
check("неистёкшее действует", B.rule_for(42, base / "ok.md", FUTURE) is not None)
BROKEN = [dict(APPROVED[0], expires_at="позавчера")]
check("нечитаемый срок трактуется НЕ В ПОЛЬЗУ отправки",
      B.rule_for(42, base / "ok.md", BROKEN) is None)
NODIR = [{"id": "R", "chat_id": 42, "added_by_user_id": 1}]
check("правило без каталога не действует (нельзя «что угодно куда угодно»)",
      B.rule_for(42, base / "ok.md", NODIR) is None)
import shutil as _s
for t_ in (base, other): _s.rmtree(t_, ignore_errors=True)

print("\nстроже: точные пути, список комнат, ярлык проекта")
b2 = Path(tempfile.mkdtemp())
(b2 / "названный.md").write_text("x"); (b2 / "новый.md").write_text("x")
EXACT = [{"id": "R010", "project": "work", "chats": [42, 43],
          "paths": [str(b2 / "названный.md")], "added_by_user_id": 7}]
check("точный путь разрешён",
      (B.rule_for(42, b2 / "названный.md", EXACT) or {}).get("id") == "R010")
check("НОВЫЙ файл в той же папке НЕ разрешён — вот в чём строгость",
      B.rule_for(42, b2 / "новый.md", EXACT) is None)
check("вторая перечисленная комната тоже покрыта",
      B.rule_for(43, b2 / "названный.md", EXACT) is not None)
check("неперечисленная комната не покрыта",
      B.rule_for(44, b2 / "названный.md", EXACT) is None)

LABEL = [{"id": "R011", "project": "work", "chats": [42],
          "dirs": [{"dir": str(b2), "glob": "*.md"}], "added_by_user_id": 7}]
check("папка целиком — новый файл покрыт",
      B.rule_for(42, b2 / "новый.md", LABEL) is not None)
FAKE = [{"id": "R012", "project": "work", "chats": [42],
         "added_by_user_id": 7}]
check("ЯРЛЫК проекта НЕ даёт разрешения сам по себе",
      B.rule_for(42, b2 / "новый.md", FAKE) is None)
OLD14 = [{"id": "R001", "chat_id": 42, "dir": str(b2), "glob": "*.md",
          "added_by_user_id": 7}]
check("форма v1.4 (chat_id/dir/glob) по-прежнему работает",
      B.rule_for(42, b2 / "новый.md", OLD14) is not None)
import shutil as _s3; _s3.rmtree(b2, ignore_errors=True)

print("\nправило доезжает от предложения до журнала")
import inspect
src = inspect.getsource(B.flush_outbox)
check("поле rule кладётся в ожидающее предложение", '"rule": prop.get("rule")' in src)
# _close стал тонкой обёрткой (замок + идемпотентность) над _close_locked;
# логика записи журнала/правила живёт в реализации, её и инспектируем.
csrc = inspect.getsource(B._close) + inspect.getsource(B._close_locked)
check("журнал пишется только при APPROVED и только с uid",
      'verdict == "APPROVED"' in csrc and 'and uid' in csrc)
check("в запись правила попадает одобривший", "added_by_user_id" in csrc)

import inspect as _i
_src = _i.getsource(B.flush_outbox)
check("отказанный файл УХОДИТ ИЗ ОЧЕРЕДИ, а не переименовывается на месте",
      "C.NEEDS_CONSENT / f.name" in _src and 'C.OUTBOX / f"needs-consent' not in _src)
check("каталог ожидающих согласия объявлен", C.NEEDS_CONSENT.name == "needs_consent")

print("\nпачка — разовые разрешения по отпечатку")
bd = Path(tempfile.mkdtemp()); f1 = bd / "один.md"; f1.write_bytes(b"aaa")
import hashlib as _h
D1 = _h.sha256(b"aaa").hexdigest()
saved = C.GRANTS
C.GRANTS = bd / "grants.json"
import json as _j
def put(gs): C.GRANTS.write_text(_j.dumps(gs), encoding="utf-8")

put([{"id": "G001", "chat_id": 42, "sha256": D1,
      "added_by_user_id": 7, "used_at": None}])
check("разрешение по отпечатку срабатывает",
      (B.grant_for(42, f1) or {}).get("id") == "G001")
check("чужая комната не покрыта", B.grant_for(43, f1) is None)

f1.write_bytes("ПОДМЕНА".encode())
check("ПОДМЕНА содержимого после метки — не проходит", B.grant_for(42, f1) is None)
f1.write_bytes(b"aaa")

put([{"id": "G002", "chat_id": 42, "sha256": D1,
      "added_by_user_id": 7, "used_at": "2026-08-22T00:00:00+00:00"}])
check("потраченное разрешение больше не действует", B.grant_for(42, f1) is None)
put([{"id": "G003", "chat_id": 42, "sha256": D1,
      "added_by_user_id": None, "used_at": None}])
check("разрешение без одобрившего не действует", B.grant_for(42, f1) is None)

put([{"id": "G004", "chat_id": 42, "sha256": D1,
      "added_by_user_id": 7, "used_at": None}])
B.spend_grant("G004")
check("потраченное помечается и второй раз не срабатывает",
      B.grant_for(42, f1) is None)
C.GRANTS = saved
check("потолок пачки объявлен и мал настолько, чтобы список читался",
      0 < C.BATCH_MAX <= 20)
import shutil as _s4; _s4.rmtree(bd, ignore_errors=True)

print("\nтупик, значок и сторож подмены")
import inspect as _i2
_fo = _i2.getsource(B.flush_outbox)
check("отказанный файл БУДИТ ассистента, а не лежит молча",
      "needsfile-" in _fo and "./propose.py --batch" in _fo)
_nu = _i2.getsource(B.nudge_unanswered)
check("напоминание шлётся ОДИН раз на сообщение", '"nudged"' in _nu)
check("свои же записки не считаются ожиданием человека",
      '"verdict-"' in _nu and '"needsfile-"' in _nu)
check("порог молчания объявлен и разумен", 5 <= C.NUDGE_AFTER_MIN <= 120)

import drift as _d
check("у отказа по подмене СВОЙ код возврата", _d.EXIT_DRIFT not in (0, 1, 2))
check("сторож следит за самим собой", "drift.py" in _d.WATCHED)
check("сторож следит за воротами согласия", "tg_bridge.py" in _d.WATCHED)
_saved = _d.APPROVED
_d.APPROVED = Path(tempfile.mkdtemp()) / "нет.json"
_okd, _det = _d.check()
check("НЕТ одобренного состояния — это ОТКАЗ, а не разрешение по умолчанию",
      _okd is False and _det["reason"] == "NO_APPROVED_MANIFEST")
_d.APPROVED = _saved

print("\nбезопасность: потолок, заголовок, новый файл")
import inspect as _i3
_ff = _i3.getsource(B.fetch_file)
check("скачивание идёт КУСКАМИ, а не одним read()",
      "resp.read(" in _ff and "resp.read()" not in _ff)
check("поток обрывается по потолку, недокачанное удаляется",
      "got > cap" in _ff and "unlink" in _ff)
check("размер спрашивается у API, а не только берётся из обновления",
      'res.get("file_size")' in _ff)
_sf = _i3.getsource(B.send_file)
check("имя файла обеззараживается перед заголовком",
      'replace(\'"\'' in _sf or "replace('\"'" in _sf)
check("перевод строки в имени тоже вычищается", '\\r' in _sf and '\\n' in _sf)
import drift as _d2
_dm = _i3.getsource(_d2.manifest)
check("сторож видит ВСЕ .py, а не только свой перечень",
      'C.ROOT.glob("*.py")' in _dm)

print("\nуведомление о записи описывает то, что СОБИРАЕТСЯ")
_a = C.announce_text(111111111)
check("сказано про запись переписки", "ПИШЕТСЯ В ФАЙЛ" in _a)
check("сказано про ВЛОЖЕНИЯ — это добавилось в v1.1.0", "ВЛОЖЕНИЯ" in _a)
check("сказано про расшифровку голоса", "расшифров" in _a)
check("сказано, что наружу само ничего не уходит", "по своему почину" in _a)
_g = C.announce_text(-5101395964)
check("там, где подпись есть, о ней сказано", "ИИ(" in _g)
check("там, где подписи нет, о ней НЕ говорится", "ИИ(" not in _a)
_an = _i3.getsource(B.announce)
check("ключ уведомления включает ОТПЕЧАТОК текста, а не только номер чата",
      "sha256" in _an and "key" in _an)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
