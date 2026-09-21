"""Agent 意图路由 · DeepSeek 实弹（阶段2 出口标准）：LLM 主线真实分类。

加载 .env（不入库）→ LLMClient(role="classification")（无 LLM_SMALL_* 时
回退主模型并如实标注 main-model-fallback）→ 三个真实用户句式路由 →
断言意图正确、layer=llm、Pipeline 场景真实执行。

用法：python scripts/agent_live_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 极简 .env 加载（与 live_llm_check 同款）
env = ROOT / ".env"
for line in env.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        import os
        os.environ.setdefault(k.strip(), v.strip())

from app.agent import route                      # noqa: E402
from app.charts import ChartBuilder              # noqa: E402
from app.compute import CostCalculator           # noqa: E402
from app.ingest import init_store                # noqa: E402
from app.llm import LLMClient                    # noqa: E402
from app.pipeline import Deps, Pipeline          # noqa: E402

CASES = [
    ("帮我把银黄口服液五月份的报告出了", "report", {"product": "银黄口服液", "month": "2026-05"}),
    ("六味地黄丸...哦不，六味地黄胶囊上个月看板给我看看", "dashboard",
     {"product": "六味地黄胶囊", "month": "2026-05"}),
    ("板蓝根颗粒 5 月跟二厂比怎么样", "benchmark", {"product": "板蓝根颗粒", "month": "2026-05"}),
    ("今天天气怎么样", None, None),   # 四入口路径
]


def main() -> int:
    store, _ = init_store()
    calc = CostCalculator(store)
    pipe = Pipeline(Deps(calc=calc, charts=ChartBuilder(calc)))
    llm = LLMClient(role="classification")
    print(f"[实弹] 分类器: {llm.role_actual}（{llm.model}）")

    for text, want_intent, want_params in CASES:
        out = route(text, pipe, llm=llm)
        print(f"[实弹] {text!r} → intent={out['intent']} conf={out['confidence']} "
              f"layer={out['layer']} params={out['params']}")
        if want_intent is None:
            assert out["result"] and "choices" in out["result"], out
            continue
        assert out["intent"] == want_intent and out["layer"] == "llm", out
        assert out["params"] == want_params, out
        assert out["result"]["ok"] is True, out
    print("\n===== Agent 实弹通过：LLM 主线分类 + 参数抽取 + 场景执行 + 四入口 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
