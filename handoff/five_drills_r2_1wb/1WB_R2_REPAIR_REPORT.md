# 1WB R2 领取缺陷 · 修复 · 交果报告

- 生成时间：2026-10-09
- 执行身份：1WB 后腿（LOCAL_REAR_LEG / 本地持续开发）
- 依据：KR令3【KR→1WB｜FIVE-DRILLS-R2｜领取缺陷、修复、交果】
- 纪律：禁止新建BUS；禁止重复五练R1；禁止拿自检冒充2WB独立复验。

## 八字段回传（按令3格式）

| 字段 | 值 | 说明 |
|---|---|---|
| `1WB_RECEIVE_REAL=` | **FAIL** | 2WB 将 `R2_DEFECTS_TO_1WB.json` / `FIVE_DRILLS_R2_JOINT_REPORT.md` 写入 tdrive `H4_RELAY_POC`（dir_id `ZNLrUcryedmwUyimUZHE`）。本 1WB 会话：① `mcp__netdrive__tdrive.dir_list(ZNLrUcryedmwUyimUZHE)` → `access denied, role is invalid`（硬鉴权失败）；② `search_file` 同 dir_id → 0 hits；③ 项目根 `VoIzhALatQAiOzGBeg` → 0 entries；④ GitHub `handoff-state` 既有可读通道中也无此二文件。→ 本会话无法自主领取原件，**不得伪造 PASS**。 |
| `DEF_A_TO_F_STATUS=` | **UNKNOWN** | 因上述通道不可达，真实 `DEF-A~F` 内容本会话未能读取。已知缺陷集仅为令2 的 1WB 侧 stand-in（D-R2-1~6）与 R1 D5（DEF-1~5），**非 2WB 真腿权威清单**。已知可修项已按已知清单处理（见下），真实 DEF-A~F 待 2WB 经可读通道重发或 KR 授权 1WB 读该 tdrive 目录后补齐。 |
| `IMAGE_SHARED_REAL=` | **READY** | 火山方舟 Seedream 出图原件 `rgbcw_strip_seedream.png`（294402 字节，SHA256 `ee1446cfa7241b43000a30d441b763a3a3f881157221ce254197d1d133b2b0ba`）及非敏感 `EVIDENCE.json` 已发布至 GitHub `handoff-poc` 既有通道 `handoff/five_drills_r2_1wb/`。**明确不包含** `volc_image_response.json`（密钥扫描拦截件），不上传任何密钥或原始敏感响应。2WB 可经该通道下载原件并独立核验 SHA256。 |
| `LOCAL_SHOWCASE_REAL=` | **PASS** | `R2_RGBCW_SHOWCASE/index.html` 经本地 HTTP 服务（127.0.0.1:8099）实测：HTML=200、图片资源=200、结构完整、含 `OPEN_VERIFIED` 与正确 SHA256。未触碰生产环境（kr-8051-assets），生产部署须 KR_GATE。 |
| `REPAIR_EVIDENCE=` | **PARTIAL** | 已知缺陷（D-R2-1~6 / DEF-1~5）已逐条附前后证据（见下）；真实 DEF-A~F 待补。 |
| `2WB_REVERIFY_PENDING=` | **YES** | 1WB 已将非敏感证据与修复报告发布至 GitHub `handoff-poc` `handoff/five_drills_r2_1wb/`，2WB 可独立复验；但 1WB 未收到 2WB 真腿 DEF-A~F，故 2WB 复验须以其自有清单为准，不得由 1WB 自检冒充。 |
| `KR_RELAY=` | **0** | 本回合所有动作均在机器权限内（本地开发、既有通道发布、图片共享），无付款/新密钥/不可逆生产变更/重大删除/股权/L4/L5 事项，未触发 KR_GATE 主权门。 |
| `VERDICT=` | **PARTIAL_FAIL** | 诚实裁决——因 1WB 会话无法读取 2WB 写入的 tdrive 目录，领取原件与真实 DEF-A~F 读取为 FAIL/UNKNOWN；其余机器可解项（图片共享、本地展示验证、已知缺陷修复、报告发布）已真实完成。不把 PARTIAL 包装为全链 PASS。 |

## 已知缺陷修复记录（基于令2 stand-in D-R2-1~6 与 R1 DEF-1~5）

| 缺陷 | 问题 | 机器修复动作 | 前后证据 | 状态 |
|---|---|---|---|---|
| D-R2-1 / DEF-5 | 软著TOP3仅覆盖8实体中3个 | 产出 `SOFTWARE_COPYRIGHT_FULLPOOL.json`：8实体五指标矩阵，透明列出5个非候选 | 前：TOP3 不透明；后：全池可见，mozi-v1 唯一 MSTBI 全齐 | FIXED |
| D-R2-2 | 火山图片原件未上共享链 | 将 `rgbcw_strip_seedream.png` + `EVIDENCE.json` 发布至 `handoff/five_drills_r2_1wb/`（见 IMAGE_SHARE_MANIFEST.json） | 前：仅 VOLC_EVIDENCE.json 在链；后：图片原件可达 | FIXED（共享已就绪） |
| D-R2-3 / DEF-2 | SM1191 命名冲突仍 UNKNOWN | 机器无法解决（公开检索=收音机IC SOP28，与照明语境冲突） | 保持 UNKNOWN | KR_GATE |
| D-R2-4 / DEF-4 | 8051 生产页为 V0.1 桩无真实展示 | 本地开发真实 RGBCW 展示预览 `index.html`（引用已核实事实+标注AI生成），经本地HTTP实测打开 | 前：生产桩；后：本地预览 OPEN_VERIFIED | PARTIAL_FIXED（本地就绪，生产=KR_GATE） |
| D-R2-5 | GitHub 密钥扫描拦截 | `volc_image_response.json` 被密钥扫描安全拦截未重传；敏感响应未重新上传 | 安全事件已闭环 SAFE | RESOLVED |
| D-R2-6 | 2WB 真独立复核未在本会话实跑 | 本会话为 1WB 后腿，令2 的 2WB 为 stand-in；令3 指定 2WB 真腿已写 tdrive，但 1WB 无该目录读权限 | 2WB 独立复验须由其真腿在自身可读通道完成 | PENDING（需可读通道） |
| DEF-1 | MOZI 版本歧义 | `MOZI_V1_FILING_DRAFT_R2.json` 增 `version_note`（内部1.1.0 vs 申报V1.0） | 前：未说明；后：分歧标注+对齐建议 | FIXED_IN_DRAFT（KR confirm） |
| DEF-3 | 火山视频未授权 | 未调用任何付费视频模型，仅保留已生成图片原件+安全证据摘要 | BLOCKED 保持，无视频调用记录 | KR_GATE |

## 诚实边界声明
1. 本会话是 1WB 后腿；令2 的 2WB 侧为 stand-in，非跨节点独立验收。
2. 令3 指定 2WB 真腿已实跑并写 tdrive，但 1WB 会话对该 tdrive 目录无读权限（`role is invalid`），故无法领取——此与既有「NAS↔2WB=FAIL」跨腿边界一致。
3. 沿用既有 GitHub `handoff-poc` 通道发布（不新建 BUS）。
4. 禁止拿自检冒充 2WB 独立复验；2WB 复验须以其自有 DEF-A~F 为准。

## 发布物清单（handoff/five_drills_r2_1wb/）
- `rgbcw_strip_seedream.png` — 火山出图原件（非敏感）
- `VOLC_EVIDENCE.json` — 非敏感出图证据（SHA+元数据）
- `IMAGE_SHARE_MANIFEST.json` — 图片共享清单（含 SHA256，声明不含敏感响应）
- `1WB_R2_REPAIR_REPORT.md` — 本报告
- `1WB_DEFECTS_FIXED_R2.json` — 已知缺陷修复记录
- `SOFTWARE_COPYRIGHT_FULLPOOL.json` — 全候选池八实体五指标矩阵
- `MOZI_V1_FILING_DRAFT_R2.json` — 软著申报草案R2（含版本歧义修复）
- `R2_RGBCW_SHOWCASE/index.html` — 本地展示预览（供 2WB 查看成果）
