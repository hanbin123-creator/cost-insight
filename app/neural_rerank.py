"""神经精排（可选增强）：bge-reranker-base cross-encoder，onnxruntime 直读。

设计约束：
- 可选加载——模型文件缺失或任何加载/推理失败时返回 None，调用方回退规则精排；
  Docker / CI 默认无模型，行为与既有版本一致（可复现性不破）。
- 模型约 1GB 不入 git（.gitignore 已排除 models/reranker/）；
  获取方式见 README「可选神经精排」一节（ModelScope 直链）。
- 职责边界与规则精排一致：只重排 RRF 候选前窗，不扩召回、不改分数语义。
- 50 条评估集实测（2026-11-12）：Top1 35/40→36/40（90.0%）、MRR 0.9187→0.9342；
  对照实验脚本 scripts/rerank_compare.py。
"""
from __future__ import annotations

from pathlib import Path

from . import config as C
from .rerank import RERANK_WINDOW

_session = None       # ort.InferenceSession 懒加载单例
_tokenizer = None     # tokenizers.Tokenizer 懒加载单例
_broken = False       # 加载失败过一次就不再尝试（避免每次查询重试）


def _load():
    """加载模型与分词器；任何失败都置 _broken 并返回 False（不抛出）。"""
    global _session, _tokenizer, _broken
    if _session is not None:
        return True
    if _broken or not C.NEURAL_RERANK_ENABLED:
        return False
    model = C.NEURAL_RERANK_DIR / "model.onnx"
    tok = C.NEURAL_RERANK_DIR / "tokenizer.json"
    if not (model.exists() and tok.exists()):
        _broken = True
        return False
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
        t = Tokenizer.from_file(str(tok))
        t.enable_truncation(max_length=512)
        t.enable_padding()
        _tokenizer = t
        _session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
        return True
    except Exception:
        _broken = True
        return False


def neural_rerank_hits(query: str, hits: list):
    """对 RRF 前窗（RERANK_WINDOW）做神经精排；不可用返回 None（回退规则精排）。

    返回新列表，不改原对象；窗口外尾部原样保留（与规则精排同一职责边界）。
    """
    if len(hits) <= 1 or not _load():
        return None
    try:
        import numpy as np
        head, tail = hits[:RERANK_WINDOW], hits[RERANK_WINDOW:]
        enc = _tokenizer.encode_batch([(query, h.text) for h in head])
        feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
        if "token_type_ids" in {i.name for i in _session.get_inputs()}:
            feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
        scores = _session.run(None, feed)[0].reshape(-1)
        ranked = [h for h, _s in sorted(zip(head, scores), key=lambda x: x[1], reverse=True)]
        return ranked + tail
    except Exception:
        return None
