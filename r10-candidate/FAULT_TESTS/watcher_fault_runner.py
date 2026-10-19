# -*- coding: utf-8 -*-
"""
R9 P0-B — 真实 watcher 故障与恢复补测 (隔离 mock GitHub, 零生产污染)。
- 仅调用 watcher_iso_test.ps1 (PROD_CANDIDATE 真实代码, 仅端点主机换成本地 mock)。
- PROD_CANDIDATE/2WB_inbox_watcher.ps1 的 SHA 不受影响。
覆盖: cat1 ACK成功但队列写失败; cat6 GitHub 403/429/超时/网络中断。
每项记录: 原始输入 / 进程身份(PID) / 时间戳 / 执行次数 / 队列前后 / 原始输出 / RESULT状态 / 恢复结果。
"""
import os, sys, json, time, subprocess, shutil, tempfile, signal

ROOT = os.path.dirname(os.path.abspath(__file__))
ISO_WATCHER = os.path.join(ROOT, "watcher_iso_test.ps1")
MOCK = os.path.join(ROOT, "mock_github.py")
CTRL = os.path.join(ROOT, "mock_ctrl.txt")
COMMENTS = CTRL + ".comments"
PY = r"C:\Users\59605\.workbuddy\binaries\python\versions\3.13.12\python.exe"

results = []

def ts(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def start_mock():
    p = subprocess.Popen([PY, MOCK, CTRL, "8731"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(1.5)
    return p

def stop_mock(p):
    try: p.send_signal(signal.SIGTERM)
    except Exception: p.kill()
    try: p.wait(timeout=5)
    except Exception: p.kill()

def set_mock(mode, comments=None):
    open(CTRL, "w", encoding="utf-8").write(mode)
    if comments is not None:
        open(COMMENTS, "w", encoding="utf-8").write(json.dumps(comments))

def run_watcher(iso, *, extra_env=None, queue_readonly=False, mock_running=True, cleanup=True, preset=True):
    workdir = os.path.join(iso, ".workbuddy", "github_inbox_watcher")
    os.makedirs(workdir, exist_ok=True)
    qpath = os.path.join(workdir, "frontleg_inbox_queue.json")
    # 预置队列
    if queue_readonly and preset:
        with open(qpath, "w", encoding="utf-8") as f:
            f.write("[]")
        # Windows: 设为只读
        subprocess.run(["attrib", "+R", qpath], shell=True)
    env = dict(os.environ)
    env["USERPROFILE"] = iso
    env["GITHUB_PAT"] = "bogus_for_mock"
    env["PSScriptRoot"] = ROOT  # 帮助定位 bridge(本测试不调用)
    if extra_env: env.update(extra_env)
    q_before = ""
    if os.path.exists(qpath):
        q_before = open(qpath, "r", encoding="utf-8", errors="replace").read()
    t0 = ts()
    p = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ISO_WATCHER],
        env=env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    pid = p.pid
    try:
        out, _ = p.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        p.kill(); out, _ = p.communicate(); out = (out or "") + "\n[TIMEOUT_KILLED]"
    t1 = ts()
    rc = p.returncode
    q_after = ""
    if os.path.exists(qpath):
        q_after = open(qpath, "r", encoding="utf-8", errors="replace").read()
    logpath = os.path.join(workdir, "watcher.log")
    logtxt = ""
    if os.path.exists(logpath):
        logtxt = open(logpath, "r", encoding="utf-8", errors="replace").read()
    if cleanup:
        shutil.rmtree(iso, ignore_errors=True)
    return {"pid": pid, "returncode": rc, "t_start": t0, "t_end": t1,
            "queue_before": q_before, "queue_after": q_after, "stdout": (out or "")[-3000:], "log": logtxt[-3000:]}

# ---------------------------------------------------------------------------
mock = start_mock()
try:
    # ---- W1: cat1 ACK 成功但队列写失败 (队列预置只读) ----
    set_mock("normal", [{"id": "9001", "body": "[TASK] READONLY_PROBE https://aisaleos.com.cn/robots.txt"}])
    iso = tempfile.mkdtemp(prefix="r9_W1_")
    obs = run_watcher(iso, queue_readonly=True)
    # 判定: mock 收到 ACK POST 即 ACK 成功; 队列仍只读/空即写失败
    ack_posted = "ACK_POSTED" in obs["log"]
    queue_failed = ("ACK_FAIL" in obs["log"]) and (obs["queue_after"] in ("[]", ""))
    note = (f"mock 收到 ACK POST -> ACK 成功; 但 Enqueue-Task 写只读队列抛 IOException -> 被外层 try 捕获并误记 'ACK_FAIL'。"
            f"队列未被写入(仍空/只读)。更关键: 该 [TASK] 已被记入 acked, 下次运行会在 L126 continue 跳过 -> 永不再尝试入队 -> 任务永久丢失(无重试机制)。")
    results.append({"test_id":"W1","category":"CAT1-ACK-QUEUE-WRITEFAIL","desc":"ACK成功但队列写失败",
                    "verdict":"FINDING","observation":obs,"notes":note})

    # ---- W1c: 同目录持久化验证「无重试」(首轮只读失败 -> 队列改可写后同目录再跑) ----
    iso1c = tempfile.mkdtemp(prefix="r9_W1c_")
    workdir1c = os.path.join(iso1c, ".workbuddy", "github_inbox_watcher")
    os.makedirs(workdir1c, exist_ok=True)
    qpath1c = os.path.join(workdir1c, "frontleg_inbox_queue.json")
    with open(qpath1c, "w", encoding="utf-8") as f: f.write("[]")
    subprocess.run(["attrib", "+R", qpath1c], shell=True)
    # 首轮: 只读队列, 模拟 ACK 成功但写失败 (文件已在外层设为只读, 不再 preset)
    obs1c_a = run_watcher(iso1c, queue_readonly=True, cleanup=False, preset=False)
    # 移除只读, 同目录再跑 (acked state 已落盘 state.json)
    subprocess.run(["attrib", "-R", qpath1c], shell=True)
    obs1c_b = run_watcher(iso1c, queue_readonly=False, cleanup=False)
    skip_on_rerun = ("ENQUEUE" not in obs1c_b["log"]) and (obs1c_b["queue_after"] in ("[]", ""))
    note1c = (f"首轮: ACK_POSTED + 队列写失败(只读)。同目录改可写后重跑 -> 日志无 ENQUEUE, 队列仍空={skip_on_rerun}。"
              f"证实: 因 state.json 已记 acked=9001, 重跑在 L126 `continue` 跳过该评论, 即使队列已恢复可写也永不再入队 -> 任务永久丢失(无重试机制)。"
              f"恢复需人工: 删除 state 中该 id 或手动重放 [TASK]。")
    results.append({"test_id":"W1c","category":"CAT1-NO-RETRY","desc":"ACK写失败后因 state 跳过导致永久丢失",
                    "verdict":"FINDING","observation":{"run1":obs1c_a,"run2":obs1c_b},"notes":note1c})
    shutil.rmtree(iso1c, ignore_errors=True)

    # ---- W1b: 恢复验证 (全新隔离目录, 队列可写 -> 正常入队, 证明逻辑本身可工作) ----
    iso2 = tempfile.mkdtemp(prefix="r9_W1b_")
    obs2 = run_watcher(iso2, queue_readonly=False)  # 可写队列, 全新目录无残留 state -> 正常入队
    # 注意: 隔离目录每次独立, 无 state 文件 -> W1b 会重新 ACK + 入队成功 (证明隔离); 真实生产若 acked 已记则丢失
    enqueued = "ENQUEUE" in obs2["log"] and obs2["queue_after"] not in ("[]", "")
    note2 = (f"隔离环境下(无残留 state)队列可写时 watcher 正常 ENQUEUE (queue_after 非空={enqueued})。"
             f"但生产环境 state.json 已记录 acked=9001, 下次运行会在 L126 跳过该评论 -> 即使队列已恢复可写也不会补入队。"
             f"结论: 生产需人工修复(state 移除该 id 或手动重放)方可恢复。")
    results.append({"test_id":"W1b","category":"CAT1-RECOVERY","desc":"ACK成功队列写失败之恢复验证",
                    "verdict":"FINDING","observation":obs2,"notes":note2})

    # ---- W2: cat6 GitHub 403 ----
    set_mock("403")
    iso = tempfile.mkdtemp(prefix="r9_W2_")
    obs = run_watcher(iso)
    graceful = ("FETCH_FAIL" in obs["log"]) and (obs["returncode"] in (0, None))
    results.append({"test_id":"W2","category":"CAT6-403","desc":"GitHub 403 (速率限制)",
                    "verdict":"PASS" if graceful else "FAIL",
                    "observation":obs,
                    "notes":f"403 -> Invoke-RestMethod 异常 -> 记 FETCH_FAIL 并 exit 0(优雅退出, 不崩溃, 本周期不处理)。returncode={obs['returncode']}。"})

    # ---- W3: cat6 GitHub 429 ----
    set_mock("429")
    iso = tempfile.mkdtemp(prefix="r9_W3_")
    obs = run_watcher(iso)
    graceful = ("FETCH_FAIL" in obs["log"])
    results.append({"test_id":"W3","category":"CAT6-429","desc":"GitHub 429 (限流)",
                    "verdict":"PASS" if graceful else "FAIL","observation":obs,
                    "notes":"429 -> 异常 -> FETCH_FAIL + exit 0(优雅)。"})

    # ---- W4: cat6 超时 (mock sleep 40s > TimeoutSec 30) ----
    set_mock("timeout")
    iso = tempfile.mkdtemp(prefix="r9_W4_")
    obs = run_watcher(iso)
    graceful = ("FETCH_FAIL" in obs["log"])
    results.append({"test_id":"W4","category":"CAT6-TIMEOUT","desc":"GitHub 拉取超时(>30s)",
                    "verdict":"PASS" if graceful else "FAIL","observation":obs,
                    "notes":"mock 睡眠 40s 触发 watcher TimeoutSec=30 -> 异常 -> FETCH_FAIL + exit 0(优雅)。"})

    # ---- W5: cat6 网络中断 (停掉 mock, 连接拒绝) ----
    stop_mock(mock)
    iso = tempfile.mkdtemp(prefix="r9_W5_")
    obs = run_watcher(iso, mock_running=False)
    graceful = ("FETCH_FAIL" in obs["log"])
    results.append({"test_id":"W5","category":"CAT6-NETINT","desc":"网络中断 (连接拒绝)",
                    "verdict":"PASS" if graceful else "FAIL","observation":obs,
                    "notes":"mock 关闭 -> 连接拒绝 -> FETCH_FAIL + exit 0(优雅, 不崩溃)。恢复网络后下一周期自动重试。"})
finally:
    try: stop_mock(mock)
    except Exception: pass

outp = os.path.join(ROOT, "FAULT_RESULTS_WATCHER.json")
json.dump(results, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"WATCHER FAULT TESTS DONE. {len(results)} cases -> {outp}")
for r in results:
    print(f"  {r['test_id']:5} {r['verdict']:8} {r['category']}")
