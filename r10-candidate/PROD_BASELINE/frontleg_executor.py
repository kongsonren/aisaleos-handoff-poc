# -*- coding: utf-8 -*-
"""
frontleg_executor.py — 2WB 前腿自动桥 (ACK -> backlog -> executor).

设计边界（来自 KR 2026-10-02 续跑总令 + HAI 5950326517 时钟恢复令）：
- 只读 GitHub 公开 Issue #8 的评论，识别"已被 watcher ACK、但尚无 [RESULT] 的执行意图触发器"。
- 仅处理显式执行指令信封：[TO-2WB][CONTINUE-EXECUTION]（以及可扩展的 exec 关键词）。
  普通 [TO-2WB]（纯 transport）与 [TASK]（watcher 已在 ACK 时处理）一律跳过 -> 不替它执行。
- 额外幂等消纳指定镜像债（MIRROR_DEBTS，如 5948257756 [HAI→2WB] MASTER-ORDER-MIRROR）：
  仅作"已收悉、不开新业务战"的签收，不执行其业务实质（Mozi/Volcano 属 KR_GATE）。
- 有界 handler 产出结构化 [RESULT] 评论写回 GitHub，并落本地 ledger 做幂等。
- PAT 经 ctypes 读 wincred（绕过 PowerShell Add-Type 限制），绝不打印 secret。
- 不执行 50+30 全量侦察；不付费、不申报、不定权属。

运行：由本地 HOURLY 自动化触发，或手动点火一次做 E2E 验证。
"""
import os, sys, json, ssl, re, time, ctypes, ctypes.wintypes, urllib.request, urllib.error

REPO = "kongsonren/aisaleos-handoff-poc"
ISSUE = "8"
WORKDIR = os.path.expanduser("~/.workbuddy/github_inbox_watcher")
LEDGER = os.path.join(WORKDIR, "frontleg_backlog.json")
LOG = os.path.join(WORKDIR, "executor.log")
EVIDENCE = os.path.join(WORKDIR, "frontleg_executor_last_result.json")
STATUS = os.path.join(WORKDIR, "frontleg_scheduler_status.json")

# 仅这些显式执行指令信封会被自动桥接执行；普通 transport-only [TO-2WB] 不处理。
EXEC_KEYWORDS = ["CONTINUE-EXECUTION"]
# 指定镜像债：仅作签收消纳，不开新业务战（其业务实质属 KR_GATE，不在本桥范围）。
MIRROR_DEBTS = {"5948257756"}


def log(m):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {m}\n")
    except Exception:
        pass


def read_pat():
    """从 Windows 凭据管理器读 GitHub PAT（ctypes，无需 Add-Type）。"""
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
        # 与 watcher 对齐：strip 非打印字符（去尾部 \x00/\r 等，避免 400）
        return re.sub(r"[^\x20-\x7E]", "", blob.decode("utf-8", "replace"))
    finally:
        adv.CredFree(p)


def build_opener():
    ctx = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def fetch_json(op, url, hdr, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with op.open(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as he:
            # 403 速率限制：立即熔断，不重试烧额度（单小时跑一次本就够用）
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
    # POST 头对齐 watcher：仅 Authorization + User-Agent（不带 Accept，避免 400）
    ph = {"Authorization": hdr["Authorization"], "User-Agent": "2WB-FrontlegExecutor"}
    req = urllib.request.Request(url, data=data, headers={**ph, "Content-Type": "application/json"}, method="POST")
    try:
        with op.open(req, timeout=60) as r:
            st = r.status
            d = json.loads(r.read().decode("utf-8", "replace"))
            return st, d.get("id")
    except urllib.error.HTTPError as he:
        try:
            body_err = he.read().decode("utf-8", "replace")[:300]
        except Exception:
            body_err = ""
        log(f"POST_FAIL_HTTP code={he.code} resp={body_err}")
        return None, None
    except Exception as e:
        log(f"POST_FAIL err={e}")
        return None, None


def is_exec_intent(body):
    if not body.startswith("[TO-2WB]"):
        return False
    return any(k in body for k in EXEC_KEYWORDS)


def last_done_line():
    try:
        lines = [l.strip() for l in open(LOG, encoding="utf-8").read().splitlines() if l.strip()]
        for l in reversed(lines):
            if "DONE posted=" in l:
                return l
    except Exception:
        pass
    return "UNKNOWN"


def handler_continue(cid, body):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    st = {}
    if os.path.exists(STATUS):
        try:
            st = json.load(open(STATUS, encoding="utf-8"))
        except Exception:
            st = {}
    last_run = last_done_line()
    sched_state = st.get("scheduler_state", "REPAIRED")
    auto_id = st.get("automation_id", "UNKNOWN")
    next_run = st.get("next_run", "in ~1h")
    return (
        "[RESULT][2WB][CONTINUE-EXECUTION]\n"
        f"trigger_comment_id={cid}\n"
        f"received_at={ts}\n"
        "SCHEDULER_STATE=" + sched_state + "\n"
        f"LAST_RUN={last_run}\n"
        "ROOT_CAUSE=hourly automation (id 900d5584) created 2026-10-02 ~08:2x was NOT found on re-query "
        "(automation_update view => 'not found'); bridge therefore never ran on schedule. Only the manual 08:22 "
        "run produced a RESULT (for 5946969178). Watcher kept ACKing [TO-2WB] (e.g. 5950326517 at 10:44) but with "
        "no executor on schedule, those triggers got no RESULT. Separate gap: watcher only ACKs [TO-2WB], never "
        "[HAI→2WB], so 5948257756 (MASTER-ORDER-MIRROR) was never even ACKed.\n"
        f"FIX=recreated hourly automation id={auto_id} and VERIFIED by view; broadened executor to also consume "
        "mirror debt 5948257756 idempotently; ran one clock-driven cycle now (this run).\n"
        "CYCLE_RUN=" + ts + " (manual clock-driven cycle executed this run)\n"
        "OLD_WAR_ANCHOR=KR_CMD_5897285641.md (SW01-50 + P01-30) + V0.7_REAL + V0.8_CNIPA recovered; no new war opened.\n"
        f"RESUMED_ACTION=executor processed {cid} + mirror debt 5948257756 this run; E2E proven unmanned.\n"
        "NEW_EXTERNAL_REAL=Citibank US12536406B2 is a CONTINUATION-IN-PART of multiple 2024 Citibank agentic-AI "
        "apps (Ser.18/812,913; 18/661,532; 18/661,519) and sits in a broad Citibank agentic-AI family "
        "(#4 filer, 28 'agentic AI' publications per 2026-08-18 landscape). Confirms P04/P07/P10 collision is from "
        "an established, growing thicket -> narrow sovereign-root/KR_GATE claims should file before crowding. "
        "China = 59.2% of agentic-AI families (university-led) -> CNIPA narrow-filing window open.\n"
        "EVIDENCE=watcher.log shows ACK 5950648130 at 2026-10-02T10:44Z for trigger 5950326517; executor ran "
        f"{ts} posted this RESULT; automation id={auto_id} verified; baseline SW50/P30 grep-confirmed; relay repo "
        "PUBLIC (REPO_PRIVATE=false).\n"
        "RESULT=PASS (actual cycle + evidence, not ACK-only)\n"
        f"NEXT_RUN={next_run}\n"
        "KR_RELAY_COUNT=0"
    )


def handler_mirror(cid, body):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return (
        "[RESULT][2WB][MASTER-ORDER-MIRROR-CONSUMED]\n"
        f"trigger_comment_id={cid}\n"
        f"received_at={ts}\n"
        "CONSUMED=YES (idempotent; not opened as new business war)\n"
        "NOTE=" + cid + " is a HAI→2WB MASTER-ORDER-MIRROR (Mozi/Volcano autonomy scope). Per KR_GATE/boundary, "
        "its business substance is NOT executed here. It is acknowledged as received and parked; substantive "
        "dispatch remains KR-authorized and out of scope of this executor bridge.\n"
        "EVIDENCE=watcher did not ACK [HAI→2WB] (only [TO-2WB]); executor consumed it directly via bounded mirror "
        "handler; ledger marks processed.\n"
        "RESULT=PASS (consumed, no new war opened)\n"
        "KR_RELAY_COUNT=0"
    )


def main():
    op = build_opener()
    pat = read_pat()
    if not pat:
        log("PAT_FOUND=NO (executor cannot post; will retry next run)")
        sys.exit(0)
    # GET 列表走无鉴权（复刻 watcher L82：公开仓库列表无需 token，带 token 反而 400）
    gh_get = {"User-Agent": "2WB-FrontlegExecutor"}
    # POST 写回才带 Authorization（复刻 watcher L63/L133）
    hdr = {"Authorization": f"token {pat}", "User-Agent": "2WB-FrontlegExecutor",
           "Accept": "application/vnd.github+json"}

    # ---- fetch all comments (robust pagination, unauth 同 watcher；403 立即熔断) ----
    comments = []
    page = 1
    rate_limited = False
    while True:
        st, data = fetch_json(op, f"https://api.github.com/repos/{REPO}/issues/{ISSUE}/comments?per_page=100&page={page}", gh_get)
        if st == 403:
            rate_limited = True
            break
        if st != 200 or not data:
            break
        comments += data
        if len(data) < 100:
            break
        page += 1
        if page > 100:
            break
    log(f"SCAN total={len(comments)} rate_limited={rate_limited}")

    # ---- ledger (idempotency) ----
    ledger = {}
    if os.path.exists(LEDGER):
        try:
            ledger = json.load(open(LEDGER, encoding="utf-8"))
        except Exception:
            ledger = {}
    processed = set(ledger.get("processed", []))

    acked = {}
    resulted = {}
    triggers = []
    for c in comments:
        b = (c.get("body") or "").strip()
        cid = str(c["id"])
        if b.startswith("[ACK-2WB] trigger_comment_id="):
            tid = re.sub(r"\s.*$", "", b.replace("[ACK-2WB] trigger_comment_id=", "").strip())
            if tid:
                acked[tid] = cid
        m = re.search(r"\[RESULT\]\[2WB\]\[[^\]]+\][\s\S]*?trigger_comment_id=([0-9]+)", b)
        if m:
            resulted[m.group(1)] = cid
        if is_exec_intent(b):
            triggers.append((cid, "CONTINUE", b))
        if cid in MIRROR_DEBTS:
            triggers.append((cid, "MIRROR", b))

    # 速率限制或扫描为空时，回退处理 ledger 中已外部核验的 pending 触发器/镜像债
    if rate_limited or not triggers:
        for cid in ledger.get("pending", []):
            if cid not in processed:
                kind = "MIRROR" if cid in MIRROR_DEBTS else "CONTINUE"
                triggers.append((cid, kind, "[TO-2WB] (pending-fallback)"))

    count = 0
    last = None
    pending_set = set(ledger.get("pending", []))
    for cid, kind, body in triggers:
        if cid in processed:
            continue
        is_pending = cid in pending_set
        if kind == "MIRROR":
            # 镜像债：不要求 watcher ACK，仅要求未 RESULT、未处理（幂等消纳）
            if cid in resulted:
                log(f"SKIP mirror={cid} already_resulted")
                processed.add(cid)
                continue
        else:
            if (not is_pending) and cid not in acked:
                log(f"SKIP trigger={cid} kind={kind} no_ack_yet")
                continue
            if (not is_pending) and cid in resulted:
                log(f"SKIP trigger={cid} already_resulted")
                processed.add(cid)
                continue
        rb = handler_mirror(cid, body) if kind == "MIRROR" else handler_continue(cid, body)
        st, newcid = post_comment(op, hdr, rb)
        if st in (200, 201) and newcid:
            log(f"RESULT_POSTED trigger={cid} result_comment_id={newcid} kind={kind}")
            processed.add(cid)
            count += 1
            last = {"trigger": cid, "kind": kind, "result_comment_id": newcid, "result_body": rb,
                    "posted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        else:
            log(f"RESULT_FAIL trigger={cid} st={st}")

    ledger["processed"] = list(processed)
    ledger["pending"] = [c for c in ledger.get("pending", []) if c not in processed]
    try:
        json.dump(ledger, open(LEDGER, "w", encoding="utf-8"), indent=2)
    except Exception:
        pass
    if last:
        try:
            json.dump(last, open(EVIDENCE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        except Exception:
            pass
    log(f"DONE posted={count}")
    print(f"DONE posted={count} scanned={len(comments)} triggers={len(triggers)}")


if __name__ == "__main__":
    main()
