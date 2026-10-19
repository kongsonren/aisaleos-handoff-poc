# R10 生产候选包 + 单次受控生产准入申请（P0-D）

- **令号**：`KR-NEZHA-R10-CONSUMER-INTEGRATION-20261019-01`
- **候选包目录**：`PROD_CANDIDATE/`
- **基线目录**：`PROD_BASELINE/`（生产原文件，R7-era，本次未改动）
- **整合来源**：R8 真实跨进程链路 + R7 消费者/幂等/状态审计/RCA3 授权守卫 + R10 三缺陷修复
- **准入申请终态**：**`PENDING_KR_GATE`**（前腿施工、后腿审查、KR 决定生产准入；本包不授权任何部署/点火/批量消费/解除 HOLD）

---

## 1. 完整差分（REAL）

- 字节级 Unified Diff：**`PROD_CANDIDATE/DIFF_BASELINE_TO_CANDIDATE.md`**（787 行，含 watcher / executor 全量 + pat_bridge.py 全文）
- SHA256 机器清单：**`PROD_CANDIDATE/SHA256_MANIFEST.md`**

### 1.1 基线 + 候选 SHA256 表（磁盘 REAL 版本，测试时间晚于文件 mtime → 被测=当前）

| 文件 | 角色 | SHA256（前16） | 大小 | 变化 |
|---|---|---|---|---|
| `PROD_BASELINE/2WB_inbox_watcher.ps1` | 生产原 watcher（R7-era） | `f422509888f5a388` | 9748B | 基线 |
| `PROD_BASELINE/frontleg_executor.py` | 生产原 executor（R7-era） | `4319d5435eed472a` | 13426B | 基线 |
| `PROD_CANDIDATE/2WB_inbox_watcher.ps1` | **候选 watcher** | `898cfd06288b7d4a` | 9625B | 改凭据获取/去幻影RESULT/入队 |
| `PROD_CANDIDATE/frontleg_executor.py` | **候选 executor** | `8e17832827dd2317` | 20543B | 整合 R7+R8+RCA3+3修复 |
| `PROD_CANDIDATE/2WB_pat_bridge.py` | **新增**（沙箱凭据桥） | `92b51b03836e2b03` | 1335B | 仅隔离/沙箱用，非生产件 |

> 注：续做前会话摘要所记候选 SHA（`8a9f69…`/`996f339…`）与当前磁盘不符，但**文件大小完全一致**且 mtime 早于测试结果，故以磁盘 REAL SHA 为权威（优先机器可验证证据，不采信口头摘要）。

### 1.2 watcher 候选关键改动（REAL，来自 diff）

1. **凭据获取机制改造（要害，见 §5 凭据审查）**：移除生产原 `Add-Type CredRead` 整块，改为 `$env:GITHUB_PAT` 优先 → 缺失则调同目录 `2WB_pat_bridge.py`（python ctypes 读 wincred）。
2. **删除幻影 `[RESULT] status=REGISTERED`**：原 watcher 未执行却声明已登记，属 FALSE PASS；改为 `[TASK]` 信封入本地队列 `frontleg_inbox_queue.json`，交 executor 真实领取执行。
3. **FETCH 评论改用带 `Authorization` 的 `$headers`**：原 `$ua` 无认证，匿名 60/h 限流会触发 403。
4. **修复 `$isDecision` 未声明**（生产 watcher 曾引用未定义变量，死代码隐患）。
5. **队列读写硬化**：UTF8NoBOM 去 BOM + 单元素数组强制包裹为 `[...]`（防 executor JSON 解包崩溃）。

### 1.3 executor 候选关键改动（REAL，来自 diff）

- 状态机 `QUEUED→CLAIMED→RUNNING→RESULT→VERIFIED→CLOSED`，异常分支 `REJECTED_AUTH`/`RESULT_POST_FAIL`/`REFUSED_UNSAFE`。
- RCA3 令牌：HMAC-SHA256 占位实现（`sign_auth`/`verify_auth`；`"*"` 通配 order_id 仅隔离测试用）。
- 幂等 ledger（`processed` 去重 + 文件锁防并发）。
- POST 后独立回读 GitHub 评论并比对 sha256，回传失败/网络失败不得 CLOSED（记 `verified=False` 仍落账）。
- 三缺陷修复（见 `FAULT_REPORT.md` 第三节）。

---

## 2. 测试证据索引（P0-C，REAL）

- `FAULT_TESTS/FAULT_RESULTS_R10_EXECUTOR.json`：17 条逐条 `verdict=PASS`（机器可验证）。
- `FAULT_TESTS/FAULT_REPORT.md`：17/17 总表 + C1 真实 E2E 全状态链证据 + 3 缺陷修复记录。
- 类别 7（watcher 侧隔离）复用 R9 验收结论，本次不重复跑。

---

## 3. 凭据审查（REAL，生产准入前置条件）

| 项 | 现状 | 风险 / 处置 |
|---|---|---|
| 生产原 watcher 凭据 | `Add-Type CredRead` 读 wincred PAT（本沙箱被 PowerShell 安全策略整体拦截；真实生产宿主预期可用） | 候选**未保留**此路径，改 `env_or_python_bridge` |
| 候选 watcher 凭据 | `$env:GITHUB_PAT` 优先；缺失调 `2WB_pat_bridge.py` | 见下条 |
| `2WB_pat_bridge.py` | python ctypes 读 wincred 后 **`print(tok)` 明文打印 PAT 到 stdout** | **凭据暴露风险**：stdout 若被日志/终端捕获即泄露。仅限沙箱隔离测试用，**不得作为生产凭据通道**。 |
| executor PAT 使用 | 仅用于认证轮询 `api.github.com` 与 POST 回执，**绝不打印/落盘 secret** | 合规 |
| PAT 存储位 | wincred（`git:https://github.com`） | 真实生产宿主沿用；沙箱经桥读取 |

**结论 / 待 KR 拍板**：候选 watcher 的凭据机制**偏离生产原版**。生产准入二选一：
- (A) 采纳候选 `env_or_python_bridge` 用于真实生产宿主（需先硬化 `2WB_pat_bridge.py`，禁止明文 print，改为只返回给调用方内存变量）；或
- (B) 生产宿主保留原 `Add-Type CredRead`，仅沙箱测试用候选+watcher-bridge，生产部署时回退 watcher 凭据段。
**在凭据机制未定前，候选包整体不得进入生产部署。**

---

## 4. 备份回滚（REAL）

- 生产原文件完整保留于 `PROD_BASELINE/`（未改），SHA256 见 §1.1，回滚即复制回生产路径。
- 候选部署前须对生产路径原文件做带时间戳备份（建议 `*.bak-<ISO8601>`）。
- 回滚触发：单次验收任一硬指标 FAIL / KR 叫停 / 未完队列恢复异常 → 立即停止并还原 `PROD_BASELINE`。

---

## 5. 未完队列恢复（REAL）

- 生产原队列 `frontleg_inbox_queue.json` 若存在未完成 `Q-` 任务，executor 启动即 `consume_queue` 按 ledger 状态续跑（CLAIMED/RUNNING 残留任务重领，RESULT 后独立回读）。
- 验收前须快照生产队列 + ledger，确认无孤儿 `RUNNING` 任务；若有，先人工确认再放行（防重复执行副作用）。
- 隔离测试已覆盖 C5b（executor 中途崩溃重启恢复），证明恢复路径可用。

---

## 6. 单次受控生产验收范围 / 费用上限 / 超时 / 停止（REAL）

| 维度 | 约定 |
|---|---|
| 验收范围 | **单次、受控、低风险只读探测**（如 1 条 `[TASK] READONLY_PROBE` 真实外网 URL），**不**批量消费历史积压、**不**点火生产写入、**不**解除 HOLD |
| 费用上限 | GitHub API 仅认证轮询（已限频，无付费）；无云计算/付费调用；**上限 ¥0 新增成本** |
| 超时 | watcher 单轮 ≤ 60s；executor 单任务 ≤ 300s；整体验收窗口 ≤ 30 分钟 |
| 停止条件 | 任一硬指标 FAIL / 出现未授权写入 / KR 显式叫停 / 凭据机制未定 → 立即 STOP 并回滚 |
| 验收判定权 | KR 独享；前腿/后腿仅提供 REAL 证据与初判，不得自判生产 PASS |

---

## 7. 生产准入申请（终态）

```
ADMISSION_REQUEST:
  from: 2WB 前腿 (R10 P0-D)
  to: KR (生产准入最终裁决)
  candidate_sha:
    watcher = 898cfd06288b7d4a68003fb9f85850136db196857624800f6a5e1753b151fca3
    executor = 8e17832827dd2317e11f91b57d154262174d5b7cea989860e16e3fb019f0ef9b
    pat_bridge = 92b51b03836e2b036970ba2d341f2ccbfa2c68b61f8fcd61cc4f998bec5e17d4
  isolation_verdict: REAL_ISOLATED_E2E = PASS (17/17)
  blocker: 凭据机制偏离生产原版（§3），需 KR 在 (A)/(B) 中裁决
  status: PENDING_KR_GATE
  authorized_actions: NONE (无部署/点火/批量消费/解除HOLD)
```

> 本包仅作「受控生产准入申请」载体；**未取得 KR 显式 `可以` 前，HOLD 全程有效，任何生产变更一律禁止。**
