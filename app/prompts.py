"""板块④ Prompt 契约：把 MetricsPack + KnowledgePack 装配成大模型输入。

核心纪律（"大模型永不算数"在生成层的落地）：
- 所有数字由代码算好放进产物包，模型只能**引用**不能**计算**——包括口径换算
- 模型输出为结构化 JSON，并对用过的每个数字、每条出处做**声明**；
  声明之外的数字/出处由 generate.py 校验器判为幻觉（声明制对账）
- 假设口径（稳价辅料）与双向口径描述句由代码预生成，模型引用时必须保留标注
"""
from __future__ import annotations

from .schemas import KnowledgePack, MetricsPack

SYSTEM_PROMPT = """你是制药企业成本分析助手，负责把结构化数据组织成归因分析文字。

铁律（违反任何一条，输出将被系统判为不合格并退回）：
1. 你只组织语言，永不计算。所有数字必须原样取自输入的指标包/知识包，
   不得做任何加减乘除、口径换算、四舍五入后的再加工
2. 输出 JSON 中每个 cause 的 figures 字段必须声明 detail 正文用到的全部数字
3. 引用知识出处用 citations 字段声明 chunk_id；正文引用写作《文档名》p页码"章节名"
4. 指标包中 note 字段含"假设口径"的分解结果，引用时必须保留"按稳价假设"字样
5. 对标描述直接使用 description 字段原文，不得改写其中的数字与口径
6. 贡献度为负时，表述为"该要素逆势变动，部分抵消了总成本的反向变动"，
   不得把负贡献度写成"降低了成本"
7. 知识包未覆盖的问题，明确说"知识库中未见相关记录"，禁止编造出处
8. 金额/成本/百分比数字必须按产物包原值完整引用，保留原值小数位（如 11.21），
   禁止写成"约 11 元""11.2 元"等取整或再舍入形式；禁止用"约/左右/大概"修饰数字"""

USER_TEMPLATE = """请为以下分析条件生成归因报告（JSON 输出）：

【分析条件】产品：{product} ｜ 月份：{month}

【指标包】（代码计算结果，数字唯一来源）
{metrics_json}

【知识包】（检索到的制药知识，引用唯一来源）
{knowledge_json}

【输出格式】严格输出 JSON，不要输出任何其他文字：
{{
  "summary": "总起段：本月单位成本/环比/同比/预算偏差的客观陈述",
  "causes": [
    {{"title": "结论标题", "detail": "论述正文",
      "figures": [正文中出现的数字], "citations": ["chunk_id"]}}
  ],
  "suggestions": ["可落地建议，每条对应至少一个 cause"]
}}"""


def build_attribution_messages(metrics: MetricsPack,
                               knowledge: KnowledgePack) -> list[dict]:
    """装配 system + user 消息。产物包序列化为 JSON 原文注入，模型只读。"""
    user = USER_TEMPLATE.format(
        product=metrics.product, month=metrics.month,
        metrics_json=metrics.model_dump_json(indent=2),
        knowledge_json=knowledge.model_dump_json(indent=2))
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user}]


def build_queries(product: str, month: str, metrics: MetricsPack) -> list[str]:
    """分面多查询（决策 I 精细化）：每个 facet 精确瞄准一类证据，替代单条宽查询。

    证据-文档映射（由知识库结构实证得出）：
    - 材料/行情面 → 配方文档的处方组成与历史变更记录
    - 设备/制造面 → 设备清单的维修历史（仅在制造费用或产量异常时启用，避免泛化噪声）
    - 工艺面 → 生产工艺文档（要素环比最大者定向）
    """
    queries: list[str] = []
    # 面①：材料行情面——量差价差影响前 2 的材料逐个定向（比"材料 涨价"宽查询精确）
    decomp = sorted((d for d in metrics.decomposition if d.qty_effect is not None),
                    key=lambda d: abs((d.price_effect or 0) + (d.qty_effect or 0)),
                    reverse=True)[:2]
    for d in decomp:
        queries.append(f"{product} {d.material} 处方用量 价格 历史变更")
    # 面②：要素异常面——环比绝对值最大的要素定向工艺文档
    elems = [(n, e.mom_pct) for n, e in metrics.elements.items() if e.mom_pct is not None]
    if elems:
        top_elem = max(elems, key=lambda kv: abs(kv[1]))[0]
        queries.append(f"{product} 生产工艺 {top_elem} 工序")
    # 面③：设备/制造面——仅当制造费用环比为正或产量环比下降时启用（条件触发）
    ov = metrics.elements.get("制造费用")
    if (ov and ov.mom_pct is not None and ov.mom_pct > 0) or \
       any(a.channel == "要素环比" for a in metrics.alerts):
        queries.append(f"{product} 设备 故障 维修 停机 折旧")
    # 面④：告警面——每条告警的要素词（行情累计/原材料环比通道捕捉到的具体药材）
    for a in metrics.alerts[:2]:
        queries.append(f"{a.element} 市场行情 质量标准")
    return queries or [f"{product} {month} 成本 配方 工艺"]


def build_query(product: str, month: str, metrics: MetricsPack) -> str:
    """兼容旧接口：单宽查询（仅供对照测试用，生产路径用 build_queries）。"""
    return " ".join(build_queries(product, month, metrics))
