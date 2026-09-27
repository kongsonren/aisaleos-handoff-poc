# -*- coding: utf-8 -*-
"""云端哪吒 · 连续工作策略层（AUTH / CAPABILITY / 候选动作池）

硬纪律（KR 2026-09-28 令牌）：
  1) **AUTH 不因上云而扩大**。这份注册表里的每一条都来自 KR 已经给后腿的令牌，
     云端只是继承；跨腿/新战场/高风险/付款/重大外发/删除覆盖/权限升级 → 一律 KR_GATE。
  2) **CLOUD_CAPABILITY 不脑补**。凡未真实证明云端可达的能力，一律 = LOCAL_ONLY，
     任务挂起记 BLOCKED_LOCAL，**不得因此整腿停工**。
  3) 本文件不消费任何 inbox / 前腿消息。前腿来料默认 INFO，**不自动成为命令**。
"""
from __future__ import annotations

ACTOR = "CLOUD_NEZHA"

# ------------------------------------------------------------------ AUTH
# FORBIDDEN_FLAGS：任一为 True 就必须走 KR_GATE，云端不得自行动作
FORBIDDEN_FLAGS = ["cross_leg", "new_battlefield", "high_risk", "payment",
                   "external_send", "delete_or_overwrite_protected", "privilege_escalation"]

AUTH_REGISTRY = {
    "KR-TOKEN-20260928-NEZHA-TAKEOVER": {
        "granted_by": "KR 直接令牌 2026-09-28 今晚总攻（断电接管）",
        "scope_slugs": ["8051.baton"],
        "cross_leg": False, "new_battlefield": False, "high_risk": False,
        "payment": False, "external_send": False,
        "delete_or_overwrite_protected": False, "privilege_escalation": False,
    },
    "KR-TOKEN-20260928-POWEROFF-V2": {
        "granted_by": "KR 直接令牌 2026-09-28《云哪吒连续工作闭环》二/三/四/五条（第二场接力）",
        "scope_slugs": ["8051.baton", "8051.cloud_verify"],
        "cross_leg": False, "new_battlefield": False, "high_risk": False,
        "payment": False, "external_send": False,
        "delete_or_overwrite_protected": False, "privilege_escalation": False,
        "note": "与第一场同一份 KR 令牌：**不因上云而扩权**。Round1 于 05:14 误判失联接管，"
                "已作废（见 8051_triage/_void_round1/README.md），本轮为同一剧情的第二场。",
    },
}


def auth_check(auth_ref: str, scope_slug: str):
    """返回 (ok, reason)。任何越权都不放行。"""
    a = AUTH_REGISTRY.get(auth_ref)
    if not a:
        return False, "AUTH_UNKNOWN: %s" % auth_ref
    bad = [f for f in FORBIDDEN_FLAGS if a.get(f)]
    if bad:
        return False, "AUTH_TAGGED_GATE: %s" % bad
    if scope_slug not in a.get("scope_slugs", []):
        return False, "AUTH_SCOPE_MISS: %s not in %s" % (scope_slug, a.get("scope_slugs"))
    return True, "AUTH_OK %s / scope=%s" % (auth_ref, scope_slug)


# --------------------------------------------------------- CAPABILITY
# 只在"已经真实证明云端可达"的资源进 CLOUD_READY；其余一律 LOCAL_ONLY / UNKNOWN
CLOUD_READY = {
    "github_repo_file": "runner checkout + Contents API 读取（已验证：多次读取 .wb1/nezha/task_state.json）",
    "git_data_write": "Git Data API 提交（已验证：blob→tree→commit→PATCH refs 多次成功）",
    "task_state_beam": "状态梁读写（同一份 task_state.py，本地与云共用）",
    "github_actions_self": "本 workflow 自身被 GitHub 调度触发（已验证：schedule + dispatch 均真实运行）",
    "python_stdlib": "Python 标准库 hashlib/json/urllib（ubuntu-latest 原生）",
}
LOCAL_ONLY = {
    "kr_local_disk": "只存在于黑武士本机的文件/程序（deploy_8051 运行态、:8051/:8052 进程）",
    "nas_smb": "NAS SMB 共享 \\\\192.168.2.107，从未在 GitHub runner 上验证可达",
    "wechat_devtools": "微信开发者工具 / AppID（本机全盘 0 命中）",
    "feishu_base_secret": "飞书 Base appId/secret 凭据仅在本地 ~/.lark-cli，云侧未验证且不得上云凭证",
    "release_publish": "WorkBuddy 发布工具（宿主会话挂载，脚本不可调用）",
}


def classify(needs):
    """返回 (capability, unknown_list, local_list)。UNKNOWN 一律当 LOCAL_ONLY 处理。"""
    unknown = [n for n in needs if n not in CLOUD_READY and n not in LOCAL_ONLY]
    local = [n for n in needs if n in LOCAL_ONLY]
    if unknown:
        return "UNKNOWN", unknown, local          # 不脑补 → 视为不可云执行
    if local:
        return "LOCAL_ONLY", unknown, local
    return "CLOUD_READY", unknown, local


def reach_evidence(needs):
    return {n: (CLOUD_READY.get(n) or LOCAL_ONLY.get(n) or "未识别：按 LOCAL_ONLY 处理") for n in needs}


# ------------------------------------------------------- 候选动作池
# 说明：这是"准入条件池"，不是预排队列。云端每轮按当前 STATE / 上一轮 RESULT /
# 现实可达能力自己过滤；谁满足谁上位。被跳过的会记下原因。
CANDIDATES = [
    {
        "id": "REVERIFY_8051_EVIDENCE",
        "title": "8051 接班产物的跨执行体独立复核",
        "task_id": "TASK-REAL-012",
        "auth_ref": "KR-TOKEN-20260928-POWEROFF-V2",
        "scope_slug": "8051.cloud_verify",
        "needs": ["github_repo_file", "git_data_write", "task_state_beam", "python_stdlib"],
        "gate": False,
        "real_value": "由第二个独立执行体复核第一棒的证据链字节完整性，"
                      "把'产出自证'升级为'他人复核'——这是证据可信度的真实台阶，不是日志、不是 sleep。",
    },
    {
        "id": "SYNC_FEISHU_8051",
        "title": "把 8051 结论同步回飞书 Base 证据库",
        "task_id": "TASK-REAL-013",
        "auth_ref": "KR-TOKEN-20260928-POWEROFF-V2",
        "scope_slug": "8051.cloud_verify",
        "needs": ["feishu_base_secret"],
        "gate": False,
        "real_value": "回填真源（真实必要），但依赖本地凭据；云侧未验证可达 → BLOCKED_LOCAL，不整腿停工。",
    },
    {
        "id": "PUBLISH_8051_REMOTE",
        "title": "远程重推 8051 发布包到线上应用",
        "task_id": "TASK-REAL-014",
        "auth_ref": "KR-TOKEN-20260928-POWEROFF-V2",
        "scope_slug": "8051.cloud_verify",
        "needs": ["release_publish"],
        "gate": True,
        "real_value": "覆盖线上应用属重大生产动作 → BLOCKED_GATE，等 KR 裁决，云端不得自行发布。",
    },
]
