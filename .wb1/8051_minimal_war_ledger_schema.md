# 8051 最小承战战争账 Schema（设计稿 · cloud-1WB）
STATUS: DESIGN / NOT_YET_BUILT_IN_REALSOURCE
REF_TASK: WAR_REF=NEZHA-60X1-FIRST-BATTLE-20260927-001 (Part A)

## 最小战争账字段
- time 时间（ISO8601）
- object 对象（指向 8051 真源对象 id，如 P-60X1-RGBCW）
- battlefield / channel 战场/渠道（外部阵地标识）
- event 事件（MARKET_LIVE / REACHED / ENGAGED / BUSINESS_REAL 等）
- executor 执行者（1WB / 2WB / 外部）
- real_result REAL结果（有效行为描述）
- evidence_ref 证据REF（URL/商品ID/发布状态/外部可访问性）
- state_change 状态变化（仅当 REAL 真实改变 8051 对象才记 STATE_CHANGED）
- next_action 下一动作

## 状态机（严禁自动升级）
LOADED -> MARKET_LIVE -> REACHED -> ENGAGED -> BUSINESS_REAL -> (SAMPLE/QUOTE/ORDER)
- MARKET_LIVE：真实产品进入外部商业阵地；仅代表市场化第一步 PASS，不冒充客户成功
- REACHED：有效触达（!= SMTP 成功 / HTTP 200）
- ENGAGED：真实互动（询盘/联系/索样/询价/规格讨论）
- BUSINESS_REAL：经营级真实行为
- 铁律：PUBLISHED/SENT != REACHED != ENGAGED != BUSINESS_REAL；SMTP 成功!=触达；HTTP 200!=市场 REAL

## 三出口
- LAW_GAP -> 菩提（法律/合规缺口）
- KR_GATE -> KR（主权/高风险/不可逆/权限边界）
- COMMAND_REQUIRED -> 子牙（跨产品/公司/人员/价格/库存/交付资源调度）

## 对象状态 != 战争事件 != 状态变化
- 区分三者的唯一权威数据源 = 8051 真源（飞书 Base）
- 本 Schema 仅为本地/云战争账记录层；不重建 8051，不另起平台
