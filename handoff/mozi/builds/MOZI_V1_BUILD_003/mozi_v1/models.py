#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""墨子 V1 · 数据模型（纯数据，无副作用）。"""

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


def fingerprint(obj: Any) -> str:
    """确定性指纹：键排序 + UTF-8，保证同输入同输出（幂等可验）。"""
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# 健康度严重度阈值（与 core.HealthModel 共用，避免漂移）
HEALTH_GRACE = 2.0
HEALTH_SEVERE = 4.0


@dataclass
class Heartbeat:
    watch_id: str
    ts: float
    source: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def key(self):
        return fingerprint({"w": self.watch_id, "t": round(self.ts, 3),
                            "s": self.source, "p": self.payload})


@dataclass
class Watch:
    watch_id: str
    source: str
    expected_interval_s: float
    layer: int = 0
    enabled: bool = True
    context: Dict[str, Any] = field(default_factory=dict)  # 六维输入的外部上下文（task_state/runtime_lag/dependency_state/service_reachability）


@dataclass
class HealthState:
    watch_id: str
    state: str                 # HEALTHY / DEGRADED / UNHEALTHY / UNKNOWN
    score: float
    reasons: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)


# ── V3 §二：六维健康状态（维度互相独立，缺证据即 UNKNOWN）─────────────
TASK_STATES = {"PENDING", "RUNNING", "DONE", "FAILED", "CANCELLED", "UNKNOWN"}
AGENT_STATES = {"ALIVE", "IDLE", "GENUINE_IDLE", "BUSY", "DEGRADED",
                "STALE", "OFFLINE", "UNKNOWN"}
RUNTIME_STATES = {"HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"}
DEPENDENCY_STATES = {"REACHABLE", "UNREACHABLE", "DEGRADED", "UNKNOWN"}
DATA_FRESHNESS_STATES = {"FRESH", "STALE", "NO_DATA", "UNKNOWN"}
SERVICE_REACHABILITY_STATES = {"REACHABLE", "UNREACHABLE", "UNKNOWN"}

# 严格互斥集：GENUINE_IDLE 绝不等同于 FAILURE / STALE / OFFLINE
GENUINE_IDLE_FORBIDDEN_EQUIVALENCE = {"FAILURE", "STALE", "OFFLINE"}


@dataclass
class DimensionalHealth:
    """六维健康度。每一维独立推导，无证据则该维 UNKNOWN。

    硬纪律（V3 §二）：
      - AGENT_STATE 仅由心跳推导，绝不来自 TASK_STATE。
      - 无心跳证据 → AGENT_STATE=UNKNOWN（绝不臆造 OFFLINE）。
      - GENUINE_IDLE（空闲但存活）≠ FAILURE / STALE / OFFLINE。
    """
    watch_id: str
    task_state: str = "UNKNOWN"
    agent_state: str = "UNKNOWN"
    runtime_state: str = "UNKNOWN"
    dependency_state: str = "UNKNOWN"
    data_freshness: str = "UNKNOWN"
    service_reachability: str = "UNKNOWN"
    evidence: Dict[str, Any] = field(default_factory=dict)
    forbidden_derivation_violation: bool = False  # 若试图 TASK_STATE→AGENT_STATE 置真（本实现恒 False）

    @property
    def state(self) -> str:
        """回滚态：供既有管线 / 测试向后兼容（不为六维本身）。"""
        if self.data_freshness == "NO_DATA":
            return "UNKNOWN"
        if self.agent_state == "OFFLINE":
            return "UNHEALTHY"
        if self.data_freshness == "STALE":
            gap = self.evidence.get("gap_s", 0)
            exp = self.evidence.get("expected_interval_s", 1) or 1
            if gap > exp * HEALTH_SEVERE:
                return "UNHEALTHY"   # 严重陈旧（>×4）仍回滚为 UNHEALTHY
            return "DEGRADED"
        if self.agent_state in ("ALIVE", "IDLE", "GENUINE_IDLE", "BUSY"):
            return "HEALTHY"
        return "UNKNOWN"

    @property
    def score(self) -> float:
        base = {"HEALTHY": 1.0, "DEGRADED": 0.6, "UNHEALTHY": 0.2, "UNKNOWN": 0.0}
        return base.get(self.state, 0.0)


@dataclass
class DiagnosisReport:
    """V3 §三：诊断门八字段 + 恢复决策。"""
    symptom: str
    evidence: Dict[str, Any]
    last_good: Optional[float]
    first_bad: Optional[float]
    affected_component: str
    likely_cause: str            # 证据不足 → "UNKNOWN"，禁止硬猜
    confidence: float            # 0..1
    next_test: str
    recovery_decision: str       # RECOVERY_OK | NO_RECOVERY_NEXT_TEST_ONLY


@dataclass
class Snapshot:
    """PRE_DIAGNOSIS_SNAPSHOT —— 诊断前的不可变冻结态。"""
    watch_id: str
    frozen_at: float
    beats: List[Heartbeat]
    health: HealthState
    fingerprint_: str = ""

    def __post_init__(self):
        if not self.fingerprint_:
            self.fingerprint_ = fingerprint({
                "w": self.watch_id,
                "t": round(self.frozen_at, 3),
                "b": sorted(b.key() for b in self.beats),
                "h": asdict(self.health),
            })

    def as_dict(self):
        return {"watch_id": self.watch_id, "frozen_at": self.frozen_at,
                "beats": len(self.beats), "health": asdict(self.health),
                "fingerprint": self.fingerprint_}


@dataclass
class Finding:
    rule_id: str
    watch_id: str
    severity: str            # INFO / WARN / CRITICAL
    message: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def dedup_key(self):
        return fingerprint({"r": self.rule_id, "w": self.watch_id,
                            "s": self.severity})


@dataclass
class Incident:
    incident_id: str
    ts: float
    finding: Finding
    prev_hash: str = ""
    hash_: str = ""

    def __post_init__(self):
        if not self.hash_:
            self.hash_ = fingerprint({
                "id": self.incident_id, "ts": round(self.ts, 3),
                "f": asdict(self.finding), "prev": self.prev_hash})

    def as_dict(self):
        return {"incident_id": self.incident_id, "ts": self.ts,
                "rule_id": self.finding.rule_id, "severity": self.finding.severity,
                "prev_hash": self.prev_hash[:12], "hash": self.hash_[:12]}


@dataclass
class ActionSpec:
    name: str
    layer: int
    pre_conditions: List[str] = field(default_factory=list)
    post_conditions: List[str] = field(default_factory=list)
    rollback: List[str] = field(default_factory=list)


@dataclass
class Verification:
    action: str
    stage: str            # PRE / POST
    ok: bool
    checks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class RollbackPlan:
    action: str
    steps: List[str] = field(default_factory=list)
    requires_layer: int = 3
    executed: bool = False
    execution_layer_result: str = "NOT_ATTEMPTED"
