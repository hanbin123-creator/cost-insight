"""规则精排测试（对比评估#3）：有/无精排的量化对照 + 安全性边界。

量化对照数据直接用于评测报告（改动权重文档：reranker 是唯一能产生
量化对比数据的改动）。对照口径：6 个内置波动事件的 MRR 与 Top1 命中率。
"""
import pytest

from app import config as C
from app.kb import build_index
from app.rerank import _coverage, rerank_hits
from app.retrieve import Retriever
from tests.test_retrieve import RECALL_CASES


@pytest.fixture(scope="session")
def retriever() -> Retriever:
    if not (C.KB_INDEX_DIR / "chunks.jsonl").exists():
        build_index()
    return Retriever()


def _mrr(retriever, rerank: bool) -> tuple[float, int]:
    """6 事件查询的 MRR 与 Top1 命中数（目标文档见 RECALL_CASES）。"""
    rr_total, top1 = 0.0, 0
    for query, target in RECALL_CASES:
        pack = retriever.search(query, top_k=5, rerank=rerank)
        rank = next((i + 1 for i, h in enumerate(pack.hits)
                     if target in h.doc_name), None)
        if rank:
            rr_total += 1.0 / rank
            top1 += rank == 1
    return rr_total / len(RECALL_CASES), top1


def test_rerank_never_worse(retriever, capsys):
    """硬约束：精排后 MRR 与 Top1 命中数不得低于关闭精排（只许赢不许输），
    并把对照数字打印出来进测试日志（评测报告取数处）。"""
    mrr_off, top1_off = _mrr(retriever, rerank=False)
    mrr_on, top1_on = _mrr(retriever, rerank=True)
    print(f"\n[rerank对照] OFF: MRR={mrr_off:.3f} Top1={top1_off}/6 | "
          f"ON: MRR={mrr_on:.3f} Top1={top1_on}/6")
    assert mrr_on >= mrr_off - 1e-9, f"精排拉低 MRR: {mrr_off}→{mrr_on}"
    assert top1_on >= top1_off, f"精排拉低 Top1: {top1_off}→{top1_on}"


def test_rerank_preserves_recall_cases(retriever):
    """6 个波动事件的目标文档在精排后仍全部留在 Top5（不破坏既有召回）。"""
    for query, target in RECALL_CASES:
        pack = retriever.search(query, top_k=5, rerank=True)
        assert any(target in h.doc_name for h in pack.hits), \
            f"精排后丢失目标: {query} → {target}"


def test_coverage_feature():
    """词元覆盖率：命中比例计算正确，单字词元与空查询安全。"""
    assert _coverage(["金银花", "涨价"], "金银花价格上涨") == 0.5
    assert _coverage(["金银花"], "金银花价格上涨") == 1.0
    assert _coverage([], "任意文本") == 0.0
    assert _coverage(["a", "b"], "文本") == 0.0     # 单字不计


def test_rerank_window_bounded():
    """窗口外原样保留：11 个命中时第 11 名位置不变（精排错误代价封顶）。"""
    from app.schemas import KnowledgeHit

    def mk(i, text):
        return KnowledgeHit(chunk_id=f"c{i}", doc_name="d", page=1,
                            section="s", doc_type="other", text=text,
                            rrf_score=0.01 * (20 - i), channels=[])
    hits = [mk(i, "金银花" if i == 10 else "无关") for i in range(11)]
    out = rerank_hits("金银花", ["金银花"], hits, graph=None)
    # 窗口内（前10）按特征重排：无人造文本命中，顺序不变；第11名仍在最后
    assert out[-1].chunk_id == "c10"


def test_rerank_deterministic(retriever):
    """同一查询两次精排结果完全一致（规则精排无可变性）。"""
    a = retriever.search("金银花价格上涨的原因", top_k=5)
    b = retriever.search("金银花价格上涨的原因", top_k=5)
    assert [h.chunk_id for h in a.hits] == [h.chunk_id for h in b.hits]
