"""Agent 自主决策（加分项，手册 6.4）：意图路由——LLM 主线 / 规则兜底 / 不猜原则。

三层路由（板块4 方案 V2 主从修正版）：
- 第1层 小模型分类（主线）：LLMClient(role="classification")，json_mode 强制
  {"intent", "confidence"}；confidence ≥ 阈值（config）→ Pipeline 场景执行
- 第2层 规则兜底：LLM 未配置/调用失败/返回破损 → 关键词表分类，layer="rule"
  （断网韧性演示剧本）；LLM 低置信但关键词硬命中 → 规则仲裁，layer="rule-arb"
  （用户打出的关键词是确定性证据，不属于"猜"）
- 第3层 双不命中/域外：返回四入口卡片由用户点选——不猜，让用户选

铁律：路由只做分发、永不算数；参数抽取规则化（产品别名/月份表达），
抽不出 → 返回澄清问题，绝不编造参数。
"""
from __future__ import annotations

import json
import re

from . import config as C
from .context import AnalysisContext
from .pipeline import SCENES, Pipeline

# 规则兜底关键词表（第2层；表外表达漏了只落到四入口，不承担主分类压力）
_KEYWORDS = {
    "rectify": ["整改", "任务", "下发", "督办", "rpa", "RPA", "推送", "责任人"],
    "benchmark": ["对标", "二厂", "对比", "差异", "三步法"],
    "report": ["报告", "报表", "导出", "下载"],
    "dashboard": ["看板", "趋势", "仪表", "图表", "走势"],
}

# 产品别名：全称之外的常见叫法（抽取规则，枚举制不猜测）
_PRODUCT_ALIAS = {"银黄": "银黄口服液", "板蓝根": "板蓝根颗粒",
                  "六味": "六味地黄胶囊", "六味地黄": "六味地黄胶囊"}


def _extract_product(text: str) -> str | None:
    for p in C.PRODUCTS:
        if p in text:
            return p
    for alias, full in _PRODUCT_ALIAS.items():
        if alias in text:
            return full
    return None


# 中文数字月份（实弹 D26：用户说"五月份"而非"5月"）
_CN_MONTH = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
             "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}


def _extract_month(text: str, latest_month: str) -> str | None:
    """月份抽取：YYYY-MM / YYYY年M月 / M月（含中文数字）/ 上月（相对最新数据月）。"""
    m = re.search(r"(20\d{2})[-/年](\d{1,2})月?", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(?<!\d)(\d{1,2})\s*月", text)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{latest_month[:4]}-{int(m.group(1)):02d}"
    m = re.search(r"(十一|十二|十|[一二三四五六七八九])月", text)
    if m:
        return f"{latest_month[:4]}-{_CN_MONTH[m.group(1)]:02d}"
    if "上月" in text or "上个月" in text:
        from .compute import _prev_month
        return _prev_month(latest_month)
    return None


# 主题抽取（赛题 5.1.3）：季度关键词优先于月份；专题=对标/异常复用链路
_QUARTER_PATTERNS = [(r"(一|1|Q1|第?一)\s*季", "Q1"), (r"(二|2|Q2|第?二)\s*季", "Q2"),
                     (r"上半年", "Q1")]


def _extract_theme(text: str) -> dict:
    """返回 {"theme": ..., "quarter": ...}；无主题词时空 dict（默认月度）。"""
    for pat, q in _QUARTER_PATTERNS:
        if re.search(pat, text):
            return {"theme": "quarterly", "quarter": q}
    if "季度" in text:
        return {"theme": "quarterly", "quarter": "Q2"}   # 数据最新季度为默认
    if "专题" in text:
        return {"theme": "topical"}
    return {}


def _rule_classify(text: str) -> tuple[str | None, float]:
    """关键词打分：命中词数最多者胜；零命中返回 None。"""
    scores = {intent: sum(1 for kw in kws if kw in text)
              for intent, kws in _KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return (best, 0.9) if scores[best] > 0 else (None, 0.0)


def _llm_classify(text: str, llm) -> tuple[str | None, float]:
    """小模型分类主线：json_mode 强制 JSON；任何失败返回 (None, 0.0) 交规则兜底。

    域围栏（D27）：意图枚举四 + 显式 "none"（域外出口）——与成本分析无关的请求
    （闲聊/天气/其他领域）必须返回 none，不允许硬归到四意图也不允许靠
    "置信度碰巧低"蒙混。返回 ("none", conf) 时调用方直接给四入口，不过规则层。"""
    intents = "、".join(f"{k}（{SCENES[k].name}）" for k in SCENES)
    messages = [
        {"role": "system", "content": "你是制药企业成本分析系统的意图分类器。"
         "把用户请求分类到四个意图之一：" + intents + "。\n"
         "纪律：①只输出 JSON: {\"intent\": \"...\", \"confidence\": 0.0-1.0}；"
         "②与成本分析无关的请求（闲聊、天气、其他领域、你不理解的内容），"
         "intent 必须输出 \"none\"——禁止硬归到四个意图之一；"
         "③拿不准但确属成本分析域的，confidence 给低分。"},
        {"role": "user", "content": text}]
    try:
        data = json.loads(llm.chat(messages, json_mode=True))
        intent, conf = data["intent"], float(data["confidence"])
        if intent == "none":
            return "none", conf          # 域外出口：显式声明，区别于"分类失败"
        if intent not in SCENES:
            return None, 0.0
        return intent, conf
    except Exception:
        return None, 0.0


def _choices_card(out_of_scope: bool = False) -> dict:
    msg = ("本助手仅支持成本分析相关操作（报告/看板/对标/整改任务），"
           "您的请求不在服务范围内。" if out_of_scope else
           "我没完全理解您的意图，请选择要执行的操作：")
    return {"message": msg,
            "choices": [{"intent": s.intent, "name": s.name,
                         "description": s.description} for s in SCENES.values()]}


def route(text: str, pipeline: Pipeline, llm=None, latest_month: str = "2026-06",
          product: str | None = None, month: str | None = None) -> dict:
    """意图路由主入口。返回契约见 /api/chat 文档；result 为场景产出或四入口卡片。"""
    # —— 意图分类：LLM 主线 → 规则兜底 → 四入口 ——
    intent, conf, layer = None, 0.0, "fallback"
    classifier = "none"
    out_of_scope = False
    if llm is not None:
        intent, conf = _llm_classify(text, llm)
        classifier = getattr(llm, "role_actual", "mock")
        if intent == "none":               # 域围栏：模型显式判定域外（D27）
            out_of_scope, intent, layer = True, None, "llm-out-of-scope"
        elif intent is not None and conf >= C.INTENT_CONFIDENCE_THRESHOLD:
            layer = "llm"
        elif intent is not None:
            layer = "fallback"     # 低置信：不执行，走四入口
            intent = None
    if intent is None and not out_of_scope:
        # LLM 缺席/失败 → 规则兜底（layer=rule）；LLM 低置信但规则硬命中 →
        # 确定性证据优先（layer=rule-arb，如实标注"规则仲裁了模型的没把握"）。
        # 用户亲自打出的关键词是硬证据，不属于"猜"；双不命中才四入口。
        rule_intent, rule_conf = _rule_classify(text)
        if rule_intent:
            # 先定 layer 再覆盖 conf——判断依据是"模型原始置信度"而非规则置信度
            layer = "rule" if (llm is None or conf == 0.0) else "rule-arb"
            intent, conf = rule_intent, rule_conf
    base = {"intent": intent, "confidence": conf, "layer": layer,
            "classifier": classifier}
    if intent is None:
        return {**base, "params": {}, "clarification": None,
                "result": _choices_card(out_of_scope)}

    # —— 参数抽取（规则；显式入参优先；抽不出→澄清，绝不编造） ——
    product = product or _extract_product(text)
    month = month or _extract_month(text, latest_month)
    theme_p = _extract_theme(text) if intent == "report" else {}
    params = {k: v for k, v in (("product", product), ("month", month)) if v}
    params.update(theme_p)
    # 季度主题月份由 quarter 推导（季末月锚点），不强制用户报月份
    missing = [k for k in ("product", "month") if k not in params]
    if theme_p.get("theme") == "quarterly":
        missing = [k for k in missing if k != "month"]
        if "month" not in params:
            from .compute import CostCalculator
            params["month"] = month = \
                CostCalculator.QUARTER_MONTHS[theme_p["quarter"]][-1]
    if missing:
        ask = "、".join("哪个产品" if k == "product" else "哪个月份" for k in missing)
        return {**base, "params": params,
                "clarification": f"请问要分析{ask}？（可选产品：{'、'.join(C.PRODUCTS)}）",
                "result": None}

    ctx = AnalysisContext(product=product, month=month, params=theme_p)
    return {**base, "params": params, "clarification": None,
            "result": pipeline.run(intent, ctx)}
