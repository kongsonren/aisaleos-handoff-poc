# 8051 产品场 · RGBCW 七星导航规格 (EXECUTION_CLOSURE_V1 测试件)

> 本文件为云端1号WB 执行闭环 V1 的隔离测试件, 非生产真源。
> 真源: 飞书 Base `S4V3biW4saCrRCsmG42cvaPSnod` (appId cli_aa3a4b1a2f399cc2)
> 生产 8051 产品场 v0.1 = READY (2026-09-21); 本件仅用于 Contents API 读写完整性验收。

## 1. RGBCW 五通道定义
- R = Red (红)
- G = Green (绿)
- B = Blue (蓝)
- C = Cool White (冷白)
- W = Warm White (暖白)
五通道独立调光, 构成 8051 基础发光单元。

## 2. 七星导航 (7-step navigation)
1. 入口: 产品场总览 Dashboard (blkupUW9XYTFXYOo)
2. 对象层: SM1191 / 60x1 软灯带 / 橱柜灯方案 / 刘总双低压风扇灯
3. 字段层: RGBCW 五通道参数 + 证据状态(REAL/UNKNOWN)
4. 视图层: 主视图 + 五层隔离视图
5. 证据层: 每条记录绑定 Evidence (来源/SHA/时间)
6. 回读层: 写后 GET 独立校验 (SHA256)
7. 收口层: 终态回执 [WB1-EXEC-RESULT]

## 3. 四对象现状 (2026-09-21 盘点)
- SM1191: UNKNOWN (自身证据空)
- 60x1 软灯带: REAL
- 橱柜灯方案: 自身证据空
- 刘总双低压风扇灯: REAL

## 4. 治理纪律 (RGBCW_8051 治理 V0.1)
- 低风险(字段/视图): 1WB 自治, 留 DIFF
- 高风险(真源语义/删核心字段/破关联/跨边界): KR_GATE
- 文件存在 != REAL; AI 稿默认不升 FACT; UNKNOWN 不洗绿

## 5. 执行闭环元数据
- run_id: CWB1-ECV1-20261011T103307Z
- cycle_id: CWB1-HOURLY-49267651-20261011T10Z
- generated_at: 2026-10-11T10:33:07.809485+00:00
- purpose: EXECUTION_CLOSURE_V1 PUT/GET/SHA256 验收
