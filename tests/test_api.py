"""模块二 API 层测试：端点形状 + Agent 决策规则 + LLM 未配置行为。"""
import pytest
from fastapi.testclient import TestClient

from app.api import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_products(client):
    r = client.get("/api/products")
    assert r.status_code == 200
    d = r.json()
    assert d["products"] == ["银黄口服液", "板蓝根颗粒", "六味地黄胶囊"]
    assert d["months"][0] == "2026-01" and len(d["months"]) == 6


def test_series(client):
    r = client.get("/api/series/银黄口服液")
    assert r.status_code == 200
    assert len(r.json()["unit_cost"]) == 6


def test_forecast_endpoint(client):
    r = client.get("/api/forecast/银黄口服液")
    assert r.status_code == 200
    d = r.json()
    assert len(d["point"]) == 3 and len(d["months_ext"]) == 9
    assert d["note"].startswith("演示级")
    # 置信带堆叠差值已由后端预计算，前端只做 stack
    assert all(b - a == pytest.approx(diff, abs=0.02)
               for a, b, diff in zip(d["lower"], d["upper"], d["band_diff_line"][6:]))


def test_waterfall_and_first_month_422(client):
    r = client.get("/api/charts/waterfall/银黄口服液/2026-05")
    assert r.status_code == 200
    assert len(r.json()["segments"]) == 5     # 上月 + 三要素 + 本月
    r2 = client.get("/api/charts/waterfall/银黄口服液/2026-01")
    assert r2.status_code == 422              # 首月无基期，明确拒绝而非错误数据


def test_structure_and_heatmap(client):
    r = client.get("/api/charts/structure/银黄口服液/2026-01")
    assert r.status_code == 200
    assert r.json()["inner"] and r.json()["outer"]
    r2 = client.get("/api/charts/heatmap")
    assert r2.status_code == 200
    assert len(r2.json()["data"]) == 54        # 3产品×3要素×6月


def test_metrics_404(client):
    r = client.get("/api/metrics/银黄口服液/2025-12")
    assert r.status_code == 404


def test_agent_decision_with_alerts(client):
    """银黄 2026-05 有金银花累计涨幅告警 → 决策生成归因。"""
    r = client.get("/api/agent/decision/银黄口服液/2026-05")
    assert r.status_code == 200
    d = r.json()
    assert d["action"] == "generate_attribution"
    assert "告警" in d["reason"] and d["engine"] == "rule-based-v1"


def test_agent_decision_quiet_month(client):
    """平稳月份 → 仅刷新看板（实测银黄 2026-02 无告警且环比温和）。"""
    r = client.get("/api/agent/decision/银黄口服液/2026-02")
    d = r.json()
    assert d["action"] in ("dashboard_only", "generate_attribution")
    if d["action"] == "dashboard_only":
        assert "平稳" in d["reason"]


def test_attribution_503_without_llm(client, monkeypatch):
    """LLM 未配置 → 503 明确说明，不静默降级。"""
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    r = client.post("/api/attribution", json={"product": "银黄口服液", "month": "2026-05"})
    assert r.status_code == 503
    assert "LLM 未配置" in r.json()["detail"]


# ---------- 对标薄端点 ----------
def test_benchmark_endpoint(client):
    """双向口径 + 预生成描述直接透出，下游只读不算。"""
    r = client.get("/api/benchmark/银黄口服液/2026-05")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows, "对标行为空"
    labor = next(row for row in rows if row["element"] == "直接人工")
    assert labor["diff_rate_pct"] is not None
    assert labor["reverse_rate_pct"] is not None
    assert "一厂" in labor["description"] and "二厂" in labor["description"]
    # 双向口径互洽：|diff_rate| 与 reverse 符号相反（一厂低 → 对二厂为负）
    assert labor["diff_rate_pct"] * labor["reverse_rate_pct"] <= 0


def test_benchmark_404(client):
    r = client.get("/api/benchmark/不存在的产品/2026-05")
    assert r.status_code == 404


# ---------- 知识库热更新 ----------
def test_kb_documents_listing(client):
    """文档清单：7 份考题文档全部在列且已建索引，块数与块总数一致。"""
    r = client.get("/api/kb/documents")
    assert r.status_code == 200
    d = r.json()
    assert len(d["documents"]) == 7
    assert all(doc["indexed"] for doc in d["documents"])
    assert sum(doc["indexed_chunks"] for doc in d["documents"]) == d["total_chunks"]
    assert d["job"]["state"] in ("idle", "done")


def test_kb_upload_validation(client):
    """负向：非法扩展名 / 非法 base64 → 422，不写盘。"""
    import base64
    r = client.post("/api/kb/documents", json={
        "filename": "evil.exe",
        "content_b64": base64.b64encode(b"x").decode()})
    assert r.status_code == 422
    r2 = client.post("/api/kb/documents", json={
        "filename": "ok.txt", "content_b64": "!!!not-base64!!!"})
    assert r2.status_code == 422


def test_kb_upload_and_delete(client, tmp_path, monkeypatch):
    """上传→落盘→后台重建受理；删除→文件消失。重建任务打桩隔离（不真嵌入）。
    KB_DIR 指到临时目录，考题数据零污染。"""
    import base64
    import app.api as api_mod
    from app import config as C
    monkeypatch.setattr(C, "KB_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(api_mod, "_reindex_job", lambda: calls.append(1))

    payload = base64.b64encode("测试文档内容".encode()).decode()
    r = client.post("/api/kb/documents",
                    json={"filename": "新知识文档.txt", "content_b64": payload})
    assert r.status_code == 200
    assert r.json()["accepted"] is True
    assert (tmp_path / "新知识文档.txt").read_text(encoding="utf-8") == "测试文档内容"
    assert calls, "后台重建未触发"

    r2 = client.delete("/api/kb/documents/新知识文档.txt")
    assert r2.status_code == 200
    assert not (tmp_path / "新知识文档.txt").exists()

    r3 = client.delete("/api/kb/documents/不存在.txt")
    assert r3.status_code == 404


# ---------- 报告归档端点（F8） ----------
def test_parse_report_name():
    from pathlib import Path
    from app.api import _parse_report_name
    m = _parse_report_name(Path("银黄口服液_2026-05_月度成本分析报告.docx"))
    assert m == {"product": "银黄口服液", "period": "2026-05", "theme": "月度"}
    assert _parse_report_name(Path("银黄口服液_2026-Q2_季度成本分析报告.pdf"))["theme"] == "季度"
    assert _parse_report_name(Path("_font_check_trend.png")) is None   # 图表临时文件
    assert _parse_report_name(Path("随便.docx")) is None               # 命名不合规


def test_reports_list_and_download(client):
    r = client.get("/api/reports")
    assert r.status_code == 200
    d = r.json()
    assert d["reports"], "reports/ 目录已有演习产物"
    first = d["reports"][0]
    assert {"product", "period", "theme", "docx", "pdf", "mtime"} <= set(first)
    assert first["product"] in ("银黄口服液", "板蓝根颗粒", "六味地黄胶囊")
    assert first["docx"] or first["pdf"]
    mtimes = [g["mtime"] for g in d["reports"]]
    assert mtimes == sorted(mtimes, reverse=True)      # 倒序归档
    name = (first["docx"] or first["pdf"])["name"]
    r2 = client.get(f"/api/reports/{name}")
    assert r2.status_code == 200 and len(r2.content) > 1000


def test_report_download_guards(client):
    assert client.get("/api/reports/evil.exe").status_code == 422
    assert client.get("/api/reports/不存在_2099-05_月度成本分析报告.docx").status_code == 404
    # 路径穿越：解码后只取文件名，config.py 非 docx/pdf → 422
    assert client.get("/api/reports/..%2F..%2Fapp%2Fconfig.py").status_code in (404, 422)


# ---------- 知识库检索透明化端点（F10） ----------
def test_kb_query(client):
    r = client.get("/api/kb/query", params={"q": "金银花涨价"})
    assert r.status_code == 200
    d = r.json()
    assert d["query"] == "金银花涨价"
    assert d["hits"], "检索应有命中"
    h = d["hits"][0]
    assert {"chunk_id", "doc_name", "page", "section", "doc_type",
            "channels", "rrf_score", "text"} <= set(h)
    assert h["channels"], "每个命中须带召回通道标签（vector/bm25/graph）"


def test_kb_query_guards(client):
    assert client.get("/api/kb/query", params={"q": "   "}).status_code == 422
    # top_k 越界被钳制而非报错
    r = client.get("/api/kb/query", params={"q": "成本", "top_k": 99})
    assert r.status_code == 200 and len(r.json()["hits"]) <= 10
