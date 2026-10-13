# KR_GATE CUT1→CUT2 v1（未授权执行）

绑定本目录SHA256SUMS.json及隔离分支交付commit；精确commit由本地DELIVERY.md记录。已有bf7eec65af9a65da065a781a5ed91b8f8038f61c只作为固定库来源，不能替代本入口manifest。本文不提供云安装/启动脚本；当前在线启动判定UNKNOWN→DENY。

1. 已完成：第1刀本地离线入口、固定MOCK单Issue、原20+新增13回归、身份只读解析与隔离分支提交。无需再次审批该已完成工作。
2. 下一阶段首先完成只读证据：issuer kongsonren/259898029与独立签发密钥控制关系；RESULT专用bot精确login/id/仓库权限；现有模拟Issue exact title=[MOZI-V2-SIM] SIM-MOZI-V2-20261014-01、非20非PR、真实id/number；缺失保留UNKNOWN。不得将MOCK 123/9001/999复制进在线票。
3. 如果确无模拟Issue，另行明确批准“仅创建一次上述标题Issue”，取得真实id/number后封版；POST响应未知禁止重试。本票未授权该动作。
4. 实现独立在线受限代理，Daemon不持GitHub token；只GET封版Issue、只一次POST该Issue comments及GET本次返回comment id，禁止列表/其他Issue/重定向/环境代理；请求体≤4096字节、响应≤1MiB、超时20秒、持久POST_ATTEMPT，超时HOLD。代理、启动器、unit和root树必须另行逐字节审核和manifest锁定，不能把本MOCK入口改几个ID就上线。
5. 秘密仅批准安全引用/注入/撤销入口，禁止在证据中记录内容。令牌单仓库Metadata read+Issues write、≤24h；当前admin连接不能直接作为Daemon凭据。可信签发关系、密钥保管与撤销实证UNKNOWN时禁止在线运行。
6. Linux施工票必须封版：UID/GID62042无冲突/附加组、路径 /opt/mozi-v2-isolated/releases/<封版SHA>/ 与 /var/lib/mozi-v2-isolated/data/{state,log,evidence}；1GiB专用镜像、代码≤256MiB、日志≤64MiB、根余量≥20GiB/inode≥500000；MemoryMax201326592、CPU20%、Tasks32、no swap、只读root树、A无网络。原设计列出的ACL/cgroup/mount/root树依赖及OOB/生产完整基线全部需新鲜实证；任何UNKNOWN停止，不临时放宽。
7. Linux只在批准封版字节后进行A离线安装/故障验收：新候选unit，Restart=no，不enable，≤900秒；专用故障镜像内ENOSPC、kill/restart去重、独立读取实际文件字节与ledger；不改旧服务、不自动git pull/重启，不改变全机防火墙。主机与服务隔离PASS必须来自真实Linux证据。
8. B另行精确审批：真实仓库/Issue及issuer/result数字ID、完整manifest、绝对UTC起止≤15min、时钟偏差≤5s、批准单次模拟RESULT内容/字节摘要、proxy权限及独立GET回读。启动前所有关键项PASS；凭据/授权/时间窗缺失时DENY。批准不继承至下一轮。
9. 回滚仅停候选并核对该unit cgroup、撤销专用秘密、保留ledger/日志；不清ledger、不修复/重启生产。任何生产基线差异、审计失败、路径/身份不符、未知POST即HOLD并停止候选。

永久排除：main、生产Daemon/云服务、Issue20任何写入、TASK-REAL-042、Actions替代验收、自动pull/自重启、未批准真实POST/新Issue。当前请求不包含CUT2云施工或B在线授权。
