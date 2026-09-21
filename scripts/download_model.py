"""受控下载嵌入模型到项目内缓存（D11：多源回退 + 冒烟验证 + 就绪标记）。

用法：python scripts/download_model.py
回退顺序（每个源在独立子进程中尝试，环境变量必须在 huggingface_hub 导入前设定）：
  1. HuggingFace 直连（境外/有代理环境）
  2. hf-mirror 镜像 + 禁用 xet（国内网络；xet 通道经镜像会 401，见开发日志02 D11）
下载成功后立即离线冒烟验证（仿 Citadel 项目 Dockerfile 的 build-time 验证模式），
通过才写入 .ready 标记——标记是 app/embedder.py 强制离线的开关。
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config as C  # noqa: E402

SOURCES = [
    ("huggingface 直连", {}),
    ("hf-mirror 镜像(禁xet)", {"HF_ENDPOINT": "https://hf-mirror.com", "HF_HUB_DISABLE_XET": "1"}),
]

_DOWNLOAD_SNIPPET = """
from fastembed import TextEmbedding
import sys
m = TextEmbedding(sys.argv[1], cache_dir=sys.argv[2])
v = list(m.embed(["金银花冒烟测试"]))
assert len(v[0]) == 512, f"维度异常: {len(v[0])}"
print("smoke OK, dim=512")
"""


def try_source(name: str, extra_env: dict[str, str]) -> bool:
    env = {**os.environ, **extra_env}
    print(f"→ 尝试 {name} ...")
    r = subprocess.run([sys.executable, "-c", _DOWNLOAD_SNIPPET,
                        C.EMBED_MODEL, str(C.MODEL_CACHE_DIR)],
                       env=env, capture_output=True, text=True, timeout=900)
    if r.returncode == 0 and "smoke OK" in r.stdout:
        print(f"  {name} 成功且冒烟验证通过")
        return True
    tail = (r.stderr or "").strip().splitlines()
    print(f"  {name} 失败: {tail[-1][:120] if tail else '未知错误'}")
    return False


def main() -> int:
    C.MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for name, env in SOURCES:
        if try_source(name, env):
            C.MODEL_READY_MARKER.write_text(f"model={C.EMBED_MODEL}\nsource={name}\n",
                                            encoding="utf-8")
            print(f"就绪标记已写入: {C.MODEL_READY_MARKER}")
            print("此后运行时将强制离线加载（local_files_only），演示现场零网络依赖")
            return 0
    print("所有下载源均失败：请检查网络，或手工把 fastembed 缓存复制到 models/fastembed/")
    return 1


if __name__ == "__main__":
    sys.exit(main())
