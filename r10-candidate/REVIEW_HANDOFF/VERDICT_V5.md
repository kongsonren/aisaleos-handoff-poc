# V5 — 凭据安全

- **裁决项**：凭据安全
- **令号**：KR-NEZHA-R10-CONSUMER-INTEGRATION-20261019-01
- **前腿初判**：BLOCKED
- **前腿初判说明**：候选 watcher 凭据机制偏离生产原版(移除 Add-Type CredRead，改 env_or_python_bridge)；2WB_pat_bridge.py 明文 print PAT，不得作生产通道。需 KR 就 (A)硬化桥/(B)生产回退 Add-Type 二选一裁决。前腿初判 BLOCKED。
- **后腿审查状态**：**PENDING_1WB_REVIEW**（前腿不得代填）
- **KR 终裁**：—（待裁决）

## 后腿(1WB)独立审查回填区

- [ ] 核对 SHA256（SHA256_MANIFEST.md）
- [ ] 抽查测试证据（建议 C1/C4b/C8c）
- [ ] 后腿结论：PASS / FAIL / BLOCKED / UNKNOWN = ___
- [ ] 后腿备注：___
