# -*- coding: utf-8 -*-
"""实弹复现：Agent 意图路由对"关键词式短输入"的行为"""
import json
import urllib.request

CASES = [
    ("报告", "银黄口服液", "2026-05"),
    ("银黄五月报告", None, None),
    ("五月报告", "银黄口服液", "2026-05"),
    ("银黄口服液 五月份 成本分析报告", None, None),
    ("生成报告", "银黄口服液", "2026-05"),
    ("对标", "银黄口服液", "2026-05"),
    ("整改", "银黄口服液", "2026-05"),
    ("看板", "银黄口服液", "2026-05"),
]

for text, p, m in CASES:
    body = {"text": text}
    if p:
        body["product"] = p
    if m:
        body["month"] = m
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8"))
        res = d.get("result") or {}
        kind = ("choices" if res.get("choices") else
                "clarify" if d.get("clarification") else
                "exec" if res.get("ok") else
                "err:" + str(res.get("error"))[:40] if res else "none")
        print(f"[{text}] -> intent={d.get('intent')} conf={d.get('confidence')} "
              f"layer={d.get('layer')} classifier={d.get('classifier')} => {kind}")
        if d.get("clarification"):
            print("   澄清:", d["clarification"][:60])
    except Exception as e:
        print(f"[{text}] -> 请求失败: {e}")
