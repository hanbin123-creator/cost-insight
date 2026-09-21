"""板块⑥ 行动闭环 + Pipeline 编排器测试（板块4 方案 V2 测试计划 1-6/12/13）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import act
from app.compute import CostCalculator
from app.ingest import init_store
from app.pipeline import SCENES, Deps, Pipeline
from app.context import AnalysisContext
from app.schemas import RectifyTask


@pytest.fixture(scope="module")
def calc():
    store, _ = init_store()
    return CostCalculator(store)


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "t.db"


# ---------- 1. RectifyTask schema 闸 ----------

def _valid_task(**kw):
    base = dict(
        task_id="TASK-2026-0001", task_title="核查金银花采购价异常（原材料环比）",
        assignee={"name": "张伟", "department": "采购部", "role": "采购经理"},
        source={"analysis_type": "月度成本分析", "analysis_month": "2026-05",
                "product": "银黄口服液", "finding": "金银花采购价环比上涨 12%"},
        priority="high", deadline="2026-06-25", suggestion="核查调价条款",
        notify_method="wechat", created_at="2026-06-15T10:30:00")
    base.update(kw)
    return base


def test_rectify_task_schema_accepts_official_contract():
    t = RectifyTask(**_valid_task())
    assert t.priority == "high" and t.assignee.department == "采购部"
    # 演示后缀合法（官方 mock 状态机彩蛋）
    assert RectifyTask(**_valid_task(task_id="TASK-2026-0002-FAST")).task_id.endswith("FAST")


@pytest.mark.parametrize("field,bad", [
    ("task_id", "ZG-2026-05-01"),        # 旧内部格式必须被拒（官方格式统一）
    ("priority", "高"),                   # 中文优先级必须被拒（官方枚举英文）
    ("deadline", "2026年6月25日"),
])
def test_rectify_task_schema_rejects_illegal(field, bad):
    with pytest.raises(Exception):
        RectifyTask(**_valid_task(**{field: bad}))


# ---------- 2. 装配：规则映射 + 口径母本 ----------

def test_assemble_tasks_rule_mapping(calc):
    pack = calc.metrics("银黄口服液", "2026-05")
    assert pack.alerts, "锚定：该月必须有告警"
    tasks = act.assemble_tasks("银黄口服液", "2026-05", pack.alerts)
    t = tasks[0]
    assert t.task_id.startswith("TASK-2026-")
    assert t.deadline == "2026-06-25"                # 次月25日规则
    assert t.source.finding == pack.alerts[0].message  # finding=告警原文（同源）
    assert t.source.analysis_month == "2026-05"
    assert t.priority in ("high", "medium", "low")   # 中英映射已发生
    assert t.assignee.name != "待指派"                # 名册命中


# ---------- 3. 闸2 纪律实证：LLM 润色编造数字 → 回退代码版 ----------

def test_polish_fabrication_falls_back(calc):
    from app.llm import MockLLM
    pack = calc.metrics("银黄口服液", "2026-05")
    tasks = act.assemble_tasks("银黄口服液", "2026-05", pack.alerts)
    bad = {"items": [{"task_id": tasks[0].task_id,
                      "task_title": "成本暴涨 999.9 元需紧急核查",  # 编造数字
                      "suggestion": "立即整改"}]}
    out, src = act.polish_tasks(tasks, MockLLM(json.dumps(bad, ensure_ascii=False)),
                                pack.alerts)
    assert src == "template·部分润色被拦截"
    assert out[0].task_title == tasks[0].task_title  # 代码版原样保留


def test_polish_good_llm_adopted(calc):
    from app.llm import MockLLM
    pack = calc.metrics("银黄口服液", "2026-05")
    tasks = act.assemble_tasks("银黄口服液", "2026-05", pack.alerts)
    good = {"items": [{"task_id": t.task_id,
                       "task_title": f"专项核查：{t.task_title}",
                       "suggestion": t.suggestion} for t in tasks]}
    out, src = act.polish_tasks(tasks, MockLLM(json.dumps(good, ensure_ascii=False)),
                                pack.alerts)
    assert src == "llm"
    assert out[0].task_title.startswith("专项核查")


# ---------- 4. 发送链路：退避/确定性分类/不可达降级 ----------

def test_post_retries_on_5xx_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class R:
        status_code = 200
        def json(self):
            return {"code": 200, "data": {"status": "sent"}}
        text = ""

    class R5:
        status_code = 500
        text = "boom"
        def json(self):
            return {}

    def fake_post(url, json, timeout):
        calls["n"] += 1
        return R() if calls["n"] >= 3 else R5()

    monkeypatch.setattr(act.httpx, "post", fake_post)
    out = act._post("http://x/api", {}, backoff=(0.01, 0.01))
    assert out["code"] == 200 and calls["n"] == 3     # 两次退避后成功


def test_post_4xx_no_retry(monkeypatch):
    calls = {"n": 0}

    class R4:
        status_code = 400
        text = "task_title不能为空"
        def json(self):
            return {}

    def fake_post(url, json, timeout):
        calls["n"] += 1
        return R4()

    monkeypatch.setattr(act.httpx, "post", fake_post)
    with pytest.raises(act.RpaError, match="确定性不重试"):
        act._post("http://x/api", {}, backoff=(0.01, 0.01))
    assert calls["n"] == 1                              # 4xx 不浪费退避


def test_dispatch_rpa_down_marks_failed(calc, db, monkeypatch):
    def boom(url, json, timeout):
        raise act.httpx.ConnectError("refused")

    monkeypatch.setattr(act.httpx, "post", boom)
    res = act.dispatch("银黄口服液", "2026-05", calc, db_path=db, backoff=(0.01, 0.01))
    assert all(t["dispatch"] == "dispatch_failed" for t in res["tasks"])
    assert all("网络故障" in t["error"] for t in res["tasks"])
    # 落库如实记录失败（不假装成功）
    import sqlite3
    conn = sqlite3.connect(str(db))
    n = conn.execute("SELECT COUNT(*) FROM dispatch_log WHERE ok=0").fetchone()[0]
    conn.close()
    assert n == len(res["tasks"])


# ---------- 5. 微信消息体与任务同源 ----------

def test_wechat_message_mirrors_task(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent.update(json)
        class R:
            status_code = 200
            def json(self):
                return {"code": 200}
        return R()

    monkeypatch.setattr(act.httpx, "post", fake_post)
    t = RectifyTask(**_valid_task())
    out = act.notify_wechat(t, backoff=(0.01,))
    assert out["ok"] and sent["recipient"] == "张伟"
    assert "TASK-2026-0001" in sent["message"] and "2026-06-25" in sent["message"]


# ---------- 6. 追踪聚合 ----------

def test_tracking_aggregation(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"code": 200, "data": {"total": 4, "tasks": [
                {"status": "sent", "priority": "high"},
                {"status": "received", "priority": "high"},
                {"status": "confirmed", "priority": "medium"},
                {"status": "completed", "priority": "low"}]}}

    monkeypatch.setattr(act.httpx, "get", lambda *a, **k: R())
    out = act.tracking()
    agg = out["aggregate"]
    assert agg["已生成"] == 4 and agg["已送达"] == 3 and agg["已确认"] == 2
    assert agg["by_priority"] == {"high": 2, "medium": 1, "low": 1}


def test_tracking_unreachable(monkeypatch):
    def boom(*a, **k):
        raise act.httpx.ConnectError("refused")

    monkeypatch.setattr(act.httpx, "get", boom)
    out = act.tracking()
    assert out["ok"] is False and out["aggregate"] is None


# ---------- 12. dispatch 幂等（重发不重复） ----------

def test_dispatch_idempotent(calc, db, monkeypatch):
    class R:
        status_code = 200
        text = ""
        def json(self):
            return {"code": 200, "data": {"status": "sent"}}

    monkeypatch.setattr(act.httpx, "post", lambda *a, **k: R())
    r1 = act.dispatch("银黄口服液", "2026-05", calc, db_path=db, backoff=(0.01,))
    assert r1["tasks"] and all(t["dispatch"] == "sent" for t in r1["tasks"])
    r2 = act.dispatch("银黄口服液", "2026-05", calc, db_path=db, backoff=(0.01,))
    assert r2["tasks"] == [] and "幂等跳过" in r2["note"]


# ---------- 13. Pipeline 预设表 ----------

def test_pipeline_scenes_registered():
    assert set(SCENES) == {"report", "dashboard", "benchmark", "rectify"}


def test_pipeline_unknown_intent_and_scene_degradation(calc):
    p = Pipeline(Deps(calc=calc))
    out = p.run("nonexistent", AnalysisContext(product="银黄口服液", month="2026-05"))
    assert out["ok"] is False and "未注册场景" in out["error"]
    # 场景失败降级：benchmark 正常，report 无 LLM 也可出（模板句轨），
    # 用一个会炸的假 deps 验证单场景失败不影响分发器本身
    p2 = Pipeline(Deps(calc=None))
    out2 = p2.run("benchmark", AnalysisContext(product="银黄口服液", month="2026-05"))
    assert out2["ok"] is False and out2["scene"] == "对标分析"
    out3 = p.run("benchmark", AnalysisContext(product="银黄口服液", month="2026-05"))
    assert out3["ok"] is True and out3["data"]["product"] == "银黄口服液"


# ---------- API 端点 ----------

def test_rectify_endpoints(monkeypatch):
    from fastapi.testclient import TestClient

    from app import storage
    from app.api import app

    # 端点走真实库（db_path=None）：先清本用例的幂等记录，保证可重复运行
    conn = storage.connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS dispatch_log (
        task_id TEXT PRIMARY KEY, product TEXT, month TEXT, title TEXT,
        ok INTEGER, detail TEXT, created_at TEXT)""")
    conn.execute("DELETE FROM dispatch_log WHERE product='板蓝根颗粒'")
    conn.commit()
    conn.close()

    class R:
        status_code = 200
        text = ""
        def json(self):
            return {"code": 200, "data": {"status": "sent"}}

    monkeypatch.setattr(act.httpx, "post", lambda *a, **k: R())
    with TestClient(app) as client:
        r = client.post("/api/rectify/dispatch",
                        json={"product": "板蓝根颗粒", "month": "2026-05",
                              "speed": "FAST"})
        assert r.status_code == 200
        d = r.json()
        assert d["tasks"], "告警月必须有任务"
        assert d["tasks"][0]["task_id"].endswith("-FAST")   # 演示后缀透传
        assert d["tasks"][0]["dispatch"] == "sent"
        r2 = client.post("/api/rectify/dispatch",
                         json={"product": "不存在", "month": "2026-05"})
        assert r2.status_code == 404

    # 清理本用例落库记录，不污染真实库
    conn = storage.connect()
    conn.execute("DELETE FROM dispatch_log WHERE product='板蓝根颗粒'")
    conn.commit()
    conn.close()
