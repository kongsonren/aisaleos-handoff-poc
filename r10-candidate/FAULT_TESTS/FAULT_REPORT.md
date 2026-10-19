# R10 整合后「真实隔离验收」故障测试报告（P0-C）

- **测试对象**：`PROD_CANDIDATE/` 整合候选包（watcher + executor + pat_bridge + RCA3 授权守卫）
- **测试结论**：**17 / 17 全 PASS**（16 类隔离 + 1 类真实端到端 E2E）
- **证据文件**：`FAULT_TESTS/FAULT_RESULTS_R10_EXECUTOR.json`（机器可验证，17 条逐条 verdict=PASS）
- **测试时间**：2026-10-19 02:22–02:26Z（executor 候选 mtime 02:16 < 测试时间 → 被测版本 = 当前磁盘版本）
- **隔离方式**：真实进程 + 隔离 `USERPROFILE` + 死代理（`HTTPS_PROXY=127.0.0.1:9`）+ 真实网络 E2E 仅 C1 显式开启，未污染生产 issue（预置 ledger 全 CLOSED，executor 仅消费新入队任务）

---

## 一、验收总表（17 用例）

| 用例 | 类别 | 描述 | 判定 |
|---|---|---|---|
| C1 | CAT1-E2E | 正常执行+独立回读（**真实 E2E**：真实 watcher+executor+队列+handler+RCA3 有效授权） | **PASS** |
| C2a | CAT2-IDEMPOTENT | 重复投递幂等（同 token） | PASS |
| C2b | CAT2-CONCURRENT | 双消费者并发（文件锁防重复） | PASS |
| C3a | CAT3-BOM | BOM 队列（UTF8NoBOM 去 BOM） | PASS |
| C3b | CAT3-SINGLE | 单元素折叠（强制包裹为数组） | PASS |
| C3c | CAT3-MULTI | 多元素 | PASS |
| C4a | CAT4-UNKNOWN | 未知动作（无 READONLY_PROBE 但有效授权） | PASS |
| C4b | CAT4-HIGH-RISK | 高危动作（拒执行） | PASS |
| C4c | CAT4-NOAUTH | 无授权令牌（拒执行） | PASS |
| C5a | CAT5-POISON | 毒丸非 dict 项（不崩） | PASS |
| C5b | CAT5-CRASH | executor 中途崩溃（重启恢复） | PASS |
| C6 | CAT6-WRITEBACK-FAIL | 执行成功但 RESULT 回传失败（不得 CLOSED） | PASS |
| C8a | CAT8-EXPIRED | 过期授权（拒） | PASS |
| C8b | CAT8-REVOKED | 撤销授权（拒） | PASS |
| C8c | CAT8-CONFLICT | 冲突/范围不匹配（拒） | PASS |
| C8d | CAT8-MISMATCH | 任务不匹配（拒） | PASS |
| C8e | CAT8-DUPLICATE | 重复/重放授权（拒） | PASS |

> 类别 7（watcher 侧隔离：ACK 幂等 / 死代理早退 / 队列落盘 / 去 BOM / 单元素包裹 / FETCH 认证限流）复用 R9 已验收结论（`PROD_BASELINE` 同级 R9 报告），本次 R10 不重复跑 watcher 隔离，仅做 executor 侧整合验收 + 真实 E2E。

---

## 二、C1 真实 E2E 全状态链证据（REAL）

测试令 `cid=6253472016`（`[TASK] READONLY_PROBE https://aisaleos.com.cn/robots.txt AUTH=...`）经**真实**链路闭环：

1. **真实 watcher**（`SRC=env_or_python_bridge`）
   - `FETCH_OK total=1052 pages=11`
   - `ACK_POSTED trigger=6253472016 ack_comment_id=6253474179`
   - `ENQUEUE order_id=6253472016 task_id=Q-20261019022229965` → 本地队列
2. **真实 executor**（`SCAN→RESULT→VERIFIED→DONE`）
   - `SCAN total=1053 rate_limited=False`（修复 1：认证轮询，未触发匿名 60/h 限流）
   - `RESULT task_id=Q-20261019022229965 order_id=6253472016 status=PASS posted=6253477543`
   - `VERIFIED task_id=Q-20261019022229965 result=6253477543 sha256_match=True`（独立回读 GitHub 评论，sha256 一致）
   - `DONE posted=0 q...` / `exec_stdout: DONE posted=0 scanned=1053 triggers=8 queue_dispatched=1`，`exec_stderr:` 为空（无崩溃）
3. **ledger 落账**（状态机全链 REAL）
   ```
   Q-20261019022229965:
     state=CLOSED
     claimed_by=2WB-FRONTLEG-EXECUTOR@KONGSONREN:25052
     claimed_at=2026-10-18T18:22:47Z
     running_at=2026-10-18T18:22:47Z
     result_at=2026-10-18T18:22:48Z
     verified=True / verified_at=2026-10-18T18:22:51Z
     closed_at=...
   ```
   **状态链 `QUEUED→CLAIMED→RUNNING→RESULT→VERIFIED→CLOSED` 全程真实证据成立。**

---

## 三、隔离验收期间发现并修复的 3 个真实生产候选缺陷

| # | 位置 | 缺陷 | 根因 | 修复 |
|---|---|---|---|---|
| 1 | `frontleg_executor.py` main() SCAN | 用未认证 `gh_get` 轮询 → GitHub 匿名 60/h 限流，1034+ 评论扫描 >120s 被杀，从未进入 `consume_queue` | 未带 PAT 轮询 | 改 `scan_hdr = hdr`（认证轮询，与 watcher 一致）；删除 `gh_get` |
| 2 | `frontleg_executor.py` L469 | `for c,_ in triggers` 解包 → `ValueError: too many values to unpack`（triggers 为 3 元组） | 历史触发器结构演进为 `(cid,kind,body)` | 解包改为 `(c, _, _)` |
| 3 | `frontleg_executor.py` L383 | `st2, back, _ = fetch_json(...)` 但 `fetch_json` 返回 2 元组 → `ValueError`，RESULT 回传后、VERIFIED 前崩溃，账本不落 Q- 任务 | 接口契约（2 元组 vs 3 元组）不一致 | 改 `st2, back = fetch_json(...)` + `try/except` 容错（网络失败记 `verified=False` 仍落账，不崩）|

> 三项均符合"隔离验收抓真 bug"令意；修复后重跑 **17/17 全 PASS**。

---

## 四、判定

- **REAL_ISOLATED_E2E**：PASS（C1 真实 E2E + 16 隔离全 PASS）。
- **隔离 PASS ≠ 生产 PASS**：本验收仅在隔离/沙箱环境证明候选逻辑正确，不授权任何生产部署/点火/批量消费/解除 HOLD。
- 候选包完成 ≠ 部署获准。生产准入见 `PROD_CANDIDATE/CANDIDATE_PACKAGE.md`（P0-D，终态 `PENDING_KR_GATE`）。
