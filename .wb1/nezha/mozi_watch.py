# -*- coding: utf-8 -*-
"""墨子 · 云端 WATCH ONLY（V0.1）

只做：看、记、判。
不做：自动业务恢复、抢任务、创建任务、调度哪吒、改业务状态。

判定：ALIVE / STALLED / OFFLINE（依据 last_progress_at）；
产出：观察记录文件 `.wb1/nezha/observations/<ts>.json`（墨子自己的最小运行状态，非业务资产）。
墨子重启后仍能恢复观察 —— 因为观察对象（TASK STATE）在仓库里，不在墨子内存里。
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from task_state import GitHubStore, TaskState, now_iso  # noqa: E402

TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("MOZI_GH_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY", "kongsonren/aisaleos-handoff-poc")
ALIVE_SEC = int(os.environ.get("MOZI_ALIVE_SEC", "120"))
STALLED_SEC = int(os.environ.get("MOZI_STALLED_SEC", "300"))
OBS_DIR = ".wb1/nezha/observations"


def log(*a):
    print("[MOZI]", *a, flush=True)


def main():
    if not TOKEN:
        log("FATAL: no token"); return 2
    store = GitHubStore(TOKEN, REPO)
    ts = TaskState(store)
    st, sha, head, code = ts.load()
    if st is None:
        log("no task state yet (code=%s)" % code); return 3

    lp = st.get("last_progress_at")
    try:
        age = (datetime.now(timezone(timedelta(hours=8))) - datetime.fromisoformat(lp)).total_seconds()
    except Exception:
        age = None

    if age is None:
        health = "UNKNOWN"
    elif age <= ALIVE_SEC:
        health = "ALIVE"
    elif age <= STALLED_SEC:
        health = "STALLED"
    else:
        health = "OFFLINE"

    obs = {
        "observer": "MOZI",
        "mode": "WATCH_ONLY",
        "observed_at": now_iso(),
        "task_id": st.get("task_id"),
        "owner": st.get("owner"),
        "epoch": st.get("epoch"),
        "checkpoint": st.get("checkpoint"),
        "state": st.get("state"),
        "next_expected": st.get("next_expected"),
        "result_present": st.get("result") is not None,
        "last_progress_at": lp,
        "age_seconds": None if age is None else int(age),
        "health": health,
        "thresholds": {"alive": ALIVE_SEC, "stalled": STALLED_SEC},
        "note": "墨子只观察记录，不下达任何指令、不创建任务。",
    }
    log(json.dumps(obs, ensure_ascii=False))

    path = "%s/%s.json" % (OBS_DIR, now_iso().replace(":", "-").split(".")[0])
    c = store.commit_files({path: json.dumps(obs, ensure_ascii=False, indent=2).encode()},
                           "[MOZI] observation %s" % obs["observed_at"])
    log("observation commit:", c.get("ok"), c.get("commit", c.get("error")))
    return 0 if c.get("ok") else 4


if __name__ == "__main__":
    sys.exit(main())
