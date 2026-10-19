# V5 — 凭据安全

- **裁决项**：凭据安全
- **令号**：KR-NEZHA-R10-CONSUMER-INTEGRATION-20261019-01
- **前腿初判**：PASS（待 1WB 独立审查）
- **前腿初判说明**：V5 修复令(Plan A)已落地——watcher 改为进程内凭据获取(测试钩子 > 环境变量 GITHUB_PAT > Windows Credential Manager P/Invoke CredReadW, UTF-8 解码匹配既有 python bridge 行为)，**彻底废除原 `(& python 2WB_pat_bridge.py 2>$null)` 捕获 stdout 明文 PAT 的泄漏链**；2WB_pat_bridge.py 降级为不打印明文的独立诊断工具(`--check` 仅输出 CRED_STATUS+TOKEN_LEN)。PAT 绝不写 stdout/stderr/日志/命令行/仓库/测试证据/异常报告；测试仅用 R10_TEST_FAKE_PAT 模拟凭据。V5 凭据三用例 3/3 PASS(V5a-1/V5a-2/V5b)，R10 executor 回归 17 cases(16 PASS + 1 SKIP 真实E2E)。前腿初判 PASS，待 1WB 独立审查。
- **后腿审查状态**：**PENDING_1WB_REVIEW**（前腿不得代填）
- **KR 终裁**：—（待裁决）

## 后腿(1WB)独立审查回填区

- [ ] 核对 SHA256（SHA256_MANIFEST.md）
- [ ] 抽查测试证据（建议 C1/C4b/C8c）
- [ ] 后腿结论：PASS / FAIL / BLOCKED / UNKNOWN = ___
- [ ] 后腿备注：___
