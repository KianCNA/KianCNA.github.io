#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI 保护：自动化任务只允许提交数据产物，UI 文件一律还原。

定时抓取/构建任务会在 runner 上重铺产物、执行 reset --hard 后重试推送，
一旦某一步写到了界面文件，`git add -A` 就会把人工改过的页面/样式/版本号
一并提交上去，等于覆盖用户的 UI。这里在提交前把 UI 路径的改动全部还原，
配合工作流里的「只 add 数据路径」，双重保证自动化碰不到界面。

用法：python3 scripts/guard_ui.py
退出码恒为 0：保护动作失败也不阻塞数据发布，但会打印到 CI 日志。
"""
import subprocess
import sys

# 界面与前端资源：自动化不得修改。数据产物（data/、pipelines/mobile/snapshots/、
# tariff-fetch-source.zip）不在列表中，由各工作流显式 git add。
UI_PATHS = [
    "index.html",
    "nav.html",
    "push-center.html",
    "style.css",
    "app.js",
    "common-extras.js",
    "version.json",
    "manifest.json",
    "_headers",
    "logo.png",
    "icons",
    "unicom",
    "telecom",
    "gb",
    "apk",
]


def git(*args):
    return subprocess.run(["git"] + list(args), capture_output=True, text=True)


def main():
    st = git("status", "--porcelain", "--", *UI_PATHS)
    lines = [ln for ln in (st.stdout or "").splitlines() if ln.strip()]
    if not lines:
        print("[ui-guard] UI 文件无改动")
        return 0
    print("[ui-guard] 检测到 UI 文件被改动，已还原（自动化不允许覆盖界面）：")
    for ln in lines:
        print("  " + ln)
    # 只还原已跟踪文件的改动/删除；未跟踪的新文件不在此列（工作流的 git add 已限定路径）
    r = git("checkout", "--", *UI_PATHS)
    if r.returncode != 0:
        print("[ui-guard] 还原失败：" + ((r.stderr or "").strip() or "未知错误"))
    else:
        print(f"[ui-guard] 已还原 {len(lines)} 处改动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
