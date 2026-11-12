"""内容级跳转登记册（A11 "指哪跳哪"）：Agent 只能从此清单选择锚点，不猜。

每条目 = 页内可定位内容的身份证：
- anchor   唯一标识（<view>:<部位> 命名；前端以 data-anchor 属性挂载同名锚点）
- view     所属页面（hash 路由名）
- title    语义名片（LLM 指代消解的选择题选项、前端跳转回执文案）
- keywords 规则兜底命中词（降级链：无 LLM 时"打开热力图"也必须能跳）

设计纪律（与 agent.py 铁律一致）：
① 清单外无目标——LLM 只能从此表选 id，选不出就是 null，落澄清 chips；
② 锚点跳转不携带任何数据，只携带位置（大模型永不算数）；
③ 知识库文档是动态目标，不入本表——由 agent._extract_anchor 运行时
   从检索器文档清单匹配（kb:doc:<文档名>）。
"""
from __future__ import annotations

CONTENT_TARGETS: list[dict] = [
    # 成本看板
    {"anchor": "dashboard:kpi", "view": "dashboard", "title": "KPI 指标卡",
     "keywords": ["KPI", "kpi", "指标卡"]},
    {"anchor": "dashboard:trend", "view": "dashboard", "title": "趋势图·近6月单位成本走势",
     "keywords": ["趋势图", "走势图", "趋势", "预测"]},
    {"anchor": "dashboard:structure", "view": "dashboard", "title": "结构图·本月成本构成",
     "keywords": ["结构图", "成本构成", "饼图", "环形图"]},
    {"anchor": "dashboard:waterfall", "view": "dashboard", "title": "瀑布图·成本变动分解",
     "keywords": ["瀑布图", "瀑布", "变动分解"]},
    {"anchor": "dashboard:heatmap", "view": "dashboard", "title": "热力图·产品×月份×要素环比",
     "keywords": ["热力图", "热力", "红格"]},
    {"anchor": "dashboard:alerts", "view": "dashboard", "title": "告警行动卡",
     "keywords": ["告警卡", "告警"]},
    {"anchor": "dashboard:attribution", "view": "dashboard", "title": "归因分析面板",
     "keywords": ["归因面板", "归因"]},
    # 对标分析
    {"anchor": "benchmark:table", "view": "benchmark", "title": "对标差异明细表",
     "keywords": ["差异表", "口径明细", "三步法"]},
    {"anchor": "benchmark:materials", "view": "benchmark", "title": "材料差异下钻",
     "keywords": ["材料下钻", "材料差异", "下钻"]},
    # 整改追踪
    {"anchor": "rectify:kanban", "view": "rectify", "title": "整改任务看板",
     "keywords": ["任务看板", "任务卡"]},
    # 报告中心
    {"anchor": "reports:list", "view": "reports", "title": "报告归档列表",
     "keywords": ["报告列表", "报告归档", "历史报告"]},
    {"anchor": "reports:usage", "view": "reports", "title": "LLM 用量行",
     "keywords": ["用量", "token", "Token"]},
    # 知识库
    {"anchor": "kb:docs", "view": "kb", "title": "文档清单",
     "keywords": ["文档清单", "文档管理", "文档列表"]},
]

# 文档名 token 匹配时剔除的通用词（"产品配方文档_银黄口服液" → 有效 token：配方/银黄口服液）
_GENERIC_TOKENS = ("产品", "文档", "记录", "清单", "企业", "公司")


def targets_for_view(view: str) -> list[dict]:
    """某页面可定位内容清单（指代消解选择题的候选集）。"""
    return [t for t in CONTENT_TARGETS if t["view"] == view]


def find_anchor(anchor: str | None) -> dict | None:
    """按 anchor id 查条目；未知 id 返回 None（清单外无目标）。"""
    if not anchor:
        return None
    return next((t for t in CONTENT_TARGETS if t["anchor"] == anchor), None)
