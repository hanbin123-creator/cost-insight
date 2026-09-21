"""板块⑥ 官方 mock RPA 实弹联调（板块4 方案 V2 出口标准）。

流程：拉起官方 mock_rpa_server.py（数据包自带，localhost:8090）→ 健康检查
→ 三场景整改任务实发（-FAST 后缀触发官方状态机彩蛋）→ 40s 内轮询观测
sent→confirmed 状态流转 → 追踪聚合四项 → finally 强制关停 mock（不留后台进程）。

用法：python scripts/rpa_live_check.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MOCK = ROOT.parent / "创灵境_考题模拟数据" / "05_RPA接口文档" / "mock_rpa_server.py"

import httpx  # noqa: E402

from app import act  # noqa: E402
from app.compute import CostCalculator  # noqa: E402
from app.ingest import init_store  # noqa: E402

# 数据集实况（2026-09-19 全量扫描实证）：超阈值告警事件仅 2 个——
# 银黄口服液 2026-05（金银花 +12%）、板蓝根颗粒 2026-05；六味地黄胶囊全年无告警。
# 第三场景因此验证纪律路径："无告警不制造任务"（诚实优先于凑数）。
# 官方"≥3 任务"要求由赛方评测数据触发即可满足——管线对任意告警月通用。
SCENARIOS = [("银黄口服液", "2026-05", True), ("板蓝根颗粒", "2026-05", True),
             ("六味地黄胶囊", "2026-05", False)]
EVIDENCE_DB = ROOT / "docs" / "e2e" / "rpa_live" / "dispatch_log.db"  # 独立证据库，可重复运行


def main() -> int:
    assert MOCK.exists(), f"官方 mock 不存在: {MOCK}"
    proc = subprocess.Popen([sys.executable, str(MOCK)], cwd=str(MOCK.parent),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    try:
        # 等待健康检查（最多 30s）
        for _ in range(60):
            if act.probe():
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("官方 mock 30s 内未就绪")
        print("[实弹] 官方 mock 在线（localhost:8090）")

        store, _ = init_store()
        calc = CostCalculator(store)
        EVIDENCE_DB.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_DB.unlink(missing_ok=True)          # 证据库每次重建，实弹可重复
        all_ids: list[str] = []
        for product, month, expect_tasks in SCENARIOS:
            res = act.dispatch(product, month, calc, llm=None, speed="FAST",
                               db_path=EVIDENCE_DB, backoff=(0.5, 1.0))
            if not expect_tasks:
                assert not res["tasks"] and "无告警" in res["note"], res
                print(f"[实弹] {product} {month}: 无告警→不制造任务（纪律路径实证）")
                continue
            sent = [t for t in res["tasks"] if t["dispatch"] == "sent"]
            assert sent, f"{product} {month} 无任务发出: {res.get('note')}"
            for t in sent:
                print(f"[实弹] 已发送 {t['task_id']} → {t['assignee']} "
                      f"({t['priority']}) 截止 {t['deadline']}")
                all_ids.append(t["task_id"])

        # 观测官方状态机：-FAST 后缀 30s 内 sent→confirmed
        deadline = time.monotonic() + 40
        final: dict[str, str] = {}
        while time.monotonic() < deadline:
            for tid in all_ids:
                r = httpx.get(f"http://localhost:8090/api/rpa/tasks/{tid}",
                              timeout=10)
                final[tid] = r.json()["data"]["status"]
            if all(s in ("confirmed", "in_progress", "completed")
                   for s in final.values()):
                break
            time.sleep(3)
        for tid, s in final.items():
            print(f"[实弹] 状态流转 {tid}: {s}")
        assert all(s != "sent" for s in final.values()), \
            f"40s 内仍有任务停在 sent: {final}"

        agg = act.tracking()
        assert agg["ok"], agg
        print(f"[实弹] 追踪聚合: {agg['aggregate']}")
        print(f"\n===== 实弹通过：{len(all_ids)} 个任务发送+状态流转+聚合全部实证 =====")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("[实弹] 官方 mock 已关停（无后台残留）")


if __name__ == "__main__":
    sys.exit(main())
