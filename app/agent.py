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
from .content_registry import CONTENT_TARGETS, find_anchor, targets_for_view
from .context import AnalysisContext
from .pipeline import SCENES, Pipeline

# 规则兜底关键词表（第2层；表外表达漏了只落到四入口，不承担主分类压力）
_KEYWORDS = {
    "rectify": ["整改", "任务", "下发", "督办", "rpa", "RPA", "推送", "责任人"],
    "benchmark": ["对标", "二厂", "对比", "差异", "三步法"],
    "report": ["报告", "报表", "导出", "下载"],
    "dashboard": ["看板", "趋势", "仪表", "图表", "走势", "热力图", "热力"],
    # qa/nav 弱词仅作兜底提示（主分类靠 LLM）：问答词不进其他四类，跳转需
    # "动词+页名"双命中（见 _extract_view），单独的页名仍归原场景意图
    "qa": ["为什么", "是什么", "怎么回事", "的原因", "如何", "规定"],
}

# 页面跳转（nav）：动词+页名双命中才判跳转，避免"下发整改任务"被误判为跳页
_NAV_VERBS = ("打开", "切换", "跳转", "转到", "去看", "去看看", "进入")
_NAV_TARGETS = {   # 页名 → 路由视图；长名先匹配（整改追踪 优先于 整改）
    "整改追踪": "rectify", "整改页": "rectify", "整改看板": "rectify",
    "整改": "rectify",
    "报告中心": "reports", "报告页": "reports", "报告列表": "reports",
    "知识库": "kb",
    "对标分析": "benchmark", "对标页": "benchmark", "对标": "benchmark",
    "成本看板": "dashboard", "看板": "dashboard",
}
_VIEW_NAMES = {"dashboard": "成本看板", "benchmark": "对标分析", "rectify": "整改追踪",
                "reports": "报告中心", "kb": "知识库"}


def _extract_view(text: str) -> str | None:
    """跳转目标抽取：枚举制不猜测。无动词或无页名 → None（归原场景意图）。"""
    if not any(v in text for v in _NAV_VERBS):
        return None
    for name in sorted(_NAV_TARGETS, key=len, reverse=True):
        if name in text:
            return _NAV_TARGETS[name]
    return None


def _has_nav_verb(text: str) -> bool:
    return any(v in text for v in _NAV_VERBS)


def _extract_anchor(text: str, kb_docs: list[str] | None = None) -> dict | None:
    """内容锚点抽取（A11）：注册表关键词（长词优先）→ 知识库文档名 token 重叠。
    枚举制不猜测：只返回清单内条目；命中文档返回 kb:doc:<文档名>。"""
    best: tuple[str, dict] | None = None
    for t in CONTENT_TARGETS:
        for kw in t["keywords"]:
            if kw in text and (best is None or len(kw) > len(best[0])):
                best = (kw, t)
    if best:
        return {"anchor": best[1]["anchor"], "view": best[1]["view"],
                "title": best[1]["title"]}
    # 文档名匹配前先做产品别名归一（"银黄配方文档"里的"银黄"→"银黄口服液"），
    # 与参数抽取同一套别名表，不另造规则
    norm = text
    for alias, full in _PRODUCT_ALIAS.items():
        if alias in text and full not in text:
            norm = norm.replace(alias, full)
    for name in kb_docs or []:
        stem = name.rsplit(".", 1)[0]
        if stem and (stem in text or stem in norm):
            return {"anchor": f"kb:doc:{name}", "view": "kb", "title": stem}
        tokens = []
        for tok in re.split(r"[_\s.]+", stem):
            for g in ("产品", "文档", "记录", "清单", "企业", "公司"):
                tok = tok.replace(g, "")
            if len(tok) >= 2:
                tokens.append(tok)
        if tokens and sum(1 for tok in tokens if tok in norm) >= 2:
            return {"anchor": f"kb:doc:{name}", "view": "kb", "title": stem}
    return None


def _llm_pick_anchor(text: str, cur_view: str | None, llm) -> dict | None:
    """指代消解（A11 第二趟 LLM，仅 nav 意图且规则抽不出目标时触发）：
    把当前页可见内容清单给模型做选择题——只能选清单内 id 或 null，
    选不出/选串台/调用失败一律 None，落澄清 chips（清单外无目标，不猜）。"""
    if llm is None or not cur_view:
        return None
    cands = targets_for_view(cur_view)
    if not cands:
        return None
    listing = "\n".join(f"- {t['anchor']}：{t['title']}" for t in cands)
    try:
        data = json.loads(llm.chat([
            {"role": "system", "content":
             "你是界面导航助手。用户在当前页面说了一句话，判断 TA 想查看下方清单中的"
             "哪一块内容。纪律：①只能从清单选 anchor；②指向不明输出 null；"
             "③只输出 JSON：{\"anchor\": \"...\" 或 null}。"},
            {"role": "user", "content": f"用户的话：{text}\n\n当前页可见内容清单：\n{listing}"}],
            json_mode=True))
        anchor = data.get("anchor")
    except Exception:
        return None
    t = find_anchor(anchor)
    if t and t["view"] == cur_view:      # 串台防御：只接受当前页条目
        return {"anchor": t["anchor"], "view": t["view"], "title": t["title"]}
    return None


# 场景意图 → 执行后联动前端动作（action 由前端执行；路由只分发不算数）
def _make_action(intent: str, product: str | None, month: str | None,
                 view: str | None = None, anchor: str | None = None,
                 anchor_title: str | None = None) -> dict | None:
    base = {"product": product, "month": month}
    if intent == "report":
        return {"type": "navigate", "view": "reports"}
    if intent == "rectify":
        return {"type": "navigate", "view": "rectify"}
    if intent in ("dashboard", "benchmark"):
        return {"type": "navigate", "view": intent, **base}
    if intent == "nav" and view:
        a = {"type": "navigate", "view": view, **base}
        if anchor:                       # A11 内容级定位（可选，前端缺失时退化为页面级）
            a["anchor"] = anchor
            a["anchor_title"] = anchor_title
        return a
    return None                                     # qa：不跳，答案即产出

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


def _choices_card(out_of_scope: bool = False) -> dict:
    msg = ("本助手仅支持成本分析相关操作与问答（报告/看板/对标/整改/问答/跳转），"
           "您的请求不在服务范围内。" if out_of_scope else
           "我没完全理解您的意图，请选择要执行的操作：")
    return {"message": msg,
            "choices": [{"intent": s.intent, "name": s.name,
                         "description": s.description} for s in SCENES.values()]}


def _rule_classify(text: str, kb_docs: list[str] | None = None) -> tuple[str | None, float]:
    """关键词打分：命中词数最多者胜；零命中返回 None。
    nav 前置：动词+页名 或 动词+内容锚点（A11）双命中是确定性证据
    （"打开整改追踪"≠"下发整改任务"；"打开热力图"≠"看看热力图"）。"""
    if _extract_view(text) or (_has_nav_verb(text) and _extract_anchor(text, kb_docs)):
        return "nav", 0.9
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
         "把用户请求分类到以下意图之一：" + intents + "。\n"
         "判别要点：用户在提问（为什么/是什么/什么原因/怎么规定/会不会）→ qa；"
         "用户想打开或切换到某个页面 → nav；"
         "用户用“打开/切换/跳转/去看”类跳转动词指向页面里的某块内容/某张图/"
         "某份文档（即使没说页面名，如“打开这张图”“打开热力图”）→ nav；"
         "注意：“看看/瞅瞅某张图”这类没有跳转动词的查看请求不归 nav，"
         "归对应场景意图（看趋势看图 → dashboard）；"
         "要生成/下载文件 → report；要看趋势指标 → dashboard；要和二厂对比 → benchmark；"
         "要下发/督办整改任务 → rectify。\n"
         "纪律：①只输出 JSON: {\"intent\": \"...\", \"confidence\": 0.0-1.0}；"
         "②与成本分析无关的请求（闲聊、天气、其他领域、你不理解的内容），"
         "intent 必须输出 \"none\"——禁止硬归到意图之一；"
         "③口语化表达（“咋样”“瞅瞅”“呗”“会不会”）只要意图明确属于成本分析域，"
         "confidence 给 0.75-0.9；仅当意图本身确实无法判断时才给低分。"},
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


def route(text: str, pipeline: Pipeline, llm=None, latest_month: str = "2026-06",
          product: str | None = None, month: str | None = None,
          view: str | None = None, kb_docs: list[str] | None = None) -> dict:
    """意图路由主入口。返回契约见 /api/chat 文档；result 为场景产出或四入口卡片。
    view=调用方当前页面（A11 指代消解的清单上下文）；kb_docs=知识库文档名清单
    （内容级跳转的动态锚点候选）。两者均可缺省，缺省时行为与 A9 完全一致。"""
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
        rule_intent, rule_conf = _rule_classify(text, kb_docs)
        if rule_intent:
            # 先定 layer 再覆盖 conf——判断依据是"模型原始置信度"而非规则置信度
            layer = "rule" if (llm is None or conf == 0.0) else "rule-arb"
            intent, conf = rule_intent, rule_conf
    base = {"intent": intent, "confidence": conf, "layer": layer,
            "classifier": classifier}
    if intent is None:
        return {**base, "action": None, "params": {}, "clarification": None,
                "options": None, "result": _choices_card(out_of_scope)}

    # —— 参数抽取（规则；文本明说优先于调用方上下文，抽不出才用上下文兜底；
    #    两级都空→澄清，绝不编造） ——
    # 优先级裁决（A9 修复）：用户在句子里明说的产品/月份 > 调用方传入（抽屉注入的
    # 是当前看板上下文，属于环境而非意图——"生成板蓝根报告"不能产出银黄报告）。
    # chips 点选场景文本里本就没有参数，抽取为空自然落到调用方入参，行为不变。
    product = _extract_product(text) or product
    month = _extract_month(text, latest_month) or month

    # qa/nav 免参数（问题/页面本身就是参数）；report/dashboard/benchmark/rectify
    # 保持原有澄清纪律
    if intent == "qa":
        params: dict = {"question": text}
    else:
        theme_p = _extract_theme(text) if intent == "report" else {}
        params = {k: v for k, v in (("product", product), ("month", month)) if v}
        params.update(theme_p)
        if intent == "nav":
            # A11 内容级目标解析：页名（动词+页名）→ 内容锚点（注册表/文档清单）
            # → LLM 指代消解（当前页清单选择题）→ 都抽不出给 chips，不猜目标
            tgt_view = _extract_view(text)
            hit = _extract_anchor(text, kb_docs)
            if hit is None and tgt_view is None:
                hit = _llm_pick_anchor(text, view, llm)
            if hit:
                params["view"] = tgt_view or hit["view"]
                params["anchor"] = hit["anchor"]
                params["anchor_title"] = hit["title"]
            elif tgt_view:
                params["view"] = tgt_view
            else:
                # 当前页内容 chips 在前（指代候选）、五个页面在后——不猜，让用户点
                content_opts = ([{"label": t["title"], "view": t["view"],
                                  "anchor": t["anchor"]}
                                 for t in targets_for_view(view)] if view else [])
                page_opts = [{"label": n, "view": v}
                             for n, v in
                             [("成本看板", "dashboard"), ("对标分析", "benchmark"),
                              ("整改追踪", "rectify"), ("报告中心", "reports"),
                              ("知识库", "kb")]]
                return {**base, "action": None, "params": params,
                        "clarification": "请问要打开哪个页面或哪块内容？",
                        "options": content_opts + page_opts,
                        "result": None}
        else:
            # 季度主题月份由 quarter 推导（季末月锚点），不强制用户报月份
            missing = [k for k in ("product", "month") if k not in params]
            if theme_p.get("theme") == "quarterly":
                missing = [k for k in missing if k != "month"]
                if "month" not in params:
                    from .compute import CostCalculator
                    params["month"] = month = \
                        CostCalculator.QUARTER_MONTHS[theme_p["quarter"]][-1]
            if missing:
                ask = "、".join("哪个产品" if k == "product" else "哪个月份"
                                for k in missing)
                # 点选 chips：缺什么给什么，用户点一下比重打一句话省力
                options = ([{"label": p, "product": p} for p in C.PRODUCTS]
                           if "product" in missing else []) + \
                          ([{"label": f"{m}月", "month": f"{latest_month[:4]}-{m:02d}"}
                            for m in range(1, 7)] if "month" in missing else [])
                return {**base, "action": None, "params": params,
                        "clarification": f"请问要分析{ask}？",
                        "options": options, "result": None}

    ctx = AnalysisContext(product=product or "", month=month or "", params=params)
    result = pipeline.run(intent, ctx)
    # 执行成功才挂联动动作（跳转/筛选写入由前端执行，路由只分发）
    action = _make_action(intent, product, month, params.get("view"),
                          params.get("anchor"), params.get("anchor_title")) \
        if result.get("ok") else None
    return {**base, "action": action, "params": params, "clarification": None,
            "options": None, "result": result}
