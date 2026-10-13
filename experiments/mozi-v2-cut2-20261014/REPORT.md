# 第2刀前置施工

PASS：受限在线代理库 proxy.py 已实现，未接入生产或修改离线 entrypoint。
固定仓库/精确Issue number+id/issuer数字ID/login/来源URL/title/open/非PR/body原字节摘要；固定RESULT及摘要、独立Bot数字ID/login/type；单次POST后只GET返回的同一comment ID并校验完整绑定。拒绝Issue20与TASK-REAL-042，无列表/扫描接口、无重试/重定向/环境代理。TLS系统证书验证，20秒限时、响应1MiB、请求4096字节上限。SQLite FULL synchronous唯一全局槽POST_ATTEMPT提交先于POST，成功后VERIFIED；未知结果保留尝试与已知ID，重启或换policy均拒绝再发。

PASS：原20+13组，新增14组，共47组。green-all.log为修复后完整验收；initial-failure.log保留首次测试环境错误（系统Python不完整及本地假HTTP不需真实TLS上下文）。测试只替换连接到127.0.0.1假API及TLS上下文，真实Wire解析/大小/HTTP状态/代理检查代码执行。测试身份与token均为synthetic。超时与数据库只读为故障注入；disconnect为真实本地HTTP断连。没有真实GitHub代理网络调用。
PASS：三个真实guard-removal mutation均以AssertionError红测失败，日志分别保留；不是用运行环境错误冒充红测。

UNKNOWN：真实在线闭环、签发密钥控制关系、专用RESULT Bot及权限/凭据引用、真实模拟Issue ID/number、Linux隔离与磁盘掉电持久性。当前库仅接受可信监督器传入的policy，不验证KR签名；无CLI/凭据发现/Daemon集成/部署入口，不能当作已上线Daemon。部署前必须把policy/代码/ledger置于分别授权、只读及独占边界中；同机任意代码或ledger删除不属于本库防护边界。不可把synthetic值带入真实票。

只读GitHub：main为875d6fa4238c58388320d18edc1b1e67da19ca60；owner kongsonren数字ID259898029，权限admin。精确模拟任务标题搜索无结果，仅支持“未找到”，不证明全库不存在。未猜测bot身份或使用admin连接为运行凭据。

Issue20本轮完全未访问，历史open/HOLD/execution_authorized=false不冒充新鲜读回。未访问云主机、生产Daemon或任何真实凭据，未真实Issue POST/创建Issue，未部署/重启/自动pull。GitHub写入范围仅授权的隔离开发分支代码交付。
