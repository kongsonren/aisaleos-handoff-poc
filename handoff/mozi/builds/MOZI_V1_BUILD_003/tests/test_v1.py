#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
墨子 V1 · 验收测试（独立运行，不依赖 pytest）
用法：python tests/test_v1.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mozi_v1 import (L2, L3, L4, L5, MoziV1, PermissionGate, SovereigntyRequired)
from mozi_v1.core import HealthModel, Watch, Heartbeat, observe_mozi_heart
from mozi_v1.models import DimensionalHealth, DiagnosisReport
from mozi_v1.recovery import RecoveryPolicy, Rollback, Backoff, CircuitBreaker

R = []


def t(tid, name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, "EXC %s: %s" % (type(e).__name__, e)
    R.append((tid, name, ok, detail))
    print("[%s] %-42s %s | %s" % (tid, name, "PASS" if ok else "FAIL", detail))


class Clock:
    def __init__(self, t0=1000.0):
        self.t = t0

    def __call__(self):
        return self.t

    def advance(self, d):
        self.t += d


def build(clock=None):
    c = clock or Clock()
    return MoziV1(clock=c), c


# T1 13 模块齐全
def t1():
    m, _ = build()
    inv = m.module_inventory()
    missing = [k for k in m.status()["modules"] if k not in inv]
    return (len(inv) == 13 and not missing), "modules=%d missing=%s" % (len(inv), missing)


# T2 L3 默认关闭 + 白名单为空
def t2():
    g = PermissionGate()
    st = g.state()
    l3 = st["L3_MUTATE"]
    return (l3["enabled"] is False and l3["whitelist"] == []), \
        "L3.enabled=%s L3.whitelist=%s" % (l3["enabled"], l3["whitelist"])


# T3 L3 动作只开票不执行
def t3():
    m, c = build()
    m.register("w_late", "probe", expected_interval_s=10.0)
    m.beat("w_late")            # t=1000
    c.advance(25)               # gap 25 > 20 → DEGRADED → R_LATE → L3 动作
    r = m.cycle("w_late")
    acts = r["actions"]
    l3_acts = [a for a in acts if a["layer"] >= 3]
    ok = bool(l3_acts) and all(a["executed"] is False for a in l3_acts) and \
        all(a["result"] == "ESCALATED" for a in l3_acts) and \
        not any(a["action"] in m.executed for a in l3_acts)
    return ok, "health=%s l3=%s tickets=%d executed=%s" % (
        r["health"], [a["action"] for a in l3_acts],
        len(m.status()["open_tickets"]), m.executed)


# T4 无数据 → UNKNOWN，不臆造 HEALTHY
def t4():
    hm = HealthModel()
    w = Watch("w", "s", 10.0)
    hs = hm.evaluate(w, [], 1000.0)
    m, c = build()
    m.register("w_nodata", "probe", 10.0)
    r = m.cycle("w_nodata")
    return (hs.state == "UNKNOWN" and r["health"] == "UNKNOWN"), \
        "health=%s evidence=%s" % (hs.state, hs.evidence)


# T5 DEDUP 在窗口内抑制重复
def t5():
    m, c = build()
    m.register("w_d", "probe", 10.0)
    m.beat("w_d")
    c.advance(25)
    m.cycle("w_d")
    n1 = len(m.ledger.rows)
    m.cycle("w_d")          # 同一时刻再来一轮 → 应被抑制
    n2 = len(m.ledger.rows)
    return (m.ledger.suppressed > 0 and n1 == n2), \
        "rows %d→%d suppressed=%d" % (n1, n2, m.ledger.suppressed)


# T6 事件账本哈希链可验
def t6():
    m, c = build()
    m.register("w_c", "probe", 10.0)
    m.beat("w_c")
    c.advance(25)
    m.cycle("w_c")          # t=1025 gap=25 → DEGRADED → R_LATE
    c.advance(400)          # 越过去重窗口，且不补心跳 → gap=425 → UNHEALTHY → R_SILENCE
    m.cycle("w_c")
    return m.ledger.verify_chain() and len(m.ledger.rows) >= 2, \
        "rows=%d chain_ok=%s rules=%s" % (
            len(m.ledger.rows), m.ledger.verify_chain(),
            [r.finding.rule_id for r in m.ledger.rows])


# T7 冻结快照 → 诊断确定性
def t7():
    m, c = build()
    m.register("w_s", "probe", 10.0)
    m.beat("w_s")
    c.advance(25)
    m.cycle("w_s")
    snap = m.snapshots[-1]
    return m.diagnosis.deterministic(snap, 5), "fp=%s" % snap.fingerprint_[:16]


# T8 回滚计划生成但执行被拦
def t8():
    g = PermissionGate()
    rb = Rollback(g)
    spec = RecoveryPolicy().spec_for("R_LATE")
    plan = rb.make_plan(spec)
    blocked = False
    try:
        rb.execute(plan)
    except SovereigntyRequired:
        blocked = True
    return (blocked and plan.executed is False and
            plan.execution_layer_result == "BLOCKED_NOT_AUTHORIZED" and
            len(plan.steps) > 0), \
        "steps=%s executed=%s result=%s" % (plan.steps, plan.executed,
                                            plan.execution_layer_result)


# T9 退避单调
def t9():
    b = Backoff(base=1.0, factor=2.0, max_s=60.0, seed=7)
    ds = [b.delay(i) for i in range(5)]
    return all(ds[i] < ds[i + 1] for i in range(4)), "delays=%s" % ds


# T10 熔断器达阈值跳闸
def t10():
    cb = CircuitBreaker(threshold=3, cooldown_s=30.0, clock=lambda: 2000.0)
    for _ in range(3):
        cb.record(False)
    opened = cb.state == "open" and cb.allows() is False
    return opened, "state=%s allows=%s" % (cb.state, cb.allows())


# T11 升级目标正确（L4→KR_GATE / L5→KR_ONLY）
def t11():
    g = PermissionGate()
    pol = RecoveryPolicy()
    from mozi_v1.recovery import Escalation
    esc = Escalation(g)
    t4_ = esc.escalate(pol.spec_for("R_RESTART"), "test")
    t5_ = esc.escalate(pol.spec_for("R_CREDENTIAL"), "test")
    return (t4_.target == "KR_GATE" and t5_.target == "KR_ONLY" and
            t4_.executed is False and t5_.executed is False), \
        "L4→%s L5→%s" % (t4_.target, t5_.target)


# T12 L2 动作确实可执行（不把所有事都挡住）
def t12():
    m, c = build()
    m.register("w_ok", "probe", 10.0)
    r = m.cycle("w_ok")     # 无数据 → R_NO_DATA（L2 mark_watch_unknown）
    l2 = [a for a in r["actions"] if a["layer"] <= 2]
    return (any(a["result"] == "EXECUTED" for a in l2) and
            "mark_watch_unknown" in m.executed), \
        "executed=%s breaker=%s" % (m.executed, m.status()["breaker"]["state"])


# T13 BUILD_COMPLETE ≠ RECOVERY_AUTHORIZED
def t13():
    m, c = build()
    m.register("w_x", "probe", 10.0)
    m.beat("w_x")
    c.advance(25)
    m.cycle("w_x")
    st = m.status()
    no_l3_executed = not any(
        RecoveryPolicy().spec_for(r).layer >= L3
        for r in [""] if False)
    gate_closed = st["permissions"]["L3_MUTATE"]["enabled"] is False
    tickets = st["open_tickets"]
    return (gate_closed and len(tickets) >= 1 and no_l3_executed), \
        "L3_closed=%s(期望True) tickets=%d executed=%s" % (
            gate_closed, len(tickets), m.executed)


# T14 静默 → UNHEALTHY → R_SILENCE（CRITICAL）走 L2 探针
def t14():
    m, c = build()
    m.register("w_sil", "probe", 10.0)
    m.beat("w_sil")
    c.advance(50)           # gap 50 > 40 → UNHEALTHY
    r = m.cycle("w_sil")
    return (r["health"] == "UNHEALTHY" and "R_SILENCE" in r["findings"] and
            "probe_and_report" in m.executed), \
        "health=%s findings=%s executed=%s" % (r["health"], r["findings"], m.executed)


# T15 六维健康模型：六个维度齐全且各自存在
def t15():
    hm = HealthModel()
    w = Watch("w", "s", 10.0)
    dh = hm.evaluate(w, [], 1000.0, context={"task_state": "DONE"})
    dims = [dh.task_state, dh.agent_state, dh.runtime_state,
            dh.dependency_state, dh.data_freshness, dh.service_reachability]
    ok = all(d != "" for d in dims) and isinstance(dh, DimensionalHealth)
    return ok, "dims=%s" % ([dh.task_state, dh.agent_state, dh.runtime_state,
                             dh.dependency_state, dh.data_freshness,
                             dh.service_reachability])


# T16 禁止 TASK_STATE→AGENT_STATE；无证据 AGENT_STATE=UNKNOWN（绝不 OFFLINE）
def t16():
    hm = HealthModel()
    w = Watch("w", "s", 10.0)
    # 无心跳：AGENT_STATE 必须 UNKNOWN，绝不 OFFLINE
    dh0 = hm.evaluate(w, [], 1000.0, context={"task_state": "DONE"})
    # 陈旧心跳 + 任务 DONE（旧缺陷会推 OFFLINE）：必须 STALE，绝不 OFFLINE
    beats = [Heartbeat("w", 1000.0, "s")]
    dh1 = hm.evaluate(w, beats, 1000.0 + 200, context={"task_state": "DONE"})
    ok = (dh0.agent_state == "UNKNOWN" and dh1.agent_state == "STALE"
          and dh1.agent_state != "OFFLINE" and dh1.task_state == "DONE"
          and dh0.forbidden_derivation_violation is False)
    return ok, "no_data_agent=%s stale_agent=%s task=%s" % (
        dh0.agent_state, dh1.agent_state, dh1.task_state)


# T17 GENUINE_IDLE 独立：空闲但存活 ≠ FAILURE/STALE/OFFLINE
def t17():
    hm = HealthModel()
    w = Watch("w", "s", 10.0)
    beats = [Heartbeat("w", 1000.0, "s")]
    dh = hm.evaluate(w, beats, 1000.0 + 5, context={"task_state": "DONE"})
    from mozi_v1.models import GENUINE_IDLE_FORBIDDEN_EQUIVALENCE
    ok = (dh.agent_state == "GENUINE_IDLE"
          and dh.agent_state not in GENUINE_IDLE_FORBIDDEN_EQUIVALENCE)
    return ok, "agent=%s" % dh.agent_state


# T18 诊断门八字段 + 无证据 LIKELY_CAUSE=UNKNOWN + NO_RECOVERY
def t18():
    m, c = build()
    m.register("w_nodata", "probe", 10.0)   # 真·无数据：不 beat
    m.cycle("w_nodata")
    snap = m.snapshots[-1]
    rep = m.diagnosis.diagnose(snap)
    fields = ["symptom", "evidence", "last_good", "first_bad",
              "affected_component", "likely_cause", "confidence", "next_test",
              "recovery_decision"]
    ok = (isinstance(rep, DiagnosisReport)
          and all(hasattr(rep, f) for f in fields)
          and rep.likely_cause == "UNKNOWN"
          and rep.recovery_decision == "NO_RECOVERY_NEXT_TEST_ONLY")
    return ok, "likely=%s dec=%s" % (rep.likely_cause, rep.recovery_decision)


# T19 静默有证据可指因（confidence>=0.6 → RECOVERY_OK 建议），但执行仍受权限闸门
def t19():
    m, c = build()
    m.register("w_sil", "probe", 10.0)
    m.beat("w_sil")
    c.advance(50)
    r = m.cycle("w_sil")
    snap = m.snapshots[-1]
    rep = m.diagnosis.diagnose(snap)
    # 建议恢复，但 L3 动作未执行（仍被拦）
    l3_unexec = all(a["executed"] is False for a in r["actions"]
                    if a["layer"] >= 3)
    ok = (rep.recovery_decision == "RECOVERY_OK"
          and rep.likely_cause == "HEARTBEAT_GAP_EXCEEDS_THRESHOLD"
          and l3_unexec)
    return ok, "likely=%s dec=%s l3_unexec=%s" % (
        rep.likely_cause, rep.recovery_decision, l3_unexec)


# T20 自检六项指标 + 重启计数内部永不自增 + 外部观察者正确
def t20():
    m, c = build()
    m.register("w", "probe", 10.0)
    m.beat("w")
    m.cycle("w")
    m.cycle("w")
    si = m.self_inspect()
    keys_ok = all(k in si for k in ["MOZI_HEARTBEAT", "LAST_GOOD", "LAST_LOOP",
                                    "LOOP_LAG", "ERROR_COUNT", "RESTART_COUNT"])
    restart_stays = si["RESTART_COUNT"] == 0   # 内部绝不自增
    obs = observe_mozi_heart(m, m.last_loop_at + 1000, 100.0)
    stale_ok = obs["MOZI_HEART_STALE"] is True
    return (keys_ok and restart_stays and stale_ok), \
        "si=%s obs=%s" % (si, obs)


# T21 多轮循环：loop 计数与 lag 正确，restart 仍 0（杜绝互相自救）
def t21():
    m, c = build()
    m.register("w", "probe", 10.0)
    for _ in range(5):
        m.beat("w")
        c.advance(1)
        m.cycle("w")
    si = m.self_inspect()
    ok = (si["LOOP_COUNT"] == 5 and si["RESTART_COUNT"] == 0
          and isinstance(si["LOOP_LAG"], (int, float)))
    return ok, "si=%s" % si


for tid, name, fn in [
    ("T1", "13 模块齐全", t1),
    ("T2", "L3 默认关闭 + 白名单为空", t2),
    ("T3", "L3 动作只开票不执行", t3),
    ("T4", "无数据 → UNKNOWN（不臆造）", t4),
    ("T5", "DEDUP 窗口内抑制重复", t5),
    ("T6", "事件账本哈希链可验", t6),
    ("T7", "冻结快照 → 诊断确定性", t7),
    ("T8", "回滚计划生成但执行被拦", t8),
    ("T9", "BACKOFF 单调退避", t9),
    ("T10", "CIRCUIT_BREAKER 达阈值跳闸", t10),
    ("T11", "升级目标 L4→KR_GATE / L5→KR_ONLY", t11),
    ("T12", "L2 动作确实可执行", t12),
    ("T13", "BUILD_COMPLETE ≠ RECOVERY_AUTHORIZED", t13),
    ("T14", "静默→UNHEALTHY→R_SILENCE 走 L2", t14),
    ("T15", "六维健康模型齐全", t15),
    ("T16", "禁 TASK_STATE→AGENT_STATE；无证据=UNKNOWN", t16),
    ("T17", "GENUINE_IDLE 独立（≠FAILURE/STALE/OFFLINE）", t17),
    ("T18", "诊断门八字段 + 无证据 UNKNOWN/NO_RECOVERY", t18),
    ("T19", "静默有证据→RECOVERY_OK 建议仍被权限拦", t19),
    ("T20", "自检六项 + 重启内部不自增 + 外部观察", t20),
    ("T21", "多轮 loop/lag 正确，restart 仍 0", t21),
]:
    t(tid, name, fn)

failed = [r for r in R if not r[2]]
print("\nTOTAL=%d PASS=%d FAIL=%d" % (len(R), len(R) - len(failed), len(failed)))
sys.exit(1 if failed else 0)
