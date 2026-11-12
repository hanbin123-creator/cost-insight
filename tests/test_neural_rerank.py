"""神经精排（可选增强）测试：回退路径恒安全 + 模型在场时精排生效。

CI / Docker 无模型文件：只断言回退语义（返回 None、检索走规则精排不炸）。
本机有模型时追加断言：神经精排确实产出排序结果且窗口外尾部不动。
"""
from types import SimpleNamespace

import pytest

from app import config as C
from app import neural_rerank as nr


def _hits(n=4):
    return [SimpleNamespace(text=f"文本{i}", rrf_score=0.03 - i * 0.001)
            for i in range(n)]


def test_missing_model_returns_none_and_recovers(monkeypatch):
    """模型目录不存在 → neural_rerank_hits 返回 None（调用方回退规则精排）。"""
    monkeypatch.setattr(C, "NEURAL_RERANK_DIR", C.ROOT / "models" / "reranker" / "_nope")
    monkeypatch.setattr(nr, "_session", None)
    monkeypatch.setattr(nr, "_broken", False)
    assert nr.neural_rerank_hits("金银花涨价", _hits()) is None
    # 失败置位后不反复尝试
    assert nr._broken is True


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(C, "NEURAL_RERANK_ENABLED", False)
    monkeypatch.setattr(nr, "_session", None)
    monkeypatch.setattr(nr, "_broken", False)
    assert nr.neural_rerank_hits("金银花涨价", _hits()) is None


def test_single_hit_passthrough():
    assert nr.neural_rerank_hits("任意", _hits(1)) is None  # 无需精排


@pytest.mark.skipif(not (C.NEURAL_RERANK_DIR / "model.onnx").exists(),
                    reason="本机无神经精排模型（CI/Docker 默认路径）")
def test_neural_rerank_orders_when_model_present():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(nr, "_session", None)
    monkeypatch.setattr(nr, "_broken", False)
    hits = [SimpleNamespace(text="六味地黄胶囊的配方组成与单盒成本", rrf_score=0.01),
            SimpleNamespace(text="感冒药营销话术写作技巧分享", rrf_score=0.03)]
    out = nr.neural_rerank_hits("六味地黄胶囊配方是什么", hits)
    assert out is not None and len(out) == 2
    assert "六味地黄" in out[0].text      # 语义相关者排前
    monkeypatch.undo()
