#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按时间戳合并多份 history.json，只增不减。

用途：Actions 构建任务的推送重试路径。重试时会把本次构建产物重新铺到工作区，
而产物可能来自「任务启动时的旧代码」，直接 cp 会把线上已累积（或已从分片恢复）
的历史回退。这里以现有 history.json 为基准做并集，保证历史永不减少。

用法：
    python3 scripts/merge_history.py data/history.json /tmp/art/data/history.json
第一个参数是基准文件（存在则优先），其余为待并入文件；结果写回第一个参数。
"""
import json
import os
import sys


def load_records(path):
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[warn] 读取失败 {path}: {e}")
        return []


def merge(base_path, extra_paths):
    """以 base 为基准并入 extra，按 ts 升序写回 base；返回 (原数, 合并后)。"""
    merged = {}
    for r in load_records(base_path):
        if isinstance(r, dict) and r.get("ts"):
            merged[str(r["ts"])] = r
    base_n = len(merged)
    for p in extra_paths:
        for r in load_records(p):
            if isinstance(r, dict) and r.get("ts"):
                merged.setdefault(str(r["ts"]), r)
    out = sorted(merged.values(), key=lambda r: str(r.get("ts")))
    tmp = base_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, base_path)
    return base_n, len(out)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    base_n, total = merge(args[0], args[1:])
    print(f"history 并集: 基准 {base_n} 条 → 合并后 {total} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
