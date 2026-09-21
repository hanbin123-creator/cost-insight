"""导出前端契约 fixture：经 pytest 验证的 API 响应固化为 JSON（缺点①对策 b）。

用法：python scripts/export_fixtures.py
产出：web/fixtures/*.json —— 前端 mock 开发与 vitest 单测的数据基础。
"""
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.api import app  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "web" / "fixtures"

CASES = {
    "products.json": ("GET", "/api/products"),
    "series_yinhuang.json": ("GET", "/api/series/银黄口服液"),
    "waterfall_yinhuang_05.json": ("GET", "/api/charts/waterfall/银黄口服液/2026-05"),
    "waterfall_liuwei_03_negative.json": ("GET", "/api/charts/waterfall/六味地黄胶囊/2026-03"),
    "structure_yinhuang_01.json": ("GET", "/api/charts/structure/银黄口服液/2026-01"),
    "heatmap.json": ("GET", "/api/charts/heatmap"),
    "metrics_yinhuang_05.json": ("GET", "/api/metrics/银黄口服液/2026-05"),
    "decision_alert.json": ("GET", "/api/agent/decision/银黄口服液/2026-05"),
    "decision_quiet.json": ("GET", "/api/agent/decision/银黄口服液/2026-02"),
    "forecast_yinhuang.json": ("GET", "/api/forecast/银黄口服液"),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with TestClient(app) as client:
        for name, (method, path) in CASES.items():
            r = client.request(method, path)
            assert r.status_code == 200, f"{path} → {r.status_code}"
            (OUT / name).write_text(json.dumps(r.json(), ensure_ascii=False, indent=1),
                                    encoding="utf-8")
            print(f"  {name}  ({len(r.content)} B)")
    _export_demo_attribution()
    print(f"fixture 导出完成 → {OUT}")


def _export_demo_attribution() -> None:
    """演示模式样例：MockLLM + 真实产物包构造的优质输出，走完整校验闭环后固化。
    前端在 LLM 未配置时加载本文件展示校验机制（页面须标注"演示模式"）。"""
    from app import prompts
    from app.generate import generate_attribution
    from app.llm import MockLLM
    from app.api import _State, _init

    _init()
    calc, retriever = _State.calc, _State.retriever
    metrics = calc.metrics("银黄口服液", "2026-05")
    knowledge = retriever.multi_search(
        prompts.build_queries("银黄口服液", "2026-05", metrics), top_k=6)
    mat = metrics.elements["直接材料"]
    hit = knowledge.hits[0]
    alert_txt = "；".join(a.message for a in metrics.alerts[:2]) or "本月无告警"
    canned = {
        "summary": (f"银黄口服液 2026-05 单位成本 {metrics.unit_cost} 元/盒，"
                    f"环比 {metrics.unit_cost_mom_pct:+.1f}%，"
                    f"同比 {metrics.unit_cost_yoy_pct:+.1f}%，"
                    f"较预算偏差 {metrics.unit_cost_budget_dev_pct:+.1f}%。"),
        "causes": [{
            "title": "金银花行情上涨推高直接材料成本",
            "detail": (f"直接材料 {mat.current} 元/盒，环比 {mat.mom_pct:+.1f}%，"
                       f"对总成本变动贡献 {mat.contribution_pct:.1f}%。"
                       f"告警：{alert_txt}。"
                       f"配方中金银花为君药，见《{hit.doc_name}》p{hit.page}"
                       f"\"{hit.section}\"。"),
            "figures": [metrics.unit_cost, metrics.unit_cost_mom_pct,
                        metrics.unit_cost_yoy_pct, metrics.unit_cost_budget_dev_pct,
                        mat.current, mat.mom_pct, mat.contribution_pct],
            "citations": [hit.chunk_id]}],
        "suggestions": ["核查金银花采购合同是否触发调价条款，适时锁价备货",
                        "跟踪黄芩提取物单耗波动，排查提取工序收率"]}
    report = generate_attribution(calc, retriever,
                                  MockLLM(json.dumps(canned, ensure_ascii=False)),
                                  "银黄口服液", "2026-05")
    assert report.verification["passed"], report.verification
    (OUT / "demo_attribution.json").write_text(
        report.model_dump_json(indent=1), encoding="utf-8")
    print("  demo_attribution.json  （演示模式样例，已通过校验闭环）")


if __name__ == "__main__":
    main()
