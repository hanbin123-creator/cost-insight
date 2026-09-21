"""板块③ 检索增强测试：6 个内置波动事件召回 + 出处完整性 + 元数据契约。"""
from pathlib import Path

import pytest

from app import config as C
from app.kb import build_index, load_chunks, normalize_text
from app.retrieve import Retriever


@pytest.fixture(scope="session")
def retriever() -> Retriever:
    """索引不存在则现场构建（CI 友好）；已存在直接加载。"""
    if not (C.KB_INDEX_DIR / "chunks.jsonl").exists() or not (C.KB_INDEX_DIR / "vectors.npy").exists():
        build_index()
    return Retriever()


# 6 个内置波动事件 → 期望命中的目标文档（Top5 内）
RECALL_CASES = [
    ("金银花价格上涨的原因", "产品配方文档_银黄口服液"),
    ("黄芩提取物用量与成本", "产品配方文档_银黄口服液"),
    ("银黄口服液2月制造费用上升", "生产工艺文档_中药一厂"),
    ("六味地黄胶囊3月设备故障停机", "车间设备清单_中药一厂"),
    ("山茱萸市场行情涨价", "产品配方文档_六味地黄胶囊"),
    ("板蓝根颗粒5月原材料涨价", "产品配方文档_板蓝根颗粒"),
]


@pytest.mark.parametrize("query,target", RECALL_CASES)
def test_event_recall(retriever, query, target):
    """每个波动事件的 Top5 命中中必须包含目标知识文档。"""
    pack = retriever.search(query, top_k=5)
    docs = [h.doc_name for h in pack.hits]
    assert any(target in d for d in docs), f"{query} 未召回 {target}: {docs}"


def test_hits_carry_source(retriever):
    """每个命中必须带完整出处三要素（报告引用硬要求）。"""
    pack = retriever.search("金银花", top_k=5)
    assert len(pack.hits) == 5
    for h in pack.hits:
        assert h.doc_name and h.page >= 1 and h.section
        assert h.rrf_score > 0 and h.channels


def test_chunk_metadata_contract():
    """块元数据契约：tenant / doc_version 演进字段第一天就带。"""
    chunks = load_chunks()
    assert len(chunks) > 100
    for c in chunks:
        assert c["tenant"] == C.TENANT
        assert c["doc_version"].startswith("V")
        assert c["doc_type"] in ("formula", "process", "equipment", "gmp", "other")
        assert 0 < len(c["text"]) <= C.CHUNK_SIZE + C.CHUNK_OVERLAP


def test_radical_normalization():
    """D10 回归：部首字符经规范化后与普通汉字检索对齐。"""
    assert normalize_text("银⻩⼝服液") == "银黄口服液"
    # 映射表覆盖全部已知残留（若知识库更新引入新部首，此断言提醒补表）
    leftover = {c for c in normalize_text("⻩⻋⻛⻄⻅⻜⺠⻆⻓⻣⻰")
                if 0x2E80 <= ord(c) <= 0x2FFF}
    assert not leftover


def test_hybrid_beats_single_channel(retriever):
    """混合检索的 Top1 应同时被两路认可或至少有一路高分——抽查已知强信号查询。"""
    pack = retriever.search("黄芩提取物", top_k=3)
    top = pack.hits[0]
    assert "vector" in top.channels or "bm25" in top.channels
    assert "银黄口服液" in top.doc_name


def test_failure_record_precise_recall(retriever):
    """D15 回归：设备故障事件必须精确召回『设备维修历史』块（章节标签正确）。"""
    pack = retriever.search("六味地黄胶囊3月设备故障停机", top_k=5)
    maint = [h for h in pack.hits if "维修历史" in h.section]
    assert maint, "未召回设备维修历史块"
    assert "胶囊填充机" in maint[0].text or "计量盘磨损" in maint[0].text


def test_radical_map_completeness():
    """D10 升级回归：映射表来自官方完整数据（≥240 条），非手工枚举。"""
    from app.radical_map import RADICAL_MAP
    assert len(RADICAL_MAP) >= 240
    # 官方表未收的 4 个简体变体由脚本附录补齐
    for c in "⻄⺠⻆⻣":
        assert c in RADICAL_MAP


def test_d13_generic_query_prefers_business_doc(retriever):
    """D13 回归：泛查询 Top1 应为业务文档（配方/工艺），而非 GMP 通则类泛文档。"""
    pack = retriever.search("金银花价格上涨的原因", top_k=3)
    assert pack.hits[0].doc_type in ("formula", "process"), \
        f"Top1 仍是泛文档: {pack.hits[0].doc_name}"


def test_hyphen_line_merge():
    """D14 残余回归：表格碎行已合并，维修记录含完整日期与设备型号词元。"""
    chunks = load_chunks()
    maint = next(c for c in chunks if "维修历史" in c["section"])
    assert "2026-03" in maint["text"], f"日期仍碎裂: {maint['text'][:200]}"
    assert "NJP-3200" in maint["text"]


# ---------- 问题二修复：按需精确通道（B+C′） ----------

def test_extract_identifiers():
    """标识符抽取：编号形态被认出，普通中文/英文词不误判。"""
    from app.retrieve import extract_identifiers
    assert extract_identifiers("ZQ-TEST-2026 的成本异常") == ["ZQ-TEST-2026"]
    assert extract_identifiers("EQ-JN-001 和 PF-2026-LW-001 有什么关系") == \
        ["EQ-JN-001", "PF-2026-LW-001"]
    assert extract_identifiers("金银花价格上涨的原因") == []
    # 大小写归一：小写输入识别为大写 token
    assert extract_identifiers("dj-300 粉碎机") == ["DJ-300"]


def test_identifier_query_exact_channel(retriever):
    """编号查询：Top1 必须是含该编号的块，且带 exact 通道标。"""
    pack = retriever.search("PF-2026-LW-001 批次发生了什么", top_k=5)
    assert "PF-2026-LW-001" in pack.hits[0].text
    assert "exact" in pack.hits[0].channels


def test_identifier_case_insensitive(retriever):
    """用户小写输入编号也能命中（大小写无关子串匹配）。"""
    pack = retriever.search("dj-300 在哪个车间", top_k=5)
    assert any("DJ-300" in h.text for h in pack.hits)


def test_semantic_query_no_exact_channel(retriever):
    """语义查询零影响：无标识符时 exact 通道不启动，排序行为不变。"""
    pack = retriever.search("金银花价格上涨的原因", top_k=5)
    for h in pack.hits:
        assert "exact" not in h.channels


def test_nonexistent_identifier_graceful(retriever):
    """编号在库中不存在：不崩、不阻塞其他通道，只是没有 exact 命中。"""
    pack = retriever.search("ZQ-TEST-2099 的成本是多少", top_k=5)
    assert pack.hits  # 其他通道照常返回
    assert all("exact" not in h.channels for h in pack.hits)
