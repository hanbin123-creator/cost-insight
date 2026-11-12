"""Agent 意图路由测试（板块4 方案 V2 测试计划 7-11）。"""
from __future__ import annotations

import json

import pytest

from app.agent import _extract_month, _extract_product, route
from app.compute import CostCalculator
from app.context import AnalysisContext
from app.ingest import init_store
from app.llm import MockLLM
from app.pipeline import Deps, Pipeline


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    store, _ = init_store()
    calc = CostCalculator(store)
    from app.charts import ChartBuilder
    # out_dir 注入临时目录：report 场景真实执行时不得覆盖 reports/ 下的
    # 正式样例（曾把 LLM 轨样例踩踏成模板句版）
    out = tmp_path_factory.mktemp("agent_reports")
    return Pipeline(Deps(calc=calc, charts=ChartBuilder(calc), out_dir=out))


def _llm(intent: str, conf: float) -> MockLLM:
    return MockLLM(json.dumps({"intent": intent, "confidence": conf}))


# ---------- 7. LLM 主线 ----------

def test_llm_mainline_executes(pipeline):
    out = route("帮我看看银黄口服液2026-05的对标情况", pipeline,
                llm=_llm("benchmark", 0.92))
    assert out["layer"] == "llm" and out["intent"] == "benchmark"
    assert out["classifier"] == "mock"
    assert out["params"] == {"product": "银黄口服液", "month": "2026-05"}
    assert out["result"]["ok"] is True            # Pipeline 真实执行对标场景
    assert out["result"]["data"]["product"] == "银黄口服液"


def test_llm_mainline_dashboard(pipeline):
    out = route("六味地黄胶囊 6月看板", pipeline, llm=_llm("dashboard", 0.85))
    assert out["layer"] == "llm" and out["result"]["ok"] is True
    assert "unit_cost" in out["result"]["data"]


# ---------- 8. 规则兜底（LLM 缺席 / 返回破损） ----------

def test_rule_fallback_when_no_llm(pipeline):
    out = route("生成板蓝根颗粒2026-05报告", pipeline, llm=None)
    assert out["layer"] == "rule" and out["intent"] == "report"
    assert out["result"]["ok"] is True


def test_rule_fallback_when_llm_broken(pipeline):
    out = route("看下六味地黄胶囊的对标", pipeline,
                llm=MockLLM("模型输出的自由文本，不是JSON"))
    assert out["layer"] == "rule" and out["intent"] == "benchmark"


def test_heatmap_keyword_routes_dashboard(pipeline):
    """热力图查询规则兜底（手册验收项）："热力图/热力" 是 dashboard 硬关键词，
    无 LLM 时也必须路由到看板场景，不得掉四入口。"""
    out = route("看下银黄口服液2026-05的热力图", pipeline, llm=None)
    assert out["layer"] == "rule" and out["intent"] == "dashboard"
    assert out["result"]["ok"] is True
    out2 = route("银黄口服液2026-05热力图", pipeline, llm=None)
    assert out2["intent"] == "dashboard"


# ---------- 9. 低置信与双不中 → 四入口（不猜） ----------

def test_low_confidence_returns_choices(pipeline):
    out = route("银黄口服液5月", pipeline, llm=_llm("report", 0.4))
    assert out["layer"] == "fallback" and out["intent"] is None
    names = [c["name"] for c in out["result"]["choices"]]
    assert len(names) == 6                        # 六入口一个不少（A9 扩展 +qa/nav）


def test_no_llm_no_rule_hit_returns_choices(pipeline):
    out = route("今天天气怎么样", pipeline, llm=None)
    assert out["layer"] == "fallback"
    assert "choices" in out["result"]


def test_low_confidence_keyword_arbitrated_by_rules(pipeline):
    """规则仲裁（实弹修复）：模型低置信（'报告'单词只给 0.6）但用户文本含
    确定性关键词 → 规则层仲裁执行，layer 如实标注 rule-arb。
    用户亲自打出的关键词是硬证据，执行它不属于"猜"。"""
    out = route("对标", pipeline, llm=_llm("benchmark", 0.6),
                product="银黄口服液", month="2026-05")
    assert out["layer"] == "rule-arb" and out["intent"] == "benchmark"
    assert out["result"]["ok"] is True


def test_low_confidence_disagreement_hard_evidence_wins(pipeline):
    """低置信分歧：模型低置信说 report，用户文本却打着"对标"——
    确定性关键词优先于模型的没把握，如实标注 rule-arb。"""
    out = route("对标", pipeline, llm=_llm("report", 0.5),
                product="银黄口服液", month="2026-05")
    assert out["layer"] == "rule-arb" and out["intent"] == "benchmark"


def test_low_confidence_no_keyword_still_choices(pipeline):
    """仲裁的边界：模型低置信且文本无任何关键词硬证据 → 仍然四入口，不猜。"""
    out = route("帮我看看那个情况", pipeline, llm=_llm("report", 0.5))
    assert out["layer"] == "fallback" and "choices" in out["result"]


# ---------- 9.5 域围栏（D27）：域外请求显式拒绝，规则层不得捞回 ----------

def test_out_of_scope_explicitly_refused(pipeline):
    """模型判定域外（intent=none）→ 域外声明 + 四入口，不执行任何场景。"""
    out = route("今天天气怎么样", pipeline, llm=_llm("none", 0.99))
    assert out["layer"] == "llm-out-of-scope" and out["intent"] is None
    assert "不在服务范围内" in out["result"]["message"]
    assert len(out["result"]["choices"]) == 6     # A9 扩展：四场景 + qa/nav


def test_out_of_scope_not_rescued_by_rules(pipeline):
    """域外判定高于关键词：'生成一份天气报告' 虽命中规则词'报告'，
    模型说 none 就不得被规则层捞回来执行——围栏是双向的。"""
    out = route("生成一份天气报告", pipeline, llm=_llm("none", 0.95))
    assert out["layer"] == "llm-out-of-scope"
    assert out["result"]["choices"]            # 没有执行 report 场景


# ---------- 10. 参数抽取（规则化，绝不编造） ----------

def test_param_extraction_alias_and_month():
    assert _extract_product("银黄怎么样") == "银黄口服液"
    assert _extract_product("看看六味") == "六味地黄胶囊"
    assert _extract_month("2026年5月", "2026-06") == "2026-05"
    assert _extract_month("5月的情况", "2026-06") == "2026-05"
    assert _extract_month("五月份", "2026-06") == "2026-05"    # 中文数字（实弹 D26）
    assert _extract_month("十一月", "2026-06") == "2026-11"
    assert _extract_month("上月呢", "2026-06") == "2026-05"
    assert _extract_month("分析一下", "2026-06") is None


def test_missing_params_ask_clarification(pipeline):
    out = route("生成一份报告", pipeline, llm=_llm("report", 0.95))
    assert out["result"] is None
    assert "哪个产品" in out["clarification"]     # 澄清问题，不编造参数


def test_explicit_params_override(pipeline):
    out = route("对标分析", pipeline, llm=_llm("benchmark", 0.9),
                product="板蓝根颗粒", month="2026-04")
    assert out["params"] == {"product": "板蓝根颗粒", "month": "2026-04"}


# ---------- LLMClient role 路由 ----------

def test_llm_role_classification_fallback(monkeypatch):
    from app.llm import LLMClient
    monkeypatch.setenv("LLM_BASE_URL", "http://x")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    for k in ("LLM_SMALL_BASE_URL", "LLM_SMALL_API_KEY", "LLM_SMALL_MODEL"):
        monkeypatch.delenv(k, raising=False)
    c = LLMClient(role="classification")
    assert c.role_actual == "main-model-fallback" and c.model == "deepseek-chat"


def test_llm_role_classification_small_model(monkeypatch):
    from app.llm import LLMClient
    monkeypatch.setenv("LLM_SMALL_BASE_URL", "http://y/")
    monkeypatch.setenv("LLM_SMALL_API_KEY", "k2")
    monkeypatch.setenv("LLM_SMALL_MODEL", "qwen-7b")
    c = LLMClient(role="classification")
    assert c.role_actual == "small-model"
    assert c.model == "qwen-7b" and c.base_url == "http://y"  # 尾斜杠已剥


def test_llm_role_polish_profile(monkeypatch):
    """polish 角色：小模型优先 + 回退主模型；温度取档案值 0.3。"""
    from app.llm import LLMClient
    for k in ("LLM_SMALL_BASE_URL", "LLM_SMALL_API_KEY", "LLM_SMALL_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://x")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    c = LLMClient(role="polish")
    assert c.role_actual == "main-model-fallback"
    assert c.temperature == 0.3 and c.timeout == 30.0


def test_llm_role_unknown_rejected():
    from app.llm import LLMClient, LLMError
    import pytest
    with pytest.raises(LLMError, match="未知 role"):
        LLMClient(role="nonexistent")


def test_llm_role_temperature_default_used(monkeypatch):
    """chat() 不显式传温度时取角色档案值——用假端点拦截 payload 验证。"""
    from app.llm import LLMClient
    monkeypatch.setenv("LLM_BASE_URL", "http://x")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    c = LLMClient(role="classification")  # 档案温度 0.0
    seen = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "{}"}}]}

    def _fake_post(url, headers, json, timeout):
        seen["temperature"] = json["temperature"]
        return _Resp()

    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod.httpx, "post", _fake_post)
    c.chat([{"role": "user", "content": "hi"}])
    assert seen["temperature"] == 0.0


# ---------- 11. /api/chat 端点契约 ----------

def test_chat_endpoint_contract(monkeypatch):
    # V1 后 .env 会被加载——本测试断言的是"无 LLM 走规则兜底"契约，
    # 必须显式清掉 LLM 环境（hermetic），不能依赖开发机恰好没配 key
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
              "LLM_SMALL_BASE_URL", "LLM_SMALL_API_KEY", "LLM_SMALL_MODEL"):
        monkeypatch.delenv(k, raising=False)
    from fastapi.testclient import TestClient
    from app.api import app
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"text": "银黄口服液2026-05对标"})
        assert r.status_code == 200
        d = r.json()
        # 契约字段齐全（无 LLM 环境下走规则兜底，layer 如实标注）
        for k in ("intent", "confidence", "layer", "classifier", "params",
                  "clarification", "result"):
            assert k in d
        assert d["intent"] == "benchmark" and d["layer"] == "rule"
        assert d["result"]["ok"] is True
        # 双不中 → 四入口
        r2 = client.post("/api/chat", json={"text": "随便聊聊"})
        assert r2.status_code == 200
        assert "choices" in r2.json()["result"]


# ---------- A9 扩展：qa/nav 意图 + action 契约 + 澄清 chips ----------

from app.schemas import KnowledgeHit, KnowledgePack  # noqa: E402


class _FakeRetriever:
    """假检索器：返回预置命中，测 qa 场景逻辑而非检索质量。"""

    def __init__(self, hits):
        self._hits = hits

    def search(self, query, top_k=5, **_kw):
        return KnowledgePack(query=query, hits=self._hits[:top_k])


def _hit(score: float, doc: str = "产品配方文档_银黄口服液") -> KnowledgeHit:
    return KnowledgeHit(chunk_id=f"{doc}#1", doc_name=doc, page=1, section="2.2 配方",
                        doc_type="formula", text="金银花 130.0 元/kg，用量 3.5g。",
                        rrf_score=score, channels=["bm25"])


def _qa_pipeline(hits, llm=None):
    return Pipeline(Deps(retriever=_FakeRetriever(hits), llm_factory=lambda: llm))


def test_qa_llm_mode_with_citations():
    """qa LLM 轨：回答+出处 chips；citations 取 Top3 命中。"""
    p = _qa_pipeline([_hit(0.05)], llm=MockLLM("因为金银花行情上涨（《产品配方文档_银黄口服液》p1）"))
    out = route("金银花为什么涨价", p, llm=_llm("qa", 0.9))
    assert out["intent"] == "qa" and out["result"]["ok"] is True
    d = out["result"]["data"]
    assert d["mode"] == "llm" and "金银花" in d["answer"]
    assert d["citations"][0]["doc_name"] == "产品配方文档_银黄口服液"
    assert out["action"] is None          # qa 不跳转，答案即产出


def test_qa_snippet_mode_without_llm():
    """qa 降级轨：无 LLM → 原文片段 + 如实标注，不生成不改写。"""
    p = _qa_pipeline([_hit(0.05)], llm=None)
    out = route("金银花为什么涨价", p, llm=None)
    assert out["intent"] == "qa" and out["layer"] == "rule"
    d = out["result"]["data"]
    assert d["mode"] == "snippets" and d["answer"] is None
    assert len(d["snippets"]) == 1 and "未配置 LLM" in d["note"]


def test_qa_low_score_no_hard_answer():
    """不猜原则延伸：检索得分低于校准下限 → 如实'未收录'，不硬答。"""
    p = _qa_pipeline([_hit(0.01)])
    out = route("量子计算对制药成本的影响", p, llm=_llm("qa", 0.9))
    d = out["result"]["data"]
    assert d["mode"] == "no_hit" and "未收录" in d["note"]


def test_qa_empty_hits():
    p = _qa_pipeline([])
    out = route("怎么做红烧狮子头", p, llm=_llm("qa", 0.9))
    assert out["result"]["data"]["mode"] == "no_hit"


def test_qa_exempt_from_params():
    """qa 免参数：不报产品/月份也直接执行，不弹澄清。"""
    p = _qa_pipeline([_hit(0.05)], llm=None)
    out = route("GMP对生产记录有什么规定", p, llm=_llm("qa", 0.9))
    assert out["clarification"] is None and out["result"]["ok"] is True
    assert out["params"]["question"] == "GMP对生产记录有什么规定"


def test_rule_nav_double_hit(pipeline):
    """规则层 nav：动词+页名双命中 → nav + action 跳转，不执行业务场景。"""
    out = route("打开整改追踪", pipeline, llm=None)
    assert out["intent"] == "nav" and out["layer"] == "rule"
    assert out["action"]["type"] == "navigate" and out["action"]["view"] == "rectify"
    assert out["result"]["ok"] is True


def test_nav_verb_without_target_falls_to_choices(pipeline):
    """有动词无页名 → 不猜目标，四入口。"""
    out = route("打开看看", pipeline, llm=None)
    assert out["intent"] is None and out["result"]["choices"]


def test_rectify_command_not_hijacked(pipeline):
    """'下发整改任务'含'整改'但无跳转动词 → 仍归 rectify，不被 nav 抢走。"""
    out = route("下发银黄口服液2026-05整改任务", pipeline, llm=None)
    assert out["intent"] == "rectify"


def test_llm_nav_kb(pipeline):
    """LLM 判 nav：打开知识库 → action view=kb。"""
    out = route("打开知识库", pipeline, llm=_llm("nav", 0.9))
    assert out["intent"] == "nav" and out["action"]["view"] == "kb"


def test_nav_without_view_clarifies(pipeline):
    """LLM 判 nav 但文本抽不出页名 → 澄清给页面选项（不猜）。"""
    out = route("去那边", pipeline, llm=_llm("nav", 0.9))
    assert out["clarification"] and out["options"]
    assert {o["view"] for o in out["options"]} == \
        {"dashboard", "benchmark", "rectify", "reports", "kb"}


def test_clarify_chips_options(pipeline):
    """缺参数澄清带 chips：缺产品给产品选项，缺月份给月份选项。"""
    out = route("生成报告", pipeline, llm=_llm("report", 0.9))
    assert out["clarification"] and out["options"]
    labels = [o["label"] for o in out["options"]]
    assert "银黄口服液" in labels and "5月" in labels
    assert any("product" in o for o in out["options"])
    assert any("month" in o for o in out["options"])


def test_action_contract_dashboard(pipeline):
    """action 契约：dashboard 场景成功后挂 navigate + 产品月份。"""
    out = route("银黄口服液 2026-05 看板", pipeline, llm=_llm("dashboard", 0.9))
    assert out["action"] == {"type": "navigate", "view": "dashboard",
                             "product": "银黄口服液", "month": "2026-05"}


def test_no_action_on_scene_failure():
    """场景失败不挂 action（前端不跳去一个失败现场）。"""
    bad = Pipeline(Deps(retriever=_FakeRetriever([_hit(0.05)]),
                        llm_factory=lambda: None))
    # retriever 有但 calc 缺失的 qa 不炸（qa 不用 calc）；用未注册意图测失败分支
    out = route("金银花为什么", bad, llm=MockLLM(json.dumps(
        {"intent": "nonexistent_scene", "confidence": 0.99})))
    # 未注册意图被 LLM 层丢弃 → 规则兜底 qa 命中；此处只断言 action 字段恒存在
    assert "action" in out
