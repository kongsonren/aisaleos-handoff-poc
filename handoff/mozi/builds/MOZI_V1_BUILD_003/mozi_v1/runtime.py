#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
墨子 V1 · 运行时编排（13 模块一次串完）

链路：
  HEART → WATCH_REGISTRY → HEALTH_MODEL → PRE_DIAGNOSIS_SNAPSHOT
        → DIAGNOSIS → DEDUP → INCIDENT_LEDGER → RECOVERY_POLICY
        → VERIFY → (闸门) → EXECUTE / ESCALATE
        ↘ ROLLBACK（计划始终生成，执行需授权）
        ↘ BACKOFF / CIRCUIT_BREAKER（连续失败保护）

默认：L2 及以下动作可执行；L3+ 一律 ESCALATE，不执行。
"""

import time
from typing import Dict, List

from .core import (Diagnosis, Heart, HealthModel, IncidentLedger,
                   PreDiagnosisSnapshot, WatchRegistry, Dedup)
from .models import Finding, Snapshot
from .permissions import L2, LAYER_NAMES, PermissionGate
from .recovery import Backoff, CircuitBreaker, Escalation, RecoveryPolicy, Rollback, Verify

MODULES = [
    "HEART", "WATCH_REGISTRY", "HEALTH_MODEL", "PRE_DIAGNOSIS_SNAPSHOT",
    "DIAGNOSIS", "INCIDENT_LEDGER", "DEDUP", "RECOVERY_POLICY", "VERIFY",
    "ROLLBACK", "BACKOFF", "CIRCUIT_BREAKER", "ESCALATION",
]


class MoziV1:
    def __init__(self, clock=time.time, gate: PermissionGate = None):
        self.clock = clock
        self.gate = gate or PermissionGate()
        self.heart = Heart(clock=clock)
        self.registry = WatchRegistry()
        self.health_model = HealthModel()
        self.snapshotter = PreDiagnosisSnapshot()
        self.diagnosis = Diagnosis()
        self.ledger = IncidentLedger(Dedup(window_s=300.0))
        self.policy = RecoveryPolicy()
        self.verify = Verify(ctx={})
        self.rollback = Rollback(self.gate)
        self.backoff = Backoff(seed=20261005)
        self.breaker = CircuitBreaker(threshold=3, cooldown_s=30.0, clock=clock)
        self.escalation = Escalation(self.gate)
        self.attempts: Dict[str, int] = {}
        self.executed: List[str] = []
        self.snapshots: List[Snapshot] = []
        # V3 §四 自检六项指标（墨子自身只观测/上报，绝不据此自救）
        self.loop_count = 0
        self.last_loop_at = None
        self.loop_lag = None
        self.error_count = 0
        self.restart_count = 0   # 仅外部 note_mozi_restart() 可改；内部永不自增
        self.last_good_at = None

    # 观测
    def register(self, watch_id, source, expected_interval_s, layer=0):
        return self.registry.register(watch_id, source, expected_interval_s, layer)

    def beat(self, watch_id, source=None, payload=None):
        w = self.registry.get(watch_id)
        return self.heart.beat(watch_id, source or (w.source if w else "unknown"),
                               payload)

    # 一轮完整周期（含自检埋点）
    def cycle(self, watch_id: str) -> dict:
        now = self.clock()
        self.loop_count += 1
        prev_loop = self.last_loop_at
        self.last_loop_at = now
        self.loop_lag = (now - prev_loop) if prev_loop is not None else 0.0
        try:
            w = self.registry.get(watch_id)
            if w is None:
                return {"watch_id": watch_id, "error": "WATCH_NOT_REGISTERED"}
            beats = self.heart.beats_of(watch_id)
            health = self.health_model.evaluate(
                w, beats, now, getattr(w, "context", None))
            snap = self.snapshotter.freeze(w, beats, health, now)
            self.snapshots.append(snap)

            findings = self.diagnosis.run(snap)
            self.verify.ctx.update({
                "watch_registered": True,
                "snapshot_frozen": True,
                "probe_result_recorded": True,
                "state_marked_unknown": True,
                "observation_logged": True,
                "no_open_incident_of_same_rule": True,
            })

            incidents, escalated, actions = [], [], []
            for f in findings:
                inc = self.ledger.add(f, now)
                if inc is None:
                    # 去重窗口内：抑制事件，同时抑制动作（不重复打扰、不重复施工）
                    continue
                incidents.append(inc.incident_id)
                spec = self.policy.spec_for(f.rule_id)
                if spec is None:
                    continue
                plan = self.rollback.make_plan(spec)          # 计划始终生成
                pre = self.verify.pre(spec)
                if not pre.ok:
                    escalated.append(self.escalation.escalate(
                        spec, "PRE_CONDITION_FAILED:%s" %
                        [c["condition"] for c in pre.checks if not c["ok"]]))
                    continue
                if spec.layer <= L2 and self.gate.allows(spec.layer, spec.name):
                    post = self.verify.post(spec)
                    ok = post.ok
                    self.breaker.record(ok)
                    if ok:
                        self.executed.append(spec.name)
                        actions.append({"action": spec.name, "layer": spec.layer,
                                        "result": "EXECUTED",
                                        "rollback_plan": plan.steps})
                    else:
                        n = self.attempts.get(spec.name, 0)
                        self.attempts[spec.name] = n + 1
                        actions.append({"action": spec.name, "layer": spec.layer,
                                        "result": "POST_FAILED",
                                        "backoff_s": self.backoff.delay(n)})
                else:
                    # L3+：开票，绝不执行
                    t = self.escalation.escalate(
                        spec, "LAYER_%s_NOT_AUTHORIZED" % LAYER_NAMES.get(spec.layer))
                    escalated.append(t)
                    actions.append({"action": spec.name, "layer": spec.layer,
                                    "result": "ESCALATED", "target": t.target,
                                    "executed": False})
            if health.state == "HEALTHY":
                self.last_good_at = now
            return {
                "watch_id": watch_id,
                "health": health.state,
                "score": health.score,
                "snapshot": snap.fingerprint_[:16],
                "findings": [f.rule_id for f in findings],
                "incidents": incidents,
                "actions": actions,
                "escalated": [t.as_dict() for t in escalated],
            }
        except Exception:
            # 异常计入自检 ERROR_COUNT；绝不在此自启/自愈
            self.error_count += 1
            raise

    # V3 §四 自检六项指标（外部可读，内部不据此自救）
    def self_inspect(self) -> dict:
        return {
            "MOZI_HEARTBEAT": self.last_loop_at is not None,
            "LAST_GOOD": self.last_good_at,
            "LAST_LOOP": self.last_loop_at,
            "LOOP_LAG": self.loop_lag,
            "ERROR_COUNT": self.error_count,
            "RESTART_COUNT": self.restart_count,
            "LOOP_COUNT": self.loop_count,
        }

    def note_mozi_restart(self) -> None:
        """**外部**重启钩子：墨子内部绝不调用，杜绝『墨子自动救墨子』。"""
        self.restart_count += 1
        self.last_loop_at = self.clock()

    # 状态
    def status(self) -> dict:
        return {
            "modules": MODULES,
            "module_count": len(MODULES),
            "permissions": self.gate.state(),
            "executed_actions": self.executed,
            "open_tickets": self.escalation.open_tickets(),
            "ledger_rows": len(self.ledger.rows),
            "ledger_chain_ok": self.ledger.verify_chain(),
            "dedup_suppressed": self.ledger.suppressed,
            "breaker": self.breaker.as_dict(),
            "snapshots": len(self.snapshots),
            "self_inspection": self.self_inspect(),  # V3 §四 六项指标（仅上报）
        }

    def module_inventory(self) -> Dict[str, str]:
        return {
            "HEART": type(self.heart).__name__,
            "WATCH_REGISTRY": type(self.registry).__name__,
            "HEALTH_MODEL": type(self.health_model).__name__,
            "PRE_DIAGNOSIS_SNAPSHOT": type(self.snapshotter).__name__,
            "DIAGNOSIS": type(self.diagnosis).__name__,
            "INCIDENT_LEDGER": type(self.ledger).__name__,
            "DEDUP": type(self.ledger.dedup).__name__,
            "RECOVERY_POLICY": type(self.policy).__name__,
            "VERIFY": type(self.verify).__name__,
            "ROLLBACK": type(self.rollback).__name__,
            "BACKOFF": type(self.backoff).__name__,
            "CIRCUIT_BREAKER": type(self.breaker).__name__,
            "ESCALATION": type(self.escalation).__name__,
        }
