#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建站点数据：snapshots -> _site（供 GitHub Pages 展示）
由 build-site.yml 在云端 runner 上调用。
输入：
  snapshots/*.json（当前快照：quanguo + 任意省份，仓库 main 检出）
  _prev/*.json（上次快照副本，来自 gh-pages 分支 prev/ 目录，首次为空）
输出：
  _site/  静态站点内容（含 data/ 与 prev/）

板块由 snapshots/ 目录自动发现：quanguo 固定在前，其余省份按文件名排序；
省份显示名内置本文件，与抓取侧 province_table.section_name 保持一致。
"""
import collections
import datetime
import json
import os
import shutil
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, "snapshots")
PREV = os.path.join(ROOT, "_prev")
SITE = os.path.join(ROOT, "_site")
# 注：原 SITE_SRC（site/ 目录）已移除。
# site/ 是历史遗留的静态页面副本，内容比仓库根目录的 index.html 旧
# （例：根目录已修「变化历史里无变化板块不占位」，site/ 仍是旧逻辑）。
# 而 build 流程会把 site/ -> _site/ -> 覆盖根目录，等于每次构建都把修复回滚。
# 根目录文件才是Pages 部署源（source: main /），故不再从 site/ 复制。
DATA = os.path.join(SITE, "data")
PREV_OUT = os.path.join(SITE, "prev")
os.makedirs(DATA, exist_ok=True)
os.makedirs(PREV_OUT, exist_ok=True)

# 板块 -> 显示名（31 省 + 全网，与官网 tariffZonePers.js 代码表一致）
SECTION_NAMES = {
    "quanguo": "全网(全国)",
    "beijing": "北京", "tianjin": "天津", "hebei": "河北", "shanxi": "山西",
    "neimenggu": "内蒙古", "liaoning": "辽宁", "jilin": "吉林",
    "heilongjiang": "黑龙江", "shanghai": "上海", "jiangsu": "江苏",
    "zhejiang": "浙江", "anhui": "安徽", "fujian": "福建", "jiangxi": "江西",
    "shandong": "山东", "henan": "河南", "hubei": "湖北", "hunan": "湖南",
    "guangdong": "广东", "guangxi": "广西", "hainan": "海南", "chongqing": "重庆",
    "sichuan": "四川", "guizhou": "贵州", "yunnan": "云南", "xizang": "西藏",
    "shaanxi": "陕西", "gansu": "甘肃", "qinghai": "青海", "ningxia": "宁夏",
    "xinjiang": "新疆",
}

# 展示站默认选中的省份（前端记忆用户选择，首次访问用此值）
DEFAULT_PROV = "beijing"


def sec_name(sec):
    return SECTION_NAMES.get(sec, sec)


def all_sections():
    """发现 snapshots/ 下所有板块（quanguo 排最前，其余按 SECTION_NAMES 声明排序）。"""
    secs = []
    if os.path.isdir(SNAP):
        for fn in sorted(os.listdir(SNAP)):
            if fn.endswith(".json") and os.path.isfile(os.path.join(SNAP, fn)):
                sec = fn[:-5]
                if sec in SECTION_NAMES:
                    secs.append(sec)
    if "quanguo" in secs:
        secs.remove("quanguo")
        secs = ["quanguo"] + secs
    return secs


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def clean_html(v):
    """展示层归一化：剥离源站字段里混入的 HTML 标签与实体。

    源站约 2026-09-29 起把「其他服务内容」「其他说明」等字段改成了富文本
    （带 <p>…</p> 包裹）。标签本身不是业务变化，直接展示会让修改前后
    看起来满屏 <p>，且 <p>-</p> 与 - 会被误判成一处改动。
    """
    x = "" if v is None else str(v)
    x = re.sub(r"<br\s*/?>", " ", x, flags=re.I)
    x = re.sub(r"</?p[^>]*>", " ", x, flags=re.I)
    x = re.sub(r"<[^>]*>", "", x)
    x = re.sub(r"&(?:nbsp|amp|lt|gt|quot|#39);", " ", x, flags=re.I)
    return re.sub(r"\s+", " ", x).strip()


def clean_fields(fields):
    """对一整份字段快照做展示层清洗（值不变则原样返回）。"""
    if not isinstance(fields, dict):
        return fields
    return {k: clean_html(v) if isinstance(v, str) else v
            for k, v in fields.items()}


_HIST_DET_KEYS = ("added_details", "removed_details", "modified_details",
                  "modified_before", "modified_after", "restored_details")


def _hist_ts_file(ts):
    """时间戳 -> 安全文件名：2026-10-01 14:36:52 -> 2026-10-01-14-36-52.json"""
    return re.sub(r"[^0-9A-Za-z]", "-", str(ts)) + ".json"


def _write_history_split(data_dir, history):
    """写摘要 history.json + 每条记录一个详情分片 data/hist/<ts>.json。

    摘要只保留计数与业务名（前端列表渲染用），体积约为整份的 4%；
    详情（字段快照/差异明细）在用户点开某条记录时才按 ts 拉取。
    """
    hist_dir = os.path.join(data_dir, "hist")
    os.makedirs(hist_dir, exist_ok=True)
    keep = set()
    slim_all = []
    for rec in (history or []):
        ts = rec.get("ts")
        if not ts:
            continue
        slim = {"ts": ts}
        if rec.get("recovered"):
            # 恢复自 hist 分片的历史记录：字段明细在分片里，靠该标记避开误报清理
            slim["recovered"] = True
        det = {}
        for sec, blk in rec.items():
            if sec == "ts" or not isinstance(blk, dict):
                continue
            s2, d2 = {}, {}
            for k, v in blk.items():
                if k in _HIST_DET_KEYS:
                    if v:
                        d2[k] = v
                else:
                    s2[k] = v
            slim[sec] = s2
            if d2:
                det[sec] = d2
        slim_all.append(slim)
        keep.add(_hist_ts_file(ts))
        if det:
            p = os.path.join(hist_dir, _hist_ts_file(ts))
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(det, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, p)
        # 摘要
    tmp_h = os.path.join(data_dir, "history.json.tmp")
    with open(tmp_h, "w", encoding="utf-8") as f:
        json.dump(slim_all, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_h, os.path.join(data_dir, "history.json"))
    # 清理已不在历史里的旧分片，避免仓库无限膨胀
    try:
        for fn in os.listdir(hist_dir):
            if fn not in keep:
                os.remove(os.path.join(hist_dir, fn))
    except Exception:
        pass
    sz = os.path.getsize(os.path.join(data_dir, "history.json"))
    print("  history 摘要 %.2f MB（详情分片按需加载）" % (sz / 1048576.0))
    return sz


def _q_price(fields):
    m = re.search(r"(\d+(?:\.\d+)?)\s*元", str(fields.get("资费标准") or ""))
    return float(m.group(1)) if m else None


def _q_date(fields):
    s = str(fields.get("上线日期") or "")
    m = re.search(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", s)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return s[:10]


def _qid(code, name, used):
    """详情分片文件名：优先用方案编号，非法字符、重号时追加序号。"""
    base = re.sub(r"[^0-9A-Za-z_-]+", "-", str(code or "").strip()).strip("-")
    if not base:
        base = re.sub(r"[^0-9A-Za-z_-]+", "-", name).strip("-")[:24] or "item"
    stem, n = base, 2
    while stem in used:
        stem = "%s~%d" % (base, n)
        n += 1
    used.add(stem)
    return stem


def _write_quanguo_index(data_dir, quanguo_json, items):
    """全国资费拆成轻量索引 + 每条业务一个详情分片。

    全国板块近三千条、整份 4MB，移动端要下完整份才能渲染列表。
    改为：data/qindex.json 只带列表与筛选要用的短字段（名称/方案编号/归属/
    类型/价格/上线日期/分片文件名），data/qd/<方案编号>.json 才是完整字段，
    用户点开某条时才拉取。
    """
    if not items:
        print("  [qindex] 本轮无全国数据，跳过索引生成")
        return
    qd_dir = os.path.join(data_dir, "qd")
    os.makedirs(qd_dir, exist_ok=True)
    used, keep, rows = set(), set(), []
    for it in items:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        fields = clean_fields(it.get("fields") or {})
        code = str(fields.get("方案编号") or "").strip()
        stem = _qid(code, name, used)
        fn = stem + ".json"
        keep.add(fn)
        p = os.path.join(qd_dir, fn)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"name": name, "fields": fields}, f, ensure_ascii=False,
                      separators=(",", ":"))
        os.replace(p + ".tmp", p)
        rows.append([name, code, fields.get("归属") or "", fields.get("资费类型") or "",
                     _q_price(fields), _q_date(fields), stem])
    idx = {"u": (quanguo_json or {}).get("timestamp") or "", "n": len(rows), "items": rows}
    tmp = os.path.join(data_dir, "qindex.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(data_dir, "qindex.json"))
    # 清理已下架/改号留下旧分片，避免仓库无限膨胀（与 hist 分片同一策略）
    for fn in os.listdir(qd_dir):
        if fn.endswith(".json") and fn not in keep:
            try:
                os.remove(os.path.join(qd_dir, fn))
            except OSError:
                pass
    print("  qindex %d 条 / %.0f KB，详情分片 %d 个" % (
        len(rows), os.path.getsize(os.path.join(data_dir, "qindex.json")) / 1024.0, len(keep)))


def name_of(item):
    return (item.get("name") or "").strip()


def _norm_val(v):
    """归一化字段值：剥离源站混入的 HTML 标签与多余空白。

    不处理的话，纯 <p></p> / 换行 之类的变化也会被记为「修改」，
    前端展示时修改前后看起来一模一样，用户无法判断到底改了什么。
    """
    import re as _re
    x = "" if v is None else str(v)
    x = _re.sub(r"<br\s*/?>", " ", x, flags=_re.I)
    x = _re.sub(r"</?p[^>]*>", " ", x, flags=_re.I)
    x = _re.sub(r"<[^>]*>", "", x)
    x = _re.sub(r"&(?:nbsp|amp|lt|gt|quot|#39);", " ", x, flags=_re.I)
    return _re.sub(r"\s+", " ", x).strip()


def field_diff(old, new):
    """字段级修改明细：对比两个业务条目的 fields 字典，返回 [{field, from, to}, ...]。"""
    def fields_of(item):
        f = item.get("fields") if isinstance(item, dict) else None
        return f if isinstance(f, dict) else {}
    of, nf = fields_of(old), fields_of(new)
    keys = list(of.keys())
    for k in nf:
        if k not in keys:
            keys.append(k)
    out = []
    for k in keys:
        ov, nv = of.get(k), nf.get(k)
        os_ = _norm_val(ov)
        ns_ = _norm_val(nv)
        if os_ != ns_:
            out.append({"field": k, "from": os_, "to": ns_})
    return out


def _clip_fields(fields, limit=300):
    """截断字段值中的超长文本，避免历史文件被个别长描述撑爆。"""
    out = {}
    for k, v in (fields or {}).items():
        if isinstance(v, str) and len(v) > limit:
            out[k] = v[:limit] + "…"
        else:
            out[k] = v
    return out



_PLAN_CODE_KEYS = ("方案编号", "productCode", "goodsCode", "businessCode", "业务编码", "编码")


def _item_plan_code(item):
    """取条目的方案编号（业务的稳定标识），用于改名后仍能配对。"""
    f = (item or {}).get("fields") or {}
    for k in _PLAN_CODE_KEYS:
        v = str(f.get(k) or "").strip()
        if v:
            return v
    return ""


def _norm_match_key(item):
    """配对用归一化名：剥离年份后缀与 A/B/C 版等版本号。

    源站会批量给存量业务改名（加「2026」「A版」），按原名求差会把同一业务
    拆成「删除+新增」两条假变化。归一化后能唯一匹配即视为同一业务。
    """
    n = str(name_of(item) or "")
    n = re.sub(r"\s+", "", n)
    n = re.sub(r"(?:20\d{2})(?:版|年)", "", n)
    n = re.sub(r"[（(]?[A-Za-z]{1,2}版[)）]?", "", n)
    n = re.sub(r"[（(]?[Vv]\d+[)）]?", "", n)
    return n


def _core_overlap(a, b):
    """去掉括号内容与数字后的字符重合度（Jaccard）。

    用于拦截「方案编号相同但确属不同业务」的误配，
    例如「咪咕悦看流量合约（24个月）」与「咪咕短剧加油包（24个月）」。
    """
    import re as _re
    def core(t):
        t = _re.sub(r"[\uff08\(][^\uff09\)]*[\uff09\)]", "", str(t or ""))
        t = _re.sub(r"[0-9A-Za-z]+", "", t)
        return set(t.replace(" ", ""))
    A, B = core(a), core(b)
    if not A or not B:
        return 0.0
    return len(A & B) / float(len(A | B))


def _pair_renamed(added, removed):
    """把「改名/改编号」造成的 删除+新增 配对起来。

    返回 (pairs, added_left, removed_left)；pairs 为 [(old_item, new_item), ...]。
    仅在归一化名/方案编号于两侧都唯一时才配对，避免张冠李戴。
    """
    def groups(items, keyfn):
        g = {}
        for i, it in enumerate(items):
            k = keyfn(it)
            if k:
                g.setdefault(k, []).append(i)
        return g

    ga_code, gr_code = groups(added, _item_plan_code), groups(removed, _item_plan_code)
    ga_name, gr_name = groups(added, _norm_match_key), groups(removed, _norm_match_key)
    used_a, used_r, pairs = set(), set(), []
    # 方案编号是业务的稳定标识，优先用它配对
    for chan, (ga, gr) in enumerate(((ga_code, gr_code), (ga_name, gr_name))):
        for k in set(ga) & set(gr):
            if len(ga[k]) != 1 or len(gr[k]) != 1:
                continue
            ai, ri = ga[k][0], gr[k][0]
            if ai in used_a or ri in used_r:
                continue
            # 方案编号通道：编号相同但名称核心词几乎不重合 → 判为不同业务，不配对
            if chan == 0 and _core_overlap(name_of(added[ai]), name_of(removed[ri])) < 0.5:
                continue
            pairs.append((removed[ri], added[ai]))
            used_a.add(ai)
            used_r.add(ri)
    return (pairs,
            [x for i, x in enumerate(added) if i not in used_a],
            [x for i, x in enumerate(removed) if i not in used_r])


def _field_noise(old_items, new_items):
    """原名相同但内容有差异的条目数（字段口径升级时的噪音 modified 量）。"""
    om = {name_of(i): i for i in (old_items or [])}
    nm = {name_of(i): i for i in (new_items or [])}
    return [k for k in om if k in nm and om[k] != nm[k]]


def pair_renamed_only(old_items, new_items):
    """只做改名/改编号配对，不做字段比对。用于字段结构升级场景——
    此时字段差异全是噪音，但改名是真实变化，必须保留。"""
    om = {name_of(i): i for i in (old_items or [])}
    nm = {name_of(i): i for i in (new_items or [])}
    _a = [nm[k] for k in nm if k not in om]
    _r = [om[k] for k in om if k not in nm]
    pairs, added, removed = _pair_renamed(_a, _r)
    modified, details, before, after = [], {}, {}, {}
    for oi, ni in pairs:
        on, nn = name_of(oi), name_of(ni)
        det = field_diff(oi, ni)
        if on != nn:
            det = [{"field": "业务名称", "from": on, "to": nn}] + det
        else:
            # 名称相同且归一化后无真实字段差异 → 仅序列化差异造成的假配对，跳过
            if not det:
                continue
        modified.append(ni)
        details[nn] = det
        before[nn] = _clip_fields(oi.get("fields") or {})
        after[nn] = _clip_fields(ni.get("fields") or {})
    return added, removed, modified, details, before, after


def diff_items(old_items, new_items):
    """返回 (新增, 下架, 修改, 修改明细 name->[{field,from,to}],
             修改前快照 name->fields, 修改后快照 name->fields)。以名称为 key。

    除了字段级差异明细，还保留修改前后的**完整字段快照**，供前端并排对比
    —— 只看差异片段无法判断改动落在哪个业务上下文里（用户明确要求）。
    """
    om = {name_of(i): i for i in (old_items or [])}
    nm = {name_of(i): i for i in (new_items or [])}
    added = [nm[k] for k in nm if k not in om]
    removed = [om[k] for k in om if k not in nm]
    modified = []
    modified_details = {}
    mod_before, mod_after = {}, {}
    for k in om:
        if k in nm and om[k] != nm[k]:
            # 修正 A：同名但「方案编号」不同 → 是不同版本/不同业务，不判 modified。
            # 方案编号是业务稳定标识。源站常把同名套餐拆成「套餐版」与「加装包版」
            # 两个编号，且每轮抓取随机返回其一（山西 6 条：铂金会员流量版等，
            # 在 25SX202194↔25SX202467 之间震荡），导致每轮都被判 modified，
            # 推送反复重复粘贴。编号不同即视为不同业务，跳过。
            if _item_plan_code(om[k]) and _item_plan_code(nm[k]) \
               and _item_plan_code(om[k]) != _item_plan_code(nm[k]):
                continue
            # 修正 B：原始 dict 不等（字段顺序 / HTML / 空白等序列化差异）但
            # 字段内容经 _norm_val 归一化后完全相同的条目，是「假修改」，
            # 不该计入 modified。
            det = field_diff(om[k], nm[k])
            if not det:
                continue   # 归一化后无任何真实字段差异 → 跳过，不误报
            modified.append(om[k])
            modified_details[k] = det
            mod_before[k] = _clip_fields(om[k].get("fields") or {})
            mod_after[k] = _clip_fields(nm[k].get("fields") or {})
    # 改名/改编号配对：源站会批量给存量业务加年份后缀或版本号
    # （「优享畅享59元折扣」→「优享畅享59元折扣2026」、
    #   「全家享99元（…）」→「全家享99元A版（…）」），按名求差会把同一业务
    # 拆成「删除+新增」两条假变化，归一化后唯一匹配即判为 modified。
    pairs, added, removed = _pair_renamed(added, removed)
    for oi, ni in pairs:
        on, nn = name_of(oi), name_of(ni)
        det = field_diff(oi, ni)
        if on != nn:
            det = [{"field": "业务名称", "from": on, "to": nn}] + det
        modified.append(ni)
        modified_details[nn] = det
        mod_before[nn] = _clip_fields(oi.get("fields") or {})
        mod_after[nn] = _clip_fields(ni.get("fields") or {})
    return added, removed, modified, modified_details, mod_before, mod_after


def _field_keys(items):
    """取快照条目统一的字段键集合；无结构字段时返回 None。"""
    for it in (items or []):
        f = it.get("fields") if isinstance(it, dict) else None
        if isinstance(f, dict):
            return tuple(sorted(f.keys()))
    return None


def _structure_upgraded(old_items, new_items):
    """新旧快照字段结构是否不一致（如字段集新增/删减），是则视为格式升级。"""
    ok, nk = _field_keys(old_items), _field_keys(new_items)
    return ok is not None and nk is not None and ok != nk


def clean_upgrade_false_records(history, st):
    """剔除字段结构升级造成的全量误报记录：
    某条记录里某板块 modified 数量 >= 该板块业务总量的 90%，几乎不可能真实发生，
    判定为新增字段（如"其他说明"）升级时快照整体 diff 产生的假数据，予以清理。"""
    cleaned = []
    for rec0 in history:
        if not isinstance(rec0, dict) or rec0.get("recovered"):
            # recovered：从 data/hist 分片恢复的历史记录，字段明细在分片里而非摘要里
            cleaned.append(rec0)
            continue
        suspicious = False
        for sec, d in rec0.items():
            if sec == "ts" or not isinstance(d, dict) or d.get("note") == "baseline":
                continue
            mod = d.get("modified") or 0
            total = len(st[sec][1]) if sec in st else 0
            if total and mod >= total * 0.9:
                suspicious = True
                break
        if not suspicious:
            cleaned.append(rec0)
    return cleaned


def clean_shell_modified_records(history):
    """剔除「空壳 modified」误报：逐板块归零，不删除整条记录。

    某板块 modified>0 但没有任何字段级明细（modified_details /
    modified_before / modified_after 全空/缺失）时，说明它只是「原始
    dict 不等但归一化后内容相同」的序列化差异造成的假变化，并非真实
    资费修改。真实修改必然伴随字段级明细快照：modified_details 限量
    500 条、before/after 限量 60 条，被截断时也只是变短、不会为空，
    故「modified>0 但三者全空」可安全判定为空壳误报。

    典型：山西 6 条固定套餐（铂金会员流量版等）每轮被记 modified=6
    却无任何明细，推送里反复重复粘贴；西藏等省也偶发同类空壳。

    只对该板块归零 modified（含 modified_names），added/removed 属
    真实变化、独立保留；不删除整条记录，其它板块不受影响。
    """
    cleaned = []
    for rec0 in history:
        if not isinstance(rec0, dict) or rec0.get("recovered"):
            cleaned.append(rec0)
            continue
        rec = dict(rec0)          # 浅拷贝，避免污染上游 history
        for sec, d in rec0.items():
            if sec == "ts" or not isinstance(d, dict):
                continue
            mod = d.get("modified") or 0
            if mod <= 0:
                continue
            has_detail = bool(d.get("modified_details")) or \
                         bool(d.get("modified_before")) or \
                         bool(d.get("modified_after"))
            if not has_detail:
                # 空壳：仅序列化差异，无字段级明细 → 归零 modified
                rec[sec] = {**d, "modified": 0, "modified_names": []}
        cleaned.append(rec)
    return cleaned


def same_change(a, b):
    """判断两条历史记录的业务变更是否等效（忽略 ts 与字段级明细），用于防止重复记录。"""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    keys = set(a) | set(b)
    for k in keys:
        if k == "ts":
            continue
        av, bv = a.get(k), b.get(k)
        if isinstance(av, dict) and isinstance(bv, dict):
            if av.get("note") or bv.get("note"):
                if av.get("note") != bv.get("note"):
                    return False
                continue
            for sk in ("added", "removed", "modified", "added_names", "removed_names", "modified_names"):
                if av.get(sk) != bv.get(sk):
                    return False
        elif av != bv:
            return False
    return True


# 板块条数骤降阈值已取消：抓取结果一律如实入库（有什么就是有什么）。


def is_reverse_change(a, b):
    """判断两条记录是否互为「反向抖动」。

    典型症状：上一轮记 add=14，本轮记 rm=14（同一批业务）；字段级修改的
    from/to 也整体互换。这不是真实业务变化，而是基线/源站在两个状态间回弹
    （prev 基线未落地、或源站返回了上一版数据）造成的假变化。
    逐板块判定：任一方向相反即视为抖动。
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    flipped = 0
    checked = 0
    for sec in set(a) | set(b):
        if sec == "ts":
            continue
        av, bv = a.get(sec), b.get(sec)
        if not isinstance(av, dict) or not isinstance(bv, dict):
            continue
        if av.get("note") or bv.get("note"):
            continue
        a_add, a_rm = av.get("added", 0), av.get("removed", 0)
        b_add, b_rm = bv.get("added", 0), bv.get("removed", 0)
        # 只有存在实际增删时才判定（纯 modified 不算反向增删）
        if a_add + a_rm > 0 or b_add + b_rm > 0:
            checked += 1
            if a_add == b_rm and a_rm == b_add and (a_add + a_rm) > 0:
                flipped += 1
    if not checked:
        return False
    # 过半板块出现「增删互换」→ 判定为整体回弹
    return flipped > 0 and flipped >= checked * 0.6


def stat_section(sec, base=None):
    j = load(os.path.join(base or SNAP, sec + ".json"))
    items = (j or {}).get("items") or []
    dist = collections.defaultdict(collections.Counter)
    for it in items:
        f = it.get("fields") or {}
        own = f.get("归属") or "未知"
        t = f.get("资费类型") or "未知"
        dist[own][t] += 1
    return j, items, dict(dist)


def union_prov_dist(st, sections):
    """31 省专区并集（不含全网），按业务名去重，返回 (条数, 归属x类型分布)"""
    names = {}
    for sec in sections:
        if sec == "quanguo":
            continue
        items = st[sec][1]
        for it in items:
            n = (it.get("name") or "").strip()
            if n:
                names.setdefault(n, it)
    d = collections.defaultdict(collections.Counter)
    for it in names.values():
        f = it.get("fields") or {}
        own = f.get("归属") or "未知"
        t = f.get("资费类型") or "未知"
        d[own][t] += 1
    return len(names), dict(d)


def prov_stats_map(st, sections):
    """每省资费统计（总数 / 个人 / 政企 / 归属x类型分布），供总览页省份切换秒级联动"""
    out = {}
    for sec in sections:
        if sec == "quanguo":
            continue
        _j, items, dist = st[sec]
        personal = sum((dist.get("个人资费") or {}).values())
        gq = sum((dist.get("政企资费") or {}).values())
        out[sec] = {"total": len(items), "personal": personal, "gq": gq, "dist": dist}
    return out


def main():
    now = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=8))
    ).strftime("%Y-%m-%d %H:%M:%S")
    sections = all_sections()
    if not sections:
        sections = ["quanguo"]

    # 0) 静态页面不再从 site/ 复制（见文件顶部说明）：
    #    根目录 index.html 即部署源，由 git 直接维护，
    #    避免旧副本在每次构建时把它们覆盖回去。

    # 1) 复制当前快照到站点 data/
    st = {}   # section -> (json, items, dist)
    kept_prev = set()   # 本轮因抓取缺失而保留线上数据的板块（不回写基线）
    for sec in sections:
        src = os.path.join(SNAP, sec + ".json")
        old_src = os.path.join(PREV, sec + ".json")
        new_j = load(src) if os.path.exists(src) else None
        old_j = load(old_src)

        # 空扫描保护：本轮快照 0 条、基线却有数据，说明这个接口本轮没返回，
        # 而不是业务集体下架。保留线上数据与基线，否则会把整板块记成下架，
        # 下一轮接口恢复再整批记成新增（历史里河南、江西、河北、山西都跳变过）。
        _new_items = (new_j or {}).get("items") or []
        _old_items = (old_j or {}).get("items") or []
        if old_j and _old_items and not _new_items:
            shutil.copy(old_src, os.path.join(DATA, sec + ".json"))
            st[sec] = stat_section(sec, PREV)
            kept_prev.add(sec)
            print(f"  [空扫描] 板块 {sec} 本轮 0 条、基线 {len(_old_items)} 条，"
                  f"保留线上数据，本轮不比对")
            continue

        # 时间倒退保护：snapshots/ 是持久目录，focus 模式下未重抓的省份会一直
        # 停留在旧快照。拿它当本轮数据会造成双重破坏：
        #   ① 线上 data/<sec>.json 被回退到旧版本（用户看到过期数据）
        #   ② 旧快照独有的业务被当成「本轮新增」→ 凭空虚报上千条
        # 实测 2026-10-11 notify 那轮因此把安徽等 31 省回退到 09-12 数据，
        # 并虚报 3177 条新增。故快照时间早于基线时一律保留线上数据。
        _nts = (new_j or {}).get("timestamp") or ""
        _ots = (old_j or {}).get("timestamp") or ""
        if new_j and old_j and _nts and _ots and _nts < _ots:
            shutil.copy(old_src, os.path.join(DATA, sec + ".json"))
            st[sec] = stat_section(sec, PREV)
            print(f"  [过期快照] 板块 {sec} 快照 {_nts} 早于基线 {_ots}，"
                  f"保留线上数据，本轮不比对")
            continue

        # 抓取结果如实入库：本轮抓到多少就写多少，不再按条数比例保留旧数据。
        # 条数骤减可能是源站限流，但也可能是真实批量下架，一律以抓到的为准。
        if new_j is not None and os.path.exists(src):
            shutil.copy(src, os.path.join(DATA, sec + ".json"))
        st[sec] = stat_section(sec)

    # 2) latest.json（仪表盘统计：sections 索引 + 全网/31省/各省分布）
    def_sec = DEFAULT_PROV if DEFAULT_PROV in sections else (sections[0] if sections else "quanguo")
    updated = ""
    for sec in sections:
        j = st[sec][0]
        ts = (j or {}).get("timestamp") or ""
        if ts > updated:
            updated = ts
    prov_total, prov_dist = union_prov_dist(st, sections)
    latest = {
        "updated": updated or now,
        "default": def_sec,
        "sections": [
            {
                "section": sec,
                "name": sec_name(sec),
                "total": len(st[sec][1]),
                "updated": (st[sec][0] or {}).get("timestamp") or "",
            }
            for sec in sections
        ],
        "quanguo_total": len(st.get("quanguo", (None, [], {}))[1]),
        "prov_total": prov_total,                 # 31省专区去重合计（不含全网）
        "prov_dist": prov_dist,                   # 31省去重后的归属x类型分布
        "prov_stats": prov_stats_map(st, sections),  # 每省统计，供总览页省份切换联动
        "hunan_total": len(st.get(def_sec, (None, [], {}))[1]),
        "dist": st.get("quanguo", (None, [], {}))[2],
        "def_dist": dict(st.get(def_sec, (None, [], {}))[2].get("个人资费", {})),
    }
    with open(os.path.join(DATA, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    # 2.5) 全国资费轻量索引 + 逐条详情分片（列表只下索引，点开某条才拉详情）
    if "quanguo" in st:
        _write_quanguo_index(DATA, st["quanguo"][0], st["quanguo"][1])

    # 3) 变化历史：逐板块对比上次快照副本（_prev/），rec 含全部板块变更 + 字段级修改明细
    history = load(os.path.join(PREV, "history.json")) or []
    # 清理历史上因字段结构升级产生的全量误报记录（如采集字段新增"其他说明"时全量 modified）
    _pre_clean = len(history)
    history = clean_upgrade_false_records(history, st)
    if len(history) != _pre_clean:
        print(f"[清理] 剔除 {_pre_clean - len(history)} 条字段升级误报历史记录")
    # 清理「空壳 modified」误报记录：某板块 modified>0 但无任何字段级明细
    # （modified_details / modified_before / modified_after 全空）。真实修改必有明细；
    # 只有序列化差异（字段顺序 / HTML / 空白）才会产生这种「有数字没内容」的空壳。
    # 曾导致山西 6 条固定套餐每轮被记 modified=6，推送反复重复粘贴。
    _pre_shell = len(history)
    history = clean_shell_modified_records(history)
    if len(history) != _pre_shell:
        print(f"[清理] 剔除 {_pre_shell - len(history)} 条空壳 modified 误报记录")
    rec = {"ts": now}
    has_change = False
    diff_details = {}   # sec -> {name: [{field,from,to}, ...]} 供回填旧记录
    for sec in sections:
        j, items, _dist = st[sec]
        old = load(os.path.join(PREV, sec + ".json"))
        old_items = (old or {}).get("items") if old else None
        if old_items is None:
            rec[sec] = {"note": "baseline"}
            continue
        # 字段结构升级检测：旧/新快照字段键集合不一致（如新增「短信」字段）时，
        # 逐条比对会把存量条目全判成 modified——新字段在旧侧为空，属误报。
        # 但 added/removed 以业务名为 key 求差集，与字段结构无关，是真实变化。
        # ★ 曾因这里直接重建基线，把「全民百G礼包网龄版」5 个真新增一并吞掉，
        #   故改为只抑制 modified，保留 added/removed。
        if _structure_upgraded(old_items, items):
            # 字段结构升级时只抑制「字段口径变化」造成的噪音 modified；
            # 改名配对与新增/下架照实记录，不按日期改判。
            _a, _r, _m, _md, _mb, _ma = pair_renamed_only(old_items, items)
            _noise = len(_field_noise(old_items, items))
            print(f"  [升级] 板块 {sec} 字段结构变化：抑制 {_noise} 条字段噪音 modified，"
                  f"保留改名 {len(_m)} / 新增 {len(_a)} / 下架 {len(_r)}")
            if _a or _r or _m:
                has_change = True
                rec[sec] = {
                    "added": len(_a),
                    "removed": len(_r),
                    "modified": len(_m),
                    "added_names": [name_of(x) for x in _a],
                    "removed_names": [name_of(x) for x in _r],
                    "modified_names": [name_of(x) for x in _m],
                    "note": "structure_upgraded",
                }
                if _a:
                    rec[sec]["added_details"] = {
                        name_of(x): clean_fields(x.get("fields") or {}) for x in _a
                    }
                if _r:
                    rec[sec]["removed_details"] = {
                        name_of(x): clean_fields(x.get("fields") or {}) for x in _r
                    }
                if _m:
                    rec[sec]["modified_details"] = _md
                    rec[sec]["modified_before"] = _mb
                    rec[sec]["modified_after"] = _ma
            else:
                rec[sec] = {"note": "baseline"}
            continue
        added, removed, modified, modified_details, mod_before, mod_after = diff_items(old_items, items)
        # 抓取结果全部生效：不按下线/上线日期回退或改判任何条目
        if added or removed or modified:
            has_change = True
        rec[sec] = {
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
            "added_names": [name_of(a) for a in added],
            "removed_names": [name_of(r) for r in removed],
            "modified_names": [name_of(m) for m in modified],
        }
        if added:
            rec[sec]["added_details"] = {
                name_of(a): clean_fields(a.get("fields") or {}) for a in added
            }
        if removed:
            rec[sec]["removed_details"] = {
                name_of(r): clean_fields(r.get("fields") or {}) for r in removed
            }
        if modified_details:
            diff_details[sec] = modified_details
            # 字段级修改明细量可能极大（一次大调整数百条），完整保留会让 history 膨胀；
            # names 已全量展示，details 保留合理上限即可（默认 500，可用环境变量覆盖）。
            MDET_LIMIT = int(os.getenv("MODIFIED_DETAILS_LIMIT") or "500")
            rec[sec]["modified_details"] = dict(list(modified_details.items())[:MDET_LIMIT])
            # 修改前后完整字段快照（供前端并排对比），同样限量防止膨胀
            MSNAP_LIMIT = int(os.getenv("MODIFIED_SNAPSHOT_LIMIT") or "60")
            rec[sec]["modified_before"] = {
                k: clean_fields(v) for k, v in list(mod_before.items())[:MSNAP_LIMIT]
            }
            rec[sec]["modified_after"] = {
                k: clean_fields(v) for k, v in list(mod_after.items())[:MSNAP_LIMIT]
            }

    # 回填历史记录中缺失的字段级修改明细（当日志只有名称列表、无 detail 时，用本次 diff 补齐）
    for rec0 in history:
        for sec in sections:
            d = rec0.get(sec)
            if not isinstance(d, dict) or d.get("note") == "baseline":
                continue
            if d.get("modified") and not d.get("modified_details"):
                md = diff_details.get(sec) or {}
                fill = {n: md[n] for n in (d.get("modified_names") or []) if n in md}
                if fill:
                    d["modified_details"] = fill

    # 等效变更去重：本次变更与上一条完全相同（prev 基线未更新时）不重复记录
    if has_change and history and is_reverse_change(history[-1], rec):
        # 与上一条完全反向 → 基线回弹产生的假变化，丢弃且不更新历史
        print("  !! 检测到与上一条反向的抖动变化（基线回弹），本轮不记录")
        has_change = False

    if has_change and not (history and same_change(history[-1], rec)):
        history.append(rec)
    # history.json 只写摘要，详情拆到 data/hist/<ts>.json 按需加载。
    # 原来单文件 15MB，前端一次性下载 + 解析导致「变化历史」打开卡十几分钟。
    _write_history_split(DATA, history)

    # 4) 保存本次快照副本到站点 prev/（下次 diff 用）
    for sec in sections:
        if sec in kept_prev:
            # 本轮抓取缺失：基线原样带过去，否则下一轮没有基线可对、或拿空快照做 diff
            old_src = os.path.join(PREV, sec + ".json")
            if os.path.exists(old_src):
                shutil.copy(old_src, os.path.join(PREV_OUT, sec + ".json"))
            continue
        src = os.path.join(SNAP, sec + ".json")
        if os.path.exists(src):
            shutil.copy(src, os.path.join(PREV_OUT, sec + ".json"))
    shutil.copy(os.path.join(DATA, "history.json"), os.path.join(PREV_OUT, "history.json"))

    print("site built:", json.dumps({
        "sections": [sec_name(s) for s in sections],
        "updated": latest["updated"],
        "quanguo_total": latest["quanguo_total"],
        "prov_total": latest["prov_total"],
        "default": sec_name(def_sec),
        "default_total": latest["hunan_total"],
        "history_records": len(history),
        "this_change": has_change,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
