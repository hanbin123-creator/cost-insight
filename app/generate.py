"""板块④ 生成编排：MetricsPack + KnowledgePack → Prompt → LLM → 解析 → 校验闭环。

声明制对账（本板块的核心机制）：
- 模型对用过的每个数字、每条出处做声明（figures/citations 字段）
- 校验器三重检查：声明的数字必须在产物包中存在；正文出现的数字必须都被声明；
  声明的 chunk_id 必须在知识包中——任一不过即判不合格，passed=False 随报告返回
- 校验在代码侧，模型不可见不可绕过
"""
from __future__ import annotations

import json
import re

from .compute import CostCalculator
from .prompts import build_attribution_messages, build_queries
from .retrieve import Retriever
from .schemas import AttributionReport, Cause, KnowledgePack, MetricsPack

_NUM_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?%?")
# 预处理豁免：年月日期（2026-05 / 2026年）与页码引用（p12）不是"数字证据"；
# ±N% 是告警阈值常量（配置值，非数据证据）——板块3 模板句引用告警原文时必需
_EXEMPT_RES = [re.compile(r"20\d{2}-\d{2}"), re.compile(r"20\d{2}(?=年)"),
               re.compile(r"[pP]\d{1,4}(?=\D|$)"), re.compile(r"±\d+(?:\.\d+)?%?"),
               re.compile(r"[A-Za-z]{2,}-[0-9]+")]  # 设备型号（NJP-3200/DXDK-40VI）非数字证据


def _numbers_in_text(text: str) -> list[float]:
    """从正文抽取数字（去千分位逗号、去百分号），日期/页码/阈值常量先豁免。"""
    for pat in _EXEMPT_RES:
        text = pat.sub(" ", text)
    out = []
    for tok in _NUM_RE.findall(text):
        tok = tok.rstrip("%")
        try:
            out.append(float(tok.replace(",", "")))
        except ValueError:
            continue
    return out


_NUM_UNIT_RE = re.compile(r"(-?\d+(?:,\d{3})*(?:\.\d+)?)(\s*(?:元|％|%))?")


def _numbers_with_units(text: str) -> list[tuple[float, bool]]:
    """同 _numbers_in_text，附"数字后紧跟 元/% 单位"标记——
    精度丢失检查的语境守卫：只盯带金额/比率单位的数字，
    放行"停产 2 天""停工 16h"这类量词整数（D20 教训的边界扩展）。"""
    for pat in _EXEMPT_RES:
        text = pat.sub(" ", text)
    out = []
    for m in _NUM_UNIT_RE.finditer(text):
        try:
            out.append((float(m.group(1).replace(",", "")), bool(m.group(2))))
        except ValueError:
            continue
    return out


def _pack_allowlist(metrics: MetricsPack, knowledge: KnowledgePack) -> set[float]:
    """数字白名单 = 指标包全部数值字段 ∪ 知识块文本中的数字。

    舍入变体（板块3 引入）：每个数值同时按 1/2/3 位小数入册——
    展示层引用低位舍入值（如 description 的 13.2 ← 存储 13.16）属合理展示，
    不是编造；校验的核心目标是拦"无中生有"，不是拦"合理舍入"。
    缺点：白名单膨胀约 4 倍，编造数字撞库概率略升；裁决：配合声明完整性检查，
    风险可控，且根治所有 display-rounding 误报。"""
    allow: set[float] = set()

    def add(x: float) -> None:
        for nd in (4, 3, 2, 1):
            allow.add(round(x, nd))
        # 绝对值变体：文本方向词承载符号（"低 7.8%" ← 存储 −7.8），绝对值不是新数字
        for nd in (4, 3, 2, 1):
            allow.add(round(abs(x), nd))

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            add(float(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(json.loads(metrics.model_dump_json()))
    for h in knowledge.hits:
        for n in _numbers_in_text(h.text):
            add(n)
    return allow


def verify_report(report: AttributionReport, metrics: MetricsPack,
                  knowledge: KnowledgePack,
                  extra_allow: set[float] | None = None) -> dict:
    """三级裁决定对账（决策 F 加固版）：
    - pass：零问题
    - auto_fixed：正文数字真实存在于产物包但未声明 → 自动补全声明（粗心可自愈，
      误报拦截率的关键区分：真实未声明=警告修复，不存在=编造拦截）
    - rejected：编造数字（不在白名单）或编造出处（chunk_id 不存在）→ 硬错误
    返回 {"verdict", "passed", "fixed", "errors"}；passed = verdict != rejected。
    extra_allow：板块3 传入对标树数值（白名单外但同为代码算好的合法数字）。
    """
    errors: list[str] = []
    fixed: list[str] = []
    allow = _pack_allowlist(metrics, knowledge)
    if extra_allow:
        allow |= extra_allow
    valid_ids = {h.chunk_id for h in knowledge.hits}

    for i, cause in enumerate(report.causes):
        tag = f"causes[{i}]《{cause.title}》"
        # ① 声明的数字必须在白名单中（编造拦截）
        for f in cause.figures:
            if round(f, 4) not in allow:
                errors.append(f"{tag} 声明的数字 {f} 在产物包中不存在（疑似编造/心算）")
        # ② 正文数字：真实未声明 → 自动补全；带单位的取整形态 → 精度丢失
        #   （错误消息直接给正确原值，反馈重试照抄即收敛）；其余不存在 → 编造拦截
        declared = {round(f, 4) for f in cause.figures}
        for n, has_unit in _numbers_with_units(cause.detail):
            if round(n, 4) in declared:
                continue
            if round(n, 4) in allow:
                cause.figures.append(n)
                declared.add(round(n, 4))
                fixed.append(f"{tag} 自动补全声明: {n}（数字真实，原漏报）")
                continue
            if has_unit and n == int(n):
                near = sorted((x for x in allow
                               if x != int(x) and abs(x - n) < 1),
                              key=lambda x: abs(x - n))[:3]
                if near:
                    errors.append(
                        f"{tag} 精度丢失：正文 {n:g} 带单位但非产物包原值（相近原值 "
                        f"{' / '.join(f'{x:g}' for x in near)}，应按原值完整引用，"
                        f"禁止取整/再舍入）")
                    continue
            errors.append(f"{tag} 正文数字 {n} 未声明且不在产物包中（疑似编造/心算）")
        # ③ 出处必须真实存在于知识包（编造出处拦截，不可自愈）
        for cid in cause.citations:
            if cid not in valid_ids:
                errors.append(f"{tag} 引用的 chunk_id {cid} 不在知识包中（疑似编造出处）")
    verdict = "rejected" if errors else ("auto_fixed" if fixed else "pass")
    return {"verdict": verdict, "passed": verdict != "rejected",
            "fixed": fixed, "errors": errors}


def parse_report(raw: str, product: str, month: str) -> AttributionReport:
    """解析模型输出为 AttributionReport；容错 markdown 代码围栏。"""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?\s*|\s*```$", "", text, flags=re.M).strip()
    data = json.loads(text)
    return AttributionReport(
        product=product, month=month,
        summary=data.get("summary", ""),
        causes=[Cause(**c) for c in data.get("causes", [])],
        suggestions=list(data.get("suggestions", [])))


_REVISION_TEMPLATE = """你上一轮的输出未通过系统校验，错误如下：
{errors}

请修正后重新输出完整 JSON（规则不变：只使用指标包/知识包中的数字，
声明全部用到的数字与 chunk_id）。这是最后一次修正机会。"""


def generate_attribution(calc: CostCalculator, retriever: Retriever,
                         llm, product: str, month: str) -> AttributionReport:
    """板块④主入口：一次分析的归因报告。

    稳定性策略（决策 F 加固）：校验 rejected 时把错误清单反馈给模型重试一轮；
    仍不过则如实返回 passed=False——系统永不因模型失误而崩溃或静默放行。"""
    metrics = calc.metrics(product, month)
    queries = build_queries(product, month, metrics)
    knowledge = retriever.multi_search(queries, top_k=6)
    messages = build_attribution_messages(metrics, knowledge)

    def _attempt(msgs: list[dict]):
        """一轮调用+解析+校验；解析失败视同 rejected（错误进反馈，不崩溃）。"""
        raw = llm.chat(msgs, json_mode=True)
        try:
            rep = parse_report(raw, product, month)
            return rep, verify_report(rep, metrics, knowledge), raw
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            return None, {"verdict": "rejected", "passed": False, "fixed": [],
                          "errors": [f"输出无法解析为合法 JSON（{e}）"]}, raw

    report, v, raw = _attempt(messages)
    if v["verdict"] == "rejected":
        # 带错误反馈的修正重试（仅一轮，防死循环）；上轮原输出回传供模型对照
        retry_msgs = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": _REVISION_TEMPLATE.format(
                errors="\n".join(v["errors"]))},
        ]
        report, v, _ = _attempt(retry_msgs)
        v["retried"] = True
    if report is None:
        # 两轮后仍不可解析：如实返回 passed=False 的空报告——
        # 系统永不因模型失误而崩溃或静默放行
        report = AttributionReport(product=product, month=month, summary="",
                                   causes=[], suggestions=[])
    report.verification = v
    return report
