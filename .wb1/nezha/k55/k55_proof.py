# -*- coding: utf-8 -*-
"""K55 隔离云验证 · 双轮闭环（非生产 / 分支隔离 / K55-* 命名空间）

运行环境：GitHub Actions ubuntu-latest（脱离本地 1WB 黑武士 / 2WB 华硕）。
三角色分离（由 k55-cloud-proof.yml 的三个 job 分别在不同 runner 上执行）：
  prep  -> 1WB云端：接令 + READONLY_SHA256(仓库内目标) + 派令给2WB + 记 ledger
  exec  -> 2WB云端：读派令 + 真实重算 SHA + 回 RESULT（不模拟）
  close -> 1WB云端：读 RESULT + 核验 + 持久 CLOSED + 写验收证据

纪律：
  · 仅用 secrets.GITHUB_TOKEN（内置，不落本地/不进仓库）
  · 仅读写分支 k55-proof 上的 K55-* 文件，绝不碰 main 上的 live 8051 循环
  · 状态读写经 GitHubStore（CAS + 分支隔离）
  · CLOUD_READY 证明：双轮闭环在云端真实跑通；OFFLINE_PASS 仍需 KR 物理关机（见 evidence.note）
"""
from __future__ import annotations
import base64, hashlib, json, os, sys, time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from task_state import GitHubStore, now_iso  # noqa: E402

CN = timezone(timedelta(hours=8))
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("MOZI_GH_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY", "kongsonren/aisaleos-handoff-poc")
BRANCH = os.environ.get("K55_BRANCH", "k55-proof")
LEDGER = ".wb1/nezha/k55/k55_ledger.json"
EVIDENCE = ".wb1/nezha/k55/k55_proof_evidence.json"
TARGET = ".wb1/nezha/k55/k55_test_target.dat"
ORDER_ID = os.environ.get("K55_ORDER_ID", "KR-NEZHA-CLOUD-K55-20261019-PROOF")
TASK_ID = "K55-PROOF-2WB-001"


def log(*a):
    print("[K55]", *a, flush=True)


def sha256_file(store, path):
    b, sha, head, code = store.read_file(path)
    if b is None:
        return None, code
    return hashlib.sha256(b).hexdigest(), code


def read_ledger(store):
    d, _, _, _ = store.read_json(LEDGER, default={"tasks": {}, "order": {}})
    return d or {"tasks": {}, "order": {}}


def write_ledger(store, data, msg):
    return store.commit_files({LEDGER: json.dumps(data, ensure_ascii=False, indent=2).encode()}, msg)


# ============================ 1WB 云端：接令 + 派令 ============================
def role_1wb_prep():
    store = GitHubStore(TOKEN, REPO, BRANCH)
    if not TOKEN:
        log("FATAL no token"); return 2
    # 真实只读动作：READONLY_SHA256（仓库内目标，非业务数据）
    h, code = sha256_file(store, TARGET)
    if h is None:
        log("FATAL cannot read target", code); return 2
    log("1WB READONLY_SHA256(%s) = %s" % (TARGET, h[:16]))

    led = read_ledger(store)
    led["tasks"][TASK_ID] = {
        "order_id": ORDER_ID, "role": "2WB", "state": "DISPATCHED",
        "assigned_to": "CLOUD_2WB", "target": TARGET, "expected_sha256": h,
        "dispatched_by": "CLOUD_1WB", "dispatched_at": now_iso(),
    }
    led["order"] = {"id": ORDER_ID, "state": "1WB_PREP_DONE",
                    "target_sha16": h[:16], "prepared_at": now_iso()}
    r = write_ledger(store, led, "[K55-1WB] dispatch %s to 2WB (expected_sha=%s)" % (TASK_ID, h[:16]))
    log("ledger:", json.dumps({k: r.get(k) for k in ("ok", "commit", "error")}, ensure_ascii=False))
    print(json.dumps({"role": "1WB_PREP", "target_sha16": h[:16], "dispatched": TASK_ID,
                      "commit": r.get("commit")}, ensure_ascii=False))
    return 0 if r.get("ok") else 1


# ============================ 2WB 云端：真实执行 + 回 RESULT ============================
def role_2wb_exec():
    store = GitHubStore(TOKEN, REPO, BRANCH)
    if not TOKEN:
        log("FATAL no token"); return 2
    led = read_ledger(store)
    t = led["tasks"].get(TASK_ID)
    if not t or t.get("state") != "DISPATCHED":
        log("no DISPATCHED task (state=%s)" % (t or {}).get("state")); return 3
    # 真实执行：在本 runner 上重算 SHA（不是 1WB 给的值，是独立重算）
    h, code = sha256_file(store, t["target"])
    if h is None:
        log("FATAL 2WB cannot read target", code); return 4
    ok = (h == t["expected_sha256"])
    cid = "K55-2WB-%s" % hashlib.sha256((TASK_ID + h + str(ok) + now_iso()).encode()).hexdigest()[:12]
    t["state"] = "EXECUTED"
    t["result"] = {"status": "PASS" if ok else "FAIL", "computed_sha256": h,
                   "match": bool(ok), "executed_by": "CLOUD_2WB",
                   "completion_id": cid, "executed_at": now_iso()}
    t["result_written_by"] = "CLOUD_2WB"
    r = write_ledger(store, led, "[K55-2WB] executed %s -> %s" % (TASK_ID, "PASS" if ok else "FAIL"))
    log("RESULT:", json.dumps(t["result"], ensure_ascii=False))
    print(json.dumps({"role": "2WB_EXEC", "status": t["result"]["status"], "completion_id": cid}, ensure_ascii=False))
    return 0 if r.get("ok") else 1


# ============================ 1WB 云端：核验 + 持久 CLOSED ============================
def role_1wb_close():
    store = GitHubStore(TOKEN, REPO, BRANCH)
    if not TOKEN:
        log("FATAL no token"); return 2
    led = read_ledger(store)
    t = led["tasks"].get(TASK_ID)
    if not t or t.get("state") != "EXECUTED" or not t.get("result"):
        log("no executed result (state=%s)" % (t or {}).get("state")); return 5
    res = t["result"]
    verified = (res.get("computed_sha256") == t.get("expected_sha256")
                and res.get("match") is True
                and res.get("executed_by") == "CLOUD_2WB"
                and bool(res.get("completion_id")))
    t["state"] = "CLOSED" if verified else "VERIFY_FAILED"
    led["order"]["state"] = "CLOSED" if verified else "VERIFY_FAILED"
    evidence = {
        "order_id": ORDER_ID,
        "verdict": "CLOSED" if verified else "VERIFY_FAILED",
        "tier": "CLOUD_READY",   # 明确：尚未证明真实关机，不得报 OFFLINE_PASS
        "target": TARGET,
        "expected_sha256": t["expected_sha256"],
        "computed_sha256": res["computed_sha256"],
        "match": bool(res["match"]),
        "executed_by": res["executed_by"],
        "completion_id": res["completion_id"],
        "closed_at": now_iso(),
        "dual_wheel": {
            "wb1_cloud": "接令 + READONLY_SHA256 + 派令(ledger) + 核验 + CLOSED",
            "wb2_cloud": "读派令 + 真实重算SHA + 回RESULT(独立runner)",
            "mozi": "WATCH ONLY（本验证未改动 MOZI，复用其既有双链）",
        },
        "note": "CLOUD_READY 证明：双轮闭环在云端 ubuntu-latest 经 GITHUB_TOKEN 真实跑通（三 job 三 runner）。"
                "OFFLINE_PASS 仍需 KR 物理关闭 1WB(黑武士) 与 2WB(华硕) 后，由云端自起拍链独立完成同款闭环。",
    }
    files = {
        LEDGER: json.dumps(led, ensure_ascii=False, indent=2).encode(),
        EVIDENCE: json.dumps(evidence, ensure_ascii=False, indent=2).encode(),
    }
    r = store.commit_files(files, "[K55-1WB] CLOSED %s verdict=%s" % (TASK_ID, evidence["verdict"]))
    log("CLOSED:", json.dumps(evidence, ensure_ascii=False)[:500])
    print(json.dumps(evidence, ensure_ascii=False))
    return 0 if verified else 6


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prep"
    sys.exit({"prep": role_1wb_prep, "exec": role_2wb_exec, "close": role_1wb_close}.get(cmd, role_1wb_prep)())
