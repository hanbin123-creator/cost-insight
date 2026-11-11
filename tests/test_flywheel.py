"""数据飞轮测试（A1）：沉淀幂等 + 状态门槛 + 语料文本契约。"""
from app import flywheel

_TASK = {
    "task_id": "TASK-2026-0001", "task_title": "核查金银花异常（累计涨幅）",
    "status": "confirmed", "priority": "high", "deadline": "2026-06-25",
    "suggestion": "核查采购合同调价条款",
    "assignee": {"name": "张三", "department": "采购部", "role": None},
    "source": {"analysis_type": "月度成本分析", "analysis_month": "2026-05",
               "product": "银黄口服液", "finding": "金银花行情价累计+12%"},
}


def test_record_text_self_contained():
    """语料文本自包含：任务编号/异常发现/建议/部门/状态全部在文，可追溯。"""
    text = flywheel.record_text(_TASK)
    for key in ("TASK-2026-0001", "金银花行情价累计+12%", "核查采购合同调价条款",
                "采购部", "confirmed", "2026-05", "银黄口服液"):
        assert key in text, f"语料缺字段 {key}: {text}"


def test_record_text_tolerates_flat_fields():
    """RPA 精简视图容错：assignee/source 为字符串时照常成文，不崩。"""
    flat = {**_TASK, "assignee": "采购部", "source": "金银花行情价累计+12%"}
    text = flywheel.record_text(flat)
    assert "采购部" in text and "金银花行情价累计+12%" in text


def test_harvest_idempotent(tmp_path):
    """幂等：同一任务重复追踪只沉淀一次，第二次 harvest 返回空。"""
    doc = tmp_path / "经验.txt"
    first = flywheel.harvest([_TASK], db_path=tmp_path / "t.db", doc_path=doc)
    assert len(first) == 1
    assert "TASK-2026-0001" in doc.read_text(encoding="utf-8")
    second = flywheel.harvest([_TASK], db_path=tmp_path / "t.db", doc_path=doc)
    assert second == []


def test_harvest_status_gate(tmp_path):
    """状态门槛：sent/received 只是送达回执，不沉淀；confirmed 起才沉淀。"""
    doc = tmp_path / "经验.txt"
    sent = {**_TASK, "status": "sent"}
    assert flywheel.harvest([sent], db_path=tmp_path / "t.db", doc_path=doc) == []
    assert not doc.exists()
    for ok in ("confirmed", "in_progress", "completed"):
        t = {**_TASK, "task_id": f"TASK-{ok}", "status": ok}
        assert len(flywheel.harvest([t], db_path=tmp_path / "t.db",
                                    doc_path=doc)) == 1
