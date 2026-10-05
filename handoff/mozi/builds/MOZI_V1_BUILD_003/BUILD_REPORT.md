# 墨子 V1 · 施工报告

**裁决：`MOZI_FULL_BODY_BUILD = COMPLETE`**

> 注意：**BUILD_COMPLETE ≠ RECOVERY_AUTHORIZED。**
> 骨架造完 ≠ 有权执行恢复动作。L3/L4/L5 默认全关，白名单为空。

---

## 一｜13 模块一次造完整

| 模块 | 落点 | 职责 |
|---|---|---|
| HEART | `core.py` | V1 新心跳采集（独立，不碰现有 Heart） |
| WATCH_REGISTRY | `core.py` | 被观测对象登记 |
| HEALTH_MODEL | `core.py` | **六维**健康度（V3 §二） |
| PRE_DIAGNOSIS_SNAPSHOT | `core.py` | 诊断前冻结（保证判定可复现） |
| DIAGNOSIS | `core.py` | 确定性规则引擎 + **八字段诊断门**（V3 §三） |
| INCIDENT_LEDGER | `core.py` | 只增不改，哈希链防篡改 |
| DEDUP | `core.py` | 窗口去重，抑制重复事件与动作 |
| RECOVERY_POLICY | `recovery.py` | Finding→ActionSpec 策略表（6 条） |
| VERIFY | `recovery.py` | PRE/POST 条件校验 |
| ROLLBACK | `recovery.py` | 计划始终生成；**执行需 L3+ 授权** |
| BACKOFF | `recovery.py` | 指数退避（带 seed 可确定性测试） |
| CIRCUIT_BREAKER | `recovery.py` | closed→open→half_open |
| ESCALATION | `recovery.py` | 只开票不执行（KR_GATE / KR_ONLY） |

## 二｜权限分层（默认，独立复核值）

```
L0 OBSERVE              开
L1 DERIVE               开
L2 READONLY_IDEMPOTENT  开
L3 MUTATE               关   白名单 []
L4 KR_GATE              关   → target=KR_GATE
L5 KR_ONLY              关   → target=KR_ONLY

allows(): L3=False  L4=False  L2=True
```

## 三｜测试 21/21 PASS（V3 §二~§四 全覆盖）

```
T1  13 模块齐全                       modules=13 missing=[]
T2  L3 默认关闭 + 白名单为空            enabled=False whitelist=[]
T3  L3 动作只开票不执行                 ESCALATED executed=[]
T4  无数据 → UNKNOWN（不臆造）          NO_DATA
T5  DEDUP 窗口内抑制重复                suppressed=1
T6  事件账本哈希链可验                   chain_ok=True
T7  冻结快照 → 诊断确定性                fp 稳定
T8  回滚计划生成但执行被拦               BLOCKED_NOT_AUTHORIZED
T9  BACKOFF 单调退避                    [1.03, 2.03, 4.26, 8.06, 16.86]
T10 CIRCUIT_BREAKER 达阈值跳闸          state=open allows=False
T11 升级目标 L4→KR_GATE / L5→KR_ONLY  正确
T12 L2 动作确实可执行                   executed=['mark_watch_unknown']
T13 BUILD_COMPLETE ≠ RECOVERY_AUTHORIZED  L3_closed=True tickets=1
T14 静默→UNHEALTHY→R_SILENCE 走 L2     probe_and_report
T15 六维健康模型齐全                   DONE/UNKNOWN/UNKNOWN/UNKNOWN/NO_DATA/UNKNOWN
T16 禁 TASK_STATE→AGENT_STATE；无证据=UNKNOWN   no_data=UNKNOWN stale=STALE(≠OFFLINE)
T17 GENUINE_IDLE 独立（≠FAILURE/STALE/OFFLINE）  agent=GENUINE_IDLE
T18 诊断门八字段 + 无证据 UNKNOWN/NO_RECOVERY      likely=UNKNOWN dec=NO_RECOVERY
T19 静默有证据→RECOVERY_OK 建议仍被权限拦        l3_unexec=True
T20 自检六项 + 重启内部不自增 + 外部观察          RESTART_COUNT=0 obs=STALE
T21 多轮 loop/lag 正确，restart 仍 0             LOOP_COUNT=5
```

## 四｜V3 §二 六维健康模型（关键纪律）

`HealthModel.evaluate` 现返回 `DimensionalHealth`，六个维度互相独立：

```
TASK_STATE           —— 透传上下文（任务状态），绝不反向推导 AGENT_STATE
AGENT_STATE          —— 仅由心跳推导；无证据 → UNKNOWN（绝不臆造 OFFLINE）
RUNTIME_STATE        —— 来自 runtime_lag（可选）
DEPENDENCY_STATE     —— 来自上下文（可选）
DATA_FRESHNESS       —— 仅由心跳间隔推导（FRESH / STALE / NO_DATA）
SERVICE_REACHABILITY —— 来自上下文（可选）
```

禁止：
- `TASK_STATE=DONE + last_progress 旧` 直接推 `AGENT_STATE=OFFLINE`（旧 Heart 缺陷，已隔离）。
- 无证据时 `AGENT_STATE=OFFLINE`（一律 UNKNOWN）。
- `GENUINE_IDLE == FAILURE / STALE / OFFLINE`（互斥集 `GENUINE_IDLE_FORBIDDEN_EQUIVALENCE`）。

## 五｜V3 §三 诊断门（八字段 + 闸门）

`Diagnosis.diagnose(snap)` 输出八字段：
`SYMPTOM / EVIDENCE / LAST_GOOD / FIRST_BAD / AFFECTED_COMPONENT / LIKELY_CAUSE / CONFIDENCE / NEXT_TEST` + `recovery_decision`。

闸门：
- 证据不足（NO_DATA）→ `LIKELY_CAUSE=UNKNOWN`，`recovery_decision=NO_RECOVERY_NEXT_TEST_ONLY`。
- `confidence < 0.6` → 强制 `NO_RECOVERY_NEXT_TEST_ONLY`（禁止为"有诊断"硬猜）。
- 有证据（如 gap 超阈值）→ 可指因 `HEARTBEAT_GAP_EXCEEDS_THRESHOLD`，建议 `RECOVERY_OK`，但**执行仍受 L3/L4/L5 权限闸门**。

## 六｜V3 §四 自检六项指标 + 外部观察

`MoziV1.self_inspect()` 暴露：`MOZI_HEARTBEAT / LAST_GOOD / LAST_LOOP / LOOP_LAG / ERROR_COUNT / RESTART_COUNT`。

纪律：
- `RESTART_COUNT` 仅由**外部** `note_mozi_restart()` 改动；墨子内部**绝不**自增（杜绝"哪吒自动救墨子"）。
- `observe_mozi_heart(mozi, now, threshold)` 为**外部**观察者，判定 `MOZI_HEART_STALE`，**不在任何恢复/自救路径内调用**（杜绝"墨子自动救哪吒"）。
- 墨子自身死亡只允许被外部观察，不形成互相拉扯闭环。

## 七｜现有 Heart 红线

未修改 / 未重启 / 未调阈值 / 未扩功能 / 未人工 wake。
旧 `mozi_watch.py` 的 age-only / DONE→OFFLINE 缺陷记 `LEGACY_DEFECT=CONFIRMED`，已隔离，不影响 V1。
V1 为独立目录，不 import、不读写现有 Heart 任何文件或进程。

## 八｜若要开权

见 `PERMISSIONS.md` —— `gate.grant(3, ["<action>"])` 是唯一入口，本工程默认从不调用。
