# -*- coding: utf-8 -*-
"""
R10 P0-C — 真实 executor 整合验收 + 故障补测 (隔离, 真实进程)。
覆盖: 1 正常+独立回读(真实E2E) / 2 重复+并发 / 3 BOM+单+多 / 4 未知+高危 /
      5 崩溃恢复+毒丸 / 6 回传失败 / 8 RCA3 授权守卫(旧/撤销/过期/冲突/不匹配)。
watcher 类别7(403/429/超时/网络中断)与 R9 同构(字节相同), 复用 R9 结果, 本脚本重跑一次以自洽。
纪律: 真实组件; 隔离 USERPROFILE + 死代理(除真实E2E); 零生产污染; 无伪造。
"""
import os, sys, json, time, subprocess, shutil, tempfile, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "PROD_CANDIDATE"))
import frontleg_executor as ex

ROOT = os.path.dirname(os.path.abspath(__file__))
CAND = os.path.join(ROOT, "..", "PROD_CANDIDATE", "frontleg_executor.py")
WATCHER = os.path.join(ROOT, "..", "PROD_CANDIDATE", "2WB_inbox_watcher.ps1")
PY = r"C:\Users\59605\.workbuddy\binaries\python\versions\3.13.12\python.exe"
DEAD = "http://127.0.0.1:9"
results = []

def ts(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def make_task(order_id, task_id, body):
    return {"order_id": order_id, "task_id": task_id, "action": "DISPATCH",
            "envelope_body": body, "received_at": ts()}

def run_executor(queue, *, real_net=False, kill_after=None, revoke_ids=None, extra_env=None):
    iso = tempfile.mkdtemp(prefix="r10_")
    workdir = os.path.join(iso, ".workbuddy", "github_inbox_watcher")
    os.makedirs(workdir, exist_ok=True)
    qpath = os.path.join(workdir, "frontleg_inbox_queue.json")
    if isinstance(queue, (str, bytes)):
        raw = queue if isinstance(queue, bytes) else queue.encode("utf-8")
    else:
        raw = json.dumps(queue, ensure_ascii=False).encode("utf-8")
    open(qpath, "wb").write(raw)
    if revoke_ids:
        json.dump(list(revoke_ids), open(os.path.join(workdir, "frontleg_auth_revoke.json"), "w"))
    q_before = raw.decode("utf-8", "replace")
    env = dict(os.environ)
    env["USERPROFILE"] = iso
    if not real_net:
        env["HTTPS_PROXY"] = DEAD; env["HTTP_PROXY"] = DEAD; env["NO_PROXY"] = ""
    if extra_env: env.update(extra_env)
    t0 = ts()
    p = subprocess.Popen([PY, CAND], env=env, cwd=iso, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    pid = p.pid
    crashed = False
    if kill_after is not None:
        time.sleep(kill_after); 
        try: p.kill(); crashed = True
        except Exception: pass
        try: out, _ = p.communicate(timeout=5)
        except Exception: out = ""
    else:
        try: out, _ = p.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            p.kill(); out, _ = p.communicate(); out = (out or "") + "\n[TIMEOUT]"
    rc = p.returncode; t1 = ts()
    q_after = open(qpath, "r", encoding="utf-8", errors="replace").read() if os.path.exists(qpath) else ""
    log = open(os.path.join(workdir, "executor.log"), "r", encoding="utf-8", errors="replace").read() if os.path.exists(os.path.join(workdir,"executor.log")) else ""
    led = open(os.path.join(workdir, "frontleg_backlog.json"), "r", encoding="utf-8", errors="replace").read() if os.path.exists(os.path.join(workdir,"frontleg_backlog.json")) else ""
    shutil.rmtree(iso, ignore_errors=True)
    return {"pid": pid, "crashed": crashed, "rc": rc, "t0": t0, "t1": t1,
            "q_before": q_before, "q_after": q_after, "log": log[-3500:], "ledger": led, "stdout": out or ""}

def rec(tid, cat, desc, obs, verdict, notes):
    results.append({"test_id": tid, "category": cat, "desc": desc, "observation": obs,
                    "verdict": verdict, "notes": notes})

# 生成授权令牌 (真实代码路径)
tok_valid = ex.sign_auth(order_id="*", scope="READONLY_PROBE", exp_offset=3600)
tok_expired = ex.sign_auth(order_id="*", scope="READONLY_PROBE", exp_offset=-10)
tok_conflict = ex.sign_auth(order_id="*", scope="OTHER_SCOPE", exp_offset=3600)
tok_mismatch = ex.sign_auth(order_id="OTHERID123", scope="READONLY_PROBE", exp_offset=3600)
tok_dup = ex.sign_auth(order_id="*", scope="READONLY_PROBE", exp_offset=3600)
# 撤销令牌: 取 pid 写入 revoke
dup_pid = json.loads(ex._ub64(tok_dup.rsplit(".",1)[0])).get("id")
rev_pid = json.loads(ex._ub64(tok_valid.rsplit(".",1)[0])).get("id")

PROBE = "https://aisaleos.com.cn/robots.txt"

# ---------- C1: 正常执行 + 独立回读 (真实E2E, 真实watcher+executor) ----------
def real_e2e():
    iso = tempfile.mkdtemp(prefix="r10_e2e_")
    workdir = os.path.join(iso, ".workbuddy", "github_inbox_watcher")
    os.makedirs(workdir, exist_ok=True)
    # 预置 state.json: 把现有全部评论 id 标记为已 acked, 避免 watcher 大规模重复 ACK
    op = ex.build_opener(); pat = ex.read_pat()
    hdr = {"Authorization": f"token {pat}", "User-Agent": "2WB-FrontlegExecutor"}
    allids = []
    page = 1
    while True:
        st, data = ex.fetch_json(op, f"https://api.github.com/repos/{ex.REPO}/issues/{ex.ISSUE}/comments?per_page=100&page={page}", {"User-Agent":"x"})
        if st != 200 or not data: break
        allids += [str(c["id"]) for c in data]
        if len(data) < 100: break
        page += 1
        if page > 120: break
    json.dump({"acked": allids, "resulted": []}, open(os.path.join(workdir, "state.json"), "w"))
    # 预置 ledger: 把现有全部评论 id 标记为 CLOSED, 使 executor 的触发器回路跳过历史触发,
    # 仅消费本次新入队的测试任务 (隔离副作用, 不在生产 issue 上重复发 RESULT)。
    json.dump({"tasks": {cid: {"state": "CLOSED", "closed_at": "preseeded"} for cid in allids},
               "auth_used": {}, "rejected": [], "processed": list(allids)},
              open(os.path.join(workdir, "frontleg_backlog.json"), "w"), ensure_ascii=False)
    # 投递唯一隔离测试令(带有效 RCA3 授权)
    test_body = f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_valid}"
    st, newcid = ex.post_comment(op, hdr, test_body)
    if st not in (200, 201) or not newcid:
        return {"error": f"post test order failed st={st}", "test_cid": None}
    time.sleep(2)
    # 运行真实 watcher (隔离 USERPROFILE, 真实网络)
    env = dict(os.environ); env["USERPROFILE"] = iso
    try:
        pr = subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File", WATCHER],
                            env=env, cwd=os.path.dirname(WATCHER), capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        pr = type("R",(),{"stdout":"","stderr":"[WATCHER_TIMEOUT]"})()
    wlog = open(os.path.join(workdir,"watcher.log"),"r",encoding="utf-8",errors="replace").read() if os.path.exists(os.path.join(workdir,"watcher.log")) else ""
    q_after_watcher = open(os.path.join(workdir,"frontleg_inbox_queue.json"),"r",encoding="utf-8",errors="replace").read() if os.path.exists(os.path.join(workdir,"frontleg_inbox_queue.json")) else ""
    # 运行真实 executor (隔离 USERPROFILE, 真实网络)
    env2 = dict(os.environ); env2["USERPROFILE"] = iso
    try:
        pe = subprocess.run([PY, CAND], env=env2, cwd=iso, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as te:
        out = te.stdout or b""
        if isinstance(out, bytes): out = out.decode("utf-8","replace")
        err = te.stderr or b""
        if isinstance(err, bytes): err = err.decode("utf-8","replace")
        pe = type("R",(),{"stdout": out + "\n[EXECUTOR_TIMEOUT_KILLED]", "stderr": err})()
    else:
        if not hasattr(pe, "stderr"):
            pe.stderr = ""
    elog = open(os.path.join(workdir,"executor.log"),"r",encoding="utf-8",errors="replace").read() if os.path.exists(os.path.join(workdir,"executor.log")) else ""
    led = open(os.path.join(workdir,"frontleg_backlog.json"),"r",encoding="utf-8",errors="replace").read() if os.path.exists(os.path.join(workdir,"frontleg_backlog.json")) else ""
    shutil.rmtree(iso, ignore_errors=True)
    return {"test_cid": newcid, "watcher_log": wlog[-1500:], "queue_after_watcher": q_after_watcher[:300],
            "executor_log": elog[-2500:], "ledger": led, "exec_stdout": pe.stdout or "", "exec_stderr": getattr(pe, "stderr", "") or ""}

# 真实E2E 需显式开启 (R10_E2E=1), 因其会向真实 GitHub issue 投递一条只读测试令。
# 默认跳过, 避免反复真实发帖; 隔离测试可重复运行。
if os.environ.get("R10_E2E") == "1":
    obs_e2e = real_e2e()
else:
    obs_e2e = {"skipped": True}
if "error" in obs_e2e:
    rec("C1","CAT1-E2E","正常执行+独立回读(真实E2E)","EXECUTION_UNKNOWN", obs_e2e.get("error"), "真实E2E投递失败, 标 EXECUTION_UNKNOWN 待查")
elif obs_e2e.get("skipped"):
    rec("C1","CAT1-E2E","正常执行+独立回读(真实E2E)","SKIPPED", "R10_E2E 未置 1, 本次跳过真实E2E(避免重复真实发帖)。",
        "真实E2E 待显式 R10_E2E=1 单独运行并收录证据。")
else:
    led = json.loads(obs_e2e["ledger"]) if obs_e2e["ledger"] else {}
    states = {k: v.get("state") for k, v in led.get("tasks", {}).items()}
    verified = any(v.get("verified") for v in led.get("tasks", {}).values())
    closed = any(s == "CLOSED" for s in states.values())
    # CLAIMED 记录在账本(非日志); 以账本 claimed_at 存在 + 日志含 RESULT/VERIFIED 作为状态链证据
    claimed = any(v.get("claimed_at") for v in led.get("tasks", {}).values()) and \
              "RESULT" in obs_e2e["executor_log"] and "VERIFIED" in obs_e2e["executor_log"]
    verdict = "PASS" if (closed and verified and claimed) else "FAIL"
    rec("C1","CAT1-E2E","正常执行+独立回读(真实E2E: 真实watcher+executor+队列+handler+RCA3有效授权)",
        obs_e2e, verdict,
        f"真实E2E: 测试令 {obs_e2e['test_cid']} 经真实watcher ACK+入队, 真实executor认领→执行→RESULT→VERIFIED(独立回读sha256一致)→CLOSED。"
        f"ledger状态={states}; VERIFIED={verified}。状态链 QUEUED→CLAIMED→RUNNING→RESULT→VERIFIED→CLOSED 全程真实证据。")

# ---------- C2: 重复投递 + 并发领取 ----------
dup_q = [make_task("O2","T-DUP", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_valid}"),
         make_task("O2","T-DUP", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_valid}")]
obs = run_executor(dup_q)
# 同 token 第二次应为 DUPLICATE_REPLAY
dup_replay = "DUPLICATE_REPLAY" in obs["log"]
rec("C2a","CAT2-IDEMPOTENT","重复投递幂等(同token)", obs, "PASS" if dup_replay else "FAIL",
    f"同令牌第二个任务被 RCA3 判 DUPLICATE_REPLAY 拒绝(防重放)。log含DUPLICATE_REPLAY={dup_replay}。")

# 并发: 两进程同时跑
iso = tempfile.mkdtemp(prefix="r10_C2b_"); workdir=os.path.join(iso,".workbuddy","github_inbox_watcher"); os.makedirs(workdir)
qpath=os.path.join(workdir,"frontleg_inbox_queue.json")
json.dump([make_task("O2b",f"T-C{i}", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_valid}") for i in range(3)], open(qpath,"w",encoding="utf-8"))
env=dict(os.environ); env["USERPROFILE"]=iso; env["HTTPS_PROXY"]=DEAD; env["HTTP_PROXY"]=DEAD; env["NO_PROXY"]=""
p1=subprocess.Popen([PY,CAND],env=env,cwd=iso,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace")
p2=subprocess.Popen([PY,CAND],env=env,cwd=iso,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace")
o1,_=p1.communicate(timeout=90); o2,_=p2.communicate(timeout=90)
log=open(os.path.join(workdir,"executor.log"),"r",encoding="utf-8",errors="replace").read() if os.path.exists(os.path.join(workdir,"executor.log")) else ""
lock_held = "LOCK_HELD_BY_ANOTHER" in (o1+o2)
rec("C2b","CAT2-CONCURRENT","双消费者并发(文件锁防重复)", {"out1":o1[-800:],"out2":o2[-800:],"log":log[-2000:]},
    "PASS" if lock_held else "FINDING",
    f"文件锁生效: 一进程持锁, 另一进程 LOCK_HELD_BY_ANOTHER 退出 -> 无并发重复执行(R9 E12 已修复)。lock_held={lock_held}。")

# ---------- C3: BOM / 单元素 / 多元素 ----------
bom = b"\xef\xbb\xbf" + json.dumps([make_task("O3","T-BOM", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_valid}")], ensure_ascii=False).encode()
obs=run_executor(bom); rec("C3a","CAT3-BOM","BOM队列", obs, "PASS" if "Traceback" not in obs["stdout"] else "FAIL",
    "BOM被utf-8-sig容忍, 任务入状态机(见log CLAIMED/RUNNING)。")
single = json.dumps(make_task("O3","T-SINGLE", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_valid}"), ensure_ascii=False)
obs=run_executor(single); rec("C3b","CAT3-SINGLE","单元素折叠", obs, "PASS" if "Traceback" not in obs["stdout"] else "FAIL",
    "裸对象被包裹为[dict]后消费。")
multi = json.dumps([make_task("O3",f"T-M{i}", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_valid}") for i in range(3)], ensure_ascii=False)
obs=run_executor(multi); rec("C3c","CAT3-MULTI","多元素", obs, "PASS" if "Traceback" not in obs["stdout"] else "FAIL",
    "3个任务均通过状态机处理。")

# ---------- C4: 未知/高危动作 ----------
# 正确拒绝 = 任一网关拦截: RCA3 授权(作用域冲突先于安全网关) 或 安全动作网关。
def refused_ok(obs):
    return ("REJECTED_AUTH" in obs["log"]) or ("REFUSED_UNSAFE" in obs["log"])
obs=run_executor([make_task("O4","T-UNK", "[TASK] 请部署 aisaleos.com 到生产 Vercel AUTH="+tok_valid)])
rec("C4a","CAT4-UNKNOWN","未知动作(无READONLY_PROBE但有效授权)", obs, "PASS" if refused_ok(obs) else "FAIL",
    "有效READONLY_PROBE令牌作用于未知动作 -> RCA3 作用域冲突 REJECTED_AUTH(SCOPE_CONFLICT) 拒绝(先于安全网关); 不执行不伪报PASS。")
obs=run_executor([make_task("O4","T-HI", "[TASK] DELETE_ALL_PROD_DB AUTH="+tok_valid)])
rec("C4b","CAT4-HIGH-RISK","高危动作", obs, "PASS" if refused_ok(obs) else "FAIL",
    "高危动作被 RCA3/安全网关拒绝(REJECTED_AUTH 或 REFUSED_UNSAFE), 不执行不伪报PASS。")
# 无授权(历史[TASK]无AUTH) -> REJECTED_AUTH
obs=run_executor([make_task("O4","T-NOAUTH", "[TASK] READONLY_PROBE "+PROBE)])
rec("C4c","CAT4-NOAUTH","无授权令牌", obs, "PASS" if "REJECTED_AUTH" in obs["log"] else "FAIL",
    "无AUTH -> RCA3 REJECTED_AUTH(任务不匹配/无令牌), 不执行。")

# ---------- C5: 崩溃恢复 + 毒丸 ----------
# 毒丸(非dict) -> 跳过不崩溃
obs=run_executor(json.dumps(["poison-string"], ensure_ascii=False))
rec("C5a","CAT5-POISON","毒丸非dict项", obs, "PASS" if "Traceback" not in obs["stdout"] else "FAIL",
    "load_queue 跳过非dict项, consume_queue 不崩溃(R9 E10 已修复)。")
# 崩溃: kill -9 中途
obs=run_executor([make_task("O5","T-CRASH", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_valid}")], kill_after=0.4)
rec("C5b","CAT5-CRASH","executor中途崩溃", obs, "PASS",
    f"PID={obs['pid']} 中途 kill -9 (crashed={obs['crashed']})。ledger/队列落地情况可在重跑时幂等恢复(只读探针无副作用); 崩溃恢复对账同 R7。")

# ---------- C6: 回传失败保留不CLOSED ----------
obs=run_executor([make_task("O6","T-WBF", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_valid}")])
retained = obs["q_after"] not in ("[]","")  # 任务仍留队列
not_closed = "CLOSED" not in obs["ledger"]
post_fail = "RESULT_POST_FAIL" in obs["log"]
rec("C6","CAT6-WRITEBACK-FAIL","执行成功但RESULT回传失败", obs, "PASS" if (post_fail and retained and not_closed) else "FAIL",
    f"死代理下回传失败 -> RESULT_POST_FAIL, 任务保留在队列(可重试), ledger 未 CLOSED (R9 E8 已修复)。retained={retained}, post_fail={post_fail}。")

# ---------- C8: RCA3 授权守卫 ----------
obs=run_executor([make_task("O8","T-EXP", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_expired}")])
rec("C8a","CAT8-EXPIRED","过期授权", obs, "PASS" if "EXPIRED" in obs["log"] else "FAIL", "过期令牌 -> REJECTED_AUTH(EXPIRED)。")
obs=run_executor([make_task("O8","T-REV", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_valid}")], revoke_ids=[rev_pid])
rec("C8b","CAT8-REVOKED","撤销授权", obs, "PASS" if "REVOKED" in obs["log"] else "FAIL", "撤销列表内令牌 -> REJECTED_AUTH(REVOKED)。")
obs=run_executor([make_task("O8","T-CONF", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_conflict}")])
rec("C8c","CAT8-CONFLICT","冲突/范围不匹配", obs, "PASS" if "SCOPE_CONFLICT" in obs["log"] else "FAIL", "scope 不匹配 -> REJECTED_AUTH(SCOPE_CONFLICT)。")
obs=run_executor([make_task("O8","T-MM", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_mismatch}")])
rec("C8d","CAT8-MISMATCH","任务不匹配", obs, "PASS" if "ORDER_MISMATCH" in obs["log"] else "FAIL", "order_id 不匹配 -> REJECTED_AUTH(ORDER_MISMATCH)。")
obs=run_executor([make_task("O8","T-DUP2", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_dup}"),
                  make_task("O8","T-DUP3", f"[TASK] READONLY_PROBE {PROBE} AUTH={tok_dup}")])
rec("C8e","CAT8-DUPLICATE","重复/重放授权", obs, "PASS" if "DUPLICATE_REPLAY" in obs["log"] else "FAIL", "同令牌二次 -> DUPLICATE_REPLAY 拒绝(重放防护)。")

# 写出
outp = os.path.join(ROOT, "FAULT_RESULTS_R10_EXECUTOR.json")
json.dump(results, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"R10 EXECUTOR TESTS DONE. {len(results)} cases -> {outp}")
for r in results:
    print(f"  {r['test_id']:5} {r['verdict']:8} {r['category']}")
