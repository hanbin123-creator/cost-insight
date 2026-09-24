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


# ---------- 9. 低置信与双不中 → 四入口（不猜） ----------

def test_low_confidence_returns_choices(pipeline):
    out = route("银黄口服液5月", pipeline, llm=_llm("report", 0.4))
    assert out["layer"] == "fallback" and out["intent"] is None
    names = [c["name"] for c in out["result"]["choices"]]
    assert len(names) == 4                        # 四入口一个不少


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
    assert len(out["result"]["choices"]) == 4


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
