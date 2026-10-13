# KR第41刀｜2026-10-14 北京时间

三项复现缺陷已在隔离分支修复并真实云验收。完整六段链仍 UNKNOWN；SSH/独立Daemon回读和无消息关窗事件验收 BLOCKED。没有生产部署。

## 范围与代码

仓库 kongsonren/aisaleos-handoff-poc；关联 Issue #19；基点为第40刀报告提交 `0ed23eee0ea84a3b8b2af4738ee201165045e80d`。
新分支 `kr-cut41-isolated-20261014`，没有更新main。
首版补丁 `a1868a25f9574fe66b4c7c67e7092b1f399eaaaa`；最终补丁 `f54edaa0d41833940361f273cee4fbc4c4315c47`。
代码继续位于 `.wb1/kr-cut39/`，新账本独立位于 `.wb1/kr-cut41/schedule.json`。隔离工作流替换仅存在于新分支，沿用原工作流 contents/actions write 权限，未改仓库或生产权限。

1. seq不再限定241/242，接受合法正整数；任务身份由分支+seq确定。此次云验收有限两拍243→244，不递归长期运行。
2. requested/actual采用同一经验证row的branch/workflow；限定精确隔离分支，不再接受任意前缀。POST适配器独立复验。
3. load、CAS、每次状态迁移、claim后回读与POST边界均校验每条row。其他row被污染也会在任何写入或dispatch前失败；校验branch/workflow/字典key/row.key/seq/状态/attempts/due及完成结果关联。
4. ACK仅记接收与run_id；执行返回0后才持久写EXECUTION_COMPLETE，异常/非0写EXECUTION_FAILED。未完成ACK/失败任务重放非0；已完成同Run重放跳过副作用，不同Run拒绝。UNKNOWN/SENT/INFLIGHT/ACK不盲重发，仅允许可信调用方提供已关联结果进行对账。
5. CAS重试最多3次，429有限退避最多3次，超时/5xx置UNKNOWN，明确拒绝置BLOCKED。入口在写账本前核查GITHUB_REF；后续代码push只跑回归，不重新初始化已有任务。

## 真实执行与结果

| 项目 | 真实记录 | 裁决 |
|---|---|---|
| seq243 | Run 38450675509 / Job 115480439945 / head a1868a25f9574fe66b4c7c67e7092b1f399eaaaa | PASS |
| 自动dispatch seq244 | 首Run发出POST，HTTP204只记SENT；第二Run actor为github-actions[bot] | PASS |
| seq244 | Run 38450710846 / Job 115480595991 / head cf5bb07028cfb3f3f6dc1e81ee566d947264e50d | PASS |
| 分支一致 | 两个Run head_branch均kr-cut41-isolated-20261014，工作流nezha-auto.yml | PASS |
| 持久RESULT | 独立回读blob 4c35f61d03fffd4b0fa87214c8de6e139623d12f，两行均EXECUTION_COMPLETE并绑定各自Run/SHA/key | PASS |
| 本地及前两云runner | 各11项定向测试通过 | PASS |
| 最终补丁云回归 | Run 38451084073，head f54edaa0d41833940361f273cee4fbc4c4315c47；只跑回归，不重新初始化或dispatch已有任务 | PASS |

首拍02:55:31 ACK，02:55:33 EXECUTION_COMPLETE；第二拍02:55:53 ACK，02:55:55 EXECUTION_COMPLETE（北京时间）。原始日志 `job-115480439945.log` / `job-115480595991.log`；Run元数据 `runs.json`，账本 `ledger.json`及`ledger-readback.json`。日志包含测试用run="run"和sha="sha"，它们是故障注入/回归夹具，绝不算真实云任务结果；`verify_evidence.py`只接受两个实际数字Run ID对应事件。

## 安全失败、幂等、重启验证的边界

11项测试覆盖seq243及10000、实际适配器payload/POST范围拒绝、其他行污染、ACK不能完成、同Run重放与不同Run冲突、错误结果关联、非0/异常失败、204/500/不确定响应重启不重发、429预算/CAS耗尽、GitHubLedger读写校验。
重启测试启动独立子进程，持久写ACK后os._exit(23)，新子进程回读磁盘账本，确认不重发，随后注入已验证完成结果进行关联恢复。它证明跨进程状态恢复和安全停留，**不证明任意业务副作用可在崩溃窗口恰好执行一次**，不证明常驻Daemon已运行。没有业务结果时保持ACK/UNKNOWN，需要可信执行证据；不会推断完成。
云端两拍证明GitHub持久账本跨runner可读写。原NAS/Obsidian业务执行器、长期无人值守扫描、独立Daemon服务重启与宿主权限仍未验收。

## SSH

仅复用root@8.141.104.58及既有id_ed25519_mozi_1wb，BatchMode=yes、StrictHostKeyChecking=yes、ConnectTimeout=10。原始 `ssh-probe.log`仍显示密钥不可访问和端口Permission denied，未进入宿主指纹核验。BLOCKED；未读取/复制私钥、修改known_hosts、绕过密钥或指纹、请求扩权。

## MCP Events → Work Cloud

官方文档本轮已搜索并打开：https://developers.openai.com/plugins/build/mcp-events 。支持Work web或桌面Cloud聊天，要求MCP 2.0事件发现、events/list/subscribe/unsubscribe、持久订阅、callback验证及签名webhook投递；2xx只确认接收，处理异步发生。
本轮插件检索确认GitHub已安装，当前可调用工具没有事件订阅方法。未取得该RESULT源的subscription_id、已验证callback、订阅的Work Cloud聊天及事件触发处理Run。**当前隔离验收BLOCKED；关窗无KR消息主动处理RESULT仍UNKNOWN。** 不能由工具目录反推平台完全不支持，也不能由GitHub hooks/GET证明订阅不存在。未新建聊天、部署事件服务、注册webhook或扩权；未用提醒、自动化轮询、GET、GitHub Actions自续跑冒充聊天唤醒。
解阻条件：可调用的事件源与已授权Work Cloud订阅，取得实际subscription/callback验证证据后，关闭窗口且不发KR消息，触发匹配RESULT并核对事件ID→处理Run→任务key。缺少任何一项均不记PASS。生产变更仍需KR_GATE。

## 逐关结论

| 关卡 | 结论 |
|---|---|
| 嗨姐→GitHub隔离代码交付 | PASS，真实diff/commit及云执行 |
| GitHub→独立Daemon | UNKNOWN，SSH回读BLOCKED |
| Daemon→可用业务执行器 | UNKNOWN；隔离Actions回归执行器PASS |
| 执行器→持久RESULT | PASS，仅此次隔离243/244范围 |
| RESULT→嗨姐读取 | PASS，独立GET回读，非唤醒 |
| 关窗无KR消息主动处理 | UNKNOWN / 验收BLOCKED |

本轮未改sources、main、生产Daemon、生产权限或部署；不重复240边界和简单回执实验。完整链不升级为PASS。最终证据提交与回读记录另存delivery.json。
