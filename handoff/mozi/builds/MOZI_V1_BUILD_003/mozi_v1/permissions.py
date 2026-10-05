#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
墨子 V1 · 权限分层（PERMISSION LAYERING）

分层定义（KR 令，写死不可改）：
  L0 OBSERVE              可运行   —— 只读观测，零副作用
  L1 DERIVE               可运行   —— 由观测推导派生量，零副作用
  L2 READONLY_IDEMPOTENT  可运行   —— 只读 / 严格幂等（重复执行结果一致）
  L3 MUTATE               默认 FALSE，白名单为空  —— 任何改变外部状态
  L4 KR_GATE              KR 门    —— 需 KR 显式授权
  L5 KR_ONLY              KR 专属  —— 仅 KR 本人

硬约束：**Recovery 写得出来 ≠ 有权执行。**
L3 未开白名单时，任何调用一律转为 ESCALATION_TICKET，绝不执行。
"""

from dataclasses import dataclass, field
from typing import Dict, Set

L0, L1, L2, L3, L4, L5 = 0, 1, 2, 3, 4, 5

LAYER_NAMES = {
    L0: "L0_OBSERVE",
    L1: "L1_DERIVE",
    L2: "L2_READONLY_IDEMPOTENT",
    L3: "L3_MUTATE",
    L4: "L4_KR_GATE",
    L5: "L5_KR_ONLY",
}
LAYER_TARGET = {L4: "KR_GATE", L5: "KR_ONLY"}


class SovereigntyRequired(Exception):
    """需要主权授权才能继续。绝不静默执行。"""

    def __init__(self, action: str, layer: int, target: str):
        self.action = action
        self.layer = layer
        self.target = target
        super().__init__(
            "ACTION=%s LAYER=%s REQUIRES=%s (未授权，拒绝执行)" % (
                action, LAYER_NAMES.get(layer, layer), target))


@dataclass
class EscalationTicket:
    action: str
    layer: int
    target: str
    reason: str
    executed: bool = False

    def as_dict(self):
        return {"action": self.action, "layer": LAYER_NAMES.get(self.layer, self.layer),
                "target": self.target, "reason": self.reason, "executed": self.executed}


@dataclass
class PermissionGate:
    """权限闸门。默认 L3/L4/L5 全关，白名单空。"""
    enabled: Dict[int, bool] = field(default_factory=lambda: {
        L0: True, L1: True, L2: True, L3: False, L4: False, L5: False})
    whitelist: Dict[int, Set[str]] = field(default_factory=lambda: {
        L0: set(), L1: set(), L2: set(), L3: set(), L4: set(), L5: set()})

    def allows(self, layer: int, action: str = "") -> bool:
        """层是否放行。L2 及以下恒放行；L3+ 须显式开层且动作在白名单内。"""
        if layer <= L2:
            return self.enabled.get(layer, False)
        if not self.enabled.get(layer, False):
            return False
        wl = self.whitelist.get(layer, set())
        if not wl:
            return False          # 白名单为空 → 一律不放行
        return action in wl

    def require(self, layer: int, action: str) -> None:
        """放行则静默返回；否则抛主权要求。"""
        if self.allows(layer, action):
            return
        target = LAYER_TARGET.get(layer, "KR_APPROVAL")
        raise SovereigntyRequired(action, layer, target)

    def ticket(self, layer: int, action: str, reason: str) -> EscalationTicket:
        return EscalationTicket(action=action, layer=layer,
                                target=LAYER_TARGET.get(layer, "KR_APPROVAL"),
                                reason=reason, executed=False)

    def grant(self, layer: int, actions) -> None:
        """开权接口 —— 仅供 KR 授权后调用；本工程默认从不调用。"""
        if layer < L3:
            return
        self.enabled[layer] = True
        self.whitelist[layer] = set(actions or [])

    def state(self):
        return {LAYER_NAMES.get(k, k): {
            "enabled": v,
            "whitelist": sorted(self.whitelist.get(k, set())),
        } for k, v in sorted(self.enabled.items())}
