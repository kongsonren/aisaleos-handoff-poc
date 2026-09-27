# -*- coding: utf-8 -*-
"""哪吒 · 云端自主连续工作循环 V0.1（Cloud Continuous Work）

运行环境：GitHub Actions runner（独立于黑武士 hostname=KR 的物理机）。
本程序**每轮只做一个动作**，做完即退；下一次动作由下一次云起搏自行重新判断 ——
这不是预排队列，是循环。

每轮：
  1. 读状态梁里所有 TASK
  2. 分类：
       RUNNING_CLOUD    owner=CLOUD_NEZHA 且未完成   → 续（不重开）
       LOCAL_HELD       owner=LOCAL_1WB 且仍新鲜     → **不抢活**（NO_TAKEOVER）
       TAKEOVER         owner=LOCAL_1WB 且已超时     → epoch+1 接管续跑
       IDLE             全部已完成                   → 扫描候选动作池
  3. IDLE 时按 reality 过滤候选：
       capability != CLOUD_READY → BLOCKED_LOCAL / BLOCKED_GATE（记录，**不停工**）
       AUTH 越权               → BLOCKED_GATE
       准入条件不满足           → 跳过并记原因
       全不满足                 → GENUINE_IDLE（允许真闲，禁止造垃圾任务）
  4. 写 heartbeat（round_seq 单调递增，证明"下一轮真的自己发生了"）

状态梁：继续复用 task_state.py（CAS + epoch 拒写 + duplicate-result rejection），不重造。
"""
from __future__ import annotations
import json, os, sys, time, hashlib, subprocess
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from task_state import GitHubStore, TaskState, now_iso  # noqa: E402
import loop_policy as P  # noqa: E402

CN = timezone(timedelta(hours=8))
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("MOZI_GH_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY", "kongsonren/aisaleos-handoff-poc")
ACTOR = P.ACTOR
STALE_SEC = int(os.environ.get("NEZHA_STALE_SEC", "180"))

INDEX_PATH = ".wb1/nezha/task_index.json"
HEARTBEAT_PATH = ".wb1/nezha/loop_heartbeat.json"
OUT_DIR = ".wb1/8051_triage"
STAGING_DIR = OUT_DIR + "/staging"
REVERIFY_MD = OUT_DIR + "/REVERIFY_REPORT.md"
REVERIFY_JSON = OUT_DIR + "/REVERIFY_MANIFEST.json"
BOOTSTRAP_TASKS = ["TASK-REAL-001"]
SCEN_FILES = ["check_scenario_A.json", "check_scenario_B.json", "check_scenario_C.json",
              "render_scenario_A.html", "render_scenario_B.html", "render_scenario_C.html"]
RV_STEPS = ["RV_1", "RV_2", "RV_3", "RV_4"]


def log(*a):
    print("[LOOP]", *a, flush=True)


def age_of(state):
    try:
        return (datetime.now(CN) - datetime.fromisoformat(state["last_progress_at"])).total_seconds()
    except Exception:
        return 10 ** 9


def read_repo(store, path):
    """runner 已 checkout 则读磁盘，否则回落 raw 域。"""
    if os.path.exists(path):
        return open(path, "rb").read()
    b = store.read_raw_text(path)
    return b


# ================================================== 第二棒：跨执行体独立复核
def cand_reverify_requires(store, ctx):
    """准入：第一棒必须真的完成，且复核产物尚未存在（防重复劳动）。"""
    t1 = ctx["tasks"].get("TASK-REAL-001") or {}
    if not t1 or t1.get("state") != "DONE" or not t1.get("result"):
        return False, "WAIT: TASK-REAL-001 not DONE yet (owner=%s ckpt=%s)" % (
            t1.get("owner"), t1.get("checkpoint"))
    arts = t1.get("result", {}).get("artifacts") or []
    need = ["%s/EVIDENCE_MANIFEST.json" % OUT_DIR, "%s/TRIAGE_RESULT.md" % OUT_DIR]
    miss = [p for p in need if p not in arts]
    if miss:
        return False, "WAIT: first-leg artifacts missing %s" % miss
    if read_repo(store, REVERIFY_MD):
        return False, "SKIP: REVERIFY_REPORT.md already exists (already done)"
    return True, "READY: TASK-REAL-001 DONE by %s, artifacts present, no prior reverify" % t1.get("owner")


CAND_REQUIRES = {"REVERIFY_8051_EVIDENCE": cand_reverify_requires}  # 其余候选恒被 capability/gate 挡住


def run_reverify(store, task_id):
    """第二棒执行：产第二个独立 REAL —— 跨执行体复核报告 + 机器可读 MANIFEST。"""
    ts = TaskState(store, ".wb1/nezha/task_state_%s.json" % task_id)
    cur, _, _, _ = ts.load()
    if not cur:
        r = ts.init(task_id=task_id, auth_id="KR-TOKEN-20260928-CLOUD-CONTINUOUS",
                    owner=ACTOR, epoch=1, checkpoint="RV_0", state="RUNNING", next_expected="RV_1")
        log("INIT new task:", json.dumps({k: r.get(k) for k in ("ok", "error", "commit")}, ensure_ascii=False))
        if not r.get("ok"):
            return {"ok": False, "error": "INIT_FAILED", "detail": r.get("error")}
        cur, _, _, _ = ts.load()

    manifest_b = read_repo(store, "%s/EVIDENCE_MANIFEST.json" % OUT_DIR)
    result_md = read_repo(store, "%s/TRIAGE_RESULT.md" % OUT_DIR)
    if not manifest_b or not result_md:
        return {"ok": False, "error": "ARTIFACT_MISSING"}
    manifest = json.loads(manifest_b.decode("utf-8"))

    # RV_1 读取 ≥ RV_2 重算 ≥ RV_3 比对 ≥ RV_4 出报告
    rows, mismatch = [], []
    for row in manifest.get("files", []):
        b = read_repo(store, "%s/%s" % (STAGING_DIR, row["file"]))
        got = hashlib.sha256(b).hexdigest() if b else None
        ok = (got is not None and got == row.get("sha256") and len(b) == row.get("bytes"))
        rows.append({"file": row["file"], "declared_sha256": row.get("sha256"), "declared_bytes": row.get("bytes"),
                     "recomputed_sha256": got, "recomputed_bytes": len(b) if b else None, "match": bool(ok)})
        if not ok:
            mismatch.append(row["file"])

    def fw(checkpoint, nxt, note):
        nonlocal cur
        r = ts.advance(actor_epoch=1, actor=ACTOR, checkpoint=checkpoint, state="RUNNING",
                       next_expected=nxt, note=note)
        if not r.get("ok"):
            return False, r.get("error"), r.get("reason")
        cur = r["state"]
        log("  ->", checkpoint, "ok")
        return True, None, None

    ok, e, why = fw("RV_1", "RV_2", "read first-leg manifest (%d files) + result md" % len(rows))
    if not ok:
        return {"ok": False, "error": e, "reason": why}
    ok, e, why = fw("RV_2", "RV_3", "recomputed sha256 on THIS runner (%s)" % os.uname().nodename[:12])
    if not ok:
        return {"ok": False, "error": e, "reason": why}
    ok, e, why = fw("RV_3", "RV_4", "compare: %d/%d matched" % (len(rows) - len(mismatch), len(rows)))
    if not ok:
        return {"ok": False, "error": e, "reason": why}

    verdict = "MATCH" if not mismatch else "MISMATCH"
    rv_manifest = {
        "task_id": task_id, "reverify_of": "TASK-REAL-001",
        "executed_by": ACTOR, "executed_at": now_iso(),
        "host": os.uname().nodename[:24],
        "recomputed_reason": "second independent execution body (different runner job / machine image) recomputes bytes of first-leg evidence",
        "source_manifest_sha256": hashlib.sha256(manifest_b).hexdigest(),
        "result_md_sha256": hashlib.sha256(result_md).hexdigest(),
        "result_md_bytes": len(result_md),
        "files": rows, "verdict": verdict,
        "completion_id": "RV-%s" % hashlib.sha256(
            (verdict + "|" + "|".join(r["recomputed_sha256"] or "-" for r in rows)).encode()).hexdigest()[:12],
    }
    L = ["# TASK-REAL-002 · 8051 证据链跨执行体独立复核", "",
         "- reverify_of: `TASK-REAL-001`", "- executed_by: **%s**（GitHub Actions runner）" % ACTOR,
         "- host_uname: `%s`" % rv_manifest["host"], "- executed_at: %s" % rv_manifest["executed_at"],
         "- completion_id: `%s`" % rv_manifest["completion_id"], "- verdict: **%s**" % verdict, "",
         "复核内容：由第二个独立执行体，对第一棒的 6 份 staging 证据重新读字节、重算 SHA256，",
         "与第一棒声明值逐字节比对。这是把「产出自证」升级为「他人复核」的真实台阶。", "",
         "| 文件 | 声明 sha256(16) | 本轮重算 sha256(16) | 字节 | 结论 |", "|---|---|---|---|---|"]
    for r in rows:
        L.append("| `%s` | `%s` | `%s` | %s/%s | %s |" % (
            r["file"], (r["declared_sha256"] or "")[:16], (r["recomputed_sha256"] or "-")[:16],
            r["recomputed_bytes"], r["declared_bytes"], "MATCH" if r["match"] else "**MISMATCH**"))
    L += ["", "- source_manifest_sha256: `%s`" % rv_manifest["source_manifest_sha256"],
          "- result_md_sha256: `%s` (%d bytes)" % (rv_manifest["result_md_sha256"], rv_manifest["result_md_bytes"]),
          "- TASK-REAL-001 completion_id: `%s`" % (ctx_first_leg_cid(store) or "?"), ""]
    report_md = ("\n".join(L) + "\n").encode("utf-8")

    c = store.commit_files({REVERIFY_MD: report_md,
                            REVERIFY_JSON: json.dumps(rv_manifest, ensure_ascii=False, indent=2).encode()},
                           "[NEZHA] second REAL: independent reverify of first-leg evidence")
    log("artifacts commit:", json.dumps({k: c.get(k) for k in ("ok", "commit", "error")}, ensure_ascii=False))
    if not c.get("ok"):
        return {"ok": False, "error": "ARTIFACT_COMMIT_FAILED", "detail": c.get("error")}

    ok, e, why = fw("RV_4", None, "second REAL written: %s" % rv_manifest["completion_id"])
    if not ok:
        return {"ok": False, "error": e, "reason": why}

    r = ts.advance(actor_epoch=1, actor=ACTOR, state="DONE", checkpoint="RV_4", next_expected=None,
                   result={"status": "PASS" if verdict == "MATCH" else "FAIL",
                           "completion_id": rv_manifest["completion_id"], "verdict": verdict,
                           "artifacts": [REVERIFY_MD, REVERIFY_JSON],
                           "note": "REAL produced independently by second cloud beat"},
                   note="RESULT written by cloud (second leg)")
    log("RESULT:", json.dumps({k: r.get(k) for k in ("ok", "error", "reason")}, ensure_ascii=False))
    return {"ok": bool(r.get("ok")), "task_id": task_id, "verdict": verdict,
            "completion_id": rv_manifest["completion_id"], "result_commit": r.get("commit")}


def ctx_first_leg_cid(store):
    d, _, _, _ = TaskState(store, ".wb1/nezha/task_state.json").load()
    if not d:
        return None
    res = d.get("result")
    return res.get("completion_id") if isinstance(res, dict) else None


# ================================================== 主循环（一轮一个动作）
def load_index(store):
    d, _, _, _ = store.read_json(INDEX_PATH, default={})
    if not d or "tasks" not in d:
        d = {"tasks": list(BOOTSTRAP_TASKS), "bootstrapped_at": now_iso()}
    return d


def load_tasks(store, index):
    out = {}
    for tid in index["tasks"]:
        path = ".wb1/nezha/task_state_%s.json" % tid if tid != "TASK-REAL-001" else ".wb1/nezha/task_state.json"
        st, _, _, _ = TaskState(store, path).load()
        if st:
            out[tid] = st
    return out


def diagnose(store, tasks):
    """诊断模式：**只看不干** —— 在真实 runner 上把候选池的 capability / gate / auth / 准入
    判定全部跑一遍并写 diag 文件。不创建任务、不改 STATE、不推进 heartbeat_seq。"""
    rows = []
    for c in P.CANDIDATES:
        cap, unknown, local = P.classify(c["needs"])
        aok, areason = P.auth_check(c["auth_ref"], c["scope_slug"])
        fn = CAND_REQUIRES.get(c["id"])
        ready, why = (fn(store, {"tasks": tasks}) if fn else (False, "no require fn"))
        rows.append({"id": c["id"], "title": c["title"], "needs": c["needs"],
                     "capability": cap, "unknown_needs": unknown, "local_only_needs": local,
                     "auth_ok": aok, "auth_reason": areason, "gate_flag": bool(c.get("gate")),
                     "real_value": c["real_value"], "admission_ready": bool(ready), "admission_reason": why})
    diag = {"diag_at": now_iso(), "host": os.uname().nodename[:24],
            "run_id": os.environ.get("GITHUB_RUN_ID"), "note": "admission logic executed on runner, no side effect",
            "rows": rows}
    c = store.commit_files({".wb1/nezha/loop_diag.json": json.dumps(diag, ensure_ascii=False, indent=2).encode()},
                           "[NEZHA] DIAG scan (no task created, no state change)")
    diag["diag_commit"] = c.get("commit")
    for r in rows:
        log("DIAG|", json.dumps({k: r[k] for k in ("id", "capability", "auth_ok", "gate_flag",
                                                   "admission_ready", "admission_reason")}, ensure_ascii=False)[:300])
    print(json.dumps(diag, ensure_ascii=False, indent=2))
    return 0


def main():
    if not TOKEN:
        log("FATAL: no token"); return 2
    store = GitHubStore(TOKEN, REPO)
    index = load_index(store)
    tasks = load_tasks(store, index)
    log("tasks:", json.dumps({k: {"owner": v.get("owner"), "epoch": v.get("epoch"),
                                  "ckpt": v.get("checkpoint"), "st": v.get("state"),
                                  "result": bool(v.get("result"))} for k, v in tasks.items()},
                             ensure_ascii=False))

    if "--diagnose" in sys.argv or os.environ.get("NEZHA_DIAG") == "1":
        log("DIAGNOSE MODE: admission logic only, zero side effect on tasks")
        return diagnose(store, tasks)

    hb_prev, _, _, _ = store.read_json(HEARTBEAT_PATH, default={})
    seq = int((hb_prev or {}).get("round_seq", 0)) + 1

    decision, skips, out = None, [], {}

    # ---- 1) 先看有没有"该我续/该我接管"的现存任务 ----
    for tid, st in tasks.items():
        if st.get("state") == "DONE":
            continue
        owner, age = st.get("owner"), age_of(st)
        if owner == ACTOR:
            decision = {"kind": "RUNNING_CLOUD", "task_id": tid, "checkpoint": st.get("checkpoint")}
            break
        if owner == "LOCAL_1WB":
            if age < STALE_SEC:
                decision = {"kind": "NO_TAKEOVER_LOCAL_HELD", "task_id": tid,
                            "age_seconds": round(age, 1), "threshold": STALE_SEC}
            else:
                decision = {"kind": "TAKEOVER", "task_id": tid, "age_seconds": round(age, 1)}
            break

    # ---- 2) 没有现存任务 → IDLE：扫描候选动作池 ----
    if decision is None:
        for c in P.CANDIDATES:
            cap, unknown, local = P.classify(c["needs"])
            if unknown:
                skips.append({"id": c["id"], "skip": "BLOCKED_LOCAL_UNKNOWN",
                              "reason": "needs %s not proven cloud-reachable (treated LOCAL_ONLY)" % unknown})
                continue
            needs_str = ", ".join(c["needs"])
            if c.get("gate") or cap != "CLOUD_READY":
                skips.append({"id": c["id"], "skip": "BLOCKED_GATE" if c.get("gate") else "BLOCKED_LOCAL",
                              "reason": "needs=%s -> %s" % (needs_str, cap), "value": c["real_value"]})
                continue
            aok, areason = P.auth_check(c["auth_ref"], c["scope_slug"])
            if not aok:
                skips.append({"id": c["id"], "skip": "BLOCKED_GATE", "reason": areason}); continue
            fn = CAND_REQUIRES.get(c["id"])
            ready, why = (fn(store, {"tasks": tasks}) if fn else (False, "no require fn"))
            skips.append({"id": c["id"], "skip": "NOT_READY" if not ready else "SELECTED", "reason": why})
            if ready:
                decision = {"kind": "NEW_TASK", "candidate": c["id"], "task_id": c["task_id"],
                            "why": why, "auth_ref": c["auth_ref"], "capability": cap,
                            "reach_evidence": P.reach_evidence(c["needs"])}
                break
        if decision is None:
            decision = {"kind": "GENUINE_IDLE",
                        "reason": "no CLOUD_READY+authorized+gated-clear candidate is actionable; "
                                  "refuse to fabricate busywork"}

    log("DECISION:", json.dumps(decision, ensure_ascii=False, indent=2)[:900])
    for s in skips:
        log("SKIP:", json.dumps(s, ensure_ascii=False)[:240])

    # ---- 3) 执行：一轮只做一件事 ----
    if decision["kind"] == "TAKEOVER":
        log("taking over via verified cloud_executor.py (first leg) ...")
        p = subprocess.run([sys.executable, ".wb1/nezha/cloud_executor.py"],
                           capture_output=True, text=True, env=dict(os.environ))
        for line in (p.stdout or "").splitlines():
            log("  CE|", line.strip()[:200])
        for line in (p.stderr or "").splitlines()[-5:]:
            log("  CE-err|", line.strip()[:200])
        out = {"cloud_executor_returncode": p.returncode}
        tid = decision["task_id"]
        st, _, _, _ = TaskState(store, ".wb1/nezha/task_state.json" if tid == "TASK-REAL-001"
                                else ".wb1/nezha/task_state_%s.json" % tid).load()
        out["after"] = {"owner": st.get("owner"), "epoch": st.get("epoch"),
                        "checkpoint": st.get("checkpoint"), "state": st.get("state"),
                        "result": st.get("result")} if st else None
    elif decision["kind"] == "RUNNING_CLOUD":
        tid = decision["task_id"]
        path = ".wb1/nezha/task_state_%s.json" % tid
        st, _, _, _ = TaskState(store, path).load()
        if tid == "TASK-REAL-002":
            out = run_reverify(store, tid)          # 续做未完成的第二棒
        else:
            out = {"ok": False, "error": "NO_CONTINUE_HANDLER", "task_id": tid}
    elif decision["kind"] == "NEW_TASK" and decision["task_id"] == "TASK-REAL-002":
        out = run_reverify(store, "TASK-REAL-002")
    else:
        out = {"acted": False}

    # ---- 4) heartbeat：round_seq 单调递增 = "下一轮真的自己发生了"的证据 ----
    hb = {"round_seq": seq, "round_at": now_iso(), "actor": ACTOR,
          "runner": os.uname().nodename[:24],
          "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
          "decision": decision, "skips": skips, "out": out}
    c = store.commit_files({HEARTBEAT_PATH: json.dumps(hb, ensure_ascii=False, indent=2).encode()},
                           "[NEZHA] loop beat #%d %s" % (seq, decision["kind"]))
    hb["heartbeat_commit"] = c.get("commit")
    log("HEARTBEAT seq=%s commit=%s" % (seq, c.get("commit")))
    print(json.dumps(hb, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
