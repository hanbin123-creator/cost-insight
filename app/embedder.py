"""嵌入模型统一工厂（D11 最终方案：项目内缓存 + 离线强制）。

GitHub 实例考证（开发日志03）：cuga-agent / Citadel / Curator 等生产项目的通行做法是
「构建时下载到受控缓存 + 运行时 HF_HUB_OFFLINE=1 硬性离线」，模型缺失时响亮报错
而不是静默联网。本模块把这一模式代码化：
- 缓存目录固定在项目内（不依赖用户目录/系统 Temp——fastembed 默认缓存落 Temp 是隐患）
- .ready 标记存在 → local_files_only=True：代码内强制离线，不依赖环境变量记忆
- 标记不存在 → 允许联网下载（开发机首次），并提示先跑 scripts/download_model.py
"""
from __future__ import annotations

import os

from . import config as C

_embedder = None


def get_embedder():
    """BGE 模型单例。模型已烘焙则强制离线加载；未烘焙则联网下载并提示。"""
    global _embedder
    if _embedder is not None:
        return _embedder
    from fastembed import TextEmbedding
    ready = C.MODEL_READY_MARKER.exists()
    if not ready:
        import warnings
        warnings.warn(
            f"模型缓存未验证（{C.MODEL_CACHE_DIR}），将尝试联网下载；"
            "建议先运行 python scripts/download_model.py 完成受控下载")
    if ready:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")  # 双保险：环境变量层也锁离线
    _embedder = TextEmbedding(C.EMBED_MODEL, cache_dir=str(C.MODEL_CACHE_DIR),
                              local_files_only=ready)
    return _embedder


def embed_texts(texts: list[str]):
    """批量嵌入（未归一化，归一化由调用方按需做）。"""
    import numpy as np
    return np.array(list(get_embedder().embed(texts)), dtype=np.float32)
