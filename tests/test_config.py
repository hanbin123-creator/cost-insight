"""配置环境变量覆盖（容器化挂点）回归测试。"""
import importlib

from app import config as C


def test_data_dir_env_override(monkeypatch):
    """compose 用 COST_INSIGHT_DATA_DIR 指向挂卷路径；缺省保持本机开发路径。"""
    monkeypatch.setenv("COST_INSIGHT_DATA_DIR", "/data-source")
    importlib.reload(C)
    assert str(C.DATA_DIR).replace("\\", "/").endswith("/data-source")
    monkeypatch.delenv("COST_INSIGHT_DATA_DIR")
    importlib.reload(C)
    assert "创灵境_考题模拟数据" in str(C.DATA_DIR)


def test_vector_backend_env_override(monkeypatch):
    """VECTOR_BACKEND 缺省 numpy（Windows 开发），容器内 compose 注入 milvus_lite。"""
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    importlib.reload(C)
    assert C.VECTOR_BACKEND == "numpy"
    monkeypatch.setenv("VECTOR_BACKEND", "milvus_lite")
    importlib.reload(C)
    assert C.VECTOR_BACKEND == "milvus_lite"
    monkeypatch.delenv("VECTOR_BACKEND")
    importlib.reload(C)


def teardown_module():
    importlib.reload(C)   # 复位，防影响其他测试模块
