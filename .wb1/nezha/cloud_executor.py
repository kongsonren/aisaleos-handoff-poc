# -*- coding: utf-8 -*-
"""哪吒 · 云端最小 EXECUTOR（V0.1）

运行环境：GitHub Actions runner（**不在本地 12WB 上**，不受 KR 关机影响）。
链路：读 TASK → 验 AUTH → 验 OWNER/EPOCH → 读 CHECKPOINT → **从下一步继续** → 执行
     → STATE_FORWARD → RESULT

硬纪律：
  · 不得从 STEP_1 重跑（否则不是接管，是重跑）
  · 任何写回都经 TaskState.advance()，epoch 不合法即被拒
  · 不创建新业务任务，不替 KR 决定业务目标
"""
from __future__ import annotations
import base64, json, os, sys, time, hashlib, urllib.request
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from task_state import GitHubStore, TaskState, now_iso  # noqa: E402

TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("MOZI_GH_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY", "kongsonren/aisaleos-handoff-poc")
AUTH_ID = os.environ.get("NEZHA_AUTH_ID", "KR-TOKEN-20260928-NEZHA-TAKEOVER")
ACTOR = "CLOUD_NEZHA"
STALE_SEC = int(os.environ.get("NEZHA_STALE_SEC", "180"))

STAGING_DIR = ".wb1/8051_triage/staging"
OUT_DIR = ".wb1/8051_triage"
STEPS = ["STEP_1", "STEP_2", "STEP_3", "STEP_4", "STEP_5"]


def log(*a):
    print("[NEZHA]", *a, flush=True)


def read_file_local_or_repo(store: GitHubStore, path: str):
    """优先本地磁盘（runner 已 checkout），否则回落到仓库 API。"""
    if os.path.exists(path):
        return open(path, "rb").read()
    return store.read_raw_text(path)


def step_3(store, state):
    """生成 EVIDENCE_MANIFEST.json：读 LOCAL 已上传的 staging 文件，逐文件算 sha256。"""
    names = ["check_scenario_A.json", "check_scenario_B.json", "check_scenario_C.json",
             "render_scenario_A.html", "render_scenario_B.html", "render_scenario_C.html"]
    rows, missing = [], []
    for n in names:
        p = "%s/%s" % (STAGING_DIR, n)
        data = read_file_local_or_repo(store, p)
        if not data:
            missing.append(n); continue
        rows.append({"file": n, "bytes": len(data),
                     "sha256": hashlib.sha256(data).hexdigest()})
    if missing:
        return None, "STAGING_MISSING: %s" % missing
    manifest = {
        "task_id": state["task_id"],
        "generated_by": ACTOR,
        "generated_at": now_iso(),
        "source": "8051 小程序三场景验证（LIVE / SNAPSHOT / RECOVER）",
        "files": rows,
        "note": "本 MANIFEST 由云端哪吒在 LOCAL 遗留 STAGING 基础上生成，未重新执行场景。",
    }
    return manifest, None


def step_4(store, state, manifest):
    """生成 TRIAGE_RESULT.md：最终可核验回执，含唯一 completion_id。"""
    cid = "NEZHA-%s-%s" % (state["task_id"], hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:12])
    L = []
    A = L.append
    A("# TASK-REAL-001 · 8051 三场景证据封包 · 云端接管 RESULT")
    A("")
    A("- task_id: `%s`" % state["task_id"])
    A("- completion_id: `%s`" % cid)
    A("- completed_by: **%s**（GitHub Actions runner，非本地 12WB）" % ACTOR)
    A("- completed_at: %s" % now_iso())
    A("- takeover_from: LOCAL_1WB @ epoch=%d" % (int(state["epoch"]) - 1))
    A("- resume_from_checkpoint: **%s**（LOCAL 遗留）" % state["checkpoint"])
    A("")
    A("## 证据清单")
    A("")
    A("| 文件 | 字节 | sha256(前16) |")
    A("|---|---|---|")
    for r in manifest["files"]:
        A("| `%s` | %d | `%s` |" % (r["file"], r["bytes"], r["sha256"][:16]))
    A("")
    A("## 连续性声明")
    A("")
    A("本机（LOCAL_1WB）完成 %s 后停止；云端从 %s 继续，**未重新执行 STEP_1/STEP_2**。"
      % (state["checkpoint"], "STEP_3"))
    return ("\n".join(L) + "\n").encode("utf-8"), cid


def main():
    if not TOKEN:
        log("FATAL: no token"); return 2
    store = GitHubStore(TOKEN, REPO)
    ts = TaskState(store)
    state, sha, head, code = ts.load()
    if state is None:
        log("FATAL: no task state", code); return 3
    log("state read:", json.dumps({k: state.get(k) for k in
        ("task_id", "auth_id", "owner", "epoch", "checkpoint", "next_expected", "state")}, ensure_ascii=False))

    # --- 1. AUTH ---
    if state.get("auth_id") != AUTH_ID:
        log("REJECT: auth mismatch", state.get("auth_id")); return 4

    # --- 2. OWNER / EPOCH / 失联判定 ---
    if state.get("owner") == ACTOR:
        log("already owned by cloud; resume from", state.get("checkpoint"))
    else:
        lp = state.get("last_progress_at")
        try:
            age = (datetime.now(timezone(timedelta(hours=8))) - datetime.fromisoformat(lp)).total_seconds()
        except Exception:
            age = 10 ** 9
        log("LOCAL last_progress age = %.0fs (threshold %ds)" % (age, STALE_SEC))
        if age < STALE_SEC:
            log("REJECT: LOCAL still fresh, no takeover"); return 5

    cur_epoch = int(state.get("epoch", 0))
    my_epoch = cur_epoch + 1 if state.get("owner") != ACTOR else cur_epoch

    # --- 3. 接管（epoch +1，owner 转移） ---
    if my_epoch != cur_epoch:
        r = ts.advance(actor_epoch=my_epoch, actor=ACTOR, state="RUNNING",
                       note="TAKEOVER from %s" % state.get("owner"), allow_takeover=True)
        if not r.get("ok"):
            log("REJECT takeover:", r.get("error"), r.get("reason")); return 6
        state = r["state"]
        log("TAKEOVER OK epoch=%d owner=%s" % (state["epoch"], state["owner"]))

    # --- 4. 从 LOCAL 遗留 CHECKPOINT 的**下一步**继续 ---
    cur_ck = state.get("checkpoint")
    if cur_ck not in STEPS:
        log("REJECT: unknown checkpoint", cur_ck); return 7
    start_idx = STEPS.index(cur_ck) + 1
    log("resume: LOCAL stopped at %s -> cloud starts at %s" % (cur_ck, STEPS[start_idx] if start_idx < len(STEPS) else "DONE"))

    pending = {}
    manifest = None
    for idx in range(start_idx, len(STEPS)):
        step = STEPS[idx]
        if step == "STEP_3":
            manifest, err = step_3(store, state)
            if err:
                log("STEP_3 FAIL:", err); return 8
            pending["%s/EVIDENCE_MANIFEST.json" % OUT_DIR] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
            log("STEP_3 built manifest with %d files" % len(manifest["files"]))
        elif step == "STEP_4":
            result_md, cid = step_4(store, state, manifest)
            pending["%s/TRIAGE_RESULT.md" % OUT_DIR] = result_md
            log("STEP_4 built result completion_id=%s" % cid)
        elif step == "STEP_5":
            pass
        nxt = STEPS[idx + 1] if idx + 1 < len(STEPS) else None
        r = ts.advance(actor_epoch=int(state["epoch"]), actor=ACTOR, checkpoint=step,
                       state="RUNNING", next_expected=nxt, note="cloud executed %s" % step)
        if not r.get("ok"):
            log("STATE_FORWARD FAIL at", step, r.get("error"), r.get("reason")); return 9
        state = r["state"]
        log("STATE_FORWARD ->", step)

    # --- 5. 提交本轮产物（真实文件落仓库） ---
    if pending:
        c = store.commit_files(pending, "[NEZHA] cloud artifacts for %s" % state["task_id"])
        log("artifacts commit:", c)
        if not c.get("ok"):
            return 10

    # --- 6. RESULT（只承认一次，重复即被拒） ---
    r = ts.advance(actor_epoch=int(state["epoch"]), actor=ACTOR, state="DONE",
                   checkpoint="STEP_5", next_expected=None,
                   result={"status": "PASS", "completion_id": hashlib.sha256(
                       json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:12],
                           "artifacts": sorted(pending.keys())},
                   note="RESULT written by cloud")
    log("RESULT:", json.dumps({k: r.get(k) for k in ("ok", "error", "reason")}, ensure_ascii=False))
    return 0 if r.get("ok") else 11


if __name__ == "__main__":
    sys.exit(main())
