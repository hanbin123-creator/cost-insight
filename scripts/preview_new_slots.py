"""答辩确认用：截取报告中心（A3 签发位）与知识库（A1 飞轮徽标）两处前端效果。

流程：起 uvicorn(8000) + vite dev(7100) → 等端口 → headless 截图 → 杀全部子进程。
截图落到工作区根目录供确认，不进仓库。用法：python scripts/preview_new_slots.py
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OUT = ROOT.parent                      # 工作区根目录
NPM = r"D:\KimiData\daimon-share\daimon\command-process-owner\bin\npm.cmd"


def wait_port(port: int, timeout: float = 240.0) -> bool:
    """双协议族探测：vite 默认绑 IPv6 ::1（localhost 解析），只探 127.0.0.1 会误判未起。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for host in ("127.0.0.1", "::1"):
            try:
                socket.create_connection((host, port), timeout=1).close()
                return True
            except OSError:
                pass
        time.sleep(0.5)
    return False


def kill_tree(proc: subprocess.Popen) -> None:
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            proc.kill()
    except Exception:
        pass


def main() -> int:
    # 演示用合规命名占位报告（reports/ 已 gitignore，不进仓库）——只为呈现签发徽标
    demo = ROOT / "reports" / "银黄口服液_2026-05_月度成本分析报告.docx"
    created = False
    if not any((ROOT / "reports").glob("*成本分析报告.docx")) if (ROOT / "reports").exists() else True:
        (ROOT / "reports").mkdir(exist_ok=True)
        demo.write_bytes(b"demo")
        created = True

    api_log = open(ROOT / "preview_api.log", "w", encoding="utf-8")
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.api:app",
                            "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT,
                           stdout=api_log, stderr=subprocess.STDOUT)
    web = subprocess.Popen([NPM, "run", "dev", "--", "--port", "7100",
                            "--strictPort"], cwd=WEB)
    try:
        ok8000 = wait_port(8000)
        ok7100 = wait_port(7100)
        print(f"port8000={ok8000} port7100={ok7100}")
        if not (ok8000 and ok7100):
            print("端口未就绪"); return 1
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(channel="msedge", headless=True)
            except Exception:
                browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            for route, name in (("reports", "答辩预览_报告中心_签发位.png"),
                                ("kb", "答辩预览_知识库_飞轮徽标.png")):
                page.goto(f"http://localhost:7100/#/{route}")
                page.wait_for_timeout(6000)     # 首屏接口+渲染
                page.screenshot(path=str(OUT / name), full_page=True)
                print("saved:", name)
            browser.close()
        return 0
    finally:
        kill_tree(web)
        kill_tree(api)
        if created:
            demo.unlink(missing_ok=True)        # 演示占位文件用完即删


if __name__ == "__main__":
    raise SystemExit(main())
