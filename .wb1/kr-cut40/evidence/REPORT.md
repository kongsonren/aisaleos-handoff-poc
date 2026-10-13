# KR第40刀｜2026-10-14 北京时间

**完整六段链 UNKNOWN；受控SSH/宿主回读 BLOCKED；恢复扫描器部署就绪 FAIL。** 本轮完成部署前审查、隔离缺陷复现及只读预检，未部署生产或独立Daemon，未新发简单回执/边界测试任务。

## 受控SSH优先核查

复用既有 `root@8.141.104.58`、`id_ed25519_mozi_1wb`，保持 BatchMode=yes、StrictHostKeyChecking=yes、ConnectTimeout=10。原始 `ssh-probe.log` 显示密钥文件不可访问及端口Permission denied，退出255，见 `ssh-probe.json`。未建立连接，未到宿主指纹或密钥认证阶段；不能据此判密钥失效、宿主死亡或指纹不符。未读取/复制私钥、未修改known_hosts、未跳过认证、未请求扩权。

远端daemon.py摘要、服务PID/UID、账本及Issue18文件独立回读仍UNKNOWN。准备了只读 `host-readback.sh`，**没有运行**，不读取EnvironmentFile或进程环境。

## 第39刀证据独立复核 PASS（历史范围）

仓库 kongsonren/aisaleos-handoff-poc，Issue #19仍open、评论为空，见 `issue19.json` / `issue19-comments.json`。
核心候选commit **345001ac2caa1372eaa4d57e19e29b3c4cf85bbd** 已通过连接器重新取得提交和固定版本模块：`candidate-commit.json` / `pinned-module.json`。原交付SHA **1c7a64ba872e2d2c690c0a2d817c9c486495a55e** 来自Issue19正文。

- Run **38444409084** / Job **115458934404**，实际执行head **76253379d9569ce190ac9e3246dd24dbf1905651**。
- Run **38444440431** / Job **115459048778**，实际执行head **045967553eab2d370a40e4ec54e0ed61fa812af9**。
- 两份日志本轮重新下载，含真实执行完成记录，首拍包含下一拍ACK；见 `job-*.json`、`jobs-*.json`，不是只看绿色结论。
- 账本重新回读blob **8df48025714cbcf7c2678a67dfb83e433f495525**，241/242均attempts=1、ACK并绑定上述Run；`ledger.json` / `ledger-content.json`。这不是第40刀新Run，也不是常驻Daemon部署证据。

## 部署前新发现：FAIL，隔离复现已通过

`review_tests.py`执行第39刀真实函数，只替换网络/执行边界为观测桩，不导入生产入口，不读取凭据。`review-tests.log`记录原始结果；复现测试本身PASS，所发现部署条件FAIL：

1. `cloud_accept.run`只接受seq241/242；第243拍在ACK前断言失败。扫描器不能直接把这个两拍验收执行器变成长期执行器。
2. loop适配/账本接受 `kr-cut39-isolated-*` 前缀，但 `cloud_accept.dispatch` 固定发送到 `kr-cut39-isolated-20261014`。另一合法前缀分支的任务会被发往不同分支；复现requested与actual不同。现有两拍固定分支验收不受此发现追溯否定。
3. `pump`不逐条验证持久row的branch/workflow/key；构造main行的隔离观测桩获得一次dispatch调用。**没有向main发实际网络请求**。固定dispatch目前仍指向隔离分支；此问题是未来扫描器信任边界缺口，不能宣称本轮实际越权。
4. 接收端先ACK、再执行；注入执行失败后账本仍ACK。ACK证明启动，不能替代完成RESULT。历史两拍另有完成日志，所以仍保留原范围PASS。

原GitHubStore构造签名已从候选固定SHA取得并AST检查，确有branch参数；没有把测试桩掩盖的问题臆测为构造错误。

第38刀路由两处差异审查：普通报告门判断取元组[0]；身份分支保留SUBTYPE。未新增关键词执行路由。本轮未重跑旧路由回归，沿用第39刀已核实结果；不冒称新的业务执行PASS。本机入口只读SHA256仍 **5cc608c7131e7891afa9ae36ac3fce13546ee44bffb2211917ba72fb19c1b9e3**，见完整性文件。

## 已施工：只读恢复预检器 PASS（本地隔离）

`recovery_preflight.py`仅读取显式输入账本，使用固定隔离分支/工作流，检查每行身份、状态、attempt预算及due；UNKNOWN/INFLIGHT/SENT只计划对账，绝不盲重发；ACK要求单独核验执行结果；seq243在当前执行器下BLOCKED。它没有网络、dispatch或写账本能力，**不是已部署扫描器或修好的调度模块**。

12项定向检查PASS，日志 `preflight-tests.log`。真实账本快照的只读计划 `recovery-plan.json`：两行均VERIFY_EXECUTION_SEPARATELY，writes=0、dispatches=0、deployment=BLOCKED。计划使用固定now=1791917000进行可复现快照分析，不冒充远端扫描时钟。

部署前必须：恢复既有受控SSH并独立验证宿主/Daemon版本；固定分支一致性、在每条记录和POST边界校验范围；换用有任务幂等/预算和真实完成结果的执行器；独立扫描进程在退出首发会话后仍运行并有重启恢复证据；已有凭据确有隔离账本和Actions所需权限（不能从连接器权限推断DynamicUser权限，缺失即BLOCKED）；保持现有服务隔离和资源限额；模糊请求必须可按任务关联Run对账，不可直接重发。未知是否启动与明确失败需分开处置。以上未通过，不安装扫描器。

## 主动唤醒核查

原嗨口11号：UNKNOWN / 当前验收BLOCKED。没有实际订阅ID、callback验证或事件触发处理Run。当前会话读取日志、现有Actions自续链、GitHub评论均不算主动唤醒。

本轮官方文档确认存在 **MCP Events → 已订阅Work Cloud聊天** 的替代途径；实际查找的GitHub插件已安装，但工具目录和插件检索不提供事件订阅证据，不能断言平台不支持，也不能宣称当前原会话支持。详见 `WAKEUP-ACCEPTANCE.md`，列出关闭会话、无KR新消息、真实事件投递及嗨姐事件处理的验收要求。方案未部署；需要新权限或生产变更时仍须KR明确批准。

官方来源：https://developers.openai.com/plugins/build/mcp-events 。2xx只证明事件接收，异步处理必须另证；OpenAI API webhooks也不等于唤醒原ChatGPT聊天：https://developers.openai.com/api/docs/guides/webhooks 。本轮实际检索并打开两页。

## 六段裁决

| 段 | 第40刀裁决 |
|---|---|
| 嗨姐→GitHub | PASS：重新读取Issue19、固定commit、两拍Jobs/日志及账本；隔离交付另记录 |
| GitHub→独立云端Daemon | UNKNOWN，宿主身份/当前版本回读BLOCKED；不重复简单Issue往返 |
| Daemon→真实可用执行器 | UNKNOWN，原Daemon/NAS业务能力未独立核验；恢复部署就绪FAIL |
| 执行器→RESULT | 保留第39刀隔离Actions完成日志PASS；不升级为原Daemon业务链PASS |
| RESULT→当前嗨姐读取 | PASS，但属于主动GET |
| 关窗后无KR消息主动触发 | UNKNOWN / 验收BLOCKED；MCP Events替代方案待部署验收 |

本轮本地Run ID **CUT40-REVIEW-20261014-01**；无新增云执行Run。未修改sources、生产入口、main、生产工作流、服务、SSH信任或权限。未等待24小时、未要求KR转交。交付摘要见 `SHA256SUMS.json`；若隔离证据发布成功，提交SHA与回读记录另见 `delivery-commit.json` / `delivery-readback.json`，它们不是部署SHA。
