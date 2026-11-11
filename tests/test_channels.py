"""消融通道开关测试（A4）：channels 参数语义 + 默认行为零变化。"""
import pytest

from app import config as C
from app.kb import build_index
from app.retrieve import ALL_CHANNELS, Retriever


@pytest.fixture(scope="session")
def retriever() -> Retriever:
    if not (C.KB_INDEX_DIR / "chunks.jsonl").exists():
        build_index()
    return Retriever()


def test_default_channels_unchanged(retriever):
    """不传 channels 与显式全开结果完全一致（既有调用零影响）。"""
    q = "金银花价格上涨的原因"
    a = retriever.search(q, top_k=5)
    b = retriever.search(q, top_k=5, channels=ALL_CHANNELS)
    assert [h.chunk_id for h in a.hits] == [h.chunk_id for h in b.hits]


def test_channel_exclusion_tags(retriever):
    """关闭某通道后，所有命中不再带该通道标签；编号查询关 exact 后失精确召回。"""
    pack = retriever.search("PF-2026-LW-001 批次", top_k=5,
                            channels=("vector", "bm25", "graph"))
    for h in pack.hits:
        assert "exact" not in h.channels
    full = retriever.search("PF-2026-LW-001 批次", top_k=5)
    assert "exact" in full.hits[0].channels       # 基线：exact 在 Top1


def test_all_channels_off_returns_empty(retriever):
    """全关如实返回空命中，不伪造结果。"""
    pack = retriever.search("金银花", top_k=5, channels=())
    assert pack.hits == []
