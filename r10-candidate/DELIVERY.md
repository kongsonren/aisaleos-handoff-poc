# R10 Consumer 集成候选包 — 2WB → 1WB 独立审查交付清单

- **令号**：`KR-NEZHA-R10-CONSUMER-INTEGRATION-20261019-01`
- **交付方**：2WB 前腿（施工 + 初判）
- **审查方**：1WB 后腿（独立审查，回填 `REVIEW_HANDOFF/VERDICT_V*.md`）
- **交付方式**：GitHub 分支 + PR（`kongsonren/aisaleos-handoff-poc`，分支 `r10-candidate-delivery-20261019`，**不改任何生产分支**）
- **纪律边界**：不部署、不点火、不解除 HOLD；生产/权限/付费/高风险单独 KR_GATE

---

## 一、候选包内容（REAL 文件，可复核）

```
r10-candidate/
├── DELIVERY.md                         # 本清单
├── PROD_BASELINE/                      # 生产原文件（R7-era，未改动）
│   ├── 2WB_inbox_watcher.ps1           # SHA f422509888f5a388… 9748B
│   └── frontleg_executor.py            # SHA 4319d5435eed472a… 13426B
├── PROD_CANDIDATE/                     # R10 整合候选（已隔离验收）
│   ├── 2WB_inbox_watcher.ps1           # SHA 898cfd06288b7d4a… 9625B
│   ├── frontleg_executor.py            # SHA 8e17832827dd2317… 20543B
│   ├── 2WB_pat_bridge.py               # SHA 92b51b03836e2b03… 1335B（沙箱凭据桥，非生产件）
│   ├── DIFF_BASELINE_TO_CANDIDATE.md   # 字节级 Unified Diff（787行）
│   ├── SHA256_MANIFEST.md              # 机器 SHA256 清单
│   └── CANDIDATE_PACKAGE.md            # P0-D 候选包+生产准入申请(PENDING_KR_GATE)
├── FAULT_TESTS/                        # 原始测试证据
│   ├── FAULT_RESULTS_R10_EXECUTOR.json # 17 条逐条 verdict=PASS（机器可验证）
│   ├── FAULT_REPORT.md                 # 17/17 总表 + C1 真实 E2E 证据 + 3 缺陷修复
│   ├── r10_executor_runner.py          # 17 用例测试 runner
│   ├── mock_github.py / watcher_fault_runner.py / watcher_iso_test.ps1
└── REVIEW_HANDOFF/                     # P0-E 后腿审查交接
    ├── REVIEW_PACKAGE.md               # 八裁决前腿初判 + 审查指引
    └── VERDICT_V1..V8.md               # 前腿初判占位 + 后腿回填区
```

---

## 二、基线 + 候选 SHA256（磁盘 REAL，测试时间晚于 mtime → 被测=当前）

| 文件 | 角色 | SHA256(前16) | 大小 |
|---|---|---|---|
| PROD_BASELINE/2WB_inbox_watcher.ps1 | 生产原 watcher | f422509888f5a388 | 9748B |
| PROD_BASELINE/frontleg_executor.py | 生产原 executor | 4319d5435eed472a | 13426B |
| PROD_CANDIDATE/2WB_inbox_watcher.ps1 | 候选 watcher | 898cfd06288b7d4a | 9625B |
| PROD_CANDIDATE/frontleg_executor.py | 候选 executor | 8e17832827dd2317 | 20543B |
| PROD_CANDIDATE/2WB_pat_bridge.py | 沙箱凭据桥(非生产) | 92b51b03836e2b03 | 1335B |

> 续做前会话摘要所记候选 SHA 与磁盘不符，但文件大小完全一致且 mtime 早于测试；以磁盘 REAL SHA 为权威。

---

## 三、依赖闭包（REAL，零第三方包）

- `frontleg_executor.py`：`os, sys, json, ssl, re, time, ctypes, ctypes.wintypes, urllib.request, urllib.error, hashlib, base64, hmac` → **全部 Python 3.13 标准库**。
- `2WB_pat_bridge.py`：`ctypes, ctypes.wintypes, re` → 标准库。
- `2WB_inbox_watcher.ps1`：PowerShell 5.1 内置（`ConvertTo-Json` / `Invoke-RestMethod` / `System.Text.Encoding` / `System.IO.File`），无外部模块。
- 运行环境：Windows（ctypes.windll.advapi32 读 wincred）、Python 3.13.12（managed）、GitHub API（`api.github.com`）、PAT 取自 wincred `git:https://github.com`。
- **闭包结论：无任何 pip/第三方依赖，标准库即可运行。**

---

## 四、原始测试证据（REAL）

- `FAULT_TESTS/FAULT_RESULTS_R10_EXECUTOR.json`：17 条用例，`verdict=PASS` 全 17。
- C1 真实 E2E：测试令 `cid=6253472016` 经**真实** watcher `ACK+ENQUEUE` → 真实 executor `SCAN→RESULT(posted=6253477543)→VERIFIED(sha256_match=True)→CLOSED`，状态链 `QUEUED→CLAIMED→RUNNING→RESULT→VERIFIED→CLOSED` 全 REAL。
- 隔离验收期间发现并修复 3 个真实候选缺陷（SCAN 认证限流 / triggers 三元组解包 / fetch_json 二元组解包+容错），修复后重跑 17/17 全 PASS。
- 类别 7（watcher 侧隔离）复用 R9 验收结论。

---

## 五、八裁决｜前腿初判（后腿审查 `PENDING_1WB_REVIEW`）

| # | 裁决项 | 前腿初判 |
|---|---|---|
| V1 | INTEGRATED_CANDIDATE | PASS |
| V2 | REAL_ISOLATED_E2E | PASS（17/17） |
| V3 | FAULT_RECOVERY | PASS |
| V4 | AUTHORIZATION_GUARD | PASS |
| V5 | CREDENTIAL_SECURITY | **BLOCKED**（见下） |
| V6 | ROLLBACK_READINESS | PASS |
| V7 | INDEPENDENT_REVIEW | PENDING_1WB_REVIEW |
| V8 | PRODUCTION_ADMISSION_REQUEST | PENDING_KR_GATE |

**V5 BLOCKED（KR_GATE 阻塞项）**：候选 watcher 凭据获取机制偏离生产原版——移除 `Add-Type CredRead`，改为 `env_or_python_bridge`；且 `2WB_pat_bridge.py` 明文 `print(PAT)` 到 stdout，**不得作生产凭据通道**。需 KR 就二选一裁决：
- (A) 硬化桥：禁止明文打印，改为仅返回调用方内存变量；
- (B) 生产宿主回退 `Add-Type CredRead`，仅沙箱测试用候选+watcher-bridge。
**V5 未决前，整体不得进入生产（八裁决不得相互抵销）。**

---

## 六、交果汇总（PASS / FAIL / BLOCKED）

- 隔离验收：**PASS（17/17）**
- 凭据安全：**BLOCKED（V5，待 KR_GATE 裁决）**
- 后腿独立审查：**PENDING_1WB_REVIEW**
- 生产准入：**PENDING_KR_GATE**
- 生产部署 / HOLD：**未授权 / HOLD 维持**

> 本交付仅提交候选包供独立审查，不含任何生产变更、不解除 HOLD。1WB 审查结论回填 `REVIEW_HANDOFF/VERDICT_V*.md` 后由 KR 终裁。
