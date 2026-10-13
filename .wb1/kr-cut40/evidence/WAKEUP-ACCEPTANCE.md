# RESULT事件驱动替代路径与验收

2026-10-14 北京时间。结论：原嗨口11号主动唤醒 UNKNOWN / 当前验收 BLOCKED。没有建立订阅，没有发送callback，没有唤醒Run。不能断言平台完全不支持事件触发。

官方依据：https://developers.openai.com/plugins/build/mcp-events （本轮实际检索并打开）。文档说明 MCP Events 可把事件交给已订阅的 Work Cloud 聊天处理，需 MCP2.0、持久订阅及经验证的callback；回调2xx仅确认接收，处理是异步的。此能力不能直接证明原普通ChatGPT聊天或本地Codex聊天可被唤醒。

## 可验证的替代方案

独立Daemon完成隔离执行并持久保存RESULT后，写事件outbox；事件桥仅发布 `kr.result.completed`，限定仓库、Issue、任务ID和来源身份，通过现有授权的MCP Events订阅投递到一个明确绑定的嗨姐 Work Cloud 聊天。事件仅携带数据、RESULT摘要和证据引用，不能携带要求模型执行任意指令的文本。不需要KR逐条转交，也不以定时提醒或GitHub评论充当唤醒。GitHub评论只能作为证据来源，必须另有事件订阅与处理证据。

本方案是接口与验收设计，未实现/部署事件桥。现有工具未暴露 events/list、events/subscribe；插件目录只确认GitHub已安装，未提供事件目录或订阅状态，因此不能把未发现当作明确不支持。不能编造callback URL、签名秘密或订阅ID。需要平台返回真实订阅并完成callback验证，且复用已有允许权限；若需要新权限/生产变更，先取得KR明确批准。

## 验收记录

1. 保存服务发现、事件目录、真实订阅ID、绑定聊天ID、过滤条件、验证挑战成功记录与有效期。秘密不进入交付证据。
2. 订阅建立后记录关窗/会话结束时间T0及最后一次KR消息ID。不能由当前聊天自己结束自己再继续读回来伪造此步骤。
3. T0以后，独立云端隔离执行器自然完成一个既有授权测试任务；记录任务源ID、RESULT摘要、执行Run、主机代码SHA及事件ID。不要由KR新发消息驱动。
4. 保持KR不发消息。保存事件桥签名投递记录、订阅ID、payload SHA256和接收响应；2xx只判DELIVERED。
5. 取得平台产生的事件触发处理记录：触发类型必须是外部事件，绑定同一eventId/任务ID，开始时间晚于T0；嗨姐处理输出中引用同一RESULT摘要。此项才可判主动触发PASS。
6. 重复投递同一eventId应只处理一次；错Issue/错仓库/无效签名不得触发；重启事件桥后待投递事件仍可恢复，确认不发生回写事件循环。恢复不能依靠手动GET触发嗨姐。

若平台无法提供原聊天订阅，明确使用新的 Work Cloud 聊天作为替代终点，不能标为原嗨口11号恢复。当前未获该环境证据，替代路径仍为待部署/待验收。

OpenAI Responses API的webhook是API完成事件通知到自有端点，不等于向原ChatGPT会话注入消息。https://developers.openai.com/api/docs/guides/webhooks （本轮实际打开）。API代理可作另一种执行终点，但必须明确是独立API嗨姐实例，不能混同原会话。
