# -*- coding: utf-8 -*-
"""验证 dingtalk_summary 的同批变化只推一次（定时触发）。"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "data"))
cst = timezone(timedelta(hours=8))
ts = datetime.now(cst).strftime("%Y-%m-%d %H:%M:%S")
json.dump([{"ts": ts, "hunan": {"added": 3, "removed": 0, "modified": 0,
                                "added_names": ["A", "B", "C"]}}],
          open(os.path.join(tmp, "data", "history.json"), "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"updated": ts, "sections": []},
          open(os.path.join(tmp, "data", "latest.json"), "w", encoding="utf-8"), ensure_ascii=False)

os.environ["SITE_ROOT"] = tmp
os.environ["GITHUB_EVENT_NAME"] = "schedule"
os.environ["SINCE_HOURS"] = "24"
os.environ["DINGTALK_WEBHOOK"] = "https://example.invalid/hook"

import dingtalk_summary as ds  # noqa: E402

sent = []
ds.send_notify = lambda title, text: (sent.append(title), [("钉钉", True, "stub")])[1]

ds.main()
first = len(sent)
ds.main()
second = len(sent)

marks = json.load(open(os.path.join(tmp, "data", ".notify_marks.json"), encoding="utf-8"))
ok1 = first == 1
ok2 = second == 1                      # 第二次同批变化不再推送
ok3 = bool(marks.get("__summary_mark"))
print("首次推送次数=%d（期望 1）: %s" % (first, "PASS" if ok1 else "FAIL"))
print("重复运行推送次数=%d（期望仍为 1）: %s" % (second, "PASS" if ok2 else "FAIL"))
print("标记文件写入=%s: %s" % (ok3, "PASS" if ok3 else "FAIL"))
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if (ok1 and ok2 and ok3) else 1)
