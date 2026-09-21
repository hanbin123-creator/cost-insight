"""检索精排（对比评估#3）：规则精排器——零新依赖、确定性、可解释。

背景决策：首选 fastembed cross-encoder（BAAI/bge-reranker-base），但本机离线环境
下载失败（HF 不可达），且 1GB 模型入镜像体积代价高。降级为规则精排：
- 候选集限定 RRF 融合后的前 N 名（精排只重排不召回，错误代价封顶）
- 特征全部确定性：词元覆盖率 + 图谱实体命中数，加权进 RRF 基础分
- 与 cross-encoder 相同的职责边界（候选重排），企业演进换神经精排时接口不变
- 量化对照：tests/test_rerank.py 输出有/无精排的 MRR 对比，直接进评测报告
"""
from __future__ import annotations

from .kg import EntityGraph, match_entities

# 精排候选窗口与特征权重（常数固定，可解释可复现）
RERANK_WINDOW = 10        # 只重排 RRF 前 10 名——精排纠错范围封顶
W_COVERAGE = 1.0          # IDF 加权词元覆盖率权重
W_ENTITY = 0.15           # 图谱实体命中权重（每个实体 +0.15，封顶 3 个）
ENTITY_CAP = 3


def _coverage(query_tokens: list[str], text: str,
              idf: dict | None = None) -> float:
    """查询词元覆盖率。给 idf 时按稀有度加权（判别词'故障/停机'权重大于
    高频词'产品名'——实测诊断：等权覆盖下产品名token淹没判别词，见开发日志）。"""
    tokens = {t for t in query_tokens if len(t) >= 2}   # 单字词元噪声大不计
    if not tokens:
        return 0.0
    if idf:
        # rank_bm25 对超高频词会给负 idf——截断为 0（无判别力而非负判别力）
        total = sum(max(idf.get(t, 0.0), 0.0) for t in tokens)
        if total <= 0:
            return 0.0
        return sum(max(idf.get(t, 0.0), 0.0) for t in tokens if t in text) / total
    return sum(1 for t in tokens if t in text) / len(tokens)


def rerank_hits(query: str, query_tokens: list[str], hits: list,
                graph: EntityGraph | None = None,
                idf: dict | None = None) -> list:
    """对 RRF 前 RERANK_WINDOW 名重排，其余原样保留。

    hits: KnowledgeHit 列表（已按 rrf_score 降序）。返回新列表，不改原对象。
    """
    if len(hits) <= 1:
        return hits
    seeds = set(match_entities(graph, query)) if graph else set()
    head, tail = hits[:RERANK_WINDOW], hits[RERANK_WINDOW:]

    def score(h) -> float:
        cov = _coverage(query_tokens, h.text, idf)
        ent = min(sum(1 for s in seeds if s in h.text), ENTITY_CAP)
        return h.rrf_score * (1 + W_COVERAGE * cov) + W_ENTITY * ent * 0.01

    return sorted(head, key=score, reverse=True) + tail
