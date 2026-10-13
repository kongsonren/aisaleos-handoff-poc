# 墨子 v2 第1刀：本地隔离入口施工交付

2026-10-14，北京时间。KR 本次“开”和“继续1”授权本地隔离开发、回归、GitHub 隔离分支提交；不扩展为云主机施工或真实 Issue POST 授权。

## 实际结果

- PASS：新增 `entrypoint.py`，一次性离线启动入口及固定单 Issue 包装器。默认无参数、live/token/Issue覆盖参数全部拒绝；无 HTTP、凭据装载、publish、scan、循环、pull、自更新、自重启入口。
- PASS：固定父版本 bf7eec65af9a65da065a781a5ed91b8f8038f61c；daemon.py 原字节不改，SHA256 0afef212dc11f0cd6a12f4281891883694047371c850a8b80819cb131d195971。先验摘要再编译同一份字节，构造库时再次校验摘要。
- PASS：固定仓库/API来源、模拟标题/task、MOCK id=9001/number=999/issuer=123；这些是离线测试专用值，绝不是实证身份。真实模式不可通过配置启用。固定 write_read_hash/test.txt、simulation-only、签名及TTL策略沿用已封版库。
- PASS：CLI 可写状态仅入口同目录 `offline-workspaces/<独立目录>/mozi-v2-cut1-state`。库测试接口允许可信测试程序传入临时目录。路径祖先拒绝 symlink/junction、普通文件硬链接、特殊文件；SQLite已有状态必须完整且审计摘要吻合；缺审计表不自动修复。
- PASS：原20组全量回归；新增13组全绿。新增测试涵盖CLI实际启动/二次调用去重、默认拒绝、唯一Issue和来源、异常/伪造身份、授权拒绝、摘要篡改、路径/硬链接、重放冲突、审计缺表/摘要篡改、禁止网络与扫描。原并发、跨进程去重、POST超时不重试组全部重跑。
- PASS：3个实际移除守卫的 mutation 红测均 exit=1，分别检测身份绕过、源码摘要绕过、审计摘要绕过。red-entry.log 是最初入口缺失的开发红测；red-audit.log 是发现审计表重建问题时的实际FAIL；最终验收以 validation.json 和 green-original20.log/green-entry.log 为准。

## 只读身份及边界核验

原始连接器响应保存在 identity-verification.json。GitHub账户 kongsonren 的数字ID=259898029，仓库owner同ID，权限admin；现有连接为宽权限，不能作为未来专用最小权限执行凭据。账户解析PASS不等于HMAC密钥归属/可信签发关系已证明；该关系UNKNOWN，未读/复制任何密钥。HMAC为共享秘密认证，不是不可否认数字签名；父commit GitHub verification=unsigned。

专用RESULT测试bot登录名/数字ID/仓库权限/秘密引用仍UNKNOWN。模拟Issue精确关键词搜索返回空，不能由搜索空结果断言绝对不存在；真实Issue id/number UNKNOWN，未新建。Issue #20新鲜读取为open、BLOCKED_HOST_ACCESS（HOLD）、execution_authorized=false；未改动、未执行TASK-REAL-042。

## 可复验

在交付目录使用Python3.12+运行 `python -B validate.py`。它重新生成三份真实红测日志和20+13绿测日志，保留原始stdout/stderr字节及退出码。日志包含MOCK结果，不能提升成在线闭环PASS。独立Git blob与本地SHA256回读校验另见本地 delivery-verification.json。

GitHub仅新增 experiments/mozi-v2-cut1-20261014 子树，父commit不变；新隔离分支 kr/mozi-v2-cut1-20261014，不提交main，不发PR、不触发Actions、不改workflow。四个继承workflow只声明schedule/workflow_dispatch，无push/create触发；已先只读核查。Github Git对象/分支提交是本次明确授权的交付写入；没有真实Issue POST、云主机写入或服务变更。

## 限制与下一阶段

此入口是已实测的离线Daemon库启动器，在线Daemon仍拒绝启动。不能把它当Linux安装器、在线受限代理或systemd沙箱证明。专用UID/root树、挂载/cgroup/配额/ACL、时钟、独立密钥管理、真实bot/Issue、在线代理与POST回读仍须下一阶段。代码及scratch要求可信、独占、不可被同UID对手并发替换；Python路径检查不宣称能抵御恶意并发文件系统替换。审计无密钥摘要不证明恶意删除/重算后的真实性，需受保护导出。Windows不宣称Linux目录fsync/掉电/ENOSPC/namespace已经验证。

下一票见KR_GATE.md。第1刀本地实现/测试PASS；在线身份闭环UNKNOWN；真实启动未执行且保持拒绝。
