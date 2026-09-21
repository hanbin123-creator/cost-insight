"""模块2 E2E 浏览器实测（单命令全包，零残留）。

流程：起 uvicorn(8000) + vite dev(7100) → 等端口就绪 →
headless Edge 打开看板 → 等待四图 canvas 渲染 → 断言首屏要素 →
点击「生成归因分析」验证 503→演示模式兜底 → 切换产品验证刷新 →
截图存证 → finally 杀掉全部子进程。

用法：python scripts/e2e_browser_check.py
退出码 0 = 全部断言通过；1 = 有失败项（明细打印在 stdout）。
"""
from __future__ import annotations

import subprocess
import sys
import time
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SHOTS = ROOT / "docs" / "e2e"
NPM = r"D:\KimiData\daimon-share\daimon\command-process-owner\bin\npm.cmd"

API_PORT = 8000
WEB_PORT = 7100


def wait_port(port: int, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True, timeout=10,
        )
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> int:
    procs: list[subprocess.Popen] = []
    logs: list = []
    try:
        # 输出重定向到文件而非 PIPE：Windows 上 PIPE 无人读取会缓冲区满阻塞子进程
        api_log = open(ROOT / "docs" / "e2e_uvicorn.log", "w", encoding="utf-8", errors="replace")
        web_log = open(ROOT / "docs" / "e2e_vite.log", "w", encoding="utf-8", errors="replace")
        logs += [api_log, web_log]
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.api:app", "--port", str(API_PORT)],
            cwd=ROOT, stdout=api_log, stderr=subprocess.STDOUT,
        ))
        procs.append(subprocess.Popen(
            [NPM, "run", "dev", "--", "--port", str(WEB_PORT), "--strictPort", "--host", "127.0.0.1"],
            cwd=WEB, stdout=web_log, stderr=subprocess.STDOUT,
        ))

        if not wait_port(API_PORT):
            print("FAIL: uvicorn 90s 内未就绪")
            return 1
        if not wait_port(WEB_PORT):
            print("FAIL: vite 90s 内未就绪")
            return 1
        print(f"服务就绪: api={API_PORT} web={WEB_PORT}")

        from playwright.sync_api import sync_playwright

        SHOTS.mkdir(parents=True, exist_ok=True)
        console_errors: list[str] = []
        bad_responses: list[str] = []
        # 预期的非 2xx：favicon 未提供（404）、LLM 未配置时归因端点 503（前端演示兜底的触发条件）
        expected_bad = ("favicon.ico", "/api/attribution")
        results: list[tuple[str, bool, str]] = []

        def check(name: str, fn):
            try:
                detail = fn()
                results.append((name, True, detail))
            except Exception as e:
                results.append((name, False, str(e)[:150]))

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(str(e)))
            page.on("response", lambda r: bad_responses.append(f"{r.status} {r.url}") if r.status >= 400 else None)

            page.goto(f"http://localhost:{WEB_PORT}/", wait_until="domcontentloaded", timeout=30000)

            # 1. 四张图表卡片挂载
            def _cards():
                page.wait_for_function(
                    "document.querySelectorAll('.grid > .panel').length === 4",
                    timeout=30000)
                return "4 张卡片已挂载"
            check("四张图表卡片", _cards)

            # 2. ECharts 实际绘制出 canvas（非空 option 才会生成）
            def _canvas():
                page.wait_for_function(
                    "document.querySelectorAll('.grid .panel canvas').length >= 4",
                    timeout=30000)
                return "≥4 个 canvas 已绘制"
            check("ECharts canvas 渲染", _canvas)

            # 3. 产品/月份下拉装载了真实数据（数据包共 3 个产品）
            def _selects():
                page.wait_for_function(
                    "document.querySelectorAll('.controls select')[0].options.length === 3",
                    timeout=15000)
                n_p = page.eval_on_selector_all(
                    ".controls select", "els => els.map(e => e.options.length)")
                return f"产品 {n_p[0]} 项 / 月份 {n_p[1]} 项"
            check("产品月份下拉", _selects)

            # 4. Agent 决策横幅（银黄口服液 2026-05 环比 +5.73% → 应建议归因）
            def _decision():
                page.wait_for_selector(".decision", timeout=15000)
                txt = page.inner_text(".decision")
                assert "Agent" in txt, f"横幅文本异常: {txt[:60]}"
                return txt.strip()[:90]
            check("Agent 决策横幅", _decision)

            # 5. 告警面板（2026-05 银黄口服液环比超阈值应有告警）
            def _alerts():
                page.wait_for_selector(".alerts", timeout=15000)
                txt = page.inner_text(".alerts")
                return txt.strip()[:90]
            check("波动告警面板", _alerts)

            # 6. 点击「生成归因分析」→ LLM 未配置 503 → 演示模式兜底
            def _demo():
                page.click(".controls button")
                page.wait_for_selector(".demo-tag", timeout=20000)
                badge = page.inner_text(".attribution-panel .badge, .panel .badge")
                summary = page.inner_text(".summary")
                assert "校验通过" in badge or "自动补全" in badge, f"badge 异常: {badge}"
                assert len(summary) > 10, "归因摘要为空"
                return f"demo 标注出现, badge={badge.strip()}, 摘要 {len(summary)} 字"
            check("归因演示模式兜底", _demo)

            # 7. 首屏稳定态：所有加载占位消失 + 每个图表 canvas 有实际图形像素
            #    （首次实测发现：canvas 存在≠图形已绘制，切换中间态会抓到空坐标轴）
            def _stable_pixels():
                page.wait_for_function(
                    "document.querySelectorAll('.grid .panel .state').length === 0",
                    timeout=30000)
                page.wait_for_timeout(800)  # 等 ECharts 入场动画完成
                stats = page.evaluate("""[...document.querySelectorAll('.grid .panel canvas')].map(c => {
                    const ctx = c.getContext('2d');
                    const d = ctx.getImageData(0, 0, c.width, c.height).data;
                    let n = 0;
                    for (let i = 0; i < d.length; i += 4) {
                        // 统计非白非透明的实际绘制像素
                        if (d[i+3] > 10 && !(d[i] > 245 && d[i+1] > 245 && d[i+2] > 245)) n++;
                    }
                    return n;
                })""")
                assert len(stats) >= 4, f"canvas 数不足: {len(stats)}"
                # 坐标轴本身约几百像素；真实图形（线/柱/饼/色块）应远超
                assert all(s > 800 for s in stats[:4]), f"有图表只有坐标轴无图形: {stats}"
                return f"4 图像素量 {stats}"
            check("图形像素实质渲染", _stable_pixels)

            # 8. 首屏（银黄口服液 2026-05）稳定态截图
            page.screenshot(path=str(SHOTS / "dashboard_first_screen.png"), full_page=True)
            print(f"截图: {SHOTS / 'dashboard_first_screen.png'}")

            # 9. 切换产品 → 等全部图表重绘完成 → 稳定态截图
            def _switch():
                old = page.inner_text(".decision")
                page.select_option(".controls select", index=1)
                page.wait_for_function(
                    f"document.querySelector('.decision') && document.querySelector('.decision').textContent !== {old!r}",
                    timeout=15000)
                # 关键：决策横幅先回来不代表图表绘完，须等加载占位消失
                page.wait_for_function(
                    "document.querySelectorAll('.grid .panel .state').length === 0",
                    timeout=30000)
                page.wait_for_timeout(800)
                new = page.inner_text(".decision")
                return f"已切换并重绘稳定: {new.strip()[:60]}"
            check("产品切换刷新", _switch)
            page.screenshot(path=str(SHOTS / "dashboard_product2.png"), full_page=True)
            print(f"截图: {SHOTS / 'dashboard_product2.png'}")

            browser.close()

        print("\n=== E2E 断言 ===")
        ok_all = True
        for name, ok, detail in results:
            print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
            ok_all &= ok
        # 非 2xx 响应分两类：预期内（favicon 404、LLM 未配置的 503）与意外
        unexpected = [r for r in bad_responses if not any(k in r for k in expected_bad)]
        expected_seen = [r for r in bad_responses if any(k in r for k in expected_bad)]
        if expected_seen:
            print("预期内非 2xx（设计行为）:")
            for r in expected_seen:
                print("  ", r)
        if unexpected:
            print("\n=== 意外非 2xx 响应 ===")
            for r in unexpected:
                print(" ", r)
            ok_all = False
        # console 错误：排除由预期 404/503 引起的 resource 加载提示
        real_console_errors = [
            e for e in console_errors
            if "Failed to load resource" not in e
        ]
        if real_console_errors:
            print("\n=== 浏览器 console 错误 ===")
            for e in real_console_errors[:10]:
                print(" ", e[:200])
            ok_all = False
        else:
            print("console 无脚本错误（resource 提示均来自预期 404/503）")
        return 0 if ok_all else 1
    finally:
        for proc in procs:
            kill_tree(proc)
        for f in logs:
            try:
                f.close()
            except Exception:
                pass
        print("子进程已全部清理")


if __name__ == "__main__":
    sys.exit(main())
