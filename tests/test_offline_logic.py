# -*- coding: utf-8 -*-
"""上下架语义回归测试：不联网，只验证快照层与构建层的判定规则。

用法: python3 tests/test_offline_logic.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "pipelines", "mobile"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import snapshot  # noqa: E402


def item(name, own="个人资费", typ="套餐", off=""):
    fields = {
        "资费标准": "10元", "方案编号": "P" + name, "资费类型": typ, "归属": own,
        "适用范围": "", "适用地区": "", "销售渠道": "", "上线日期": "2026年01月01日",
        "下线日期": off, "有效期限": "", "在网要求": "", "退订方式": "", "违约责任": "",
        "国内通话": "", "国内通用流量": "", "短信": "", "定向流量": "", "宽带": "",
        "移动高清": "", "权益": "", "超出资费说明": "", "其他服务内容": "", "其他说明": "",
    }
    return {"name": name, "fields": fields}


def pack(items, failed=None):
    return {
        "timestamp": "2026-11-17 12:00:00",
        "section": "hunan",
        "items": list(items),
        "error": None,
        "failed_categories": list(failed or []),
        "categories_total": 6,
    }


def fresh_state(tmp):
    snapshot.SNAPSHOT_DIR = tmp
    snapshot._STATE_PATH = os.path.join(tmp, "_missing.json")
    snapshot.MISSING_ROUNDS = 2


def names(items):
    return sorted(x["name"] for x in items)


def snapshot_items(section="hunan"):
    d = snapshot.load_snapshot(section) or {}
    return d.get("items") or []


results = []


def check(label, cond, detail=""):
    results.append((label, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + detail) if detail and not cond else ""))


def case_missing_streak():
    tmp = tempfile.mkdtemp()
    fresh_state(tmp)
    base = [item("A%d" % i) for i in range(10)]
    snapshot.check_section("hunan", pack(base))          # 建基线

    r2 = snapshot.check_section("hunan", pack(base[:5])) # 第一轮缺 5 条
    check("缺一轮：不判下架", r2 is None or r2["removed"] == [], str(r2))
    check("缺一轮：基线仍保留 10 条", len(snapshot_items()) == 10, str(len(snapshot_items())))

    r3 = snapshot.check_section("hunan", pack(base[:5])) # 连续第二轮缺
    removed = names(r3["removed"]) if r3 else []
    check("连续两轮缺失：判下架 5 条", sorted(removed) == sorted(names(base[5:])), str(removed))
    check("下架后基线只剩 5 条", len(snapshot_items()) == 5, str(len(snapshot_items())))
    shutil.rmtree(tmp)


def case_return_soon():
    tmp = tempfile.mkdtemp()
    fresh_state(tmp)
    base = [item("B%d" % i) for i in range(6)]
    snapshot.check_section("hunan", pack(base))
    snapshot.check_section("hunan", pack(base[:3]))      # 缺 3 条（第一轮）
    r = snapshot.check_section("hunan", pack(base))      # 下一轮全回来
    check("漏采回补：不产生新增", r is None or r["added"] == [], str(r))
    check("漏采回补：基线恢复 6 条", len(snapshot_items()) == 6, str(len(snapshot_items())))
    shutil.rmtree(tmp)


def case_failed_category():
    tmp = tempfile.mkdtemp()
    fresh_state(tmp)
    a = [item("C%d" % i, own="个人资费", typ="套餐") for i in range(4)]
    b = [item("D%d" % i, own="政企资费", typ="营销活动") for i in range(4)]
    snapshot.check_section("hunan", pack(a + b))

    # 政企/营销活动 接口整轮抓空，只返回个人套餐
    r = snapshot.check_section("hunan", pack(a, failed=["2,3"]))
    check("分类抓空：不判下架", r is None or r["removed"] == [], str(r))
    check("分类抓空：基线补齐到 8 条", len(snapshot_items()) == 8, str(len(snapshot_items())))
    r2 = snapshot.check_section("hunan", pack(a + b))
    check("接口恢复：不产生新增", r2 is None or r2["added"] == [], str(r2))
    shutil.rmtree(tmp)


def case_offline_date():
    tmp = tempfile.mkdtemp()
    fresh_state(tmp)
    expired = item("E-old", off="2020年05月01日")
    alive = item("E-new", off="2099年12月31日")
    keep = item("E-stay")
    snapshot.check_section("hunan", pack([expired, alive, keep]))
    # 已过期的与未到期的都不见了，只有常驻条目还在
    r = snapshot.check_section("hunan", pack([keep]))
    removed = names(r["removed"]) if r else []
    check("下线日期已过：立即下架", removed == ["E-old"], str(r))
    check("下线日期未到：保留在基线", names(snapshot_items()) == ["E-new", "E-stay"], str(names(snapshot_items())))
    shutil.rmtree(tmp)


def case_empty_scan_snapshot():
    """快照层：接口整轮返回 0 条时不得清空基线。"""
    tmp = tempfile.mkdtemp()
    fresh_state(tmp)
    base = [item("G%d" % i) for i in range(3)]
    snapshot.check_section("hunan", pack(base))
    r = snapshot.check_section("hunan", pack([]))
    check("快照层空扫描：不产生变化", r is None, str(r))
    check("快照层空扫描：基线保持 3 条", len(snapshot_items()) == 3, str(len(snapshot_items())))
    shutil.rmtree(tmp)


def case_build_site_empty_scan():
    """构建层：快照 0 条、基线有数据时，不得把线上数据清空、不得记下架。"""
    import build_site

    root = tempfile.mkdtemp()
    for sub in ("snapshots", "_prev", "_site/data", "_site/prev"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    build_site.ROOT = root
    build_site.SNAP = os.path.join(root, "snapshots")
    build_site.PREV = os.path.join(root, "_prev")
    build_site.SITE = os.path.join(root, "_site")
    build_site.DATA = os.path.join(root, "_site", "data")
    build_site.PREV_OUT = os.path.join(root, "_site", "prev")

    base = {"timestamp": "2026-11-17 10:00:00", "section": "hunan", "items": [item("F%d" % i) for i in range(3)]}
    json.dump(base, open(os.path.join(root, "_prev", "hunan.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"timestamp": "2026-11-17 12:00:00", "section": "hunan", "items": []},
              open(os.path.join(root, "snapshots", "hunan.json"), "w", encoding="utf-8"), ensure_ascii=False)

    build_site.main()

    data = json.load(open(os.path.join(build_site.DATA, "hunan.json"), encoding="utf-8"))
    prev = json.load(open(os.path.join(build_site.PREV_OUT, "hunan.json"), encoding="utf-8"))
    hist = json.load(open(os.path.join(build_site.DATA, "history.json"), encoding="utf-8"))
    removed = sum((r.get("hunan", {}) or {}).get("removed", 0) or 0 for r in hist if isinstance(r, dict))
    check("构建层空扫描：线上数据保持 3 条", len(data.get("items") or []) == 3, str(len(data.get("items") or [])))
    check("构建层空扫描：基线不被空快照覆盖", len(prev.get("items") or []) == 3, str(len(prev.get("items") or [])))
    check("构建层空扫描：不记下架", removed == 0, str(removed))
    shutil.rmtree(root, ignore_errors=True)


case_missing_streak()
case_return_soon()
case_failed_category()
case_offline_date()
case_empty_scan_snapshot()
case_build_site_empty_scan()

failed = [r for r in results if not r[1]]
print("\n%d/%d 通过" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
