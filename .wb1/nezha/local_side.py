# -*- coding: utf-8 -*-
"""LOCAL_1WB 端：执行 TASK-REAL-001 的前半段，然后**故意不完成**，交给云端接管。

用法：
    python local_side.py init      # 建立 TASK STATE（owner=LOCAL_1WB, epoch=1）
    python local_side.py prepare   # STEP_1 收集证据 + STEP_2 上传 staging，随后停止
    python local_side.py observe   # 重新上线后读 STATE；发现 epoch 更大 → 退避（不抢活）
"""
from __future__ import annotations
import hashlib, json, os, shutil, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from task_state import GitHubStore, TaskState, now_iso  # noqa: E402

TOKEN = os.environ.get("MOZI_GH_TOKEN")
REPO = os.environ.get("NEZHA_REPO", "kongsonren/aisaleos-handoff-poc")
TASK_ID = "TASK-REAL-001"
AUTH_ID = os.environ.get("NEZHA_AUTH_ID", "KR-TOKEN-20260928-NEZHA-TAKEOVER")
ACTOR = "LOCAL_1WB"
SRC = r"C:/Users/59605/.wb1/8051_mp_scenarios"
LOCAL_STAGING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "staging")
STAGING_DIR = ".wb1/8051_triage/staging"
NAMES = ["check_scenario_A.json", "check_scenario_B.json", "check_scenario_C.json",
         "render_scenario_A.html", "render_scenario_B.html", "render_scenario_C.html"]


def log(*a):
    print("[LOCAL]", *a, flush=True)


def store():
    tok = TOKEN
    if not tok:  # Bash 环境会剥离 env，回落到凭据文件（不打印、不落日志）
        p = os.path.expanduser("~/.wb1/github_pat")
        if os.path.exists(p):
            tok = open(p).read().strip()
    if not tok:
        raise SystemExit("FATAL: no GitHub token (MOZI_GH_TOKEN or ~/.wb1/github_pat)")
    return GitHubStore(tok, REPO)


def cmd_init():
    ts = TaskState(store())
    r = ts.init(TASK_ID, AUTH_ID, owner=ACTOR, epoch=1,
                checkpoint="STEP_0", state="RUNNING", next_expected="STEP_1")
    log("init:", json.dumps({k: r.get(k) for k in ("ok", "error", "commit")}, ensure_ascii=False))
    return 0 if r.get("ok") else 1


def cmd_prepare():
    """STEP_1：收集证据（本地 staging + sha256）；STEP_2：上传仓库。然后停。"""
    s = store()
    ts = TaskState(s)

    # STEP_1 —— 真收集（读真实产物，算真实哈希）
    os.makedirs(LOCAL_STAGING, exist_ok=True)
    rows = []
    for n in NAMES:
        src = os.path.join(SRC, n)
        if not os.path.exists(src):
            log("MISSING source:", src); return 2
        data = open(src, "rb").read()
        dst = os.path.join(LOCAL_STAGING, n)
        shutil.copyfile(src, dst)
        rows.append({"file": n, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    log("STEP_1 collected %d files" % len(rows))
    for r in rows:
        log("   %-26s %7d  %s" % (r["file"], r["bytes"], r["sha256"][:16]))

    r = ts.advance(actor_epoch=1, actor=ACTOR, checkpoint="STEP_1", state="RUNNING",
                   next_expected="STEP_2", note="LOCAL collected 8051 triage evidence")
    if not r.get("ok"):
        log("STEP_1 state FAIL:", r.get("error"), r.get("reason")); return 3
    log("STEP_1 -> state checkpoint=STEP_1")

    # STEP_2 —— 上传 staging 到仓库（云端后续才能读到）
    files = {"%s/%s" % (STAGING_DIR, n): open(os.path.join(LOCAL_STAGING, n), "rb").read() for n in NAMES}
    c = s.commit_files(files, "[NEZHA] LOCAL_1WB uploaded staging evidence for %s" % TASK_ID)
    log("STEP_2 commit:", json.dumps({k: c.get(k) for k in ("ok", "commit", "error")}, ensure_ascii=False))
    if not c.get("ok"):
        return 4

    r = ts.advance(actor_epoch=1, actor=ACTOR, checkpoint="STEP_2", state="RUNNING",
                   next_expected="STEP_3", note="LOCAL uploaded staging; STOPs here by design")
    if not r.get("ok"):
        log("STEP_2 state FAIL:", r.get("error"), r.get("reason")); return 5

    st = r["state"]
    print()
    print("=" * 72)
    print(" READY_FOR_POWER_OFF")
    print("=" * 72)
    print("  task_id      :", st["task_id"])
    print("  owner        :", st["owner"])
    print("  epoch        :", st["epoch"])
    print("  checkpoint   :", st["checkpoint"], "   (故意未完成，剩余 STEP_3/4/5 留给云端)")
    print("  state        :", st["state"])
    print("  next_expected:", st["next_expected"])
    print("  last_progress:", st["last_progress_at"])
    print("  result       :", st["result"])
    print()
    print("  >> 此时本地 12WB 已无后续动作。请 KR 物理关闭 12WB，云端哪吒将从 STEP_3 接管。")
    print("=" * 72)
    return 0


def cmd_observe():
    """重新上线后：先读 STATE，若 epoch 已被云端推进 → 必须退避。"""
    ts = TaskState(store())
    st, _, _, code = ts.load()
    if st is None:
        log("no state (code=%s)" % code); return 3
    local_epoch = 1
    cur_epoch = int(st.get("epoch", 0))
    print(json.dumps({k: st.get(k) for k in ("task_id", "owner", "epoch", "checkpoint", "state",
                                             "next_expected", "result", "result_written_by")},
                     ensure_ascii=False, indent=2))
    if cur_epoch > local_epoch:
        print()
        print("LOCAL_EPOCH=%d < CLOUD_EPOCH=%d  owner=%s" % (local_epoch, cur_epoch, st.get("owner")))
        print("=> LOCAL MUST STAND DOWN: OBSERVE / IDLE —— 不抢活、不重复执行。")
        # 真退避验证：尝试用旧 epoch 写一次，必须被拒
        r = ts.advance(actor_epoch=local_epoch, actor=ACTOR, checkpoint="STEP_5",
                       note="LOCAL attempting to resume after power-on")
        print("fencing test (old epoch write):", json.dumps(
            {k: r.get(k) for k in ("ok", "error", "reason")}, ensure_ascii=False))
        if r.get("error") == "REJECT_STALE_EPOCH":
            print("=> FENCING PROVEN: 旧执行体写入被拒。LOCAL 退避成立。")
            return 0
        print("=> FENCING FAILED: 旧 epoch 竟然写进去了！")
        return 1
    print("epoch still local; no takeover happened yet.")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "observe"
    sys.exit({"init": cmd_init, "prepare": cmd_prepare, "observe": cmd_observe}[cmd]())
