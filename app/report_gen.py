"""板块3 报告文本段落生成：6 个叙述段落 + 改进建议，声明制校验闭环复用。

双轨策略（与看板演示模式同一哲学——系统永不因模型缺席崩溃，且降级透明）：
- 有 LLM：一次调用产出 6 段 + 建议，每段声明 figures/citations，
  校验复用 generate.py 的三重对账（编造拦截/漏报自愈/出处核验），rejected 反馈重试一轮
- 无 LLM：代码模板句兜底——全部数字取自指标包/对标树（客观陈述，零幻觉空间），
  source 标注"模板句·LLM未配置"，渲染层据此在报告中保留来源标注
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel

from .compute import CostCalculator
from .generate import _numbers_in_text, _pack_allowlist, verify_report  # 复用校验原语
from .prompts import build_queries
from .retrieve import Retriever
from .schemas import AttributionReport, Cause, KnowledgePack, MetricsPack


class SectionResult(BaseModel):
    text: str
    figures: list[float] = []
    citations: list[str] = []
    source: str = "llm"          # llm / 模板句·LLM未配置


SECTION_FIELDS = frozenset({
    "section.material_attribution",   # 材料成本归因分析文本
    "section.anomaly",                # 成本异常排查分析
    "section.diff_structure",         # 差异结构拆解分析
    "section.diff_attribution",       # 差异归因分析文本
    "section.highlights",             # 本月亮点
    "section.concerns",               # 需关注问题
})
# 内部统一使用标准字段 id；模板键名只在 config/placeholder_map.yaml 出现（L1 映射）
SECTION_NAMES = sorted(SECTION_FIELDS)

_SYSTEM = """你是制药企业成本分析助手，负责把结构化数据组织成成本分析报告（月度/季度/专题）的叙述段落。
铁律（违反任何一条，输出将被系统判为不合格并退回）：
1. 你只组织语言，永不计算。所有数字必须原样取自输入的指标包/对标树/知识包，
   不得做任何加减乘除、口径换算、四舍五入后的再加工
2. 每段的 figures 字段必须声明该段正文用到的全部数字
3. 引用知识出处用 citations 字段声明 chunk_id；正文引用写作《文档名》p页码"章节名"
4. 对标描述直接使用对标树 description 字段原文，不得改写其中的数字与口径
5. 贡献度为负时表述为"该要素逆势变动，部分抵消了总成本的反向变动"
6. 知识包未覆盖的问题，明确说"知识库中未见相关记录"，禁止编造出处
7. 建议条中如出现数字，同样必须来自输入并在 suggestion_figures 声明
8. 金额/成本/百分比数字必须按产物包原值完整引用，保留原值小数位（如 11.21），
   禁止写成"约 11 元""11.2 元"等取整或再舍入形式；禁止用"约/左右/大概"修饰数字
9. 报告 3.1.2 节旁会附每种材料的量价分解明细表（代码生成），
   因此 section.material_attribution 正文不必逐材料罗列全部数字，
   点出影响最大的 1~2 种材料、讲清结论与原因即可"""

_USER = """请为以下分析条件生成报告叙述段落（JSON 输出）：

【分析条件】产品：{product} ｜ 月份：{month}

【指标包】（代码计算结果，数字唯一来源）
{metrics_json}

【对标树】（一厂 vs 二厂，双向口径已由代码算好）
{diff_json}

【知识包】（检索到的制药知识，引用唯一来源）
{knowledge_json}

【输出格式】严格输出 JSON，不要输出任何其他文字：
{{
  "sections": {{
    "section.material_attribution": {{"text": "材料成本归因……", "figures": [数字], "citations": ["chunk_id"]}},
    "section.anomaly": {{"text": "成本异常排查……", "figures": [], "citations": []}},
    "section.diff_structure": {{"text": "差异结构拆解……", "figures": [], "citations": []}},
    "section.diff_attribution": {{"text": "差异归因……", "figures": [], "citations": []}},
    "section.highlights": {{"text": "本月亮点……", "figures": [], "citations": []}},
    "section.concerns": {{"text": "需关注问题……", "figures": [], "citations": []}}
  }},
  "suggestions": ["可落地建议，每条对应至少一个发现"],
  "suggestion_figures": [建议中出现的数字]
}}"""

_REVISION = """你上一轮的输出未通过系统校验，错误如下：
{errors}

请修正后重新输出完整 JSON（规则不变）。这是最后一次修正机会。"""


def _diff_allow(diff) -> set[float]:
    """对标树数值（含 1-3 位舍入变体）作为扩展白名单——与指标包同为代码算好的合法数字。"""
    allow: set[float] = set()

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            for nd in (4, 3, 2, 1):
                allow.add(round(float(x), nd))
                allow.add(round(abs(float(x)), nd))  # 方向词承载符号的绝对值变体
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(json.loads(diff.model_dump_json()))
    return allow


def _verify_sections(sections: dict[str, SectionResult], suggestions: list[str],
                     suggestion_figures: list[float],
                     metrics: MetricsPack, knowledge: KnowledgePack,
                     extra_allow: set[float] | None = None) -> dict:
    """对 6 段做与 verify_report 同源的三重对账（借道 AttributionReport 复用）。"""
    causes = [Cause(title=name, detail=s.text, figures=list(s.figures),
                    citations=list(s.citations))
              for name, s in sections.items()]
    if suggestions:
        causes.append(Cause(title="改进建议", detail="；".join(suggestions),
                            figures=list(suggestion_figures), citations=[]))
    pseudo = AttributionReport(product=metrics.product, month=metrics.month,
                               summary="", causes=causes, suggestions=[])
    # 引用闸门只对 LLM 轨生效：模板句本就不引用知识块，强制引用是造假
    require_citation = any(s.source == "llm" for s in sections.values())
    v = verify_report(pseudo, metrics, knowledge, extra_allow=extra_allow,
                      require_citation=require_citation)
    # 自愈的 figures 回写各段（auto_fixed 的补全声明要落到展示层）
    for name, cause in zip(list(sections) + (["改进建议"] if suggestions else []), causes):
        if name in sections:
            sections[name].figures = list(cause.figures)
    return v


# ---------- 模板句兜底（无 LLM）：全部数字取自产物包 ----------
def _template_sections(metrics: MetricsPack, diff, calc: CostCalculator,
                       src: str = "模板句·LLM未配置",
                       period: str | None = None) -> dict[str, SectionResult]:
    period = period or metrics.month
    scope = "本季度" if "Q" in period else "本月"
    out: dict[str, SectionResult] = {}
    mat = metrics.elements["直接材料"]
    figs = [mat.current]
    parts = [f"直接材料 {mat.current} 元/盒"]
    if mat.mom_pct is not None:
        parts.append(f"环比 {mat.mom_pct:+.1f}%")
        figs.append(mat.mom_pct)
    if mat.contribution_pct is not None:
        parts.append(f"对总成本变动贡献 {mat.contribution_pct:.1f}%")
        figs.append(mat.contribution_pct)
    top = next((d for d in metrics.decomposition if d.price_effect is not None), None)
    if top is not None:
        parts.append(f"其中{top.material}价差影响 {top.price_effect:+.3f} 元/盒"
                     f"（{top.note or '行情价分解'}）")
        figs.append(top.price_effect)
    out["section.material_attribution"] = SectionResult(
        text="，".join(parts) + "。", figures=figs, source=src)

    if metrics.alerts:
        txt = "；".join(a.message for a in metrics.alerts)
        figs2 = [a.mom_pct for a in metrics.alerts]
        out["section.anomaly"] = SectionResult(
            text=f"{scope}触发以下告警：{txt}。", figures=figs2, source=src)
    else:
        out["section.anomaly"] = SectionResult(
            text=f"{scope}各要素环比波动均在阈值内，未触发告警。", source=src)

    descs = [r.description for r in diff.rows]
    figs3 = [v for r in diff.rows for v in (r.main, r.bench, r.diff, r.diff_rate_pct)]
    out["section.diff_structure"] = SectionResult(
        text="对标中药二厂：" + "；".join(descs) + "。", figures=figs3, source=src)

    worst = max(diff.rows, key=lambda r: abs(r.diff_rate_pct))
    out["section.diff_attribution"] = SectionResult(
        text=f"差异最大要素为{worst.element}：{worst.description}。"
             "原材料级明细见差异总览表，深入归因需结合知识库证据（LLM 配置后生成）。",
        figures=[worst.main, worst.bench, worst.diff, worst.diff_rate_pct], source=src)

    best = min((e for e in metrics.elements.values() if e.mom_pct is not None),
               key=lambda e: e.mom_pct, default=None)
    if best is not None and best.mom_pct < 0:
        out["section.highlights"] = SectionResult(
            text=f"成本管控成效：要素环比最大降幅 {best.mom_pct:+.1f}%。",
            figures=[best.mom_pct], source=src)
    else:
        out["section.highlights"] = SectionResult(
            text=f"产量 {metrics.output_qty} 盒，单位成本 {metrics.unit_cost} 元/盒，"
                 "生产组织保持平稳。", figures=[metrics.output_qty, metrics.unit_cost],
            source=src)

    if metrics.alerts:
        out["section.concerns"] = SectionResult(
            text="；".join(f"{a.element}（{a.channel}）" for a in metrics.alerts) + "。",
            figures=[a.mom_pct for a in metrics.alerts], source=src)
    else:
        out["section.concerns"] = SectionResult(text="暂无需重点关注事项。", source=src)
    return out


# ---------- 主入口 ----------
def generate_report_sections(calc: CostCalculator, retriever: Retriever,
                             llm, product: str, month: str,
                             theme: str = "monthly",
                             quarter: str | None = None) -> tuple[dict[str, SectionResult],
                                                                  list[str], dict]:
    """返回 (六段结果, 建议列表, 校验结论)。llm 为 None 时走模板句兜底。
    theme=quarterly：指标走 quarter_pack 加权包（month 参数忽略，锚定季末月做对标）。"""
    if theme == "quarterly":
        metrics = calc.quarter_pack(product, quarter)
        diff = calc.benchmark(product, calc.QUARTER_MONTHS[quarter][-1])
        period = f"2026年{quarter}季度"
    else:
        metrics = calc.metrics(product, month)
        diff = calc.benchmark(product, month)
        period = month

    if llm is None:
        sections = _template_sections(metrics, diff, calc, period=period)
        knowledge = KnowledgePack(query="", hits=[])
        v = _verify_sections(sections, [], [], metrics, knowledge,
                             extra_allow=_diff_allow(diff))
        suggestions = [f"核查{a.element}异常（{a.channel}）" for a in metrics.alerts] \
            or ["维持现行成本管控节奏，持续跟踪行情"]
        return sections, suggestions, v

    queries = build_queries(product, month if theme != "quarterly"
                            else calc.QUARTER_MONTHS[quarter][-1], metrics)
    knowledge = retriever.multi_search(queries, top_k=6)
    user = _USER.format(product=product, month=period,
                        metrics_json=metrics.model_dump_json(indent=2),
                        diff_json=diff.model_dump_json(indent=2),
                        knowledge_json=knowledge.model_dump_json(indent=2))
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user}]

    def _parse(raw: str):
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(json)?\s*|\s*```$", "", text, flags=re.M).strip()
        data = json.loads(text)
        secs = {name: SectionResult(**data["sections"].get(name, {"text": ""}))
                for name in SECTION_NAMES}
        return secs, list(data.get("suggestions", [])), list(data.get("suggestion_figures", []))

    def _attempt(msgs: list[dict]):
        """一轮调用+解析+校验；解析失败视同 rejected（错误进反馈，不崩溃）。"""
        raw = llm.chat(msgs, json_mode=True)
        try:
            secs, suggs, figs = _parse(raw)
            vv = _verify_sections(secs, suggs, figs, metrics, knowledge,
                                  extra_allow=_diff_allow(diff))
            return (secs, suggs), vv, raw
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
            return None, {"verdict": "rejected", "passed": False, "fixed": [],
                          "errors": [f"输出无法解析为合法 JSON（{e}）"]}, raw

    (parsed, v, raw) = _attempt(messages)
    if v["verdict"] == "rejected":
        retry = messages + [{"role": "assistant", "content": raw},
                            {"role": "user", "content": _REVISION.format(
                                errors="\n".join(v["errors"]))}]
        parsed, v, _ = _attempt(retry)
        v["retried"] = True
    if parsed is None:
        # 两轮后仍不可解析：降级模板句（与 llm=None 同轨），如实标注——
        # 报告主体永不因模型失误而缺失
        sections = _template_sections(metrics, diff, calc, period=period)
        suggestions = [f"核查{a.element}异常（{a.channel}）" for a in metrics.alerts] \
            or ["维持现行成本管控节奏，持续跟踪行情"]
        v["llm_parse_failed"] = True
        v["fallback"] = "template_sections"
        return sections, suggestions, v
    sections, suggestions = parsed
    if v["verdict"] == "rejected":
        # 两轮后仍 rejected：未过校验的 LLM 文本不得进入正式报告（安全底线）——
        # 降级模板句；verdict 保留 rejected 如实记录 LLM 轨失败，来源标注"被拦截"
        sections = _template_sections(metrics, diff, calc, src="模板句·LLM被拦截", period=period)
        suggestions = [f"核查{a.element}异常（{a.channel}）" for a in metrics.alerts] \
            or ["维持现行成本管控节奏，持续跟踪行情"]
        v["llm_rejected_fallback"] = True
        v["fallback"] = "template_sections"
    else:
        _attach_citations(sections, knowledge)
    return sections, suggestions, v


def _attach_citations(sections: dict[str, "SectionResult"], knowledge: "KnowledgePack") -> None:
    """把校验通过的 chunk_id 声明解析成人读出处，行内追加到段尾。

    校验器只保证 citations 字段合法，渲染层此前不落地——读者在报告里看不到
    出处（修复 3 的遗留缺口）。此处在校验通过后追加，追加内容不参与再校验
    （页码是知识库元数据，非数据证据）。模板句/被拦截轨不经过本函数。
    """
    by_id = {h.chunk_id: h for h in knowledge.hits}
    for s in sections.values():
        if s.source != "llm" or not s.citations:
            continue
        seen, parts = set(), []
        for cid in s.citations:
            h = by_id.get(cid)
            if h is None or cid in seen:
                continue          # 校验已保证 cid 合法；重复引用去重保序
            seen.add(cid)
            sec = f'"{h.section}"' if h.section else ""
            parts.append(f"《{h.doc_name}》p{h.page}{sec}")
        if parts and "出处：" not in s.text:
            s.text = s.text.rstrip() + f"（出处：{'；'.join(parts)}）"
