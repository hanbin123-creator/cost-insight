"""真实 LLM 实弹联调（DeepSeek）：板块2 归因 + 板块3 报告六段。

用法：python scripts/live_llm_check.py
读取项目根 .env（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL），key 不打印不落日志。
观察指标：冒烟连通 / verdict 分布（pass·auto_fixed·rejected）/ 重试收敛 / 实产文本质量。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---- .env 极简加载（不引第三方依赖；key=value，忽略注释与空行） ----
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from app.compute import CostCalculator          # noqa: E402
from app.generate import generate_attribution   # noqa: E402
from app.ingest import init_store               # noqa: E402
from app.llm import LLMClient                   # noqa: E402
from app.report_gen import generate_report_sections  # noqa: E402
from app.retrieve import Retriever              # noqa: E402

PRODUCT, MONTH = "银黄口服液", "2026-05"


def main() -> None:
    llm = LLMClient()  # 配置缺失会在此响亮报错
    model = os.environ["LLM_MODEL"]
    base = os.environ["LLM_BASE_URL"]

    # ---- 1. 冒烟：连通性 + 协议兼容 ----
    ping = llm.chat([{"role": "user", "content": "只回复两个字：正常"}])
    print(f"[1/3] 冒烟通过  base={base}  model={model}  回复={ping.strip()[:20]!r}")

    store, _ = init_store()
    calc = CostCalculator(store)
    retriever = Retriever()

    # ---- 2. 板块2：归因分析实弹 ----
    rep = generate_attribution(calc, retriever, llm, PRODUCT, MONTH)
    v = rep.verification
    print(f"\n[2/3] 板块2 归因  verdict={v['verdict']}  retried={v.get('retried', False)}")
    if v.get("errors"):
        print("  errors:", *v["errors"], sep="\n   - ")
    fx = v.get("fixed") or []
    print(f"  auto_fixed {len(fx)} 处" + (f"：{fx[:5]}" if fx else ""))
    print("  --- 归因正文（实产） ---")
    print("  总起：" + rep.summary)
    for c in rep.causes:
        print(f"  ◆ {c.title}\n    {c.detail}\n    声明数字={c.figures} 出处={c.citations}")
    print("  建议：" + "；".join(rep.suggestions[:3]))

    # ---- 3. 板块3：报告六段实弹 ----
    sections, suggestions, v3 = generate_report_sections(
        calc, retriever, llm, PRODUCT, MONTH)
    print(f"\n[3/3] 板块3 六段  verdict={v3['verdict']}  retried={v3.get('retried', False)}")
    if v3.get("errors"):
        print("  errors:", *v3["errors"], sep="\n   - ")
    for name, s in sections.items():
        print(f"  · {name}: {len(s.text)}字 | {s.text[:60]}…")
    print("  建议:", "；".join(suggestions[:3]))

    print("\n联调结论：verdict 全 pass 则双轨实弹通过；auto_fixed/rejected 见上。")


if __name__ == "__main__":
    main()
