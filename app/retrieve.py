"""板块③后半 混合检索：向量 + BM25 → RRF(k=60) 融合 → 带出处的 KnowledgePack。

设计要点：
- 向量后端抽象 VectorBackend：numpy=开发机精确余弦（Windows 本机，Milvus Lite
  不支持原生 Windows）；milvus_lite=Docker/生产。百级 chunk 规模下两者结果一致
- 查询与语料同走 kb.normalize_text 规范化（部首字符两端对齐，D10 防线）
- 每个命中都带 {doc_name, page, section} 出处——报告引用要求的硬保障
"""
from __future__ import annotations

from pathlib import Path

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

from . import config as C
from .embedder import embed_texts
from .kb import load_chunks, normalize_text
from .kg import graph_recall, load_or_build
from .schemas import KnowledgeHit, KnowledgePack


def embed_query(text: str) -> np.ndarray:
    v = embed_texts([normalize_text(text)])[0]
    return v / np.linalg.norm(v)


class NumpyBackend:
    """开发后端：内存精确余弦。chunk 量百级时与 Milvus Lite 结果一致，零依赖。"""
    name = "numpy"

    def __init__(self, index_dir: Path):
        self.vectors = np.load(index_dir / "vectors.npy")

    def search(self, qvec: np.ndarray, top_k: int) -> list[tuple[int, float]]:
        scores = self.vectors @ qvec
        idx = np.argsort(scores)[::-1][:top_k]
        return [(int(i), float(scores[i])) for i in idx]


class MilvusLiteBackend:
    """生产后端：Milvus Lite 本地文件库（仅 Linux/Docker，演进路线图 M2）。"""
    name = "milvus_lite"

    def __init__(self, index_dir: Path):
        from pymilvus import MilvusClient
        self.client = MilvusClient(str(index_dir / "milvus_lite.db"))
        # 集合由构建侧创建；此处假定 data/kb 已由 Docker 构建流程写入
        self.collection = "kb_chunks"

    def search(self, qvec: np.ndarray, top_k: int) -> list[tuple[int, float]]:
        res = self.client.search(self.collection, data=[qvec.tolist()],
                                 limit=top_k, output_fields=["chunk_idx"])[0]
        return [(int(h["entity"]["chunk_idx"]), float(h["distance"])) for h in res]


_BACKENDS = {"numpy": NumpyBackend, "milvus_lite": MilvusLiteBackend}


def _tokenize(text: str) -> list[str]:
    return [t for t in jieba.lcut(normalize_text(text)) if t.strip()]


class Retriever:
    """混合检索器：加载索引 → 向量 Top10 + BM25 Top10 → RRF 融合。"""

    def __init__(self, index_dir: Path = C.KB_INDEX_DIR, backend: str = C.VECTOR_BACKEND):
        self.chunks = load_chunks(index_dir)
        self.vector = _BACKENDS[backend](index_dir)
        self.bm25 = BM25Okapi([_tokenize(c["text"]) for c in self.chunks])
        self.graph = load_or_build(index_dir)   # 图谱通道：缺 kg.json 时现场重建

    def search(self, query: str, top_k: int = 5, per_channel: int = 10,
               rerank: bool = True) -> KnowledgePack:
        vec_hits = self.vector.search(embed_query(query), per_channel)
        bm25_scores = self.bm25.get_scores(_tokenize(query))
        bm25_idx = np.argsort(bm25_scores)[::-1][:per_channel]
        bm25_hits = [(int(i), float(bm25_scores[i])) for i in bm25_idx]
        graph_hits = graph_recall(self.graph, query, per_channel)

        # RRF：score = Σ 1/(k + rank)，只认排名不认原始分——三路量纲天然不可比
        rrf: dict[int, float] = {}
        channels: dict[int, list[str]] = {}
        for rank, (idx, _) in enumerate(vec_hits):
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (C.RRF_K + rank + 1)
            channels.setdefault(idx, []).append("vector")
        for rank, (idx, _) in enumerate(bm25_hits):
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (C.RRF_K + rank + 1)
            channels.setdefault(idx, []).append("bm25")
        for rank, (idx, _) in enumerate(graph_hits):
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (C.RRF_K + rank + 1)
            channels.setdefault(idx, []).append("graph")

        # D13 复核结论：不加产品名加成。实测表明表格感知抽取已让"金银花涨价"
        # 类查询 Top1 命中配方变更记录（泛文档自然下沉）；而产品名加成会把
        # "设备故障"查询的正确证据块挤出 Top3——加成收益为零、副作用真实，撤销。

        # 精排需要更大候选窗：先取 max(top_k, 精排窗口) 构造，重排后再截 top_k
        from .rerank import RERANK_WINDOW
        n_cand = max(top_k, RERANK_WINDOW) if rerank else top_k
        top = sorted(rrf.items(), key=lambda kv: kv[1], reverse=True)[:n_cand]
        hits = [KnowledgeHit(chunk_id=self.chunks[i]["chunk_id"],
                             doc_name=self.chunks[i]["doc_name"],
                             page=self.chunks[i]["page"],
                             section=self.chunks[i]["section"],
                             doc_type=self.chunks[i]["doc_type"],
                             text=self.chunks[i]["text"],
                             rrf_score=round(score, 6),
                             channels=channels[i])
                for i, score in top]
        if rerank:
            # 规则精排（rerank.py）：只重排前窗不扩召回，错误代价封顶；
            # IDF 取自 BM25 通道（同分词器，量纲天然对齐）
            from .rerank import rerank_hits
            hits = rerank_hits(query, _tokenize(query), hits, self.graph,
                               idf=self.bm25.idf)[:top_k]
        return KnowledgePack(query=query, hits=hits)

    def multi_search(self, queries: list[str], top_k: int = 6,
                     per_facet: int = 4) -> KnowledgePack:
        """分面多查询合并（决策 I）：每条 facet 各取前 per_facet，
        按 chunk_id 去重保留最高分与通道并集，再按分数取 top_k。
        文档多样性保护：同一文档最多 3 块，防单文档刷屏挤掉异类证据。"""
        merged: dict[str, KnowledgeHit] = {}
        for q in queries:
            for h in self.search(q, top_k=per_facet).hits:
                if h.chunk_id not in merged or h.rrf_score > merged[h.chunk_id].rrf_score:
                    if h.chunk_id in merged:
                        h.channels = sorted(set(h.channels) | set(merged[h.chunk_id].channels))
                    merged[h.chunk_id] = h
        ranked = sorted(merged.values(), key=lambda h: h.rrf_score, reverse=True)
        out: list[KnowledgeHit] = []
        doc_count: dict[str, int] = {}
        for h in ranked:
            if doc_count.get(h.doc_name, 0) >= 3:
                continue
            doc_count[h.doc_name] = doc_count.get(h.doc_name, 0) + 1
            out.append(h)
            if len(out) >= top_k:
                break
        return KnowledgePack(query=" | ".join(queries), hits=out)
