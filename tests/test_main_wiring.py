# -*- coding: utf-8 -*-
"""集成测试：用桩替换 fetcher/notifier，验证 main.run_once 的板块取舍。

用法: python3 tests/test_main_wiring.py
"""
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
MOBILE = os.path.join(HERE, "..", "pipelines", "mobile")
sys.path.insert(0, MOBILE)

# ── 桩：fetcher / notifier（避免依赖 pycryptodome 与外网）──
fake = types.ModuleType("fetcher")
fake.SECTIONS = []
fake.FETCH = {}
fake.fetch_all = lambda: fake.FETCH
sys.modules["fetcher"] = fake

notifier = types.ModuleType("notifier")
notifier.send_mail = lambda reports: True
notifier.send_summary = lambda reports: True
notifier.send_nochange = lambda ts: True
sys.modules["notifier"] = notifier

import snapshot  # noqa: E402
import main as mobile_main  # noqa: E402


def item(name, own="个人资费", typ="套餐"):
    return {"name": name, "fields": {"资费类型": typ, "归属": own, "方案编号": "P" + name}}


def pack(sec, items, failed=None, total=6, empty=None):
    return {"timestamp": "2026-11-17 12:00:00", "section": sec, "items": list(items),
            "error": None, "failed_categories": list(failed or []),
            "empty_categories": list(empty or []), "categories_total": total}


results = []


def check(label, cond, detail=""):
    results.append((label, bool(cond)))
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + detail) if detail and not cond else ""))


tmp = tempfile.mkdtemp()
snapshot.SNAPSHOT_DIR = tmp
snapshot._SEEN_PATH = os.path.join(tmp, "_seen.json")
mobile_main._ROOT_DIR = tmp
mobile_main._write_diag = lambda diag: None

a = [item("A%d" % i) for i in range(4)]
b = [item("B%d" % i, own="政企资费", typ="营销活动") for i in range(4)]

# 第一轮：三个板块
fake.FETCH = {"hunan": pack("hunan", a + b), "henan": pack("henan", a + b), "shanxi": pack("shanxi", a + b)}
mobile_main.run_once(send_mail=False)

# 第二轮：hunan 只有一个分类抓空（应补齐不报下架）；henan 半数分类失败（应整块跳过）；shanxi 完全空（应跳过）
fake.FETCH = {
    "hunan": pack("hunan", a, failed=["2,3"]),
    "henan": pack("henan", a, failed=["1,2", "1,3", "2,2"]),
    "shanxi": pack("shanxi", []),
}
mobile_main.run_once(send_mail=False)

hunan = snapshot.load_snapshot("hunan")["items"]
henan = snapshot.load_snapshot("henan")["items"]
shanxi = snapshot.load_snapshot("shanxi")["items"]
check("单分类抓空：湖南基线仍 8 条", len(hunan) == 8, str(len(hunan)))
check("半数分类失败：河南基线保持 8 条", len(henan) == 8, str(len(henan)))
check("整板块空：山西基线保持 8 条", len(shanxi) == 8, str(len(shanxi)))

# 第三轮：全部恢复，不应产生任何「新增」
fake.FETCH = {"hunan": pack("hunan", a + b), "henan": pack("henan", a + b), "shanxi": pack("shanxi", a + b)}
reports = []
_orig = snapshot.check_section
def spy(section, new_data, failed=None):
    r = _orig(section, new_data, failed)
    if r:
        reports.append(r)
    return r
snapshot.check_section = spy
mobile_main.run_once(send_mail=False)
snapshot.check_section = _orig
check("接口恢复：无新增报告", all(not r["added"] for r in reports), str([(r["section"], len(r["added"])) for r in reports]))

# 第四轮：某省 3 个分类「请求成功但 0 条」（可能本来就没业务）——不能整块跳过
fake.FETCH = {
    "hunan": pack("hunan", a, empty=["2,1", "2,2", "2,3"]),
    "henan": pack("henan", a + b),
    "shanxi": pack("shanxi", a + b),
}
mobile_main.run_once(send_mail=False)
hunan = snapshot.load_snapshot("hunan")["items"]
check("空分类不阻塞板块：湖南基线仍 8 条", len(hunan) == 8, str(len(hunan)))
check("空分类不阻塞板块：快照已更新到本轮", snapshot.load_snapshot("hunan")["timestamp"] == "2026-11-17 12:00:00")

shutil.rmtree(tmp, ignore_errors=True)
failed = [r for r in results if not r[1]]
print("\n%d/%d 通过" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
