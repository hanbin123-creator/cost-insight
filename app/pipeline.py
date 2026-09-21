"""编排器（最小实现，板块4 方案 V2 阶段0）：场景=板块组合预设表。

手册 2.2 职责兑现：
- 所有场景是板块组合的预设表，新增场景只加一行 SCENES 注册
- 单场景失败捕获降级，不影响其余场景（测试锚定）
范围红线：只服务 agent 意图分发（/api/chat）；api.py 既有端点一律不动，
不做全站重构——双轨并存是企业演进版的收口债，已在审计 C2 记录。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .context import AnalysisContext


@dataclass
class Deps:
    """场景运行依赖包（api/agent 层注入；测试可全用假身）。"""
    calc: Any = None
    retriever: Any = None
    charts: Any = None
    llm_factory: Callable = lambda: None     # 默认无 LLM（降级轨）
    out_dir: Path | None = None              # 报告产物目录


# ---------- 四场景（懒导入避免环：pipeline 是被 agent/api 引用的顶层） ----------

def _run_report(d: Deps, ctx: AnalysisContext) -> dict:
    from .render import build_report
    out = d.out_dir or Path(__file__).resolve().parent.parent / "reports"
    out.mkdir(parents=True, exist_ok=True)
    theme = ctx.params.get("theme", "monthly")      # 季度/专题主题经意图参数透传
    quarter = ctx.params.get("quarter")
    month = ctx.month
    if theme == "quarterly" and quarter in ("Q1", "Q2"):
        from .compute import CostCalculator
        month = CostCalculator.QUARTER_MONTHS[quarter][-1]  # 季末月锚点
    res = build_report(d.calc, d.retriever, d.llm_factory(),
                       ctx.product, month, out, theme=theme, quarter=quarter)
    return {"docx": res["docx"], "pdf": res["pdf"], "theme": res["theme"],
            "verification": res["verification"]}


def _run_dashboard(d: Deps, ctx: AnalysisContext) -> dict:
    m = d.calc.metrics(ctx.product, ctx.month)
    s = d.charts.series_data(ctx.product)
    return {"unit_cost": m.unit_cost, "mom_pct": m.unit_cost_mom_pct,
            "alerts": len(m.alerts),
            "trend": {"months": s["months"], "unit_cost": s["unit_cost"]}}


def _run_benchmark(d: Deps, ctx: AnalysisContext) -> dict:
    return d.calc.benchmark(ctx.product, ctx.month).model_dump()


def _run_rectify(d: Deps, ctx: AnalysisContext) -> dict:
    from .act import dispatch
    return dispatch(ctx.product, ctx.month, d.calc, llm=d.llm_factory(),
                    speed=ctx.params.get("speed"))


@dataclass(frozen=True)
class Scene:
    intent: str            # agent 四意图之一：report/dashboard/benchmark/rectify
    name: str
    description: str
    run: Callable[[Deps, AnalysisContext], dict]


SCENES: dict[str, Scene] = {
    "report": Scene("report", "智能报告", "生成月度成本分析报告（Word+PDF）", _run_report),
    "dashboard": Scene("dashboard", "看板速览", "单位成本趋势与告警摘要", _run_dashboard),
    "benchmark": Scene("benchmark", "对标分析", "中药一厂 vs 二厂三步法差异树", _run_benchmark),
    "rectify": Scene("rectify", "整改任务", "告警装配整改任务并下发 RPA", _run_rectify),
}


class Pipeline:
    """意图 → 场景分发器。run() 永不抛异常：场景失败如实降级返回。"""

    def __init__(self, deps: Deps):
        self.deps = deps

    def run(self, intent: str, ctx: AnalysisContext) -> dict:
        scene = SCENES.get(intent)
        if scene is None:
            return {"ok": False, "intent": intent,
                    "error": f"未注册场景: {intent}", "available": sorted(SCENES)}
        try:
            data = scene.run(self.deps, ctx)
            ctx.result = data
            return {"ok": True, "intent": intent, "scene": scene.name, "data": data}
        except Exception as e:   # 单场景失败捕获降级，不拖垮其余场景
            return {"ok": False, "intent": intent, "scene": scene.name,
                    "error": f"{type(e).__name__}: {e}"}
