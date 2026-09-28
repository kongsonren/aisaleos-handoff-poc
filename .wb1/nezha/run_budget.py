# -*- coding: utf-8 -*-
"""七日纪律③｜运行预算层：TIMEOUT_BUDGET / RETRY_LIMIT / CHECKPOINT / SWITCH_WORK

KR 令（KR-EXODUS-7D-SEAL-20260928-001 §③）：
  任何任务不得无限等待；连续失败达到合理上限 → BLOCKED；
  保留 Checkpoint，然后找其他已授权工作；不得死磕。

本模块**不改架构**，只在既有循环外面加四道闸：
  1) TIMEOUT_BUDGET —— 单拍墙钟预算（env NEZHA_BUDGET_SEC，默认 240s）。
     预算耗尽：本拍不再开新动作，保留 CHECKPOINT，等下一拍（绝不无限等待）。
  2) RETRY_LIMIT    —— 同一 task_id 连续失败上限（env NEZHA_RETRY_LIMIT，默认 3）。
     达到上限：该任务标 BLOCKED，并从候选池里剔除（不再死磕同一个）。
  3) CHECKPOINT     —— 记录每个任务最后一次推进到的检查点，供下一拍续做。
  4) SWITCH_WORK    —— 一个任务 BLOCKED，立刻看下一个候选（换别的已授权工作）。

诚实边界：
  · 这些闸只在**本循环内**生效，不假装能约束外部世界；
  · 状态文件不撞车 ≠ 现实世界不会重复执行，涉及外部副作用仍靠 CAS/fencing。
"""
from __future__ import annotations
import os, json, datetime

BUDGET_PATH = ".wb1/nezha/run_budget.json"
BUDGET_SEC = int(os.environ.get("NEZHA_BUDGET_SEC", "240"))
RETRY_LIMIT = int(os.environ.get("NEZHA_RETRY_LIMIT", "3"))


def _now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    except Exception:
        return datetime.datetime.now().isoformat(timespec="seconds")


def load(store):
    """读预算账本；读不到就当空账本（不得因读失败拖垮主循环）"""
    try:
        d, _, _, _ = store.read_json(BUDGET_PATH, default={})
        return d or {}
    except Exception:
        return {}


def save(store, data):
    """写预算账本；写失败只返回 False，不得让主循环崩"""
    try:
        store.commit_files({BUDGET_PATH: json.dumps(data, ensure_ascii=False, indent=2).encode()},
                           "[NEZHA] run_budget update")
        return True
    except Exception:
        return False


def is_blocked(budget, task_id):
    rec = (budget.get("tasks") or {}).get(task_id) or {}
    return bool(rec.get("blocked")) or int(rec.get("consecutive_fail", 0)) >= RETRY_LIMIT


def note_result(store, task_id, ok, checkpoint=None, note=""):
    """记一次结果：成功清零连续失败；失败累加；达上限 → BLOCKED（并保留 checkpoint）"""
    b = load(store)
    tasks = b.setdefault("tasks", {})
    rec = tasks.setdefault(task_id, {"consecutive_fail": 0, "runs": 0, "blocked": False})
    rec["runs"] = int(rec.get("runs", 0)) + 1
    rec["last_at"] = _now()
    if checkpoint:
        rec["checkpoint"] = checkpoint          # CHECKPOINT：失败也保留，供续做
    if ok:
        rec["consecutive_fail"] = 0
        rec["blocked"] = False
        rec["last_ok_at"] = _now()
    else:
        rec["consecutive_fail"] = int(rec.get("consecutive_fail", 0)) + 1
        rec["last_note"] = str(note)[:200]
        if rec["consecutive_fail"] >= RETRY_LIMIT:
            rec["blocked"] = True               # RETRY_LIMIT 用尽 → BLOCKED，不再死磕
            rec["blocked_at"] = _now()
    b["updated_at"] = _now()
    b["policy"] = {"budget_sec": BUDGET_SEC, "retry_limit": RETRY_LIMIT}
    save(store, b)
    return rec


def budget_left(t0):
    """返回本拍剩余秒数（负数=已超时）"""
    return BUDGET_SEC - (datetime.datetime.now().timestamp() - t0)


def exceeded(t0):
    return budget_left(t0) <= 0


def switch_candidates(candidates, budget):
    """SWITCH_WORK：过滤掉已 BLOCKED 的任务，剩下的按顺序排（第一个可用即换过去）"""
    alive, blocked = [], []
    for c in candidates:
        tid = c.get("task_id")
        (blocked if is_blocked(budget, tid) else alive).append(c)
    return alive, blocked
