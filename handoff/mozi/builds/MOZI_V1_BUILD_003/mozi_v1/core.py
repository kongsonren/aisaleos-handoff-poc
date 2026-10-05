#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
墨子 V1 · 核心七模块

HEART / WATCH_REGISTRY / HEALTH_MODEL / PRE_DIAGNOSIS_SNAPSHOT
DIAGNOSIS / INCIDENT_LEDGER / DEDUP

**本文件全部为 L0~L1 语义：观测与推导，零外部副作用。**
不读取、不连接、不修改正在接受生存观察的现有 Heart。
"""

import time
from dataclasses import asdict
from typing import Dict, List, Optional

from .models import (DiagnosisReport, DimensionalHealth, Finding, Heartbeat,
                     HealthState, Incident, Snapshot, Watch, fingerprint)

# ── HEART ──────────────────────────────────────────────────────────────
class Heart:
    """V1 新心跳采集器（独立于现有 Heart，互不干扰）。"""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.beats: List[Heartbeat] = []
        self.ticks = 0

    def beat(self, watch_id: str, source: str, payload: Optional[dict] = None) -> Heartbeat:
        hb = Heartbeat(watch_id=watch_id, ts=self.clock(), source=source,
                       payload=payload or {})
        self.beats.append(hb)
        self.ticks += 1
        return hb

    def beats_of(self, watch_id: str) -> List[Heartbeat]:
        return [b for b in self.beats if b.watch_id == watch_id]

    def last(self, watch_id: str) -> Optional[Heartbeat]:
        seq = self.beats_of(watch_id)
        return seq[-1] if seq else None


# ── WATCH_REGISTRY ─────────────────────────────────────────────────────
class WatchRegistry:
    """被观测对象的登记表。注册即登记，不做任何外部动作。"""

    def __init__(self):
        self._w: Dict[str, Watch] = {}

    def register(self, watch_id: str, source: str, expected_interval_s: float,
                 layer: int = 0) -> Watch:
        if watch_id in self._w:
            raise ValueError("WATCH_ALREADY_REGISTERED: %s" % watch_id)
        w = Watch(watch_id=watch_id, source=source,
                  expected_interval_s=expected_interval_s, layer=layer)
        self._w[watch_id] = w
        return w

    def get(self, watch_id: str) -> Optional[Watch]:
        return self._w.get(watch_id)

    def all(self) -> List[Watch]:
        return list(self._w.values())

    def disable(self, watch_id: str) -> None:
        w = self._w.get(watch_id)
        if w:
            w.enabled = False


# ── HEALTH_MODEL ───────────────────────────────────────────────────────
class HealthModel:
    """
    V3 §二 六维健康度模型。

    六维互相独立，各自推导：
      TASK_STATE           —— 透传上下文（任务状态），不参与 AGENT_STATE 推导
      AGENT_STATE          —— 仅由心跳推导；无证据 → UNKNOWN（绝不臆造 OFFLINE）
      RUNTIME_STATE        —— 来自上下文 runtime_lag（可选）
      DEPENDENCY_STATE     —— 来自上下文（可选）
      DATA_FRESHNESS       —— 仅由心跳间隔推导
      SERVICE_REACHABILITY —— 来自上下文（可选）

    硬纪律：
      - 禁止 TASK_STATE=DONE + last_progress 旧 → 推 AGENT_STATE=OFFLINE。
      - 无心跳证据 → AGENT_STATE=UNKNOWN。
      - GENUINE_IDLE（空闲但存活）≠ FAILURE/STALE/OFFLINE。
    """

    GRACE = 2.0
    SEVERE = 4.0

    def evaluate(self, watch: Watch, beats: List[Heartbeat], now: float,
                 context: dict = None) -> DimensionalHealth:
        ctx = context or {}
        ev = {}
        if not beats:
            # 无数据 → 全部 UNKNOWN，绝不臆造 HEALTHY / OFFLINE
            return DimensionalHealth(
                watch.watch_id,
                task_state=ctx.get("task_state", "UNKNOWN"),
                agent_state="UNKNOWN",
                data_freshness="NO_DATA",
                evidence={"beats": 0,
                          "note": "无心跳样本：不臆造健康度、不臆造下线"})

        ts = sorted(b.ts for b in beats)
        last = ts[-1]
        gap = now - last
        ev.update(beats=len(ts), last_ts=round(last, 3), gap_s=round(gap, 3),
                  expected_interval_s=watch.expected_interval_s)

        # DATA_FRESHNESS：仅由心跳间隔推导
        if gap > watch.expected_interval_s * self.GRACE:
            data_freshness = "STALE"
        else:
            data_freshness = "FRESH"

        # AGENT_STATE：仅由心跳推导，绝不来自 TASK_STATE
        if data_freshness == "FRESH":
            task_state = ctx.get("task_state", "UNKNOWN")
            # 有新鲜心跳 = 进程存活；空闲但存活 → GENUINE_IDLE（≠ FAILURE/STALE/OFFLINE）
            if task_state in ("DONE", "PENDING") and gap <= watch.expected_interval_s:
                agent_state = "GENUINE_IDLE"
            else:
                agent_state = "ALIVE"
        else:
            # 久未上报：可疑但未确认下线，绝不臆造 OFFLINE
            agent_state = "STALE"

        # TASK_STATE：独立维度，仅透传，绝不反向推导 AGENT_STATE
        task_state = ctx.get("task_state", "UNKNOWN")

        # RUNTIME_STATE：来自 subject runtime_lag（可选）
        lag = ctx.get("runtime_lag")
        if lag is None:
            runtime_state = "UNKNOWN"
        elif lag > watch.expected_interval_s * self.SEVERE:
            runtime_state = "DEGRADED"
        else:
            runtime_state = "HEALTHY"

        dependency_state = ctx.get("dependency_state", "UNKNOWN")
        service_reachability = ctx.get("service_reachability", "UNKNOWN")

        return DimensionalHealth(
            watch.watch_id, task_state=task_state, agent_state=agent_state,
            runtime_state=runtime_state, dependency_state=dependency_state,
            data_freshness=data_freshness,
            service_reachability=service_reachability, evidence=ev)


# ── PRE_DIAGNOSIS_SNAPSHOT ─────────────────────────────────────────────
class PreDiagnosisSnapshot:
    """诊断前冻结：保证 Diagnosis 只在同一份不可变状态上判定（可复现）。"""

    def freeze(self, watch: Watch, beats: List[Heartbeat],
               health: HealthState, now: float = None) -> Snapshot:
        return Snapshot(watch_id=watch.watch_id,
                        frozen_at=now if now is not None else time.time(),
                        beats=list(beats), health=health)


# ── DIAGNOSIS ──────────────────────────────────────────────────────────
class Diagnosis:
    """确定性规则引擎：同一 Snapshot → 同一组 Finding。"""

    RULES = [
        ("R_SILENCE", "CRITICAL", lambda h: h.state == "UNHEALTHY"),
        ("R_LATE", "WARN", lambda h: h.state == "DEGRADED"),
        ("R_NO_DATA", "WARN", lambda h: h.state == "UNKNOWN"),
        ("R_JITTER", "INFO", lambda h: (h.evidence or {}).get("interval_cv", 0) > 1.0),
        ("R_UNREGISTERED", "INFO", lambda h: h.watch_id.startswith("__")),
    ]

    def run(self, snap: Snapshot) -> List[Finding]:
        out = []
        for rule_id, sev, pred in self.RULES:
            try:
                hit = bool(pred(snap.health))
            except Exception:
                hit = False
            if hit:
                out.append(Finding(rule_id=rule_id, watch_id=snap.watch_id,
                                   severity=sev,
                                   message="%s @ %s" % (rule_id, snap.watch_id),
                                   evidence={"health": asdict(snap.health),
                                             "snapshot": snap.fingerprint_[:16]}))
        return out

    def deterministic(self, snap: Snapshot, n: int = 3) -> bool:
        base = fingerprint([asdict(f) for f in self.run(snap)])
        return all(fingerprint([asdict(f) for f in self.run(snap)]) == base
                   for _ in range(n))

    # ── V3 §三 诊断门：八字段 ────────────────────────────────────────
    def diagnose(self, snap: Snapshot) -> DiagnosisReport:
        """确定性诊断。证据不足 → LIKELY_CAUSE=UNKNOWN；把握不足 → NO_RECOVERY。

        硬纪律：
          - LIKELY_CAUSE 必须有证据支撑，否则 UNKNOWN（禁止为"有诊断"硬猜）。
          - confidence < 0.6 → 强制 NO_RECOVERY_NEXT_TEST_ONLY。
        """
        h = snap.health
        ev = dict(h.evidence or {})
        beats = snap.beats
        last_good, first_bad = None, None
        if beats:
            ts = sorted(b.ts for b in beats)
            last = ts[-1]
            if h.data_freshness == "FRESH":
                last_good = last
            else:
                first_bad = last  # 最后上报时刻，其后失联

        if h.data_freshness == "NO_DATA":
            # 无证据：不臆造原因，不处置
            return DiagnosisReport(
                symptom="无心跳样本", evidence=ev, last_good=last_good,
                first_bad=first_bad, affected_component=snap.watch_id,
                likely_cause="UNKNOWN", confidence=0.0,
                next_test="补充心跳采集或确认观测对象已注册",
                recovery_decision="NO_RECOVERY_NEXT_TEST_ONLY")

        if h.data_freshness == "STALE" and h.agent_state == "STALE":
            # 有 gap 证据：可指因，但执行仍受权限闸门
            rep = DiagnosisReport(
                symptom="静默失联 / 数据陈旧", evidence=ev, last_good=last_good,
                first_bad=first_bad, affected_component=snap.watch_id,
                likely_cause="HEARTBEAT_GAP_EXCEEDS_THRESHOLD", confidence=0.7,
                next_test="主动探针确认进程是否存活",
                recovery_decision="RECOVERY_OK")
        elif h.agent_state == "GENUINE_IDLE":
            rep = DiagnosisReport(
                symptom="空闲存活（无新进展）", evidence=ev, last_good=last_good,
                first_bad=first_bad, affected_component=snap.watch_id,
                likely_cause="IDLE_NO_PROGRESS", confidence=0.6,
                next_test="无需处置，持续观测",
                recovery_decision="NO_RECOVERY_NEXT_TEST_ONLY")
        elif h.runtime_state == "DEGRADED":
            rep = DiagnosisReport(
                symptom="运行时延迟偏高", evidence=ev, last_good=last_good,
                first_bad=first_bad, affected_component=snap.watch_id,
                likely_cause="RUNTIME_LAG_HIGH", confidence=0.5,
                next_test="复测 runtime_lag",
                recovery_decision="NO_RECOVERY_NEXT_TEST_ONLY")
        else:
            rep = DiagnosisReport(
                symptom="观测正常", evidence=ev, last_good=last_good,
                first_bad=first_bad, affected_component=snap.watch_id,
                likely_cause="NONE", confidence=0.9,
                next_test="持续观测",
                recovery_decision="NO_RECOVERY_NEXT_TEST_ONLY")

        # 把握不足 → 强制不恢复，只补测
        if rep.confidence < 0.6:
            rep.recovery_decision = "NO_RECOVERY_NEXT_TEST_ONLY"
        return rep


# ── DEDUP ──────────────────────────────────────────────────────────────
class Dedup:
    """窗口去重：同 (rule, watch, severity) 在 window 内只记一次。"""

    def __init__(self, window_s: float = 300.0):
        self.window_s = window_s
        self._seen: Dict[str, float] = {}

    def is_duplicate(self, finding: Finding, now: float) -> bool:
        k = finding.dedup_key()
        last = self._seen.get(k)
        return last is not None and (now - last) < self.window_s

    def mark(self, finding: Finding, now: float) -> None:
        self._seen[finding.dedup_key()] = now

    def size(self):
        return len(self._seen)


# ── INCIDENT_LEDGER ────────────────────────────────────────────────────
class IncidentLedger:
    """只增不改的事件账本，哈希链防篡改。"""

    def __init__(self, dedup: Dedup = None):
        self.rows: List[Incident] = []
        self.dedup = dedup or Dedup()
        self.suppressed = 0

    def add(self, finding: Finding, now: float = None) -> Optional[Incident]:
        now = now if now is not None else time.time()
        if self.dedup.is_duplicate(finding, now):
            self.suppressed += 1
            return None
        prev = self.rows[-1].hash_ if self.rows else ""
        inc = Incident(incident_id="INC%04d" % (len(self.rows) + 1),
                       ts=now, finding=finding, prev_hash=prev)
        self.rows.append(inc)
        self.dedup.mark(finding, now)
        return inc

    def verify_chain(self) -> bool:
        prev = ""
        for r in self.rows:
            if r.prev_hash != prev:
                return False
            if r.hash_ != fingerprint({"id": r.incident_id, "ts": round(r.ts, 3),
                                       "f": asdict(r.finding), "prev": r.prev_hash}):
                return False
            prev = r.hash_
        return True

    def as_list(self):
        return [r.as_dict() for r in self.rows]


# ── V3 §四：外部观察者（墨子自身死亡只允许被外部观察）─────────────────
def observe_mozi_heart(mozi, now: float, threshold_s: float) -> dict:
    """**外部**观察墨子是否 STALE。

    关键纪律：此函数绝不在墨子的任何恢复 / 自救路径内被调用。
    墨子不得据此自动重启自己（哪吒自动救墨子），也不得自动救哪吒
    （墨子自动救哪吒）——杜绝互相拉扯闭环。
    """
    last = getattr(mozi, "last_loop_at", None)
    if last is None:
        return {"MOZI_HEART_STALE": True, "reason": "NO_LOOP_YET"}
    lag = now - last
    return {"MOZI_HEART_STALE": lag > threshold_s,
            "reason": "LAG=%.1f/TH=%.1f" % (lag, threshold_s)}
