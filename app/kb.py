"""板块③前半 知识库构建：文档解析 → 规范化 → 章节感知切分 → 索引持久化。

设计要点：
- 文本规范化两段式：NFKC（修 U+2F00 康熙部首区）+ 手工部首映射表（修 U+2E80
  部首补充区，NFKC 不覆盖，D10）。部首字符不修，检索会直接漏召回
- 章节感知切分：识别「一、」「2.1」类标题行，块 ≤500 字、重叠 50 字
- 元数据第一天就带 tenant / doc_version（企业演进友好，演进路线图 M2）
- 产物：chunks.jsonl（块+元数据）、vectors.npy（BGE 嵌入）、bm25 在检索侧现算
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

import numpy as np

from . import config as C

logger = logging.getLogger(__name__)

# D10：完整部首映射（Unicode UCD 官方数据生成，243 条，覆盖部首补充区+康熙区全部）。
# 由 app/radical_map.py 承载，scripts/build_radical_map.py 可重新生成。
from .radical_map import RADICAL_MAP

DOC_TYPES = {"产品配方": "formula", "生产工艺": "process",
             "车间设备": "equipment", "GMP": "gmp", "药品生产": "gmp"}

SECTION_RE = re.compile(r"^\s*([一二三四五六七八九十]+、|\d+\.\d+|\d+、|第[一二三四五六七八九十百]+[章节条])")
VERSION_RE = re.compile(r"版本[:：]\s*(\S+)")


def normalize_text(text: str) -> str:
    """NFKC + 部首映射；发现映射表未覆盖的部首字符时记录警告（防静默漏召回）。"""
    t = unicodedata.normalize("NFKC", text)
    t = "".join(RADICAL_MAP.get(c, c) for c in t)
    leftover = {c for c in t if 0x2E80 <= ord(c) <= 0x2FFF}
    if leftover:
        logger.warning("部首映射表未覆盖: %s —— 请补 RADICAL_MAP", [hex(ord(c)) for c in leftover])
    return t


def _doc_type(filename: str) -> str:
    for prefix, dtype in DOC_TYPES.items():
        if prefix in filename:
            return dtype
    return "other"


def _in_any_bbox(obj: dict, bboxes: list[tuple]) -> bool:
    """字符中心点是否落在任一表格区域内。"""
    cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
    return any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in bboxes)


def _read_pdf_page(page) -> str:
    """表格感知抽取（D14 根治）：
    - 表格区域用 extract() 按行还原，每行渲染成「列名: 值；…」的自包含记录
      （单元格内换行合并：'2026-\\n03' → '2026-03'），关键词元对 BM25 完整可见
    - 非表格区域走普通文本抽取，两者合并返回
    残余限制：表格行在页面文本之后进入行序列，章节归属取页内末尾章节——
    本知识库章节与表格同页相邻，可接受（记录于开发日志03）。
    """
    tables = page.find_tables()
    bboxes = [t.bbox for t in tables]
    parts: list[str] = []
    if bboxes:
        text = page.filter(lambda obj: not _in_any_bbox(obj, bboxes)).extract_text() or ""
    else:
        text = page.extract_text() or ""
    parts.append(text)
    for t in tables:
        rows = t.extract()
        if len(rows) < 2:
            continue
        header = [(h or "").replace("\n", "") for h in rows[0]]
        for row in rows[1:]:
            cells = [f"{h}: {(c or '').replace(chr(10), '')}"
                     for h, c in zip(header, row) if c and c.strip()]
            if cells:
                parts.append("；".join(cells))
    return "\n".join(p for p in parts if p.strip())


def _read_pages(path: Path) -> list[tuple[int, str]]:
    """返回 [(页码, 规范化文本)]；支持 PDF / TXT / DOCX（G1：TXT 声明的兑现）。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return [(i + 1, normalize_text(_read_pdf_page(p)))
                    for i, p in enumerate(pdf.pages)]
    if suffix == ".txt":
        return [(1, normalize_text(path.read_text(encoding="utf-8")))]
    if suffix in (".docx", ".doc"):
        import docx
        doc = docx.Document(path)
        return [(1, normalize_text("\n".join(p.text for p in doc.paragraphs)))]
    raise ValueError(f"不支持的文档格式: {path.name}")


def _merge_hyphen_lines(lines: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    """D14 残余修复：PDF 表格抽取把"2026-"/"03"、"NJP-"/"3200"拆成两行，
    导致 BM25 无法匹配完整日期/型号词元。凡短行以连字符结尾，与下一行合并。"""
    merged: list[tuple[int, str, str]] = []
    i = 0
    while i < len(lines):
        page, sec, line = lines[i]
        if line.endswith("-") and len(line) <= 30 and i + 1 < len(lines):
            np_, ns, nl = lines[i + 1]
            merged.append((page, sec, line + nl))
            i += 2
        else:
            merged.append((page, sec, line))
            i += 1
    return merged


def chunk_document(path: Path) -> list[dict]:
    """章节感知切分：标题行必开新块（D15 修复：章节边界强制断开，块名不再张冠李戴）；
    同章节内块 ≤CHUNK_SIZE 字，重叠 CHUNK_OVERLAP 字；跨章节不重叠。"""
    pages = _read_pages(path)
    full_version = next((m.group(1) for _, t in pages if (m := VERSION_RE.search(t))), "V1.0")
    dtype = _doc_type(path.name)

    # 按行聚合，跟踪当前章节与页码（标题行本身归属新章节）
    lines: list[tuple[int, str, str]] = []   # (页码, 章节, 行文本)
    section = "导言"
    for page_no, text in pages:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if SECTION_RE.match(line) and len(line) <= 40:
                section = line
            lines.append((page_no, section, line))
    lines = _merge_hyphen_lines(lines)

    chunks: list[dict] = []
    buf: list[tuple[int, str, str]] = []
    buf_len = 0
    for item in lines:
        page_no, sec, line = item
        section_break = buf and sec != buf[0][1]
        if buf and (section_break or buf_len + len(line) > C.CHUNK_SIZE):
            chunks.append(_emit(buf, path.name, dtype, full_version, len(chunks)))
            if section_break:
                buf, buf_len = [], 0          # 章节边界：不重叠，保证块名=块内容
            else:
                # 同章节重叠：保留缓冲末尾累计 ≤CHUNK_OVERLAP 字的行
                tail: list[tuple[int, str, str]] = []
                t_len = 0
                for it in reversed(buf):
                    if t_len + len(it[2]) > C.CHUNK_OVERLAP:
                        break
                    tail.insert(0, it)
                    t_len += len(it[2])
                buf, buf_len = tail, t_len
        buf.append(item)
        buf_len += len(line)
    if buf:
        chunks.append(_emit(buf, path.name, dtype, full_version, len(chunks)))
    return chunks


def _emit(buf: list[tuple[int, str, str]], doc_name: str,
          dtype: str, version: str, idx: int) -> dict:
    return {"chunk_id": f"{Path(doc_name).stem}#{idx:03d}",
            "doc_name": doc_name, "page": buf[0][0], "section": buf[0][1],
            "doc_type": dtype, "tenant": C.TENANT, "doc_version": version,
            "text": "\n".join(it[2] for it in buf)}


def build_index(kb_dir: Path = C.KB_DIR, out_dir: Path = C.KB_INDEX_DIR) -> list[dict]:
    """全量构建：解析全部文档 → 切分 → BGE 嵌入 → 持久化 chunks.jsonl + vectors.npy。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[dict] = []
    for path in sorted(kb_dir.iterdir()):
        if path.suffix.lower() not in (".pdf", ".txt", ".docx", ".doc"):
            continue
        chunks.extend(chunk_document(path))
    if not chunks:
        raise ValueError(f"知识库为空: {kb_dir}")

    from .embedder import embed_texts
    vectors = embed_texts([c["text"] for c in chunks])
    # L2 归一化，检索时点积即余弦
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    (out_dir / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks), encoding="utf-8")
    np.save(out_dir / "vectors.npy", vectors)

    from .kg import build_graph
    build_graph(chunks).save(out_dir / "kg.json")   # 图谱与索引同批产出
    return chunks


def build_milvus_lite(out_dir: Path = C.KB_INDEX_DIR,
                      collection: str = "kb_chunks") -> int:
    """把 vectors.npy 灌入 Milvus Lite（生产后端写入侧，C7 补全）。

    仅 Linux/Docker 可运行（Milvus Lite 运行时限制）；从已构建的
    chunks.jsonl + vectors.npy 重建集合，幂等（存在即删重建）。
    检索侧 MilvusLiteBackend 假定 chunk 顺序与 vectors 行序一致——
    此处用 chunk_idx 显式存行号，语义不依赖隐式顺序。返回写入条数。"""
    from pymilvus import MilvusClient, DataType

    chunks = load_chunks(out_dir)
    vectors = np.load(out_dir / "vectors.npy")
    if len(chunks) != vectors.shape[0]:
        raise ValueError(f"chunks({len(chunks)}) 与 vectors({vectors.shape[0]}) 行数不一致")

    db = out_dir / "milvus_lite.db"
    client = MilvusClient(str(db))
    if client.has_collection(collection):
        client.drop_collection(collection)
    schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
    schema.add_field("id", DataType.INT64, is_primary=True)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=vectors.shape[1])
    schema.add_field("chunk_idx", DataType.INT64)
    client.create_collection(collection, schema=schema)
    rows = [{"vector": vectors[i].tolist(), "chunk_idx": i}
            for i in range(len(chunks))]
    client.insert(collection, rows)
    client.flush(collection)
    return len(rows)


def load_chunks(index_dir: Path = C.KB_INDEX_DIR) -> list[dict]:
    path = index_dir / "chunks.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"知识索引未构建，请先运行 kb.build_index(): {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def ensure_index() -> bool:
    """索引缺失则现场构建（本地开发自愈，与 Docker entrypoint 同行为）。

    返回 True=本次新建，False=已存在。构建语料来自 COST_INSIGHT_DATA_DIR
    挂载/同级数据包；语料缺失时给中文指引而非裸堆栈。"""
    if (C.KB_INDEX_DIR / "chunks.jsonl").exists():
        return False
    if not C.KB_DIR.exists():
        raise FileNotFoundError(
            f"找不到知识库语料目录 {C.KB_DIR}。请将考题数据包放到本仓库同级目录"
            "（../创灵境_考题模拟数据），或设 COST_INSIGHT_DATA_DIR 指向它——"
            "详见 README 第 0 步。")
    print(f"[kb] 索引缺失，正在从 {C.KB_DIR} 现场构建（约 30 秒，仅首次）...")
    chunks = build_index()
    print(f"[kb] 索引构建完成：{len(chunks)} 块 → {C.KB_INDEX_DIR}")
    return True


def main() -> None:
    """命令行入口：python -m app.kb 构建知识库索引。"""
    if ensure_index():
        print("完成。")
    else:
        print(f"索引已存在（{C.KB_INDEX_DIR}），无需重建。")


if __name__ == "__main__":
    main()
