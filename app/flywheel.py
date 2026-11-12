"""数据飞轮（A1）：整改闭环经验回流知识库。

闭环链路：act.tracking() 拉到 RPA 侧任务状态 → 首次进入 confirmed 及以后状态的
任务沉淀为「历史整改经验记录」文本 → 追加到飞轮语料文档 → 复用 kb 热更新链路
（build_index 全量重建 + 检索器热切换）增量入库——飞轮不是 PPT 概念，已闭环。

纪律：
- 幂等：task_id 去重存 SQLite flywheel_log 表（与 dispatch_log 同库同风格），
  重复追踪不产生重复记录
- 如实：只记录 RPA 侧真实存在的任务与状态，不编造处理结果；记录文本完整保留
  任务原始字段（发现/建议/责任部门/截止），可追溯
- 旁路：写语料与重建索引分离——本模块只负责"沉淀"，重建由 api 层后台任务触发，
  失败不影响追踪主链路
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from . import config as C
from . import storage

# 进入这些状态即视为"已确认的经验"，值得沉淀（与 tracking() 的已确认口径一致）
_CONFIRMED_STATUSES = ("confirmed", "in_progress", "completed")

_DDL = """CREATE TABLE IF NOT EXISTS flywheel_log (
  task_id TEXT PRIMARY KEY, status TEXT, title TEXT, harvested_at TEXT)"""


def record_text(task: dict) -> str:
    """单条任务 → 知识库语料文本（自包含记录，BM25/向量可直接索引）。

    字段全部来自任务原文（RPA 侧返回），不新增任何编造的数值或结论。
    字段形态容错：assignee/source 在 RPA 侧可能是 dict（RectifyTask 全字段）
    或 str（精简视图）——两种都如实采用，不崩。"""
    src = task.get("source") or {}
    if not isinstance(src, dict):
        src = {"finding": str(src)}
    assignee = task.get("assignee") or {}
    if isinstance(assignee, dict):
        dept, name = assignee.get("department", "?"), assignee.get("name", "?")
    else:
        dept, name = str(assignee), "?"
    return (
        f"【历史整改记录】任务编号: {task.get('task_id', '?')}\n"
        f"任务: {task.get('task_title', '?')}\n"
        f"异常发现: {src.get('finding', '?')}\n"
        f"分析口径: {src.get('analysis_month', '?')} {src.get('analysis_type', '?')}"
        f"-{src.get('product', '?')}\n"
        f"责任部门: {dept}（{name}）\n"
        f"整改建议: {task.get('suggestion', '?')}\n"
        f"优先级: {task.get('priority', '?')}；截止时间: {task.get('deadline', '?')}\n"
        f"处理状态: {task.get('status', '?')}（RPA 侧实时状态）")


def _ensure_table(conn) -> None:
    conn.execute(_DDL)
    conn.commit()


def _harvested_ids(conn) -> set[str]:
    _ensure_table(conn)
    df = storage.query("SELECT task_id FROM flywheel_log", (), conn)
    return set(df["task_id"]) if not df.empty else set()


def _fetch_detail(task_id: str) -> dict | None:
    """向 RPA 侧拉取单任务全字段详情（列表接口是精简视图，缺 source/finding）。
    不可达返回 None——记录按现有字段如实沉淀，不阻塞主链路。"""
    import httpx
    try:
        r = httpx.get(f"{C.RPA_BASE_URL}/api/rpa/tasks/{task_id}", timeout=C.RPA_TIMEOUT)
        if r.status_code == 200:
            return r.json().get("data")
    except Exception:
        pass
    return None


def _needs_detail(task: dict) -> bool:
    """精简视图判定：source 缺失或不是完整 dict 时需要补详情。"""
    src = task.get("source")
    return not isinstance(src, dict) or "finding" not in src


def harvest(tasks: list[dict], db_path=None,
            doc_path: Path = C.FLYWHEEL_DOC,
            fetch_detail: Callable[[str], dict | None] | None = _fetch_detail
            ) -> list[dict]:
    """从追踪任务中沉淀新确认的经验。返回本次新沉淀的任务列表（空列表=无新增）。

    幂等：已沉淀过的 task_id 直接跳过；状态未达 confirmed 的任务不沉淀
    （sent/received 只是送达回执，还没有"处理结果"可言）。
    字段补全：列表视图为精简字段时，逐条拉详情接口补全 source/assignee——
    沉淀进知识库的必须是完整记录，"异常发现: ?"的残记录不如不沉淀。"""
    fresh = [t for t in tasks
             if t.get("status") in _CONFIRMED_STATUSES and t.get("task_id")]
    if not fresh:
        return []
    conn = storage.connect(db_path)
    try:
        done = _harvested_ids(conn)
        new = [t for t in fresh if t["task_id"] not in done]
        if not new:
            return []
        if fetch_detail is not None:
            new = [(fetch_detail(t["task_id"]) if _needs_detail(t) else None) or t
                   for t in new]
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        with doc_path.open("a", encoding="utf-8") as f:
            for t in new:
                f.write(record_text(t) + "\n\n")
        now = datetime.now().isoformat(timespec="seconds")
        for t in new:
            conn.execute(
                "INSERT OR IGNORE INTO flywheel_log VALUES (?,?,?,?)",
                (t["task_id"], t.get("status"), t.get("task_title"), now))
        conn.commit()
        return new
    finally:
        conn.close()
