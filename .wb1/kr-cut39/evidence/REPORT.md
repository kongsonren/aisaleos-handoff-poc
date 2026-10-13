# KR第39刀｜2026-10-14 北京时间

**总体 UNKNOWN。隔离调度候选及两拍云验收 PASS；独立Daemon迁移/持续恢复 BLOCKED；会话结束后的主动唤醒 UNKNOWN，当前验收 BLOCKED。**

Issue：https://github.com/kongsonren/aisaleos-handoff-poc/issues/19

## 已完成的真实云执行

- 隔离分支 `kr-cut39-isolated-20261014`；创建基点 `d865eaa0a5f3162443c72ca7932f68a7874a29ac`。
- 核心代码补丁 commit `345001ac2caa1372eaa4d57e19e29b3c4cf85bbd`。不是生产部署SHA。
- 首拍 Run **38444409084**，Job **115458934404**，seq241，head `76253379d9569ce190ac9e3246dd24dbf1905651`。
- 首拍云runner自动创建第二拍 Run **38444440431**，Job **115459048778**，seq242，head `045967553eab2d370a40e4ec54e0ed61fa812af9`。第二拍无KR/本机dispatch。
- 首拍创建2026-10-14 02:09:05+08:00，第二拍02:09:19；两拍均实际运行调度回归，日志有 `REAL_EXECUTOR_COMPLETE`。首拍日志还包含下一拍独立 `NEXT_RUN_ACK`。
- GitHub隔离账本 `.wb1/kr-cut39/schedule.json` 经独立API回读：241、242均 `attempts=1/status=ACK`，分别绑定上述Run。账本跨runner保存，未依赖runner本地磁盘。
- 原始日志：`job-115458934404.log`、`job-115459048778.log`；完整元数据 `runs.json`、`jobs-*.json`；独立账本快照 `durable-ledger.json`。
- 云执行器是GitHub Actions中的**隔离调度回归执行器**，不是原独立常驻Daemon，也不是NAS/Obsidian业务执行器；没有重复简单文件往返回执实验。

## MAX_BEATS根因与候选修复

第38刀原函数累计round_seq>=240立即return0、不dispatch；且dispatch失败也return0。本轮再复现，见 `router-regression.log` 后段。生产故障仍未部署修复，不宣称已治好生产。

`durable_schedule.py` 把累计seq仅作为下一拍幂等键的一部分，不作总寿命预算。调度意图先持久化，POST前CAS认领；HTTP204只记SENT，返回4表示未确认；接收runner ACK后才能确认启动。独立的隔离验收预算限定两次实际云执行，第二拍明确输出 `ISOLATED_ACCEPTANCE_BUDGET_COMPLETE`，没有无限递归。

- 429为明确拒绝，最多3次，指数退避，到限BLOCKED。
- 400/401/403/404/422为BLOCKED；超时、连接异常、5xx保留UNKNOWN，禁止盲目重发。
- CAS竞争最多3次；持久INFLIGHT在重启后等待对账，不能以重新POST补偿不确定性。
- 已ACK重复消费不dispatch；同一key不同run_id拒绝为DUPLICATE_EXECUTION。
- `loop-fix.patch`/`loop_candidate.py` 给出原wait_and_schedule函数的隔离迁移适配。`patched-loop.log`实际抽取并执行补丁后的函数，seq240/241/1000各一次发送、重复调用零追加发送，未确认exit4；main分支guard exit3。
- **核心模块云端实测；原loop适配函数仅本地隔离实测。不能把适配补丁的后续保存SHA冒充已运行云SHA。**

测试范围：本地与云测试均覆盖239/240/241/1000边界、子进程退出后新进程恢复意图、429三次上限、响应丢失五次扫描只发一次、认领后崩溃、旧版本CAS拒绝和生产分支拒绝。429/丢响应/CAS竞争为故障注入，**不是GitHub真实返回429或真实云机断电**。实际GitHub HTTP204、两次云运行、账本跨runner读取是线上隔离实测。

### 持久调度的剩余限制

账本持久化已实测，但**独立周期恢复扫描器未部署**。如果进程在持久化PENDING后、POST前死亡，需要独立pump恢复；若认领后死亡且没有ACK，需要对账，当前实现宁可UNKNOWN不重发。因此持久账本与两拍续跑PASS不等于长期调度存活PASS。

原独立Daemon在 `/opt/kr-isolated-daemon-20261013/daemon.py`，既有SSH不可用，本轮没有再试图扩权限/信任。未在该宿主安装调度修复或恢复扫描器。用户限定不改生产、不扩权，当前缺可用独立Daemon部署/核验通道，判BLOCKED。

## SUBTYPE_NOT_MAPPED核验

第38刀两处修复重新执行原main/dispatch函数回归：普通CLOSEOUT_ARCHIVE报告IGNORE；身份标签SUBTYPE保留、进入既有QUEUE_IDENTITY观测桩；KR_GATE STOP，未知subtype HELD。PASS仅限隔离路由，无真实队列/NAS执行。

生产入口本轮结束SHA256仍为 `5cc608c7131e7891afa9ae36ac3fce13546ee44bffb2211917ba72fb19c1b9e3`；修复候选SHA256 `6a982e3f76ae755320c5d0645a9be2fb4ff457c22c651f43b9ee7b99fa0a8e6b`。见 `router-regression.log`、`production-integrity.json`。第38刀修复未部署。

## 六段主链裁决

| 环节 | 判定 | 证据与边界 |
|---|---|---|
| 嗨姐当前会话→GitHub | PASS | 隔离分支、Issue19、真实workflow_dispatch；非KR搬运 |
| GitHub→独立云端Daemon | UNKNOWN / 部署核验BLOCKED | 沿用第38刀Issue18；本轮没有重做简单回执，未独立回读Daemon代码/账本 |
| Daemon→可用执行器 | UNKNOWN | 原Daemon宿主核验未通；本轮Actions隔离执行器PASS不能替代此段 |
| 执行器→RESULT | PASS（隔离Actions范围） | 两份原始日志实际测试完成；不升级为原Daemon业务链PASS |
| RESULT→嗨姐当前会话读取 | PASS（主动GET） | 本轮独立读取Run/Job日志、账本；这属于会话内读取 |
| KR不发消息、会话结束后主动唤醒嗨姐 | UNKNOWN / 验收BLOCKED | 无结束会话后自动进入处理流程的实证，无对应唤醒Run |

仓库 `/hooks` 返回200，列表为空，见 `hook-observability.json`；本地既有Daemon参考实现终点为GitHub评论与本地receipt，没有可见嗨姐会话callback。当前工作流也没有会话唤醒调用。**这些证据不排除仓库外部其他订阅存在。**本轮不创建提醒冒充原链路，不通过send_message_to_thread人工转送RESULT，不把GET或Actions自续跑叫作嗨姐主动唤醒。

## 隔离与交付

仅修改隔离分支的工作流版本（无cron、独立job、5分钟timeout、明确分支guard），复用原有contents/actions write权限，未增加权限、未改生产工作流/Daemon/SSH信任。`production-integrity.json`确认main的loop.py及nezha-auto.yml blob前后相同，生产本机入口摘要相同。main可能被原有后台活动推进，不能把全仓head变化直接归因本次。

所有本轮真实日志与候选补丁在本目录；`SHA256SUMS.json`提供交付文件摘要。最终隔离证据提交另见 `delivery-commit.json`；实际云验收SHA以上述两次Run为准。未等待24小时压测。
