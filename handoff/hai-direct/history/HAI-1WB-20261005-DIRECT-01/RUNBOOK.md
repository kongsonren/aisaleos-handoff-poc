# 嗨姐→1WB直发通道：恢复入口与运维
Run: HAI-1WB-20261005-DIRECT-01

## 本轮裁决
MACHINE_SIDE_BUS=PASS（本轮自然消费实测）
HAI_DIRECT_LOOP=PASS（当前Codex Work席位，两轮实测）
PERSISTENT_CONSUMER_RESTART_RECOVERY=UNKNOWN
OVERALL_REQUEST=INCOMPLETE（持久启动/重启恢复未完成验收）
RESULT_1/2/3=NOT_YET_PASS；RESULT_4=STANDBY。
KR_COPY_PASTE=0；KR_WAKEUP=0；KR_RELAY=0。

## Registry / Locator
仓库：kongsonren/aisaleos-handoff-poc（公开仓库；只保存通道技术证据，不上传业务资产或凭证）
COMMAND_BUS：GitHub Issue #6 的 [HAI→1WB][DIAG] 或 [HAI→1WB][TASK] 信封。
RESULT_BUS：同一 Issue 的 [WB1-INBOX-ACK] 与 [WB1-HAI-REAL]，按 EVENT_ID、COMMENT_ID 关联。
https://github.com/kongsonren/aisaleos-handoff-poc/issues/6
消费者：C:/Users/59605/.wb1/wb1_github_inbox_heartbeat.py
路由：C:/Users/59605/.wb1/router_rules.json
桥：C:/Users/59605/.wb1/wb1_local_exec_bridge.py
本机账本：C:/Users/59605/.wb1/github_inbox_ledger.json
B机器证据：C:/Users/59605/.wb1/exec_results/HAI-1WB-20261005-DIRECT-01-B__READBACK_HASH.json
这份文件是本轮新增的恢复索引，不声称找到了历史全局Registry。
handoff-state原始观察HEAD=e7ff0bd86acdc0e10aa35de057f4371b4d9b9813；main原始观察HEAD=0e3b7691071604eb37f64963223aad3a67e8ca1e。
证据commit=316fd7adfc0295504962fdbf0ad3afd1cafd2866。
https://github.com/kongsonren/aisaleos-handoff-poc/blob/316fd7adfc0295504962fdbf0ad3afd1cafd2866/handoff/hai-direct/history/HAI-1WB-20261005-DIRECT-01/evidence.json

## 两轮证据
A=5996129850；ACK_A=5996135948；RESULT_A=5996136459。
B=5996252453；ACK_B=5996267437；RESULT_B=5996267943。
A于14:06:56Z发布，ACK/RESULT于14:07:17Z/14:07:18Z。
嗨姐实际读取A，依据其路径和hash生成B；B于14:13:28Z发布，ACK/RESULT于14:14:16Z/14:14:17Z。
A/B及本地独立读盘SHA256一致：
9451fa84e5663378c030d0b436bc6e1cddf5a3a7ff4c67885cc756f291211100
B正文的HAI_READ_RESULT_A时间区间未经过时钟验证，不用作时间证据；先读A再发B由本聊天工具调用顺序及B对A结果的引用证明。

## 凭证与权限
GitHub连接器读写均已实测；未读取或展示密钥。
本机github_pat存在；既有消费者成功回传证明其运行身份在当时可写，不宣称永久有效或扩大权限。
Windows任务定义与进程命令行查询拒绝访问；目录读授权后仍拒绝，属宿主权限依赖。
历史任务名WB1_Issue6_5Min_Heartbeat本轮查询失败，不能据历史报告断言配置仍有效。
已发现Startup/WB1_SELF_SOLVE_DAEMON.cmd，但它启动另一个SELF_SOLVE消费者，代码默认24小时退出，不可替代本轮DIAG/TASK持久性验收。
未发现可直接调用的WorkBuddy聊天/调度管理接口；未修改WorkBuddy数据库。
墨子8771代码只提供状态面，不把它冒充指令总线。

## 最短运维
重新上钟：先从Issue #6读取本次结果及后续新回执；按EVENT_ID恢复，不让KR转发。
只读探针：使用唯一新EVENT_ID发送DIAG；收到真实RESULT后才以其TARGET发TASK/ACTION=READBACK_HASH。
ACK不等于完成；缺RESULT、hash不符、心跳过期均不判PASS。
现有桥的允许动作不等于业务自治已完成；123必须继续逐项真实验收。
未取得启动绑定证据前，不增加第二个消费者、不手动补跑冒充自主发现。
下一待办：核实当前持久启动入口、失败自动重试和重启恢复；取得真实证据后才升级对应状态。
本轮启用Codex每10分钟续查（成功状态以工具回执为准），它依赖Codex应用，不替代黑武士watchdog。

## 最短回退
本轮没有修改生产代码、路由、业务CURRENT、凭证或计划任务；无需回滚生产。
A/B均只读，保留命令与回执作为HISTORY，不删除。
若停止后续续查，在Codex自动化中暂停“嗨姐→1WB直发通道与123续航”。
新建的handoff/hai-direct/history证据只追加，不覆盖既有CURRENT。
