# 墨子 V1 · 权限分层与红线

> **`BUILD_COMPLETE ≠ RECOVERY_AUTHORIZED`。**
> Recovery 代码已经完整写出来，但**默认一个 L3+ 动作都不执行**。

## 分层表

| 层 | 名称 | 默认 | 语义 |
|---|---|---|---|
| L0 | OBSERVE | **开** | 只读观测，零副作用 |
| L1 | DERIVE | **开** | 由观测推导派生量，零副作用 |
| L2 | READONLY_IDEMPOTENT | **开** | 只读 / 严格幂等（重复执行结果一致） |
| L3 | MUTATE | **关**（白名单为空） | 任何改变外部状态的动作 |
| L4 | KR_GATE | **关** | 需 KR 显式授权（如重启服务） |
| L5 | KR_ONLY | **关** | 仅 KR 本人（如轮换凭证） |

## 硬约束（写进代码）

1. `PermissionGate.allows()`：L2 及以下恒放行；**L3+ 必须层已开且动作在白名单内**，白名单为空时一律拒绝。
2. `PermissionGate.require()`：未放行直接抛 `SovereigntyRequired`，**绝不静默执行**。
3. 未授权的动作不执行，而是生成 `EscalationTicket`（`executed=False`），目标 `KR_GATE` / `KR_ONLY`。
4. `Rollback.make_plan()` 始终生成计划；`Rollback.execute()` 需 L3+ 授权，未授权记为 `BLOCKED_NOT_AUTHORIZED` 并抛出。
5. `grant()` 是唯一开权入口——**本工程默认从不调用**，只能由 KR 授权后执行。

## 现有 Heart 红线（本轮施工未触碰）

- 未修改、未重启、未调阈值、未扩功能、未人工 wake。
- V1 是**独立新建目录**（`80-Code/mozi-v1/`），不 import、不读写现有 Heart 的任何文件/进程。
- 生存观察窗继续按原计划；`MOZI_HEART_24H` 状态由独立只读收果，不因本施工改写。

## 若要开权（KR 授权路径）

```python
gate = PermissionGate()
gate.grant(3, ["tighten_poll_interval"])   # 例：仅开这一个动作
```

开权前建议先确认：动作有 rollback 计划、有 pre/post 条件、有 circuit breaker 兜底。
