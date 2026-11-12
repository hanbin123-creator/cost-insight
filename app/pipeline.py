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
    # 只回相对文件名：前端用 api.reportUrl 拼下载链接；绝对路径不进浏览器（防泄露）
    return {"docx": Path(res["docx"]).name,
            "pdf": Path(res["pdf"]).name if res.get("pdf") else None,
            "theme": res["theme"], "verification": res["verification"]}


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


def _run_qa(d: Deps, ctx: AnalysisContext) -> dict:
    """知识库自由问答（qa 意图）：检索 Top5 → LLM 带出处回答 / 无 LLM 降级原文片段。

    不猜原则的问答域延伸：top1 低于校准阈值（config.QA_MIN_RRF_SCORE）不硬答，
    如实回"知识库未收录"。回答中的数字不承诺精度——数字真源仍是看板/报告，
    前端卡片固定标注。"""
    from . import config as C
    question = ctx.params.get("question", "")
    pack = d.retriever.search(question, top_k=5)
    if not pack.hits:
        return {"mode": "no_hit", "answer": None, "snippets": [], "citations": [],
                "note": "知识库未收录相关内容"}
    best = max(h.rrf_score for h in pack.hits)
    if best < C.QA_MIN_RRF_SCORE:
        return {"mode": "no_hit", "answer": None, "snippets": [], "citations": [],
                "note": "知识库未收录足够相关的内容（检索得分低于域内校准下限，不硬答）",
                "score": round(best, 4)}
    cites = [{"doc_name": h.doc_name, "page": h.page, "section": h.section}
             for h in pack.hits[:3]]
    llm = d.llm_factory()
    if llm is None:
        # 降级轨：不生成、不改写，只呈现原文片段——零幻觉空间
        return {"mode": "snippets", "answer": None, "citations": cites,
                "snippets": [{"doc_name": h.doc_name, "page": h.page,
                              "section": h.section, "text": h.text[:200]}
                             for h in pack.hits[:3]],
                "note": "未配置 LLM，以下为知识库原文片段",
                "score": round(best, 4)}
    material = "\n".join(
        f"《{h.doc_name}》p{h.page}「{h.section}」：{h.text[:300]}"
        for h in pack.hits[:5])
    try:
        answer = llm.chat([
            {"role": "system", "content":
             "你是制药成本分析平台的知识库问答助手。纪律：①只依据给定资料片段回答；"
             "②片段未覆盖的内容如实说“知识库未收录”；③禁止编造数字；"
             "④引用出处格式《文档名》p页码；⑤200 字以内。"},
            {"role": "user", "content": f"问题：{question}\n\n资料片段：\n{material}"}])
    except Exception as e:
        return {"mode": "snippets", "answer": None, "citations": cites,
                "snippets": [{"doc_name": h.doc_name, "page": h.page,
                              "section": h.section, "text": h.text[:200]}
                             for h in pack.hits[:3]],
                "note": f"LLM 调用失败（{type(e).__name__}），降级为原文片段",
                "score": round(best, 4)}
    return {"mode": "llm", "answer": answer.strip(), "citations": cites,
            "snippets": [], "note": None, "score": round(best, 4)}


def _run_nav(d: Deps, ctx: AnalysisContext) -> dict:
    """页面跳转意图（nav）：不执行任何业务场景，只回目标视图——
    跳转由前端 action 执行（路由只分发的字面兑现）。"""
    return {"view": ctx.params.get("view")}


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
    "qa": Scene("qa", "知识库问答", "回答成本/工艺/行情/GMP 等问题（带出处）", _run_qa),
    "nav": Scene("nav", "页面跳转", "打开指定页面（整改/看板/报告/知识库/对标）", _run_nav),
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
