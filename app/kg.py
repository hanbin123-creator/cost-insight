"""知识图谱增强召回（加分项）：实体抽取 → 关系表 → 图扩展，作为 RRF 第三通道。

设计要点（LightRAG 思路的最小自研，参照《GitHub开源参照与迁移可行性评估》功能 1）：
- 零依赖零 LLM：邻接表用 dict-of-set 自实现（不引 networkx），实体抽取用
  表格感知抽取留下的「字段: 值」记录模式 + 词表匹配，完全确定性、可测试。
  LLM 抽取方案（GraphRAG 默认）成本高且不可复现，竞赛数据规模下规则已够
- 三类实体：product（产品，配方文档文件名）/ material（原料，"原料名称: X"
  记录 + 行情词表）/ equipment + maker（设备/制造商，"设备名称/制造商: X"）
- 三类边：contains（产品→原料，配方文档）/ made_by（设备→制造商）/
  cooccur（同块共现，捕捉 产品↔设备、原料↔工艺 等隐性关联）
- 图扩展召回：查询命中实体 → 1 跳邻居扩展 → 提到种子实体的块权重 1.0、
  提到邻居实体的块权重 0.6，作为 "graph" 通道进 RRF。
  价值场景："金银花涨价影响哪个产品"——向量/BM25 只找回行情与配方块，
  图扩展把「银黄口服液」整块簇拉进候选，正是 GraphRAG 的全局关联能力
- 产物 kg.json 随索引持久化；检索侧缺文件时从 chunks.jsonl 现场重建（秒级）
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config as C
from .kb import load_chunks, normalize_text

# 「字段: 值」记录模式（表格感知抽取的产物，kb._read_pdf_page 生成）
_RECORD_RE = re.compile(r"(原料名称|原材料|设备名称|设备编号|制造商)[:：]\s*([^；;]+)")
_PRODUCT_DOC_RE = re.compile(r"产品配方文档_(.+?)(?:\.pdf|\.docx?|\.txt)?$")

# 实体类型中文标签（仅供explain/调试输出）
ETYPE_LABEL = {"product": "产品", "material": "原料",
               "equipment": "设备", "maker": "制造商"}

# 共现边只在这几类实体对之间建立（防噪声：原料×原料同清单必然共现，无信息）
_COOCCUR_PAIRS = {frozenset(("product", "equipment")),
                  frozenset(("product", "maker")),
                  frozenset(("material", "equipment"))}

DIRECT_WEIGHT = 1.0    # 块提到查询种子实体
NEIGHBOR_WEIGHT = 0.6  # 块只提到种子的一跳邻居


class EntityGraph:
    """邻接表图：entities{name: etype}，edges{name: {neighbor: 边类列表}}，
    mentions{name: set(chunk行号)}。全部可 JSON 序列化。"""

    def __init__(self) -> None:
        self.entities: dict[str, str] = {}
        self.edges: dict[str, dict[str, list[str]]] = {}
        self.mentions: dict[str, list[int]] = {}

    # ----- 建图原语 -----
    def add_entity(self, name: str, etype: str) -> None:
        name = name.strip()
        if not name or len(name) > 30:
            return
        # 同名实体类型冲突时保留首次登记（产品>原料>设备的登记顺序保证优先级）
        self.entities.setdefault(name, etype)

    def add_edge(self, a: str, b: str, kind: str) -> None:
        if a == b or a not in self.entities or b not in self.entities:
            return
        for x, y in ((a, b), (b, a)):  # 无向存储，扩展时不区分方向
            self.edges.setdefault(x, {}).setdefault(y, [])
            if kind not in self.edges[x][y]:
                self.edges[x][y].append(kind)

    def add_mention(self, name: str, chunk_idx: int) -> None:
        if name in self.entities:
            lst = self.mentions.setdefault(name, [])
            if chunk_idx not in lst:
                lst.append(chunk_idx)

    def neighbors(self, name: str) -> dict[str, list[str]]:
        return self.edges.get(name, {})

    # ----- 持久化 -----
    def to_dict(self) -> dict:
        return {"entities": self.entities, "edges": self.edges,
                "mentions": self.mentions}

    @classmethod
    def from_dict(cls, d: dict) -> "EntityGraph":
        g = cls()
        g.entities = dict(d["entities"])
        g.edges = {k: {n: list(kinds) for n, kinds in v.items()}
                   for k, v in d["edges"].items()}
        g.mentions = {k: [int(i) for i in v] for k, v in d["mentions"].items()}
        return g

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False),
                        encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "EntityGraph":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _extract_records(text: str) -> list[tuple[str, str]]:
    """从块文本抽出 (字段名, 值)；值截到首个分隔符，过滤纯数字/空值。"""
    out = []
    for field, value in _RECORD_RE.findall(text):
        value = value.strip()
        if value and not re.fullmatch(r"[\d.,\-—]+", value):
            out.append((field, value))
    return out


def build_graph(chunks: list[dict]) -> EntityGraph:
    """从切分块建图。两遍扫描：先登记全部实体（保证边端点存在），再建边与提及。"""
    g = EntityGraph()
    per_chunk: list[list[tuple[str, str]]] = []  # 每块 [(实体名, 类型)]

    # 第一遍：登记实体
    for c in chunks:
        found: list[tuple[str, str]] = []
        product = None
        m = _PRODUCT_DOC_RE.search(c["doc_name"])
        if m:
            product = m.group(1)
            g.add_entity(product, "product")
            found.append((product, "product"))
        for field, value in _extract_records(c["text"]):
            if field in ("原料名称", "原材料"):
                # 「原材料: 合计/包装材料」类伪实体过滤
                if value in ("合计",) or "包装材料" in value:
                    continue
                g.add_entity(value, "material")
                found.append((value, "material"))
            elif field == "设备名称":
                g.add_entity(value, "equipment")
                found.append((value, "equipment"))
            elif field == "制造商":
                g.add_entity(value, "maker")
                found.append((value, "maker"))
            # 设备编号(EQ-XXX)不建实体：检索价值低，且与设备名称重复指向
        per_chunk.append(found)

    # 第二遍：边与提及
    for idx, (c, found) in enumerate(zip(chunks, per_chunk)):
        names = [n for n, _ in found]
        for n in names:
            g.add_mention(n, idx)
        product = next((n for n, t in found if t == "product"), None)
        if product:  # 配方文档：产品→原料 contains 边
            for n, t in found:
                if t == "material":
                    g.add_edge(product, n, "contains")
        # 设备→制造商 made_by 边（同块同记录内成对出现）
        equips = [n for n, t in found if t == "equipment"]
        makers = [n for n, t in found if t == "maker"]
        if equips and makers and "设备清单" in c["doc_name"]:
            # 设备清单每行「设备名称…制造商…」成对；行级对齐已由切分保证
            for e in equips:
                for mk in makers:
                    g.add_edge(e, mk, "made_by")
        # 共现边（仅限有信息量的实体对）
        for i in range(len(found)):
            for j in range(i + 1, len(found)):
                na, ta = found[i]
                nb, tb = found[j]
                if frozenset((ta, tb)) in _COOCCUR_PAIRS:
                    g.add_edge(na, nb, "cooccur")
    return g


def match_entities(g: EntityGraph, query: str) -> list[str]:
    """查询中的实体命中：规范化后做双向子串匹配（实体⊂查询 或 查询⊂实体）。
    双向是为「银黄」命中「银黄口服液」这类简称；长度≥2 防单字误配。"""
    q = normalize_text(query)
    hits = []
    for name in g.entities:
        if len(name) >= 2 and (name in q or (2 <= len(q) <= 6 and q in name)):
            hits.append(name)
    return hits


def graph_recall(g: EntityGraph, query: str, top_k: int = 10) -> list[tuple[int, float]]:
    """图扩展召回：种子实体直提块 1.0，一跳邻居提及块 0.6，按权重排序取 top_k。
    返回 [(chunk行号, 权重)]——权重只定排名，进 RRF 后原始分不影响融合。"""
    seeds = match_entities(g, query)
    if not seeds:
        return []
    expanded = set(seeds)
    for s in seeds:
        expanded.update(g.neighbors(s))
    scores: dict[int, float] = {}
    for name in expanded:
        w = DIRECT_WEIGHT if name in seeds else NEIGHBOR_WEIGHT
        for idx in g.mentions.get(name, []):
            scores[idx] = max(scores.get(idx, 0.0), w)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:top_k]


def load_or_build(index_dir: Path = C.KB_INDEX_DIR) -> EntityGraph:
    """检索侧入口：kg.json 存在直接加载；否则从 chunks.jsonl 现场重建并保存
    （建图纯规则无嵌入调用，351 块实测毫秒级，重建代价可忽略）。"""
    path = index_dir / "kg.json"
    if path.exists():
        return EntityGraph.load(path)
    g = build_graph(load_chunks(index_dir))
    g.save(path)
    return g
