"""A3 报告签发状态机 + A6 告警统计口径测试。"""
import pytest
from fastapi.testclient import TestClient

from app.api import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------- A3：签发状态机 ----------
def test_approve_flow(client, tmp_path, monkeypatch):
    """待签发(缺省) → POST approve → 已签发带签发人留痕；列表状态同步。"""
    import app.api as api_mod
    (tmp_path / "银黄口服液_2026-05_月度成本分析报告.docx").write_bytes(b"x" * 100)
    monkeypatch.setattr(api_mod, "_REPORTS_DIR", tmp_path)
    monkeypatch.setattr(api_mod, "_REGISTRY_PATH", tmp_path / ".registry.json")

    r = client.get("/api/reports")
    rep = next(x for x in r.json()["reports"] if x["stem"].startswith("银黄口服液"))
    assert rep["status"] == "待签发"          # 未注册报告缺省为待签发

    r2 = client.post("/api/reports/approve/银黄口服液_2026-05_月度成本分析报告",
                     json={"approver": "王老师"})
    assert r2.status_code == 200
    d = r2.json()
    assert d["status"] == "已签发" and d["approved_by"] == "王老师"
    assert d["approved_at"]

    rep2 = next(x for x in client.get("/api/reports").json()["reports"]
                if x["stem"].startswith("银黄口服液"))
    assert rep2["status"] == "已签发" and rep2["approved_by"] == "王老师"


def test_approve_404(client, tmp_path, monkeypatch):
    """签发不存在的报告 → 404，不产生注册表副作用。"""
    import app.api as api_mod
    monkeypatch.setattr(api_mod, "_REPORTS_DIR", tmp_path)
    monkeypatch.setattr(api_mod, "_REGISTRY_PATH", tmp_path / ".registry.json")
    assert client.post("/api/reports/approve/不存在_2099-01_月度成本分析报告",
                       json={}).status_code == 404
    assert not (tmp_path / ".registry.json").exists()


# ---------- A3：页脚草稿戳 ----------
def test_draft_footer_stamp(tmp_path):
    """草稿戳写入每节主页脚；链接页脚不重复盖。"""
    import docx
    from app.render import _stamp_draft_footer
    doc = docx.Document()
    doc.add_paragraph("正文")
    assert _stamp_draft_footer(doc) == 1       # 默认模板一节
    out = tmp_path / "t.docx"
    doc.save(str(out))
    doc2 = docx.Document(str(out))
    texts = [p.text for p in doc2.sections[0].footer.paragraphs]
    assert any("内部草稿" in t and "待人工复核签发" in t for t in texts)


# ---------- A6：告警统计口径 ----------
def test_element_mom_std():
    """标准差参考：数据足够时返回 (std, n)；1 月（无环比序列）返回 None。"""
    from app.compute import CostCalculator
    from app.ingest import init_store
    calc = CostCalculator(init_store()[0])
    std = calc._element_mom_std("银黄口服液", "2026-06", "直接材料(元/盒)")
    assert std is not None and std[1] >= 3 and std[0] >= 0
    assert calc._element_mom_std("银黄口服液", "2026-01", "直接材料(元/盒)") is None
