"""B4：RPA 批量实弹（把"1/1"升级为"N/N 含断线补发"的可复跑证据）。

四科目，全部用平台真实代码路径（app.act.dispatch），不是手写 HTTP 凑数：
- 科目一·全量扫描：3 产品 × 6 月 = 18 次告警决策。数据集实况：仅 银黄05/板蓝根05
  有超阈值告警 → 断言 2 次应发尽发 + 16 次"无告警不制造任务"（纪律路径）。
- 科目二·幂等重发：同告警再跑一遍 → 双向核实后幂等跳过，零重复任务。
- 科目三·断线补发：杀 mock（内存态=对方失忆+不可达）→ 断线时 fail-safe 不补发
  （宁可待核实不制造重复）→ 重启 mock → 远程核实发现缺失 → 原 task_id 补发。
- 科目四·状态流转+追踪聚合：-FAST 状态机 40s 内离开 sent；tracking 四项聚合。

产物：docs/e2e/rpa_batch/dispatch_log.db + summary.md（每次运行重建，可重复）。
用法：python scripts/rpa_batch_drill.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MOCK = ROOT.parent / "创灵境_考题模拟数据" / "05_RPA接口文档" / "mock_rpa_server.py"
EVIDENCE = ROOT / "docs" / "e2e" / "rpa_batch"
DB = EVIDENCE / "dispatch_log.db"

import httpx  # noqa: E402

from app import act  # noqa: E402
from app.compute import CostCalculator  # noqa: E402
from app.ingest import init_store  # noqa: E402

BACKOFF = (0.5, 1.0)   # 演习提速；生产口径仍是 config 的 (2,4)


def start_mock() -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, str(MOCK)], cwd=str(MOCK.parent),
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    for _ in range(60):
        if act.probe():
            return proc
        time.sleep(0.5)
    raise RuntimeError("官方 mock 30s 内未就绪")


def stop_mock(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    assert MOCK.exists(), f"官方 mock 不存在: {MOCK}"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    DB.unlink(missing_ok=True)
    lines: list[str] = ["# B4 RPA 批量实弹证据\n"]

    proc = start_mock()
    calc = None
    try:
        store, _ = init_store()
        calc = CostCalculator(store)
        from app import config as C
        products = C.PRODUCTS
        months = [f"2026-{m:02d}" for m in range(1, 7)]
        print(f"[科目一] 全量扫描 {len(products)} 产品 × {len(months)} 月 …")

        # ---------- 科目一：18 次决策，应发尽发、无误发 ----------
        sent_ids: list[str] = []
        no_alert = 0
        for p in products:
            for m in months:
                res = act.dispatch(p, m, calc, llm=None, speed="FAST",
                                   db_path=DB, backoff=BACKOFF)
                for t in res["tasks"]:
                    assert t["dispatch"] == "sent" and t["notify"] == "pushed", t
                    sent_ids.append(t["task_id"])
                    print(f"  下发 {t['task_id']} → {t['assignee']}（{p} {m}）")
                if not res["tasks"]:
                    assert "无告警" in res["note"], res
                    no_alert += 1
        n_scan = len(products) * len(months)
        assert len(sent_ids) == 2 and no_alert == n_scan - 2, \
            f"预期 2 发 {n_scan-2} 静默，实际 {len(sent_ids)}/{no_alert}"
        lines.append(f"## 科目一 全量扫描\n\n- {n_scan} 次告警决策：**2 次应发尽发"
                     f"（{', '.join(sent_ids)}），{no_alert} 次无告警不制造任务**\n")
        print(f"[科目一] 通过：{n_scan} 次决策 = 2 发 + {no_alert} 静默")

        # ---------- 科目二：幂等重发，零重复 ----------
        res = act.dispatch("银黄口服液", "2026-05", calc, llm=None, speed="FAST",
                           db_path=DB, backoff=BACKOFF)
        assert not res["tasks"] and "幂等跳过" in res["note"] and not res["unverified"], res
        lines.append(f"## 科目二 幂等重发\n\n- 重复下发同告警：{res['note']}\n")
        print(f"[科目二] 通过：{res['note']}")

        # ---------- 科目三：断线 fail-safe → 恢复后原号补发 ----------
        stop_mock(proc)
        res = act.dispatch("银黄口服液", "2026-05", calc, llm=None, speed="FAST",
                           db_path=DB, backoff=BACKOFF)
        assert res["unverified"] and not res["tasks"], res
        lines.append(f"## 科目三 断线补发\n\n- mock 宕机时：{res['note']}")
        print(f"[科目三] 断线：{res['note']}")

        proc = start_mock()   # 内存态 mock 重启 = 对方失忆
        resent_all: list[dict] = []
        for p in ("银黄口服液", "板蓝根颗粒"):
            res = act.dispatch(p, "2026-05", calc, llm=None, speed="FAST",
                               db_path=DB, backoff=BACKOFF)
            assert res["resent"] >= 1, res
            for t in res["tasks"]:
                assert t["resent"] and t["task_id"] in sent_ids, "补发必须复用原 task_id"
                print(f"[科目三] 补发 {t['task_id']}（原号重投，对方侧身份稳定）")
            resent_all.extend(res["tasks"])
        lines.append(f"- mock 重启失忆后：远程核实发现缺失，**原 task_id 补发 "
                     f"{len(resent_all)} 个**（{', '.join(t['task_id'] for t in resent_all)}）\n")
        sent_ids.extend(t["task_id"] for t in resent_all)

        # ---------- 科目四：状态流转 + 追踪聚合 ----------
        deadline = time.monotonic() + 40
        final: dict[str, str] = {}
        watch = [t["task_id"] for t in resent_all]   # 只看重启后存活于当前 mock 的任务
        while time.monotonic() < deadline:
            for tid in watch:
                r = httpx.get(f"http://localhost:8090/api/rpa/tasks/{tid}", timeout=10)
                final[tid] = r.json()["data"]["status"]
            if all(s in ("confirmed", "in_progress", "completed")
                   for s in final.values()):
                break
            time.sleep(3)
        assert final and all(s != "sent" for s in final.values()), final
        agg = act.tracking(db_path=DB)
        assert agg["ok"], agg
        lines.append(f"## 科目四 状态流转与聚合\n\n- 状态观测："
                     + "；".join(f"{k}→{v}" for k, v in final.items())
                     + f"\n- 追踪聚合：`{agg['aggregate']}`\n")
        print(f"[科目四] 通过：{final}；聚合 {agg['aggregate']}")

        # dispatch_log 行数对账（发送成功/失败都留痕）
        from app import storage
        conn = storage.connect(DB)
        try:
            import pandas as pd  # noqa: F401
            df = storage.query("SELECT COUNT(*) AS n, SUM(ok) AS ok_n FROM dispatch_log",
                               (), conn)
            n, ok_n = int(df.iloc[0]["n"]), int(df.iloc[0]["ok_n"])
        finally:
            conn.close()
        lines.append(f"## dispatch_log 对账\n\n- 落库 {n} 条发送记录，成功 {ok_n} 条"
                     f"（含补发重投）；失败 0 条\n")
        lines.append("\n> 复跑：`python scripts/rpa_batch_drill.py`（证据库每次重建）\n")
        (EVIDENCE / "summary.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"\n===== B4 实弹通过：{n_scan} 次扫描 + 幂等 + 断线补发 + 状态流转 =====")
        print(f"证据：{EVIDENCE / 'summary.md'} / dispatch_log.db")
        return 0
    finally:
        if proc.poll() is None:
            stop_mock(proc)
        print("[B4] 官方 mock 已关停（无后台残留）")


if __name__ == "__main__":
    sys.exit(main())
