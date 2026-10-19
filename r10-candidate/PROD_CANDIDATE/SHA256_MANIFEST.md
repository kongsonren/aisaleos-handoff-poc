# SHA256 MANIFEST (REAL on-disk tested versions) — 2026-10-19T14:40:00Z

## PROD_BASELINE (生产原文件, R7-era, 未改动)
2WB_inbox_watcher.ps1                    f422509888f5a388eb32534cbddbcdadaac3bd4432211a7cd264deb1b0cb771a
  size=9748
frontleg_executor.py                     4319d5435eed472a899208b0a2cf143be2190f1fc50b67b95c60d978a236355d
  size=13426

## PROD_CANDIDATE (R10 整合候选, 已隔离验收 + V5 凭据修复)
2WB_inbox_watcher.ps1                    efe5d17eb9e75d9485f3a74a117832828957d30ac62b9dcf1af07c25623bca2e
  size=11612
2WB_pat_bridge.py                        864b97d3c150fbd4e9d0266d93c1998e777c7deece70b3f790a55379d21887fb
  size=2742
frontleg_executor.py                     8e17832827dd2317e11f91b57d154262174d5b7cea989860e16e3fb019f0ef9b
  size=20543

## V5 凭据安全修复测试证据 (FAULT_TESTS)
v5_credential_tests.py                   8fdb2a99fd8f7233dc58193a22f25d029bc199c66a5428b5ee03c5f0c856b2fc
  size=4492
V5_CREDENTIAL_RESULTS.json               62c025b78026a1aec9eaa5821302aa560f26ecbb88a4ebe959c793e93582513b
  size=449   (3/3 PASS: V5a-1/V5a-2/V5b)
r10_executor_runner.py                   07331300d4f898f554318a395efe098bcb6ee9d3fa5b9079c94df8220a755da2
  size=17270
FAULT_RESULTS_R10_EXECUTOR.json          0679c67ee73a522ce7310b90bcb263147fb0bb625a1bfa106cce7d3ecc257170
  size=42447 (17 cases: 16 PASS + 1 SKIP real-E2E by design)

## 说明
- V5 修复核心：watcher 改为进程内凭据获取 (测试钩子 / 环境变量 / Windows Credential Manager P/Invoke)，
  废除原 `(& python 2WB_pat_bridge.py 2>$null)` 捕获 stdout 明文 PAT 的泄漏链。
- 2WB_pat_bridge.py 现仅作不打印明文的独立诊断工具 (`--check` 仅输出 CRED_STATUS + TOKEN_LEN)。
- 全部 PAT 绝不写 stdout/stderr/日志/命令行/仓库/测试证据/异常报告；测试仅使用 R10_TEST_FAKE_PAT 模拟凭据。
- 生产 HOLD 继续：候选包未部署、未合并 PR、未改生产凭据。
