---
title: RGBCW 真实资料索引（60×1cm 软灯带 / SM1191）
tags: [RGBCW, 8051, 照明, REAL资料, 五练贯通令, 2WB前腿]
date: 2026-10-08
campaign: FIVE_DRILLS_V1
role: 1WB_LOCAL_EXECUTOR
verdict: PARTIAL_REAL
source_discipline: 仅记可检索到的真实证据；无法佐证者标 UNKNOWN，不洗绿
---

# RGBCW 真实资料索引

> 落点：五练贯通令 D2（RGBCW 真实资料接入 Obsidian，写入+回读）。本笔记只承载真实可检索证据。

## CURRENT（真实、可检索）
- **60×1cm RGBCW 柔性 LED 软灯带**（产品类，REAL）：
  - 市场真实型号示例：5050 RGBCW LED Strip，60 LEDs/m，PCB 宽 12mm（即≈1cm），长 5m/卷。
  - 电气：DC24V（亦有 DC12V 版本），功率 15–19 W/m（RGBW+CCT 合计；单色通道约 3.6 W/m）。
  - 光参数：RGB + 3000K/6000K（或 2700K/6400K 双白），CRI 80Ra，单灯 18–22 lm。
  - 防护：IP20（裸板）/ IP65 / IP67 / IP68 可选；3oz FPC，无压降首尾一致。
  - 调光：支持 2.4G / 0-1-10V / 可控硅 / DALI 调光驱动器；裁剪点 50/100mm。
  - 寿命：>50,000 h（部分标 >80,000 h）；认证 CE / FCC / RoHS / IEC-EN62471 / LM-80。
  - 证据来源：公开产品页（topledvision / siled.cn / ledownia.pl / shop4electrical / coovee）2026-10-08 WebSearch 命中。
- **8051 产品场架构真相**（来自 `8051_VERSION_MAP.md` 真源归档）：
  - Embedded_8051（MCU/LED 固件）≠ LEGACY_8051（企业经营系统祖宗）。两概念须分开。
  - 活源：8090 REAL源（192.168.2.107:8090，runs=410）、kr-8051-assets 公网只读镜像、飞书 Base 8051 产品场（6表，1WB 不可达）。

## HISTORY（曾运行，现已关闭）
- 8052「8051AISALEOS产品资产」本地服务（2026-09-29）→ CLOSED。
- 8053 V2 视觉母件 MOCK（2026-09-29）→ CLOSED。
- 8051/8052/8053/8054 端口全 CLOSED（2026-10-05 batch5 复核）。

## UNKNOWN（诚实保留，不硬查成 PASS）
- **SM1191 真实身份冲突（重要）**：公开检索到的 "SM1191" 是 **NPC（Seiko）FM/AM 收音机集成电路（SOP28）**，与 LED 驱动/照明无关。
  - 我方 8051 语境下的 SM1191（记忆：8090-REAL源.json `MARKET_REAL=SM1191` 经营主落点）**具体是什么，1WB 无法确证**。
  - **结论**：若我方 SM1191 指照明产品/LED 驱动，则与市场公开 "SM1191=收音机IC" 存在命名冲突，须 KR 确认我方 SM1191 的真实定义（型号/厂商/功能），否则不得作为照明 REAL 证据使用。
- 飞书 Base 8051 真源内容：1WB 无权限不可达 → UNKNOWN。
- 豆包V1.1 / 新专修界面 / 8053 V2 源文件：UNKNOWN（PARK 裁定，不主动续扫）。

## Evidence 索引
- 市场真实产品页（WebSearch 2026-10-08）：topledvision.en.made-in-china.com、siled.cn/Products/info/id/127、ledownia.pl、shop4electrical.co.uk、coovee.com。
- 架构真相：`E:\AISALEOS-Vault\20-Projects\哪吒后轮\8051_VERSION_MAP.md`。
- 火山出图（D3 真实产出）：`E:\AISALEOS-Vault\20-Projects\哪吒后轮\VOLC_DRILL_001\rgbcw_strip_seedream.png`（SHA256 ee1446cf…b2b0ba）。

## 下一机器动作
- 待 KR 确认 SM1191 真实定义（命名冲突澄清）→ 否则 SM1191 维持 UNKNOWN。
- 60×1cm 软灯带可进 8051 产品场"组合应用方案"真实条目（需 KR 授权回写飞书 Base）。
