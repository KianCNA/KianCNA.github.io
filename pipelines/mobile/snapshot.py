# 快照模块：存储历史数据并对比变化
import json
import os
import re
import time

SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

# 源站按「IP + UA 配额」返回**波动的子集**：同一分类不同时刻可能返回 1,480 或 1,567 条。
# 每轮直接用单次结果覆盖快照，就会「这轮少 87 条、下轮又多 87 条」，站点看起来永远不齐。
# 因此快照改为**跨轮累积并集**：没再采到的条目继续保留 POOL_TTL_DAYS 天，
# 超过保留期仍未出现才视为下架（同时尊重业务自己的下线日期）。
POOL_TTL_DAYS = float(os.getenv("POOL_TTL_DAYS") or "2")
_SEEN_PATH = os.path.join(SNAPSHOT_DIR, "_seen.json")

# 归属/资费类型 → 抓取分类（与 fetcher.TYPE_COMBOS 的 (type1,type2) 对应）
_OWN_TO_T1 = {"个人资费": "1", "政企资费": "2"}
_TYPE_TO_T2 = {"套餐": "1", "加装包": "2", "营销活动": "3", "流量包": "4"}
_DATE_RE = re.compile(r"(\d{4})\D{0,3}(\d{1,2})\D{0,3}(\d{1,2})")


def _snapshot_path(section: str) -> str:
    return os.path.join(SNAPSHOT_DIR, f"{section}.json")


def load_snapshot(section: str):
    """读取上次抓取结果，不存在返回 None"""
    path = _snapshot_path(section)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_snapshot(section: str, data: dict):
    """保存本次抓取结果。

    紧凑格式（无缩进/无多余空格）：快照体量大（33 省约 60MB），
    indent=2 会让工作区再膨胀约 16%，拖慢 Actions 每次 checkout。
    原子写入：先写临时文件再 os.replace，避免进程中途被 kill 时
    留下半个 JSON，导致下一轮基线损坏、全量误报。
    """
    path = _snapshot_path(section)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _parse_name(item) -> str:
    """从资费条目里解析业务名称。新版 item 为 dict{'name':...}，兼容旧版字符串。"""
    if isinstance(item, dict):
        return (item.get("name") or "").strip()
    if isinstance(item, str):
        for sep in ("：", ":"):
            if sep in item:
                return item.split(sep, 1)[0].strip()
        return item.strip()
    return ""


def _same_structure(old_items: list, new_items: list) -> bool:
    """新旧快照数据格式是否一致（都是结构化 dict 或都是字符串）。"""
    def is_dict(l):
        return bool(l) and isinstance(l[0], dict)
    return is_dict(old_items) == is_dict(new_items)


def _field_keys(items: list):
    """取快照条目统一的 fields 字段键集合；无结构字段时返回 None。"""
    for it in (items or []):
        if isinstance(it, dict):
            f = it.get("fields")
            if isinstance(f, dict):
                return tuple(sorted(f.keys()))
    return None


def _structure_upgraded(old_items: list, new_items: list) -> bool:
    """新旧快照字段结构是否不一致（字段集新增/删减，如新增采集字段）。"""
    ok, nk = _field_keys(old_items), _field_keys(new_items)
    return ok is not None and nk is not None and ok != nk


def _norm(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(v).strip()


def _mobile_key(item):
    """移动业务身份键：优先稳定业务编号，否则名称+分类；绝不包含价格/字段内容。"""
    if not isinstance(item, dict):
        return ("text", _parse_name(item))
    fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
    for k in ("productCode", "goodsCode", "businessCode", "code", "方案编号"):
        v = fields.get(k) or item.get(k)
        if v not in (None, ""):
            return ("code", k, _norm(v))
    return ("name", _norm(item.get("name")), _norm(fields.get("资费类型")), _norm(fields.get("归属")))


def _mobile_fields(item):
    if isinstance(item, dict):
        f = item.get("fields")
        if isinstance(f, dict):
            return {k: v for k, v in f.items()}
        return {k: v for k, v in item.items() if k not in ("id", "name")}
    return {"name": item}


def _changed(old, new):
    a, b = _mobile_fields(old), _mobile_fields(new)
    return {k: (a.get(k), b.get(k)) for k in sorted(set(a) | set(b)) if _norm(a.get(k)) != _norm(b.get(k))}


def diff(old_items: list, new_items: list) -> dict:
    """重复安全的移动 Diff：同身份一对一匹配，避免同名条目互相覆盖。"""
    old, new = list(old_items or []), list(new_items or [])
    used_old, used_new = set(), set()
    pairs = []

    def groups(items, key_fn, used):
        out = {}
        for i, x in enumerate(items):
            if i not in used:
                out.setdefault(key_fn(x), []).append(i)
        return out

    # 先精确 ID；只有唯一 ID 才配对。
    om, nm = groups(old, lambda x: _norm(x.get("id")) if isinstance(x, dict) else "", used_old), groups(new, lambda x: _norm(x.get("id")) if isinstance(x, dict) else "", used_new)
    for k in set(om) & set(nm):
        if k and len(om[k]) == len(nm[k]) == 1:
            oi, ni = om[k][0], nm[k][0]; used_old.add(oi); used_new.add(ni); pairs.append((oi, ni))

    # 再稳定业务键；多条同身份时一对一，不覆盖。
    om, nm = groups(old, _mobile_key, used_old), groups(new, _mobile_key, used_new)
    for k in set(om) & set(nm):
        for oi, ni in zip(om[k], nm[k]):
            used_old.add(oi); used_new.add(ni); pairs.append((oi, ni))

    added = [new[i] for i in range(len(new)) if i not in used_new]
    removed = [old[i] for i in range(len(old)) if i not in used_old]
    modified = []
    for oi, ni in pairs:
        changed = _changed(old[oi], new[ni])
        if changed:
            modified.append({"name": _parse_name(new[ni]), "old": _mobile_fields(old[oi]), "new": _mobile_fields(new[ni]), "changed": changed})
    return {"added": added, "removed": removed, "modified": modified, "restored": []}

def _key_of(item):
    return json.dumps(_mobile_key(item), ensure_ascii=False, separators=(",", ":"))


def _cat_of(item):
    """从条目字段推回抓取分类 (type1,type2)，如 "1,2"。推不出返回空串。"""
    f = _mobile_fields(item)
    t1 = _OWN_TO_T1.get(_norm(f.get("归属")))
    t2 = _TYPE_TO_T2.get(_norm(f.get("资费类型")))
    return f"{t1},{t2}" if t1 and t2 else ""


def _off_date(item):
    """解析业务自带的「下线日期」，返回 YYYY-MM-DD；无/无法识别返回空串。"""
    f = _mobile_fields(item)
    raw = _norm(f.get("下线日期"))
    if not raw:
        return ""
    m = _DATE_RE.search(raw)
    if not m:
        return ""
    y, mo, d = m.groups()
    try:
        return "%04d-%02d-%02d" % (int(y), int(mo), int(d))
    except ValueError:
        return ""


def merge_failed_categories(prev_items, new_items, failed_keys):
    """把基线里属于「本轮抓空分类」的条目补回去。

    接口没返回数据不等于这批业务下架；不补齐就会在 diff 里变成整分类的下架，
    下一轮接口恢复又整批「新增」。返回 (补齐后的列表, 补齐条数)。
    """
    if not failed_keys or not prev_items:
        return list(new_items or []), 0
    have = {_key_of(x) for x in (new_items or [])}
    kept = [x for x in prev_items if _cat_of(x) in failed_keys and _key_of(x) not in have]
    if not kept:
        return list(new_items or []), 0
    return kept + list(new_items or []), len(kept)


def _seen_load():
    try:
        with open(_SEEN_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _seen_save(state):
    try:
        tmp = _SEEN_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, _SEEN_PATH)
    except Exception as e:
        print(f"  [state] 采集时间戳写入失败: {e}")


def union_with_baseline(section, prev_items, new_items):
    """把本轮结果与基线做并集，按「保留期」与「业务下线日期」回收。

    - 本轮采到的条目：更新内容、刷新 last_seen
    - 本轮没采到、但仍在 POOL_TTL_DAYS 内的：原样保留（源站子集波动，不代表下架）
    - 超过保留期仍未再出现，或「下线日期」已过：丢弃（视为下架）

    返回 (合并后的列表, 保留条数, 回收条数)。采集时间戳存在 snapshots/_seen.json。
    """
    state = _seen_load()
    sec_seen = state.setdefault(section, {})
    now = time.time()
    ttl = POOL_TTL_DAYS * 86400
    today = time.strftime("%Y-%m-%d")

    merged = {}
    for it in prev_items or []:
        k = _key_of(it)
        merged[k] = it
        sec_seen.setdefault(k, now)      # 老数据迁移：初次没有时间戳，先给一个宽限
    fresh = set()
    for it in new_items or []:
        k = _key_of(it)
        merged[k] = it
        sec_seen[k] = now
        fresh.add(k)

    out, held, dropped = [], 0, 0
    for k, it in merged.items():
        off = _off_date(it)
        if off and off <= today:
            sec_seen.pop(k, None)
            dropped += 1
            continue
        if k not in fresh and (now - sec_seen.get(k, now)) > ttl:
            sec_seen.pop(k, None)
            dropped += 1
            continue
        if k not in fresh:
            held += 1
        out.append(it)

    state[section] = {k: v for k, v in sec_seen.items() if k in merged}
    _seen_save(state)
    return out, held, dropped


def check_section(section: str, new_data: dict, failed_categories=None):
    """对比某板块变化，返回变化报告 dict 或 None。

    三层护栏，目的都是把「接口没返回数据」和「业务真的下架」分开：

      1) failed_categories 里的分类本轮彻底抓空 → 用基线补齐该分类的条目。
      2) 快照改为**跨轮累积并集**：源站每次只返回一个波动的子集，本轮没采到
         但仍在 POOL_TTL_DAYS 内的条目原样保留；超过保留期或「下线日期」已过
         才回收（回收的那部分就是真正的下架）。
      3) 空扫描（整板块 0 条）直接保留旧快照，不记变化。

    这样每次采集都会把新看到的条目并进快照，覆盖面逐轮扩大，站点不再
    「这轮少一批、下轮多一批」。
    """
    old = load_snapshot(section)
    prev_items = (old or {}).get("items") or []
    cur = dict(new_data or {})
    items = list(cur.get("items") or [])

    if prev_items and failed_categories:
        merged_items, merged = merge_failed_categories(prev_items, items, set(failed_categories))
        if merged:
            print("  [补齐] 板块 %s 有 %d 个分类本轮抓空，沿用基线 %d 条，不计入变化"
                  % (section, len(set(failed_categories)), merged))
            items = merged_items
            cur["items"] = items

    # 空扫描：本轮一条都没采到而基线有数据 → 接口未返回，不是业务集体下架。
    # 不写快照、不改基线，等下一轮（写空快照会让下游整板块判成下架）。
    if prev_items and not items:
        print("  [空扫描] 板块 %s 本轮 0 条、基线 %d 条，保留旧快照" % (section, len(prev_items)))
        return None

    # 并集：源站只给子集时，用基线里仍在保留期内的条目补齐（同时按保留期/下线日期回收）
    items, held, dropped = union_with_baseline(section, prev_items, items)
    cur["items"] = items
    if held or dropped:
        print("  [并集] 板块 %s 本轮采到 %d 条，沿用基线 %d 条，回收 %d 条"
              % (section, len(items) - held, held, dropped))

    # 若旧快照格式与新数据不兼容（如升级前的字符串快照），先重建基线不通知。
    if old is not None and not _same_structure(prev_items, items):
        print(f"  [基线] 板块 {section} 快照格式已升级，重建基线不通知")
        save_snapshot(section, cur)
        return None
    # 字段结构升级（如新增采集字段）同样重建基线，避免一次性全量误报"修改"
    if old is not None and _structure_upgraded(prev_items, items):
        print(f"  [基线] 板块 {section} 快照字段结构升级，重建基线不通知")
        save_snapshot(section, cur)
        return None

    d = diff(prev_items, items)
    real_removed = d["removed"]

    # 抓取结果全部生效：不按下线/上线日期回退或改判任何条目
    has_change = bool(d["added"] or real_removed or d["modified"])
    report = {
        "section": section,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "added": d["added"],
        "removed": real_removed,
        "modified": d["modified"],
        "restored": [],
        "held": held,
        "keep_old": None if not old else old.get("timestamp"),
    }
    save_snapshot(section, cur)
    return report if has_change else None
