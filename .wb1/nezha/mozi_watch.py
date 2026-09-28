# -*- coding: utf-8 -*-
"""墨子 · 云端 WATCH ONLY（V0.1）

只做：看、记、判。
不做：自动业务恢复、抢任务、创建任务、调度哪吒、改业务状态。

判定：ALIVE / STALLED / OFFLINE（依据 last_progress_at）；
产出：观察记录文件 `.wb1/nezha/observations/<ts>.json`（墨子自己的最小运行状态，非业务资产）。
墨子重启后仍能恢复观察 —— 因为观察对象（TASK STATE）在仓库里，不在墨子内存里。
"""
from __future__ import annotations
import json, os, sys, time
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


def wait_and_schedule():
    """⑥ 独立故障域：墨子**自己**起拍下一拍（不依赖哪吒链）。

    验收口径（KR）：哪吒执行链死掉以后，墨子还能不能独立发现。
    所以墨子必须有**自己的**起搏链、自己的 concurrency 组、自己的 workflow 文件：
    哪吒链断 ≠ 墨子停。节拍默认 30 分钟（成本约 48 拍/日 ≈ 34 分钟/日）。
    """
    beat = int(os.environ.get("MOZI_BEAT_MIN", "30"))
    maxb = int(os.environ.get("MOZI_MAX_BEATS", "120"))
    store = GitHubStore(TOKEN, REPO)
    marker, _, _, _ = store.read_json(".wb1/nezha/mozi_beat.json", default={})
    seq = int((marker or {}).get("seq", 0))
    if seq >= maxb:
        log("MOZI_MAX_BEATS=%d reached; independent chain stops here" % maxb)
        return 0
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    add = beat - (now.minute % beat)
    nxt = now + timedelta(minutes=add)
    sleep_s = (nxt - datetime.now(timezone.utc)).total_seconds() + 5
    log("sleep %.0fs until next mozi beat %s (seq=%d)" % (max(sleep_s, 0), nxt.isoformat(), seq))
    if sleep_s > 0:
        time.sleep(sleep_s)
    store.commit_files({".wb1/nezha/mozi_beat.json": json.dumps(
        {"seq": seq + 1, "last_dispatch_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "beat_min": beat, "note": "MOZI independent self-schedule marker"},
        ensure_ascii=False, indent=2).encode()}, "[MOZI] beat marker seq=%d" % (seq + 1))
    s, d = store._req("POST", "/repos/%s/actions/workflows/mozi-auto.yml/dispatches" % REPO, {"ref": "main"})
    log("self-scheduled next mozi beat -> HTTP %s (seq was %d)" % (s, seq))
    print(json.dumps({"mozi_self_scheduled": s in (204, 201, 200), "http": s, "detail": str(d)[:160]},
                     ensure_ascii=False))
    return 0


def main():
    if not TOKEN:
        log("FATAL: no token"); return 2
    if "--wait-and-schedule" in sys.argv:
        if os.environ.get("MOZI_SELF_SCHEDULE") != "1":
            log("mozi self-schedule disabled"); return 0
        return wait_and_schedule()
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
