"""知识图谱（加分项）测试：实体抽取 → 关系表 → 图扩展召回 → RRF 三通道。"""
import pytest

from app import config as C
from app.kb import build_index, load_chunks
from app.kg import (EntityGraph, build_graph, graph_recall, load_or_build,
                    match_entities)
from app.retrieve import Retriever


@pytest.fixture(scope="session")
def graph() -> EntityGraph:
    if not (C.KB_INDEX_DIR / "chunks.jsonl").exists():
        build_index()
    return build_graph(load_chunks())


def test_entities_extracted(graph):
    """三类实体全部抽到：产品×3、原料（金银花等）、设备、制造商。"""
    types = {}
    for name, t in graph.entities.items():
        types.setdefault(t, []).append(name)
    products = types.get("product", [])
    assert {"银黄口服液", "板蓝根颗粒", "六味地黄胶囊"} <= set(products)
    assert "金银花" in types.get("material", [])
    assert "黄芩提取物" in types.get("material", [])
    assert any("灌封" in e for e in types.get("equipment", []))
    assert "楚天科技" in types.get("maker", [])


def test_contains_edges(graph):
    """contains 边：银黄口服液处方组成与配方文档一致（金银花/黄芩提取物/蔗糖）。"""
    nb = graph.neighbors("银黄口服液")
    contains = {n for n, kinds in nb.items() if "contains" in kinds}
    assert {"金银花", "黄芩提取物", "蔗糖"} <= contains
    # 边必须双向可查
    assert "contains" in graph.neighbors("金银花")["银黄口服液"]


def test_made_by_edges(graph):
    """made_by 边：设备清单行级对齐，设备能找到制造商。"""
    nb = graph.neighbors("口服液灌封一体机")
    assert any("made_by" in kinds and n == "楚天科技"
               for n, kinds in nb.items())


def test_mentions_cover_chunks(graph):
    """提及索引：金银花至少在银黄配方块中出现；行号在语料范围内。"""
    chunks = load_chunks()
    idxs = graph.mentions.get("金银花", [])
    assert idxs, "金银花无任何提及块"
    assert all(0 <= i < len(chunks) for i in idxs)
    assert any("银黄口服液" in chunks[i]["doc_name"] for i in idxs)


def test_match_entities_substring(graph):
    """实体匹配：全称/简称都中，单字与无关词不中。"""
    assert "金银花" in match_entities(graph, "金银花价格上涨的原因")
    assert "银黄口服液" in match_entities(graph, "银黄口服液2月制造费用上升")
    assert not match_entities(graph, "今天天气怎么样")


def test_graph_recall_expansion(graph):
    """图扩展核心：查原料 → 一跳扩展到产品 → 产品簇块进入候选。"""
    hits = graph_recall(graph, "金银花涨价会影响什么", top_k=15)
    assert hits, "图召回为空"
    chunks = load_chunks()
    docs = {chunks[i]["doc_name"] for i, _ in hits}
    # 种子块（提金银花）权重 1.0 必须在前排
    assert hits[0][1] == 1.0
    # 扩展块（只提银黄口服液、不提金银花的块）也被拉进候选
    assert any("银黄口服液" in d for d in docs)


def test_graph_recall_no_match_empty(graph):
    """无实体命中的查询：图通道安静退场，不造噪声。"""
    assert graph_recall(graph, "资产负债表怎么看") == []


def test_persistence_roundtrip(tmp_path, graph):
    """kg.json 序列化往返无损（索引持久化契约）。"""
    p = tmp_path / "kg.json"
    graph.save(p)
    g2 = EntityGraph.load(p)
    assert g2.entities == graph.entities
    assert g2.edges == graph.edges
    assert g2.mentions == graph.mentions


def test_load_or_build_fallback(tmp_path):
    """缺 kg.json 时从 chunks.jsonl 现场重建并落盘——索引目录自愈。"""
    import shutil
    for f in ("chunks.jsonl",):
        shutil.copy(C.KB_INDEX_DIR / f, tmp_path / f)
    g = load_or_build(tmp_path)
    assert g.entities, "现场重建的图为空"
    assert (tmp_path / "kg.json").exists()


@pytest.fixture(scope="session")
def retriever() -> Retriever:
    if not (C.KB_INDEX_DIR / "chunks.jsonl").exists():
        build_index()
    return Retriever()


def test_graph_channel_in_rrf(retriever):
    """三通道融合：实体中心查询的命中里出现 graph 通道，且出处完整。"""
    pack = retriever.search("金银花价格上涨的原因", top_k=5)
    all_channels = [c for h in pack.hits for c in h.channels]
    assert "graph" in all_channels, f"graph 通道未参与: {[h.channels for h in pack.hits]}"
    for h in pack.hits:
        assert h.doc_name and h.page >= 1 and h.section


def test_graph_improves_cross_doc_recall(retriever):
    """图通道价值场景：'金银花涨价影响哪个产品'——扩展把产品配方块拉进 Top6。"""
    pack = retriever.search("金银花涨价影响哪个产品", top_k=6)
    assert any("银黄口服液" in h.doc_name for h in pack.hits), \
        f"跨文档关联召回失败: {[h.doc_name for h in pack.hits]}"
