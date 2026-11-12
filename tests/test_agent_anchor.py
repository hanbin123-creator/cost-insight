"""A11 内容级跳转测试：锚点抽取 / 指代消解 / 降级链（不猜原则的内容级延伸）。"""
from __future__ import annotations

import json

import pytest

from app.agent import _extract_anchor, _llm_pick_anchor, route
from app.compute import CostCalculator
from app.ingest import init_store
from app.llm import MockLLM
from app.pipeline import Deps, Pipeline

KB_DOCS = ["产品配方文档_银黄口服液.txt", "生产工艺_板蓝根颗粒.docx",
           "数据飞轮_整改经验记录.txt"]


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    store, _ = init_store()
    calc = CostCalculator(store)
    from app.charts import ChartBuilder
    out = tmp_path_factory.mktemp("agent_anchor_reports")
    return Pipeline(Deps(calc=calc, charts=ChartBuilder(calc), out_dir=out))


# ---------- 规则链：动词+内容锚点（无 LLM 也必须能跳，降级哲学优先） ----------

def test_rule_nav_anchor_heatmap(pipeline):
    """"打开热力图"无页名也跳：锚点推出页面，动作携带 anchor。"""
    out = route("打开热力图", pipeline, llm=None)
    assert out["intent"] == "nav" and out["layer"] == "rule"
    assert out["params"]["view"] == "dashboard"
    assert out["params"]["anchor"] == "dashboard:heatmap"
    assert out["action"]["anchor"] == "dashboard:heatmap"
    assert out["action"]["anchor_title"]
    assert out["result"]["ok"] is True


def test_rule_nav_anchor_benchmark(pipeline):
    out = route("打开材料差异下钻", pipeline, llm=None)
    assert out["intent"] == "nav"
    assert out["params"]["view"] == "benchmark"
    assert out["params"]["anchor"] == "benchmark:materials"


def test_page_level_nav_unchanged(pipeline):
    """页面级跳转行为不变："打开整改追踪" 只有 view 没有 anchor。"""
    out = route("打开整改追踪", pipeline, llm=None)
    assert out["intent"] == "nav" and out["params"]["view"] == "rectify"
    assert "anchor" not in out["action"]


def test_page_and_anchor_together(pipeline):
    """"打开看板的热力图"：页名+锚点双命中，以页名为准、锚点定位。"""
    out = route("打开看板的热力图", pipeline, llm=None)
    assert out["params"]["view"] == "dashboard"
    assert out["params"]["anchor"] == "dashboard:heatmap"


def test_no_verb_anchor_not_nav(pipeline):
    """无动词不提跳转："看看热力图" 仍归 dashboard 场景（看板速览），不是 nav。"""
    out = route("看下银黄口服液2026-05的热力图", pipeline, llm=None)
    assert out["intent"] == "dashboard"
    assert out["action"]["view"] == "dashboard"
    assert "anchor" not in out["action"]


# ---------- 知识库文档动态锚点 ----------

def test_kb_doc_anchor_by_tokens(pipeline):
    """文档名 token 重叠 ≥2 命中："打开银黄配方文档" → kb:doc:<全名>。"""
    out = route("打开银黄配方文档", pipeline, llm=None, kb_docs=KB_DOCS)
    assert out["intent"] == "nav" and out["params"]["view"] == "kb"
    assert out["params"]["anchor"] == "kb:doc:产品配方文档_银黄口服液.txt"


def test_kb_doc_anchor_full_stem(pipeline):
    out = route("打开数据飞轮_整改经验记录", pipeline, llm=None, kb_docs=KB_DOCS)
    assert out["params"]["anchor"] == "kb:doc:数据飞轮_整改经验记录.txt"


def test_kb_doc_no_match_falls_back(pipeline):
    """文档名对不上且规则无锚点、无 LLM → 不猜：落六入口卡片（规则链的正确降级）。
    nav 澄清 chips（当前页内容优先）只在 LLM 判了 nav 但抽不出目标时出现。"""
    out = route("打开不存在的文档", pipeline, llm=None, kb_docs=KB_DOCS)
    assert out["intent"] is None and out["action"] is None
    assert "choices" in out["result"]


# ---------- LLM 指代消解（第二趟选择题） ----------

def test_llm_pick_anchor_direct():
    hit = _llm_pick_anchor("打开这张图", "dashboard",
                           MockLLM('{"anchor": "dashboard:heatmap"}'))
    assert hit and hit["anchor"] == "dashboard:heatmap"


def test_llm_pick_anchor_null():
    assert _llm_pick_anchor("打开那个啥", "dashboard",
                            MockLLM('{"anchor": null}')) is None


def test_llm_pick_anchor_cross_view_rejected():
    """串台防御：模型选了别的页面的锚点 → 拒绝，等效没选。"""
    assert _llm_pick_anchor("打开这张图", "dashboard",
                            MockLLM('{"anchor": "kb:docs"}')) is None


def test_llm_pick_anchor_broken_json():
    assert _llm_pick_anchor("打开这张图", "dashboard",
                            MockLLM("不是JSON")) is None


def test_llm_deictic_integration(pipeline):
    """端到端：LLM 判 nav → 规则无目标 → 第二趟选锚点（canned 队列依次返回）。"""
    llm = MockLLM([json.dumps({"intent": "nav", "confidence": 0.9}),
                   '{"anchor": "dashboard:heatmap"}'])
    out = route("打开这张图", pipeline, llm=llm, view="dashboard")
    assert out["intent"] == "nav" and out["layer"] == "llm"
    assert out["params"]["anchor"] == "dashboard:heatmap"
    assert out["action"]["anchor"] == "dashboard:heatmap"


def test_llm_deictic_unsure_falls_to_content_chips(pipeline):
    """LLM 指代消解也拿不准 → 当前页内容 chips 在前、页面 chips 在后，不猜。"""
    llm = MockLLM([json.dumps({"intent": "nav", "confidence": 0.9}),
                   '{"anchor": null}'])
    out = route("打开那个", pipeline, llm=llm, view="dashboard")
    assert out["clarification"] and out["action"] is None
    anchors = [o.get("anchor") for o in out["options"]]
    assert "dashboard:heatmap" in anchors        # 内容 chips 带锚点
    assert any(o.get("view") == "kb" for o in out["options"])   # 页面 chips 仍在


# ---------- 锚点抽取单测（枚举制不猜测） ----------

def test_extract_anchor_longest_keyword():
    hit = _extract_anchor("看看这个热力图")
    assert hit["anchor"] == "dashboard:heatmap"
    assert hit["view"] == "dashboard"


def test_extract_anchor_unknown_returns_none():
    assert _extract_anchor("看看今天天气") is None
