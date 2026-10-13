# KR_GATE CUT2→隔离验收（STOP，未批准）

本票绑定本目录SHA256SUMS.json、从69a2c3743974138e3a53fe3b60d891085daa745b派生的kr/mozi-v2-cut2-20261014交付commit（见提交后DELIVERY.md）。当前授权已完成代码开发/本地测试/只读核查/隔离分支提交。本票不激活任何真实操作。

可集中批准以下施工范围，但UNKNOWN需取得精确实证并封版，不能以笼统“开”替代数字ID、时间窗和凭据引用：

1. 专用模拟Issue：仅允许创建一次标题 `[MOZI-V2-SIM] SIM-MOZI-V2-20261014-01`，仓库kongsonren/aisaleos-handoff-poc，作者kongsonren/259898029，正文固定为 `SIM ONLY`（UTF-8，无末尾换行）。创建前精确搜索复查；如已有候选，先绑定真实id/number，不重复创建。创建响应未知即HOLD，禁止重试。当前真实number/id UNKNOWN，未创建。
2. 专用RESULT bot：先提供精确login/id/type=Bot与单仓库Metadata read+Issues write权限实证、≤24h凭据的安全引用/注入/撤销入口（只记录引用，不读取/复制内容到证据）。禁止admin连接充当运行凭据。签发密钥归kongsonren控制的独立实证、授权签名验证监督器及撤销机制须PASS；目前全部UNKNOWN。
3. Linux前置：批准只读核对后，独立UID/GID62042、无附加组；/opt/mozi-v2-isolated/releases/<封版manifest SHA>/只读，/var/lib/mozi-v2-isolated/data/{state,log,evidence}独占；1GiB专用镜像，代码≤256MiB、日志≤64MiB、根余量≥20GiB/inode≥500000；MemoryMax201326592、CPUQuota20%、TasksMax32、无swap；A无网络，broker与Daemon分离，Daemon不持token。目录/配额/unit/监督器尚未实现或核实，均UNKNOWN，不允许临场放宽。保持旧服务和全机防火墙原状。
4. A离线安装和故障验收：新候选unit，Restart=no，不enable，≤900秒；真实Linux ENOSPC/kill/restart/审计与ledger独立读取验收，保留原33+新增14回归；生产完整基线/OOB/ACL/cgroup/mount隔离验证PASS。安装/启动脚本与unit须独立逐字节审核封版后才可执行。
5. B单次在线：取得真实repo=1357322725、Issue id/number、issuer=259898029、RESULT bot id/login及签发控制关系后，生成不可改policy。固定RESULT为 `RESULT\nSIM PASS`（此处表示一个LF，无末尾换行），其UTF-8摘要由proxy.digest计算并写入最终票；精确UTC起止≤15分钟、时钟偏差≤5秒、最终policy及所有执行文件SHA清单必须在运行前另行封版。仅GET该Issue、至多一次POST其comments、GET返回同一comment ID；任一未知/超时/绑定差异即HOLD，人工独立精确ID回查，不扫描不盲重试。
6. 回滚：仅停候选unit并核对其cgroup、撤销专用凭据，保留ledger/日志。不得删除尝试记录、修复或重启生产。生产基线差异立即停止。

永久排除：main变更、Issue20任何访问/写入、现有云服务、生产Daemon、TASK-REAL-042、Actions代替Linux验收、自动git pull/自更新/自重启。当前STOP等待KR单独批准上述精确施工；UNKNOWN不得被批准措辞自动变为PASS。
