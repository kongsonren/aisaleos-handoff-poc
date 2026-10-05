#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
墨子 V1 · 恢复与保护六模块

RECOVERY_POLICY / VERIFY / ROLLBACK / BACKOFF / CIRCUIT_BREAKER / ESCALATION

**纪律：本文件把 Recovery 完整写出来，但默认一个都不执行。**
L3 变更类动作在权限闸门前一律转为 ESCALATION_TICKET。
BUILD_COMPLETE ≠ RECOVERY_AUTHORIZED。
"""

import random
import time
from typing import Dict, List, Optional

from .models import ActionSpec, RollbackPlan, Verification
from .permissions import (L2, L3, L4, L5, EscalationTicket, LAYER_TARGET,
                          PermissionGate, SovereigntyRequired)


# ── RECOVERY_POLICY ────────────────────────────────────────────────────
class RecoveryPolicy:
    """Finding → 动作规格。策略完整定义，是否可执行由闸门决定。"""

    TABLE: Dict[str, ActionSpec] = {
        "R_SILENCE": ActionSpec(
            name="probe_and_report", layer=L2,
            pre_conditions=["watch_registered", "snapshot_frozen"],
            post_conditions=["probe_result_recorded"],
            rollback=["no_state_change_to_rollback"]),
        "R_LATE": ActionSpec(
            name="tighten_poll_interval", layer=L3,
            pre_conditions=["watch_registered", "no_open_incident_of_same_rule"],
            post_conditions=["interval_updated", "health_reevaluated"],
            rollback=["restore_previous_interval"]),
        "R_NO_DATA": ActionSpec(
            name="mark_watch_unknown", layer=L2,
            pre_conditions=["watch_registered"],
            post_conditions=["state_marked_unknown"],
            rollback=["no_state_change_to_rollback"]),
        "R_JITTER": ActionSpec(
            name="observe_only", layer=L2,
            pre_conditions=["snapshot_frozen"],
            post_conditions=["observation_logged"],
            rollback=["no_state_change_to_rollback"]),
        "R_RESTART": ActionSpec(
            name="restart_service", layer=L4,
            pre_conditions=["kr_approval", "rollback_plan_ready"],
            post_conditions=["service_up", "health_reevaluated"],
            rollback=["restore_last_known_good"]),
        "R_CREDENTIAL": ActionSpec(
            name="rotate_credential", layer=L5,
            pre_conditions=["kr_only"],
            post_conditions=["credential_rotated"],
            rollback=["KR_MANUAL_ONLY"]),
    }

    def spec_for(self, rule_id: str) -> Optional[ActionSpec]:
        return self.TABLE.get(rule_id)

    def inventory(self):
        return {k: {"layer": v.layer, "name": v.name,
                    "rollback_steps": len(v.rollback)}
                for k, v in self.TABLE.items()}


# ── VERIFY ─────────────────────────────────────────────────────────────
class Verify:
    """前置 / 后置条件校验。校验本身零副作用。"""

    def __init__(self, ctx=None):
        self.ctx = ctx or {}

    def _check(self, cond: str) -> dict:
        ok = bool(self.ctx.get(cond, False))
        return {"condition": cond, "ok": ok}

    def pre(self, spec: ActionSpec) -> Verification:
        checks = [self._check(c) for c in spec.pre_conditions]
        return Verification(spec.name, "PRE", all(c["ok"] for c in checks), checks)

    def post(self, spec: ActionSpec) -> Verification:
        checks = [self._check(c) for c in spec.post_conditions]
        return Verification(spec.name, "POST", all(c["ok"] for c in checks), checks)


# ── ROLLBACK ───────────────────────────────────────────────────────────
class Rollback:
    """回滚计划生成器。**生成 ≠ 执行**：执行需 L3+ 授权。"""

    def __init__(self, gate: PermissionGate):
        self.gate = gate
        self.plans: List[RollbackPlan] = []

    def make_plan(self, spec: ActionSpec) -> RollbackPlan:
        plan = RollbackPlan(action=spec.name, steps=list(spec.rollback),
                            requires_layer=max(spec.layer, L3))
        self.plans.append(plan)
        return plan

    def execute(self, plan: RollbackPlan) -> RollbackPlan:
        """尝试执行回滚。未授权则记 NOT_ATTEMPTED 并抛主权要求。"""
        try:
            self.gate.require(max(plan.requires_layer, L3), plan.action + ":rollback")
        except SovereigntyRequired:
            plan.executed = False
            plan.execution_layer_result = "BLOCKED_NOT_AUTHORIZED"
            raise
        plan.executed = True
        plan.execution_layer_result = "EXECUTED"
        return plan


# ── BACKOFF ────────────────────────────────────────────────────────────
class Backoff:
    """指数退避。带 seed → 确定性（可测试），不带 seed → 真随机抖动。"""

    def __init__(self, base: float = 1.0, factor: float = 2.0,
                 max_s: float = 60.0, seed: int = None):
        self.base, self.factor, self.max_s = base, factor, max_s
        self.rng = random.Random(seed) if seed is not None else random.Random()

    def delay(self, attempt: int) -> float:
        raw = min(self.max_s, self.base * (self.factor ** max(0, attempt)))
        jitter = self.rng.uniform(0, raw * 0.1)
        return round(raw + jitter, 3)


# ── CIRCUIT_BREAKER ────────────────────────────────────────────────────
class CircuitBreaker:
    """closed → open（失败达阈值）→ half_open（冷却后可试探）→ closed/open。"""

    def __init__(self, threshold: int = 3, cooldown_s: float = 30.0,
                 clock=time.time):
        self.threshold, self.cooldown_s, self.clock = threshold, cooldown_s, clock
        self.state = "closed"
        self.failures = 0
        self.opened_at = 0.0

    def record(self, success: bool) -> str:
        if success:
            self.failures = 0
            self.state = "closed"
        else:
            self.failures += 1
            if self.failures >= self.threshold:
                self.state = "open"
                self.opened_at = self.clock()
        return self.state

    def allows(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open" and (self.clock() - self.opened_at) >= self.cooldown_s:
            self.state = "half_open"
        return self.state == "half_open"

    def as_dict(self):
        return {"state": self.state, "failures": self.failures,
                "threshold": self.threshold}


# ── ESCALATION ─────────────────────────────────────────────────────────
class Escalation:
    """升级通道。**只开票，绝不执行。**"""

    def __init__(self, gate: PermissionGate):
        self.gate = gate
        self.tickets: List[EscalationTicket] = []

    def escalate(self, spec: ActionSpec, reason: str) -> EscalationTicket:
        t = self.gate.ticket(spec.layer, spec.name, reason)
        self.tickets.append(t)
        return t

    def open_tickets(self):
        return [t.as_dict() for t in self.tickets]
