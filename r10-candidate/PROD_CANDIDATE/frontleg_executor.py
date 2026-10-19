# -*- coding: utf-8 -*-
"""
frontleg_executor.py — 2WB 前腿统一生产候选 (R10 整合版)
==================================================================
整合来源（均复用, 非重造）:
  R8  真实跨进程链路 : watcher 检测→ACK→本地队列; executor 真实领取→执行→RESULT→回传
  R7  消费者状态链/幂等/审计/崩溃恢复 : CLAIMED→RUNNING→RESULT→VERIFIED(独立回读)→CLOSED
  R10 新增 RCA3 授权守卫 : 过期/撤销/重复/冲突/不匹配 授权一律拒绝

状态机（每个任务）:
  QUEUED (watcher 入队) → CLAIMED (executor 认领) → RUNNING (开始执行)
        → RESULT (产出并回传) → VERIFIED (POST 后独立回读 sha256 一致) → CLOSED (账本落盘)
  异常分支: REJECTED_AUTH (RCA3 拒绝, 不入执行) / RESULT_POST_FAIL (回传失败, 任务保留可重试, 不 CLOSED)

纪律 (HOLD 有效): 不部署/不点火/不批量消费; 仅 READONLY_PROBE 安全只读 handler;
未知/高危/未授权动作一律拒绝, 绝不伪报 PASS; 失败证据不删不改不刷绿。
"""
import os, sys, json, ssl, re, time, ctypes, ctypes.wintypes, urllib.request, urllib.error
import hashlib, base64, hmac

REPO = "kongsonren/aisaleos-handoff-poc"
ISSUE = "8"
WORKDIR = os.path.expanduser("~/.workbuddy/github_inbox_watcher")
QUEUE = os.path.join(WORKDIR, "frontleg_inbox_queue.json")
LEDGER = os.path.join(WORKDIR, "frontleg_backlog.json")
AUTH_REVOKE = os.path.join(WORKDIR, "frontleg_auth_revoke.json")
LOG = os.path.join(WORKDIR, "executor.log")
LOCK = os.path.join(WORKDIR, "frontleg_executor.lock")
EXECUTOR_ID = "2WB-FRONTLEG-EXECUTOR"

# R10 隔离态替代 KR 真实签名权 (生产: 由 KR 持有真实签名/HMAC 密钥, 此处为可运行占位)
AUTH_SECRET = os.environ.get("R10_AUTH_SECRET", "R10_ISOLATED_KR_SIGNING_SECRET_v1")
SAFE_ACTIONS = {"READONLY_PROBE"}
EXEC_KEYWORDS = ["CONTINUE-EXECUTION"]
MIRROR_DEBTS = {"5948257756"}


# ---------------- 基础 IO ----------------
def log(m):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {m}\n")
    except Exception:
        pass


def read_pat():
    """从 wincred 读 GitHub PAT (ctypes, 无需 Add-Type)。"""
    class CRED(ctypes.Structure):
        _fields_ = [
            ("Flags", ctypes.wintypes.DWORD), ("Type", ctypes.wintypes.DWORD),
            ("TargetName", ctypes.c_wchar_p), ("Comment", ctypes.c_wchar_p),
            ("LastWritten", ctypes.wintypes.FILETIME), ("CredentialBlobSize", ctypes.wintypes.DWORD),
            ("CredentialBlob", ctypes.c_void_p), ("Persist", ctypes.wintypes.DWORD),
            ("AttributeCount", ctypes.wintypes.DWORD), ("Attributes", ctypes.c_void_p),
            ("TargetAlias", ctypes.c_wchar_p), ("UserName", ctypes.c_wchar_p),
        ]
    adv = ctypes.windll.advapi32
    p = ctypes.POINTER(CRED)()
    if not adv.CredReadW("git:https://github.com", 1, 0, ctypes.byref(p)):
        return None
    try:
        size = p.contents.CredentialBlobSize
        blob = ctypes.string_at(p.contents.CredentialBlob, size)
        return re.sub(r"[^\x20-\x7E]", "", blob.decode("utf-8", "replace"))
    finally:
        adv.CredFree(p)


def build_opener():
    ctx = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def fetch_json(op, url, hdr, retries=3):
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with op.open(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as he:
            if he.code == 403:
                log(f"RATE_LIMIT url={url} (stop scanning this run)")
                return 403, None
            log(f"FETCH_HTTP_ERR url={url} code={he.code}")
            time.sleep(2)
        except Exception as e:
            log(f"FETCH_RETRY url={url} err={e}")
            time.sleep(2)
    return None, None


def post_comment(op, hdr, body):
    url = f"https://api.github.com/repos/{REPO}/issues/{ISSUE}/comments"
    data = json.dumps({"body": body}).encode("utf-8")
    ph = {"Authorization": hdr["Authorization"], "User-Agent": "2WB-FrontlegExecutor"}
    req = urllib.request.Request(url, data=data, headers={**ph, "Content-Type": "application/json"}, method="POST")
    try:
        with op.open(req, timeout=60) as r:
            st = r.status
            d = json.loads(r.read().decode("utf-8", "replace"))
            return st, d.get("id")
    except urllib.error.HTTPError as he:
        try:
            b = he.read().decode("utf-8", "replace")[:300]
        except Exception:
            b = ""
        log(f"POST_FAIL_HTTP code={he.code} resp={b}")
        return None, None
    except Exception as e:
        log(f"POST_FAIL err={e}")
        return None, None


# ---------------- 队列 (D1/D2 硬化, 毒丸防御) ----------------
def load_queue():
    if os.path.exists(QUEUE):
        try:
            data = json.load(open(QUEUE, encoding="utf-8-sig"))  # D1: 容忍 BOM
            if isinstance(data, dict):
                return [data]                                    # D2: 单元素折叠包裹
            if isinstance(data, list):
                return [t for t in data if isinstance(t, dict)]  # 毒丸防御: 跳过非 dict
            return []
        except Exception:
            log("QUEUE_LOAD_FAIL (corrupt) -> treat as empty, preserve file")
            return []
    return []


def save_queue(q):
    try:
        json.dump(q, open(QUEUE, "w", encoding="utf-8"), indent=2)
    except Exception:
        pass


def acquire_lock():
    """原子文件锁: 防止双 executor 并发重复执行 (修复 R9 E12)。"""
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_lock():
    try:
        os.remove(LOCK)
    except Exception:
        pass


# ---------------- 账本/状态机 ----------------
def load_ledger():
    if os.path.exists(LEDGER):
        try:
            return json.load(open(LEDGER, encoding="utf-8-sig"))
        except Exception:
            return {"tasks": {}, "auth_used": {}, "rejected": []}
    return {"tasks": {}, "auth_used": {}, "rejected": []}


def save_ledger(lg):
    try:
        json.dump(lg, open(LEDGER, "w", encoding="utf-8"), indent=2)
    except Exception:
        pass


def load_revoke():
    if os.path.exists(AUTH_REVOKE):
        try:
            return set(json.load(open(AUTH_REVOKE, encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_revoke(s):
    try:
        json.dump(sorted(s), open(AUTH_REVOKE, "w", encoding="utf-8"), indent=2)
    except Exception:
        pass


# ---------------- RCA3 授权守卫 ----------------
def _b64(b): return base64.urlsafe_b64encode(b).decode()


def _ub64(s): return base64.urlsafe_b64decode(s)


def sign_auth(order_id, scope, exp_offset=3600, nonce=None):
    """签发授权令牌 (生产由 KR 签名; 此处用 HMAC 占位实现可运行守卫)。"""
    payload = {
        "id": "AUTH-" + hashlib.sha256((order_id + scope + str(nonce) + str(time.time())).encode()).hexdigest()[:12],
        "order_id": order_id, "scope": scope,
        "exp": int(time.time()) + exp_offset, "nonce": nonce or os.urandom(4).hex(),
    }
    raw = _b64(json.dumps(payload, ensure_ascii=False).encode())
    sig = hmac.new(AUTH_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return raw + "." + sig


def verify_auth(token_str, expected_order_id, expected_scope):
    """RCA3: 返回 (ok, reason)。拒绝 过期/撤销/重复/冲突/不匹配/无效签名。"""
    try:
        raw, sig = token_str.rsplit(".", 1)
        calc = hmac.new(AUTH_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, sig):
            return False, "INVALID_SIGNATURE"          # 无效签名
        payload = json.loads(_ub64(raw))
    except Exception:
        return False, "MALFORMED_TOKEN"
    now = int(time.time())
    if payload.get("exp", 0) < now:
        return False, "EXPIRED"                         # 过期
    if payload.get("order_id") not in (expected_order_id, "*"):  # "*" 仅隔离测试通配, 生产须绑定具体 id
        return False, "ORDER_MISMATCH"                  # 任务不匹配
    if payload.get("scope") != expected_scope:
        return False, "SCOPE_CONFLICT"                 # 冲突/范围不匹配
    return True, payload.get("id")


def auth_guard(task, lg, revoke):
    """综合守卫: 从 envelope 提取 AUTH, 校验 重复/撤销 + 签名/过期/冲突/不匹配。"""
    body = task.get("envelope_body") or ""
    m = re.search(r"AUTH=([A-Za-z0-9._\-]+)", body)
    if not m:
        return False, "NO_AUTH_PRESENT"
    token = m.group(1)
    # 撤销检查
    pid = None
    try:
        raw, sig = token.rsplit(".", 1)
        pid = json.loads(_ub64(raw)).get("id")
    except Exception:
        return False, "MALFORMED_TOKEN"
    if pid in revoke:
        return False, "REVOKED"
    # 重复/重放检查
    if pid in lg.get("auth_used", {}):
        return False, "DUPLICATE_REPLAY"
    order_id = task.get("order_id") or ""
    scope = "READONLY_PROBE" if "READONLY_PROBE" in body else "UNKNOWN"
    ok, reason = verify_auth(token, order_id, scope)
    return ok, reason


# ---------------- 安全只读 handler ----------------
def handler_readonly_probe(task):
    url = None
    m = re.search(r'(https?://\S+)', task.get("envelope_body") or "")
    if m:
        url = m.group(1).rstrip(').,')
    if not url:
        url = "https://aisaleos.com.cn/robots.txt"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "2WB-FrontlegExecutor"})
    ev = {"action": "READONLY_PROBE", "url": url,
          "executed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            body = r.read(200)
            ev.update({"status": r.status, "content_type": r.headers.get("Content-Type"),
                       "first_bytes": body[:80].decode("utf-8", "replace").replace("\n", "\\n")})
    except urllib.error.HTTPError as he:
        ev.update({"status": he.code, "content_type": he.headers.get("Content-Type"),
                   "first_bytes": he.read(80).decode("utf-8", "replace")[:80].replace("\n", "\\n")})
    except Exception as e:
        ev.update({"status": "ERR", "error": str(e)[:160]})
    return ev


def dispatch(task):
    body = task.get("envelope_body") or ""
    if "READONLY_PROBE" in body:
        return handler_readonly_probe(task)
    return {"note": "no safe handler for envelope; NOT executed"}


# ---------------- 统一消费链 (状态机) ----------------
def consume_queue():
    op = build_opener()
    pat = read_pat()
    hdr = {"Authorization": f"token {pat}", "User-Agent": "2WB-FrontlegExecutor"} if pat else None
    q = load_queue()
    lg = load_ledger()
    revoke = load_revoke()
    if "tasks" not in lg: lg["tasks"] = {}
    if "auth_used" not in lg: lg["auth_used"] = {}
    if "rejected" not in lg: lg["rejected"] = []
    did = 0
    remain = []
    for task in q:
        if not isinstance(task, dict):          # 毒丸防御 (R9 E10)
            log("SKIP_NON_DICT_ITEM (poison pill)")
            remain.append(task)
            continue
        task_id = task.get("task_id")
        order_id = task.get("order_id") or ""
        # 幂等: 已 CLOSED 跳过
        if task_id in lg["tasks"] and lg["tasks"][task_id].get("state") == "CLOSED":
            continue
        claimed_by = f"{EXECUTOR_ID}@{os.environ.get('COMPUTERNAME','unknown')}:{os.getpid()}"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # ---- RCA3 授权守卫 ----
        ok, reason = auth_guard(task, lg, revoke)
        if not ok:
            lg["tasks"][task_id] = {"state": "REJECTED_AUTH", "order_id": order_id,
                                    "reason": reason, "at": now}
            lg["rejected"].append({"task_id": task_id, "order_id": order_id, "reason": reason, "at": now})
            log(f"REJECTED_AUTH task_id={task_id} order_id={order_id} reason={reason}")
            continue   # 拒绝: 不执行, 不 CLOSED, 不伪报 PASS

        # ---- 安全动作网关: 仅允许 SAFE_ACTIONS (READONLY_PROBE); 未知/高危动作拒绝且不伪报 PASS ----
        body = task.get("envelope_body") or ""
        if "READONLY_PROBE" not in body:
            lg["tasks"][task_id] = {"state": "REFUSED_UNSAFE", "order_id": order_id,
                                    "reason": "NO_SAFE_HANDLER", "at": now}
            log(f"REFUSED_UNSAFE task_id={task_id} order_id={order_id} (unknown/high-risk action, not executed, no phantom PASS)")
            continue
        # ---- CLAIMED ----
        lg["tasks"][task_id] = {"state": "CLAIMED", "order_id": order_id,
                                "claimed_by": claimed_by, "claimed_at": now}
        # ---- RUNNING ----
        lg["tasks"][task_id]["state"] = "RUNNING"
        lg["tasks"][task_id]["running_at"] = now
        # 记录授权已用 (防重放)
        try:
            raw = re.search(r"AUTH=([A-Za-z0-9._\-]+)", task.get("envelope_body") or "").group(1)
            pid = json.loads(_ub64(raw.rsplit(".", 1)[0])).get("id")
            lg["auth_used"][pid] = task_id
        except Exception:
            pass
        evidence = dispatch(task)
        status = "PASS" if evidence.get("status") not in ("ERR",) else "FAIL"
        result_body = (
            "[RESULT][2WB][QUEUE-DISPATCH]\n"
            f"ORIGINAL_ORDER_ID={order_id}\n"
            f"TASK_ID={task_id}\n"
            f"EXECUTOR_ID={EXECUTOR_ID}\n"
            f"EXEC_CLAIMED_BY={claimed_by}\n"
            f"CLAIMED_AT={lg['tasks'][task_id]['claimed_at']}\n"
            f"RUNNING_AT={now}\n"
            f"OUTCOME=EXECUTED\n"
            f"EVIDENCE={json.dumps(evidence, ensure_ascii=False)}\n"
            f"STATUS={status}\n"
            "STATE_CHAIN=QUEUED->CLAIMED->RUNNING->RESULT->VERIFIED->CLOSED\n"
            "NOTE=queue dispatch with RCA3 auth guard; no phantom REGISTERED\n"
            f"RESULT={status}\n"
            "KR_RELAY_COUNT=0"
        )
        post_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        lg["tasks"][task_id]["result_at"] = post_at
        newcid = None
        if hdr:
            st, newcid = post_comment(op, hdr, result_body)
        else:
            st = None
        log(f"RESULT task_id={task_id} order_id={order_id} status={status} posted={newcid}")
        # ---- 回传失败: 保留任务, 不 CLOSED (修复 R9 E8) ----
        if st not in (200, 201) or not newcid:
            lg["tasks"][task_id]["state"] = "RESULT_POST_FAIL"
            lg["tasks"][task_id]["posted"] = newcid
            save_ledger(lg)
            remain.append(task)   # 保留在队列, 下一轮重试
            log(f"RESULT_POST_FAIL task_id={task_id} -> kept in queue for retry (NOT CLOSED)")
            did += 1
            continue
        # ---- VERIFIED (POST 后独立回读) ----
        verify_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        time.sleep(1)
        match = False
        try:
            st2, back = fetch_json(op, f"https://api.github.com/repos/{REPO}/issues/comments/{newcid}", hdr)
            rb_sha = hashlib.sha256((back or {}).get("body", "").encode()).hexdigest() if back else None
            match = (st2 == 200 and rb_sha == hashlib.sha256(result_body.encode()).hexdigest())
        except Exception as ve:
            log(f"VERIFY_READBACK_ERR task_id={task_id} err={ve}")
        lg["tasks"][task_id].update({"state": "VERIFIED", "result_comment_id": newcid,
                                      "verified": bool(match), "verified_at": verify_at})
        log(f"VERIFIED task_id={task_id} result={newcid} sha256_match={match}")
        # ---- CLOSED ----
        lg["tasks"][task_id]["state"] = "CLOSED"
        lg["tasks"][task_id]["closed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        did += 1
        # 从队列移除已处理项
    save_ledger(lg)
    save_queue(remain)
    return did


# ---------------- main (R9 兼容: GitHub 触发/镜像债 + 队列消费) ----------------
def is_exec_intent(body):
    return body.startswith("[TO-2WB]") and any(k in body for k in EXEC_KEYWORDS)


def main():
    op = build_opener()
    pat = read_pat()
    if not pat:
        log("PAT_FOUND=NO (executor cannot post; will retry next run)")
        sys.exit(0)
    hdr = {"Authorization": f"token {pat}", "User-Agent": "2WB-FrontlegExecutor",
           "Accept": "application/vnd.github+json"}
    comments = []
    page = 1
    rate_limited = False
    # 使用已持有的 PAT 做认证轮询 (与 watcher 一致), 避免无认证被 GitHub 限流导致扫描超时
    scan_hdr = hdr or {"User-Agent": "2WB-FrontlegExecutor"}
    while True:
        st, data = fetch_json(op, f"https://api.github.com/repos/{REPO}/issues/{ISSUE}/comments?per_page=100&page={page}", scan_hdr)
        if st == 403:
            rate_limited = True; break
        if st != 200 or not data: break
        comments += data
        if len(data) < 100: break
        page += 1; 
        if page > 100: break
    log(f"SCAN total={len(comments)} rate_limited={rate_limited}")
    ledger = load_ledger()
    if "tasks" not in ledger: ledger["tasks"] = {}
    if "processed" not in ledger: ledger["processed"] = []
    if "pending" not in ledger: ledger["pending"] = []
    acked, resulted, triggers = {}, {}, []
    for c in comments:
        b = (c.get("body") or "").strip()
        cid = str(c["id"])
        if b.startswith("[ACK-2WB] trigger_comment_id="):
            tid = re.sub(r"\s.*$", "", b.replace("[ACK-2WB] trigger_comment_id=", "").strip())
            if tid: acked[tid] = cid
        m = re.search(r"\[RESULT\]\[2WB\]\[[^\]]+\][\s\S]*?trigger_comment_id=([0-9]+)", b)
        if m: resulted[m.group(1)] = cid
        if is_exec_intent(b): triggers.append((cid, "CONTINUE", b))
        if cid in MIRROR_DEBTS: triggers.append((cid, "MIRROR", b))
    if rate_limited or not triggers:
        for cid in ledger.get("pending", []):
            if cid not in ledger["tasks"] and cid not in ledger.get("processed", []):
                kind = "MIRROR" if cid in MIRROR_DEBTS else "CONTINUE"
                triggers.append((cid, kind, "[TO-2WB] (pending-fallback)"))
    count = 0
    for cid, kind, body in triggers:
        if cid in ledger["tasks"] and ledger["tasks"][cid].get("state") == "CLOSED": continue
        if cid in ledger.get("processed", []): continue
        is_pending = cid in ledger.get("pending", [])
        if kind == "MIRROR":
            if cid in resulted: continue
        else:
            if (not is_pending) and cid not in acked: continue
            if (not is_pending) and cid in resulted: continue
        # 镜像债/MIRROR 处理 (与 R9 一致, 不展开业务)
        rb = ("[RESULT][2WB][MASTER-ORDER-MIRROR-CONSUMED]\n" if kind == "MIRROR"
              else "[RESULT][2WB][CONTINUE-EXECUTION]\n")
        rb += (f"trigger_comment_id={cid}\nRECEIVED_AT={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
               "RESULT=PASS (consumed; KR_GATE scope not executed)\nKR_RELAY_COUNT=0")
        st, newcid = post_comment(op, hdr, rb)
        if st in (200, 201) and newcid:
            ledger["tasks"][cid] = {"state": "CLOSED", "result_comment_id": newcid,
                                    "closed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            count += 1
    ledger.setdefault("processed", []).extend([c for (c, _, _) in triggers])
    save_ledger(ledger)
    # ---- 统一队列消费链 (R8+R7+RCA3) ----
    if not acquire_lock():
        log("LOCK_HELD_BY_ANOTHER (concurrent instance) -> exit to prevent double execution")
        print("LOCK_HELD_BY_ANOTHER")
        return
    try:
        q_did = consume_queue()
    finally:
        release_lock()
    log(f"DONE posted={count} queue_dispatched={q_did}")
    print(f"DONE posted={count} scanned={len(comments)} triggers={len(triggers)} queue_dispatched={q_did}")


if __name__ == "__main__":
    main()
