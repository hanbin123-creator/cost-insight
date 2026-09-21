"""板块⑥ 行动闭环（RPA）：装配 → 闸2 schema → 发送 → 微信 → 落库 → 追踪聚合。

纪律（赛题约束原文）："RPA任务JSON必须过schema校验才发送"。
- 口径母本：任务字段由告警 + _DEPT_RULES 驱动，与报告 6.4 表同源同规则——
  一份规则两种投影，禁止另起炉灶
- LLM 仅润色 task_title/suggestion：数字回查闸 + RectifyTask schema 闸双过才替换
  代码版；任何一闸不过用代码版发送（降级不失败，来源如实标注）
- 状态真源在 RPA 服务侧：本系统只记 dispatch_log 发送日志，追踪实时拉取，
  不搞双写状态（避免对账问题）
- 重试策略与 llm.py 等效（3 次指数退避 2s/4s）；用手工循环而非 tenacity 装饰器，
  只为 backoff 可注入测试——策略本身一致（决策记录：可测性优先于写法统一）
- 演示后缀（官方 mock 状态机彩蛋，接口文档第七节）：speed="FAST" 时 task_id 带
  -FAST 后缀，30 秒内可观测 sent→confirmed 流转
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

import httpx
import yaml

from . import config as C
from . import storage
from .report_data import _DEPT_RULES
from .schemas import RectifyTask

_PRIORITY_EN = {"高": "high", "中": "medium", "低": "low"}
_SUGGEST_BY_DEPT = {
    "采购部": "核查采购合同调价条款，比对新老供应商报价，评估锁价备货",
    "生产部": "排查对应工序单耗与收率波动，核查设备运行记录",
    "财务部": "复核成本归集口径与预算执行偏差",
    "设备部": "核查设备故障记录与检维修计划执行",
}
_DDL = """CREATE TABLE IF NOT EXISTS dispatch_log (
  task_id TEXT PRIMARY KEY, product TEXT, month TEXT, title TEXT,
  ok INTEGER, detail TEXT, created_at TEXT)"""


class RpaError(Exception):
    """RPA 调用失败（4xx 确定性 / 重试耗尽的 5xx 或网络故障）。"""


# ---------- 名册与装配（规则，永不算数之外的纯映射） ----------

def load_roster(path: Path | None = None) -> dict:
    p = path or C.RPA_ROSTER_PATH
    with Path(p).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _deadline_of(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y}-{m + 1:02d}-25" if m < 12 else f"{y + 1}-01-25"


def assemble_tasks(product: str, month: str, alerts, roster: dict | None = None,
                   speed: str | None = None, seq_start: int = 1) -> list[RectifyTask]:
    """告警 → 官方十二字段任务（装配即过 RectifyTask schema，闸2 第一道）。"""
    roster = roster or load_roster()
    tasks = []
    for i, a in enumerate(alerts):
        dept, prio_cn = _DEPT_RULES.get(a.channel, ("财务部", "中"))
        person = roster.get(dept) or {"name": "待指派", "role": None}
        suffix = f"-{speed}" if speed else ""
        tasks.append(RectifyTask(
            task_id=f"TASK-{month[:4]}-{seq_start + i:04d}{suffix}",
            task_title=f"核查{a.element}异常（{a.channel}）",
            assignee={"name": person["name"], "department": dept,
                      "role": person.get("role")},
            source={"analysis_type": "月度成本分析", "analysis_month": month,
                    "product": product, "finding": a.message},
            priority=_PRIORITY_EN[prio_cn],
            deadline=_deadline_of(month),
            suggestion=_SUGGEST_BY_DEPT.get(dept, _SUGGEST_BY_DEPT["财务部"]),
            notify_method="wechat",
            created_at=datetime.now().isoformat(timespec="seconds")))
    return tasks


# ---------- LLM 润色（可选层；双闸不过回退代码版） ----------

def _numbers_in(text: str) -> set[float]:
    return {float(x) for x in re.findall(r"\d+\.\d+|\d+", text)}


def polish_tasks(tasks: list[RectifyTask], llm, alerts) -> tuple[list[RectifyTask], str]:
    """LLM 润色标题/建议。返回 (任务列表, 来源标注)。
    闸1 数字回查：润色文本数字必须 ⊆ 告警数字集；闸2：改后重过 RectifyTask。"""
    if llm is None:
        return tasks, "template"
    allowed = set()
    for a in alerts:
        allowed.update({round(a.mom_pct, 2), round(a.mom_pct, 1), round(abs(a.mom_pct), 2),
                        round(abs(a.mom_pct), 1)})
    briefing = "\n".join(
        f'{t.task_id}｜{t.task_title}｜建议: {t.suggestion}｜发现: {t.source.finding}'
        for t in tasks)
    messages = [
        {"role": "system", "content": "你是制药企业成本管理助理。把整改任务的标题与建议"
         "改写得更专业、可执行。纪律：只允许使用输入中出现的数字，禁止编造任何数值；"
         "逐字保留任务编号。输出 JSON: {\"items\": [{\"task_id\", \"task_title\", "
         "\"suggestion\"}]}，数量与输入一致。"},
        {"role": "user", "content": briefing}]
    try:
        import json
        data = json.loads(llm.chat(messages, json_mode=True))
        items = {i["task_id"]: i for i in data["items"]}
    except Exception:
        return tasks, "template·LLM润色失败"
    out, fell_back = [], False
    for t in tasks:
        it = items.get(t.task_id)
        if not it:
            out.append(t)
            continue
        nums = _numbers_in(it.get("task_title", "") + it.get("suggestion", ""))
        nums -= {float(t.task_id.split("-")[1]), float(t.task_id.split("-")[2][:4])}
        if not nums <= allowed:                      # 闸1：数字回查
            out.append(t)
            fell_back = True
            continue
        try:                                          # 闸2：schema 重验
            out.append(t.model_copy(update={
                "task_title": it["task_title"], "suggestion": it["suggestion"]}))
        except Exception:
            out.append(t)
            fell_back = True
    src = "llm" if not fell_back else "template·部分润色被拦截"
    return out, src


# ---------- 发送 / 微信 / 落库 ----------

def _post(url: str, payload: dict, backoff: tuple = C.RPA_RETRY_BACKOFF) -> dict:
    """3 次尝试指数退避；4xx 确定性失败不重试（与 render_pdf 死因分类同原则）。"""
    last: Exception = RpaError("未知错误")
    for attempt in range(len(backoff) + 1):
        try:
            r = httpx.post(url, json=payload, timeout=C.RPA_TIMEOUT)
            if r.status_code >= 500:
                last = RpaError(f"RPA 服务端错误 {r.status_code}: {r.text[:120]}")
            elif r.status_code >= 400:
                raise RpaError(f"RPA 请求被拒 {r.status_code}（确定性不重试）: "
                               f"{r.text[:120]}")
            else:
                return r.json()
        except httpx.TransportError as e:
            last = RpaError(f"网络故障: {e}")
        if attempt < len(backoff):
            time.sleep(backoff[attempt])
    raise last


def send_task(task: RectifyTask, backoff: tuple = C.RPA_RETRY_BACKOFF) -> dict:
    try:
        return {"ok": True, "receipt": _post(f"{C.RPA_BASE_URL}/api/rpa/tasks",
                                             task.model_dump(), backoff)}
    except RpaError as e:
        return {"ok": False, "error": str(e)}


def notify_wechat(task: RectifyTask, backoff: tuple = C.RPA_RETRY_BACKOFF) -> dict:
    """微信推送（消息体代码拼装，数字直接引用任务字段，不过手）。
    推送失败不否定任务本身——只记 warning（任务已分发是主事实）。"""
    msg = (f"【成本整改任务】\n任务编号: {task.task_id}\n任务: {task.task_title}\n"
           f"优先级: {task.priority}\n来源: {task.source.analysis_month} "
           f"{task.source.analysis_type}-{task.source.product}\n"
           f"截止: {task.deadline}\n请及时处理!")
    try:
        return {"ok": True,
                "receipt": _post(f"{C.RPA_BASE_URL}/api/notify/wechat",
                                 {"recipient": task.assignee.name,
                                  "department": task.assignee.department,
                                  "message": msg}, backoff)}
    except RpaError as e:
        return {"ok": False, "error": str(e)}


def _ensure_table(conn) -> None:
    conn.execute(_DDL)
    conn.commit()


def _log_dispatch(task, send: dict, notify: dict, db_path=None) -> None:
    conn = storage.connect(db_path)
    try:
        _ensure_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO dispatch_log VALUES (?,?,?,?,?,?,?)",
            (task.task_id, task.source.product, task.source.analysis_month,
             task.task_title, 1 if send["ok"] else 0,
             str({"send": send, "notify": notify})[:500],
             task.created_at))
        conn.commit()
    finally:
        conn.close()


def _sent_records(product: str, month: str, db_path=None) -> list[dict]:
    """幂等查重：同产品同月已成功发送的 [{task_id, title}]（双向核实要用 task_id）。"""
    conn = storage.connect(db_path)
    try:
        _ensure_table(conn)
        df = storage.query(
            "SELECT task_id, title FROM dispatch_log WHERE product=? AND month=? AND ok=1",
            (product, month), conn)
        return df.to_dict("records")
    finally:
        conn.close()


def _verify_remote(task_ids: list[str], timeout: float = 5.0) -> set[str] | None:
    """双向核实（问题一修复）：逐个问 RPA 侧任务是否仍在，覆盖 mock 重启失忆场景。
    返回对方查不到的 task_id 集合；服务不可达返回 None——fail-safe：
    全部视为已送达、不补发，防止对方其实有记录时重复下发（对方 400 去重
    是第二道保险）。参考 task-state-guard：不把未知结果猜成已送达。"""
    missing: set[str] = set()
    for tid in task_ids:
        try:
            r = httpx.get(f"{C.RPA_BASE_URL}/api/rpa/tasks/{tid}", timeout=timeout)
            if r.status_code == 404:
                missing.add(tid)
        except httpx.TransportError:
            return None
    return missing


def _next_seq(month: str, db_path=None) -> int:
    conn = storage.connect(db_path)
    try:
        _ensure_table(conn)
        df = storage.query("SELECT COUNT(*) AS n FROM dispatch_log", (), conn)
        return int(df.iloc[0]["n"]) + 1
    finally:
        conn.close()


# ---------- 编排入口 ----------

def dispatch(product: str, month: str, calc, llm=None, speed: str | None = None,
             roster: dict | None = None, db_path=None,
             backoff: tuple = C.RPA_RETRY_BACKOFF) -> dict:
    """告警 → 整改任务下发全流程。任何环节失败如实记录，不假装成功。

    幂等 = 双向核实（问题一修复）：本地 dispatch_log 记"已发送"只是收据，
    跳过前先逐个远程核实任务仍在 RPA 侧；对方查不到（mock 重启失忆）的
    用原 task_id 补发；对方不可达则不补发并标 unverified（fail-safe，
    宁可待核实也不制造重复任务——对方 400 去重是第二道保险）。"""
    pack = calc.metrics(product, month)
    if not pack.alerts:
        return {"product": product, "month": month, "tasks": [],
                "note": "本月无告警，无整改任务", "unverified": False, "resent": 0}
    records = _sent_records(product, month, db_path)
    missing = _verify_remote([r["task_id"] for r in records]) if records else set()
    unverified = missing is None
    if unverified:
        already = {r["title"] for r in records}
        resend_ids: dict[str, str] = {}
    else:
        already = {r["title"] for r in records if r["task_id"] not in missing}
        resend_ids = {r["title"]: r["task_id"] for r in records
                      if r["task_id"] in missing}
    tasks = assemble_tasks(product, month, pack.alerts, roster, speed,
                           seq_start=_next_seq(month, db_path))
    tasks = [t for t in tasks if t.task_title not in already]
    # 补发任务复用原 task_id：对方侧身份稳定，追踪页历史与补发单自然合并
    tasks = [t.model_copy(update={"task_id": resend_ids[t.task_title]})
             if t.task_title in resend_ids else t for t in tasks]
    if not tasks:
        note = ("全部告警任务此前已发送；RPA 暂不可达，未远程核实（不补发防重复）"
                if unverified else
                "全部告警任务此前已发送并经远程核实（幂等跳过，不重复下发）")
        return {"product": product, "month": month, "tasks": [],
                "note": note, "unverified": unverified, "resent": 0}
    tasks, text_source = polish_tasks(tasks, llm, pack.alerts)

    results = []
    for t in tasks:
        send = send_task(t, backoff)
        notify = notify_wechat(t, backoff) if send["ok"] else \
            {"ok": False, "error": "任务未发送成功，不推送"}
        _log_dispatch(t, send, notify, db_path)
        results.append({
            "task_id": t.task_id, "title": t.task_title,
            "assignee": f"{t.assignee.name}({t.assignee.department})",
            "priority": t.priority, "deadline": t.deadline,
            "dispatch": "sent" if send["ok"] else "dispatch_failed",
            "notify": "pushed" if notify["ok"] else "push_failed",
            "resent": t.task_title in resend_ids,
            "receipt": send.get("receipt"), "error": send.get("error")})
    return {"product": product, "month": month, "tasks": results,
            "text_source": text_source, "rpa_base_url": C.RPA_BASE_URL,
            "unverified": unverified,
            "resent": sum(1 for r in results if r["resent"])}


def tracking() -> dict:
    """任务追踪聚合（官方文档 6.2 前端展示四项：已生成/已送达/已确认/优先级分布）。
    状态真源在 RPA 侧，实时拉取；不可达如实返回，不展示假数据。"""
    try:
        r = httpx.get(f"{C.RPA_BASE_URL}/api/rpa/tasks",
                      params={"page_size": 100}, timeout=C.RPA_TIMEOUT)
        r.raise_for_status()
        data = r.json().get("data") or {}
        tasks = data.get("tasks") or []
    except Exception as e:
        return {"ok": False, "error": f"RPA 服务不可达: {e}", "aggregate": None}
    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for t in tasks:
        by_status[t.get("status", "?")] = by_status.get(t.get("status", "?"), 0) + 1
        by_priority[t.get("priority", "?")] = by_priority.get(t.get("priority", "?"), 0) + 1
    delivered = sum(by_status.get(s, 0) for s in
                    ("received", "confirmed", "in_progress", "completed"))
    confirmed = sum(by_status.get(s, 0) for s in
                    ("confirmed", "in_progress", "completed"))
    return {"ok": True,
            "aggregate": {"已生成": data.get("total", len(tasks)),
                          "已送达": delivered, "已确认": confirmed,
                          "by_status": by_status, "by_priority": by_priority},
            "tasks": tasks}


def probe(base_url: str | None = None) -> bool:
    """启动探活：RPA 健康检查（lifespan 挂点；不可达降级，不拒绝启动）。"""
    try:
        r = httpx.get(f"{base_url or C.RPA_BASE_URL}/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False
