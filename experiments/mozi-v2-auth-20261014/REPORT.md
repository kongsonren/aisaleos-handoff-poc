# 墨子 Daemon v2 隔离开发验收

日期：2026-10-14。结论：LOCAL_SIMULATION_PASS；云端部署及真实授权 NOT_RUN，生产验收 UNKNOWN。

基线：kongsonren/aisaleos-handoff-poc main d30a9a1b5639d707a4cd732a8c8238b6a7f2eae2。独立分支 kr/mozi-v2-auth-isolated-20261014。新增候选位于 experiments/mozi-v2-auth-20261014，不替换现有入口或工作流。

源码依据：本地 cloud-daemon-poc-20261013/daemon_v2.py，保留逐字副本 legacy-daemon-reference.py；读取 kr-cut43-20261014/REPORT.md 及历史PoC报告。仓库基线递归树无 daemon/AGENTS/kr-cut42/kr-cut43 路径。参考源码足以开发独立候选，不能证明云端实际代码版本。历史聊天返回的部分消息只有内容引用标记，未将其视为已读取的报告内容。

协议：新版本 mozi-v2-auth；精确字段集合、拒绝重复JSON键。HMAC-SHA256绑定除auth_digest外完整规范JSON，并加协议域分隔；绑定repository、GitHub数值issue ID/number、可信数值author ID、key ID、task/run/nonce、授权与状态、作用域、执行动作、固定文件名、内容、时间窗、执行器源码SHA256。可信主体由注入的独立key映射与GitHub API元数据确定，不信任payload自报主体。只允许 SIM-*、simulation-only、write_read_hash、test.txt。#20在扫描、消费、API写入处均拒绝；TASK-REAL-042和全部旧协议均不能进入执行器。

时间：issued_at <= now < expires_at，最大300秒，无未来宽限；依赖部署宿主可信时钟。SQLite WAL + synchronous FULL，在文件副作用前原子持久CLAIMED，task/run/nonce/issue唯一。已领取但未完成一律HOLD，不自动重跑；DONE可重发本地缓存给发布器，不重新写文件。POST_ATTEMPT在请求前持久提交；超时或崩溃歧义一律HOLD，不盲目重复评论。VERIFIED只在GET回读一致后产生。当前策略保证最多一次执行尝试，不宣称崩溃后必然完成或端到端exactly-once。

真实测试：在当前Work本地Python运行11组unittest，全部通过；每字段篡改使用subTest逐一验证。覆盖false/缺失/字符串true/数值1/伪造true错误签名、可信主体与Issue绑定、过期/未来/超长窗口、旧协议/受保护任务、合法文件写入与独立字节及SHA256检查、重开连接及新进程重复任务、4线程竞争领单、CLAIMED崩溃遗留、RESULT模拟API回读、POST超时不重试、扫描不碰旧标题与#20。test.log为未经摘要的最终输出；test-first-failed.log保留首次发现SQL占位符错误的失败输出。最终测试未调用真实GitHub写入、未投递任务Issue、未接触云端。

限制：API传输类已提供，轮询scan通过注入API调用；非部署候选故意无自动网络启动入口。当前只在Windows做本地文件/SQLite及模拟API测试，Linux文件系统断电持久性、真实网络、云端凭据、服务常驻与生产端到端均未验收。结果中的本地PASS仅是模拟文件操作成功，不是云端任务完成，也不满足#20核销条件。状态根目录必须由可信部署建立，私有且祖先路径不可由其他用户写入；不能与旧账本共享，不能将恶意本地文件系统攻击纳入当前保证。签名方与Daemon共用HMAC秘密，Daemon失陷可伪造签名，必须独立签名服务/权限隔离后再评价生产安全。

## 部署前验收方案（须另行KR_GATE，当前未执行）

1. 固定审阅分支commit和源码SHA256，独立红队复核；绝不自动git pull或自更新。只部署经批准的固定字节到独立目录、独立非特权身份，不覆盖旧服务。
2. 由既有可信云管理通道只读采集实际旧代码SHA256、服务配置与PID、账本/pending/receipt/post-attempt；保持#20 open/HOLD/false。若通道不可用，云端阶段STOP，不影响已完成的本地测试结论。
3. 专用私有状态目录及不可写祖先、最小GitHub仓库权限、独立模拟签名密钥、可信数值Bot主体、准确时钟；不得复用生产密钥或复制SSH私钥。审查旧账本隔离/迁移方案，默认不导入授权。
4. 在Linux隔离环境按固定commit重跑全部测试，增加进程kill、主机重启、断电/磁盘满、目录与symlink攻击、并发多进程和网络超时测试。CLAIMED/POST_ATTEMPT歧义必须HOLD，由独立审计对账，不删除账本重新执行。
5. 仅在获准独立测试Issue上，以专用短效签名跑拒绝矩阵及合法模拟任务；确认常驻Daemon直接GitHub API轮询→受限文件Executor→RESULT POST/GET闭环，无Work/Windows/SSH依赖。不得创建旧Daemon可消费的标题或旧协议任务。
6. 用独立可信宿主通道读取原始文件字节，关联task/run/issue/payload/code摘要并重算文件SHA256；验证RESULT作者主体、重启重复任务无新增文件副作用或评论。记录真实宿主/PID/启动时间/uptime，当前候选未伪造这些生产证据。
7. 全部验收后另行提交KR_GATE决定是否启用生产适配；本候选只支持simulation-only，不允许靠更改标题/置true直接运行真实任务。#20和TASK-REAL-042仍须独立真实授权、独立协议评审与核销流程。

没有修改main、生产Daemon、服务、工作流、Issue #20或权限；没有SSH、自更新、服务重启或TASK-REAL-042执行。
