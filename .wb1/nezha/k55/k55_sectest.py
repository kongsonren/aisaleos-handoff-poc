# -*- coding: utf-8 -*-
"""K55-FINAL-二｜云端安全测试隔离件（非生产 / 分支隔离 / K55-SECTEST-* 命名空间）

KR 最终令第二项三项安全测试的施工件（任务 #651/#652/#653）：
  ① 双消费者竞争：两个云端消费者（Actions matrix 双 job）同时竞争同一 ORDER_ID
     → 验证最多一次实际执行、一次有效 RESULT（claim 机制 + 单次 CAS）；
  ② 三类授权拒绝：伪造 ISSUER / 错误授权锚点 / 过期 TTL 分别投递
     → 验证类型化拒绝、零执行（无 ACK / 无 RESULT / 无 executed_order_ids）；
  ③ 回执失败恢复：执行成功但 RESULT POST 失败（故障注入）
     → 验证恢复回执而不重新执行（EXECUTED_PENDING_POST + 存储载荷重 POST）。

与原 k55_proof.py 的关键差异（隔离副本，不碰 DW1 生产测试账本）：
  · 独立账本 SECTEST_LEDGER / 独立目标 SECTEST_TARGET / 独立 ORDER 家族；
  · known_orders 隔离：只处理本账本 dispatch 创建的 ORDER_ID；
  · commit_cas()：单次 CAS（blob→tree→commit→PATCH force=false；
    409/422 均判 CAS_CONFLICT——GitHub 对 ref 被推进有两种返回码）；
    绝不复用 GitHubStore.commit_files 的 409 自动重试覆盖（并行竞态根因）；
  · claim 机制（SECTEST_CLAIM=1）：执行前 CAS 抢占（带 head 刷新 + 最多 3 次尝试），
    败者类型化 REJECT_CLAIM_LOST / REJECT_CLAIM_CONTENDED，零执行零回传；
    SECTEST_CLAIM=0 = 原始行为（用于记录未加固竞态的真实后果）；
  · EXECUTED_PENDING_POST 断点：RESULT POST 失败即持久化计算结果，恢复只补 POST；
  · 故障注入 SECTEST_FAIL_RESULT_POST=1：模拟 GitHub 回执失败（跳过真实 POST）。

版本记录：
  rev1：首次 hardened 竞态逮到两个自身 bug（claim 重试后 head 未刷新；
        422 未按 CAS 处理）——执行层 exactly-once 当时已成立（1 ACK/1 RESULT/1 exec），
        账本入账失败；本 rev2 修复后重跑（DW7）。
  rev2：DW7 竞态执行层 exactly-once 再次成立（1 ACK/1 RESULT/1 exec，双 job success），
        但账本被败者拒绝提交覆盖（note_task_reject 改 state=REJECTED 覆盖胜者 CLAIMED），
        且胜者 EXECUTED 冲突重试提交磁盘旧版丢 exec_events——第三处 bug；
        本 rev3：败者拒绝走独立 claim_rejections 字段（不动 state）+ 全账本合并重试
        （merge_ledgers：列表并集去重/计数取 max/任务逐键合并），DW9 重跑。
铁律：只写分支 k55-proof 上的 K55-SECTEST-* 账本/目标文件；绝不碰 main 与 DW1 账本；
只发 [ACK-2WB]/[RESULT][2WB] 标记（2WB 侧）；PAT/token 仅内存。
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

_here = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(_here), os.path.join(_here, "nezha_raw"), _here):
    if os.path.exists(os.path.join(_p, "task_state.py")):
        sys.path.insert(0, _p)
        break
from task_state import GitHubStore, now_iso  # noqa: E402

CN = timezone(timedelta(hours=8))
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("MOZI_GH_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY", "kongsonren/aisaleos-handoff-poc")
BRANCH = os.environ.get("K55_BRANCH", "k55-proof")
ISSUE = os.environ.get("K55_ISSUE", "8")
ANCHOR_COMMENT_ID = os.environ.get("K55_ANCHOR_COMMENT_ID", "6272173951")
TRUSTED_ISSUER = os.environ.get("K55_TRUSTED_ISSUER", "kongsonren")
PARENT_ORDER = os.environ.get("K55_PARENT_ORDER", "KR-NEZHA-CLOUD-K55-20261019")

SECTEST_LEDGER = os.environ.get(
    "SECTEST_LEDGER", ".wb1/nezha/k55/k55_sectest_ledger.json")
SECTEST_TARGET = os.environ.get(
    "SECTEST_TARGET", ".wb1/nezha/k55/k55_sectest_target.dat")
SECTEST_FAMILY = os.environ.get(
    "K55_SECTEST_FAMILY", "KR-NEZHA-CLOUD-K55-SECTEST-20261020")
ORDER_ID_RE = re.compile(os.environ.get(
    "K55_ORDER_ID_RE", r"^KR-NEZHA-CLOUD-K55-SECTEST-\d{8}-DW\d+$"))
SECTEST_CLAIM = os.environ.get("SECTEST_CLAIM", "1") == "1"
SECTEST_FAIL_RESULT_POST = os.environ.get("SECTEST_FAIL_RESULT_POST", "0") == "1"
BARRIER_MAX_WAIT = int(os.environ.get("SECTEST_BARRIER_MAX_WAIT", "240"))

RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
CONSUMER = os.environ.get("SECTEST_CONSUMER_ID") or RUN_ID
SCOPE_WHITELIST = {"READONLY_SHA256"}
CLOCK_SKEW = 300

MARK_TASK = "[TO-2WB][TASK]"
MARK_ACK = "[ACK-2WB]"
MARK_RESULT = "[RESULT][2WB]"


def log(*a):
    print("[K55-SECTEST]", *a, flush=True)


def api(method, path, payload=None):
    url = "https://api.github.com" + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, method=method, data=data, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "k55-sectest",
    })
    try:
        r = urllib.request.urlopen(req, timeout=40)
        return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "ignore")[:300]}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": repr(e)[:200]}


# ---------- 单次 CAS 提交（核心：409/422 即冲突，绝不重试覆盖） ----------
def commit_cas(store, files, message, expected_head):
    """blob→tree→commit→PATCH force=false，单次尝试。

    返回 {"ok": bool, "commit": sha|None, "error": ...}；
    CAS 冲突（head 被他人推进，GitHub 返回 409 或 422）→ CAS_CONFLICT。
    expected_head 为空时先读当前 head（仅用于无并发场景，如恢复通道）。
    """
    import base64 as _b64

    def _req(method, path, payload):
        url = "https://api.github.com" + path
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, method=method, data=data, headers={
            "Authorization": "Bearer " + store.token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "k55-sectest-cas",
        })
        try:
            r = urllib.request.urlopen(req, timeout=40)
            return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, {"error": e.read().decode("utf-8", "ignore")[:300]}
        except Exception as e:  # noqa: BLE001
            return 0, {"error": repr(e)[:200]}

    head = expected_head
    if not head:
        s, ref = _req("GET", "/repos/%s/git/ref/heads/%s" % (store.repo, store.branch))
        if s != 200:
            return {"ok": False, "error": "REF_READ_FAILED", "detail": ref}
        head = ref["object"]["sha"]
    tree_items = []
    for path, data in files.items():
        s, b = _req("POST", "/repos/%s/git/blobs" % store.repo,
                    {"content": _b64.b64encode(data).decode(), "encoding": "base64"})
        if s not in (200, 201):
            return {"ok": False, "error": "BLOB_FAILED", "path": path, "detail": b}
        tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": b["sha"]})
    s, t = _req("POST", "/repos/%s/git/trees" % store.repo,
                {"base_tree": head, "tree": tree_items})
    if s not in (200, 201):
        return {"ok": False, "error": "TREE_FAILED", "detail": t}
    s, c = _req("POST", "/repos/%s/git/commits" % store.repo,
                {"message": message, "tree": t["sha"], "parents": [head]})
    if s not in (200, 201):
        return {"ok": False, "error": "COMMIT_FAILED", "detail": c}
    s, r = _req("PATCH", "/repos/%s/git/refs/heads/%s" % (store.repo, store.branch),
                {"sha": c["sha"], "force": False})
    if s == 200:
        return {"ok": True, "commit": c["sha"]}
    if s in (409, 422):
        # 409 = CAS 冲突；422 = not fast-forward（ref 被推进的另一种返回码）
        return {"ok": False, "error": "CAS_CONFLICT", "code": s}
    return {"ok": False, "error": "REF_PATCH_FAILED", "code": s, "detail": r}


def parse_kv_body(body):
    out = {}
    for ln in body.splitlines():
        m = re.match(r"^([A-Z0-9_]+):\s*(.+)$", ln.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def parse_dt(s):
    try:
        return datetime.fromisoformat(s)
    except Exception:  # noqa: BLE001
        return None


def sha256_file(store, path):
    b, sha, head, code = store.read_file(path)
    if b is None:
        return None, code
    return hashlib.sha256(b).hexdigest(), code


def new_ledger():
    return {"state": "IDLE", "known_orders": [], "tasks": {},
            "executed_order_ids": [], "rejections": [], "rejection_counts": {},
            "history": []}


def read_led(store):
    d, _, head, _ = store.read_json(SECTEST_LEDGER, default=None)
    if not d:
        d, head = new_ledger(), None
    for k, v in (("known_orders", []), ("tasks", {}), ("executed_order_ids", []),
                 ("rejections", []), ("rejection_counts", {}), ("history", []),
                 ("state", "IDLE")):
        d.setdefault(k, v)
    return d, head


def write_led(store, data, head, msg):
    """提交账本；成功返回 (ok, new_head)。head 在成功时刷新为新 commit。"""
    r = commit_cas(store, {SECTEST_LEDGER: json.dumps(
        data, ensure_ascii=False, indent=2).encode()}, msg, head)
    return r.get("ok"), (r.get("commit") if r.get("ok") else head), r


def _merge_list(a, b):
    """列表并集去重（按 JSON 序列化判重），保留 a 的顺序在前。"""
    seen = {json.dumps(x, sort_keys=True, ensure_ascii=False) for x in a}
    return list(a) + [x for x in b
                      if json.dumps(x, sort_keys=True, ensure_ascii=False) not in seen]


def merge_ledgers(disk, local):
    """CAS 冲突后：以磁盘版为底合并本地版。

    - 列表字段（history/rejections/exec_events/claim_rejections…）并集去重；
    - rejection_counts 取 count 最大值；
    - tasks 逐 ORDER_ID 合并（本地执行结果覆磁盘，磁盘独有的 claim_rejections 等保留）；
    - 绝不丢失任何一方的记录（胜者执行 + 败者拒绝都要留在账本）。
    """
    out = dict(disk)
    for k in ("known_orders", "executed_order_ids"):
        out[k] = sorted(set(disk.get(k, [])) | set(local.get(k, [])))
    out["history"] = _merge_list(disk.get("history", []),
                                 local.get("history", []))[-80:]
    out["rejections"] = _merge_list(disk.get("rejections", []),
                                    local.get("rejections", []))[-40:]
    rc = dict(disk.get("rejection_counts", {}))
    for k, v in local.get("rejection_counts", {}).items():
        d = rc.get(k, {})
        rc[k] = {"count": max(d.get("count", 0), v.get("count", 0)),
                 "last_at": v.get("last_at") or d.get("last_at"),
                 "last_consumer": v.get("last_consumer") or d.get("last_consumer"),
                 "detail": v.get("detail") or d.get("detail")}
    out["rejection_counts"] = rc
    tasks = dict(disk.get("tasks", {}))
    for oid, lt in local.get("tasks", {}).items():
        dt = tasks.get(oid, {})
        mt = dict(dt)
        mt.update(lt)  # 本地字段覆磁盘（执行结果、state 等）
        for lk in ("exec_events", "claim_rejections", "rejections"):
            mt[lk] = _merge_list(dt.get(lk, []), lt.get(lk, []))
        tasks[oid] = mt
    out["tasks"] = tasks
    return out


def note_reject(led, rtype, oid, detail=""):
    key = "%s:%s" % (rtype, oid)
    led["rejection_counts"][key] = {
        "count": led["rejection_counts"].get(key, {}).get("count", 0) + 1,
        "last_at": now_iso(), "last_consumer": CONSUMER, "detail": detail[:200]}
    led["rejections"] = (led.get("rejections", []) + [{
        "type": rtype, "order_id": oid, "at": now_iso(),
        "consumer": CONSUMER, "run": RUN_ID, "detail": detail[:200]}])[-40:]


def note_task_reject(led, oid, rtype, detail=""):
    t = led["tasks"].setdefault(oid, {})
    t["state"] = "REJECTED"
    t.setdefault("rejections", []).append(
        {"type": rtype, "at": now_iso(), "consumer": CONSUMER, "detail": detail[:200]})


def note_task_claim_reject(led, oid, rtype, detail=""):
    """claim 败者的记录：**不改变 task state**（state 归胜者的状态机），
    只追加 claim_rejections——避免覆盖胜者的 CLAIMED→EXECUTED 转移。"""
    t = led["tasks"].setdefault(oid, {})
    t.setdefault("claim_rejections", []).append(
        {"type": rtype, "at": now_iso(), "consumer": CONSUMER, "detail": detail[:200]})


def note_hist(led, actor, action, **kw):
    led.setdefault("history", []).append(
        dict(at=now_iso(), actor=actor, action=action, consumer=CONSUMER,
             run=RUN_ID, **kw))
    led["history"] = led["history"][-80:]


# ---------- Issue #8 扫描（末页二分 + 倒序，comments API 为旧→新排序） ----------
def _get_page(p, per=100):
    s, j = api("GET", "/repos/%s/issues/%s/comments?per_page=%d&page=%d"
               % (REPO, ISSUE, per, p))
    if s != 200 or not isinstance(j, list):
        return None
    return j


def _last_page(per=100):
    if _get_page(1, per) is None:
        return 0
    if not _get_page(1, per):
        return 0
    lo, hi = 1, 1
    while True:
        pg = _get_page(hi, per)
        if pg:
            lo = hi
            hi *= 2
            if hi > 2000:
                break
        else:
            break
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _get_page(mid, per):
            lo = mid
        else:
            hi = mid - 1
    return lo


def scan_orders(max_pages=4):
    orders, seen, total_raw = [], set(), 0
    lp = _last_page()
    if lp == 0:
        return orders, total_raw
    pages, p = [], lp
    while p >= 1 and len(pages) < max_pages:
        pg = _get_page(p)
        if not pg:
            break
        pages.append(pg)
        p -= 1
    for pg in reversed(pages):
        for c in pg:
            body = c.get("body") or ""
            if MARK_TASK not in body:
                continue
            total_raw += 1
            kv = parse_kv_body(body)
            oid = kv.get("ORDER_ID", "")
            if not ORDER_ID_RE.match(oid) or oid in seen:
                continue
            seen.add(oid)
            o = dict(kv)
            o["_comment_id"] = c["id"]
            o["_author"] = (c.get("user") or {}).get("login", "")
            o["_created_at"] = c.get("created_at", "")
            orders.append(o)
    orders.sort(key=lambda x: x.get("_comment_id", 0))
    return orders, total_raw


def find_result_comment(order_id):
    lp = _last_page()
    p, found = lp, []
    while p >= 1:
        pg = _get_page(p)
        if not pg:
            break
        for c in reversed(pg):
            body = c.get("body") or ""
            if MARK_RESULT in body and order_id in body:
                kv = parse_kv_body(body)
                if kv.get("ORDER_ID") == order_id:
                    found.append({"id": c["id"], "kv": kv,
                                  "author": (c.get("user") or {}).get("login", ""),
                                  "created_at": c.get("created_at", "")})
                    if len(found) >= 3:
                        return found[-1]
        if found:
            return found[-1]
        p -= 1
    return None


# ---------- 恢复通道：EXECUTED_PENDING_POST → 只补 POST 不重执行 ----------
def recovery_pass(store, led, head):
    """返回 (处理数, head)。只对 EXECUTED_PENDING_POST 任务重 POST RESULT。"""
    n = 0
    for oid, t in list(led["tasks"].items()):
        if t.get("state") != "EXECUTED_PENDING_POST":
            continue
        p = t.get("pending_post") or {}
        if not p.get("result_body"):
            log("recovery skip (no stored payload)", oid)
            continue
        log("RECOVERY re-POST RESULT (no re-exec)", oid,
            "stored_executed_at=%s" % p.get("executed_at"))
        s, rc = api("POST", "/repos/%s/issues/%s/comments" % (REPO, ISSUE),
                    {"body": p["result_body"]})
        if s != 201:
            note_reject(led, "RECOVERY_POST_FAILED", oid, "http=%s" % s)
            ok, head, r = write_led(store, led, head,
                                    "[K55-SECTEST] recovery post failed %s" % oid)
            log("recovery POST failed", s, r)
            return n, head
        t["state"] = "EXECUTED"
        t["result_comment_id"] = rc.get("id")
        t["recovered_at"] = now_iso()
        t["recovered_by"] = CONSUMER
        # 回填 result 字段（恢复通道的账本自洽：verify 六项核验需要）
        t["result"] = {
            "status": "PASS" if p.get("match") else "FAIL",
            "computed_sha256": p.get("computed_sha256"),
            "match": bool(p.get("match")),
            "executed_by": "CLOUD_2WB",
            "completion_id": p.get("completion_id"),
            "executed_at": p.get("executed_at"),
            "consumer": CONSUMER,
            "recovered": True}
        if oid not in led["executed_order_ids"]:
            led["executed_order_ids"].append(oid)
        note_hist(led, "CLOUD_2WB", "recover_receipt", order_id=oid,
                  result_comment_id=rc.get("id"),
                  stored_executed_at=p.get("executed_at"))
        ok, head, r = write_led(
            store, led, head,
            "[K55-SECTEST] RECOVERED receipt %s (comment %s, no re-exec)"
            % (oid, rc.get("id")))
        if not ok:
            # 冲突：重读合并重试（保留他人记录）
            log("recovery commit conflict -> merge retry")
            led2, head2 = read_led(store)
            led2 = merge_ledgers(led2, led)
            ok, head, r = write_led(
                store, led2, head2,
                "[K55-SECTEST] RECOVERED(merge) %s" % oid)
        log("RECOVERED", oid, "comment=%s" % rc.get("id"), "commit_ok=%s" % ok)
        n += 1
        if ok:
            led, head = read_led(store)
    return n, head


# ---------- claim：单次 CAS 抢占（head 全程刷新；409/422 均重读） ----------
def try_claim(store, led, head, oid, max_attempts=3):
    """返回 (claimed: bool, led, head, outcome)。outcome:
    CLAIMED / CLAIMED_BY_OTHER / CLAIM_CONTENDED"""
    for attempt in range(max_attempts):
        t = led["tasks"].setdefault(oid, {})
        if t.get("state") == "CLAIMED" and t.get("claimer") != CONSUMER:
            return False, led, head, "CLAIMED_BY_OTHER"
        t.update({"state": "CLAIMED", "claimer": CONSUMER,
                  "claimed_at": now_iso(), "claim_attempt": attempt + 1})
        ok, head, r = write_led(
            store, led, head, "[K55-SECTEST] CLAIM %s by %s (attempt %d)"
            % (oid, CONSUMER, attempt + 1))
        if ok:
            return True, led, head, "CLAIMED"
        log("claim attempt %d CAS_CONFLICT/err:" % (attempt + 1), r.get("error"))
        led, head = read_led(store)
    return False, led, head, "CLAIM_CONTENDED"


# ---------- 授权校验 ----------
def auth_checks(o):
    """五要素授权校验。返回 (ok, reject_type, detail)。"""
    if o.get("ANCHOR_COMMENT_ID") != ANCHOR_COMMENT_ID:
        return False, "ANCHOR_NOT_ALLOWLISTED", "anchor=%s allow=%s" % (
            o.get("ANCHOR_COMMENT_ID"), ANCHOR_COMMENT_ID)
    s, ac = api("GET", "/repos/%s/issues/comments/%s" % (REPO, ANCHOR_COMMENT_ID))
    if s != 200:
        return False, "ANCHOR_MISSING", "http=%s" % s
    if (ac.get("user") or {}).get("login") != TRUSTED_ISSUER:
        return False, "ANCHOR_UNAUTHORIZED", "author=%s" % (
            ac.get("user") or {}).get("login")
    if PARENT_ORDER not in (ac.get("body") or ""):
        return False, "PARENT_ORDER_MISMATCH", "parent=%s" % o.get("PARENT_ORDER")
    oid = o["ORDER_ID"]
    if not ORDER_ID_RE.match(oid) or not oid.startswith(SECTEST_FAMILY):
        return False, "ORDER_FORMAT", oid
    if o.get("ISSUER") != "CLOUD_1WB":
        return False, "ISSUER_MISMATCH", "issuer=%s" % o.get("ISSUER")
    if o.get("SCOPE") not in SCOPE_WHITELIST:
        return False, "SCOPE_VIOLATION", "scope=%s" % o.get("SCOPE")
    iss = parse_dt(o.get("ISSUED_AT", ""))
    ttl = int(o.get("TTL_SECONDS", "0") or 0)
    if not iss or ttl <= 0:
        return False, "VALIDITY_MALFORMED", "issued_at=%s ttl=%s" % (
            o.get("ISSUED_AT"), ttl)
    now = datetime.now(CN)
    if now < iss - timedelta(seconds=CLOCK_SKEW):
        return False, "NOT_YET_VALID", "issued_at=%s" % o["ISSUED_AT"]
    if now > iss + timedelta(seconds=ttl):
        return False, "TTL_EXPIRED", "issued_at=%s ttl=%s" % (o["ISSUED_AT"], ttl)
    if not o.get("TARGET") or not o.get("EXPECTED_SHA256"):
        return False, "TARGET_MALFORMED", "target=%s" % o.get("TARGET")
    return True, None, None


def barrier_wait(led, oid):
    """race_start_at 到点前等待（制造真实并行竞争窗口）。"""
    t = led["tasks"].get(oid) or {}
    start = parse_dt(t.get("race_start_at") or "")
    if not start:
        return False
    log("barrier wait until", t["race_start_at"], "order", oid)
    deadline = time.time() + BARRIER_MAX_WAIT
    while time.time() < deadline:
        if datetime.now(CN) >= start:
            log("barrier released", oid, "at", now_iso())
            return True
        time.sleep(2)
    log("barrier TIMEOUT (proceeding anyway)", oid)
    return False


# ---------- 消费者主流程 ----------
def exec_all():
    store = GitHubStore(TOKEN, REPO, BRANCH)
    if not TOKEN:
        log("FATAL no token")
        return 2
    summary = {"mode": "exec-all", "consumer": CONSUMER, "run": RUN_ID,
               "claim_enabled": SECTEST_CLAIM,
               "fail_result_post": SECTEST_FAIL_RESULT_POST,
               "recovered": 0, "rejected": [], "executed": None,
               "claim_lost": False, "verdict": None}

    led, head = read_led(store)
    log("ledger state=%s known_orders=%s executed=%s" % (
        led.get("state"), led.get("known_orders"), led.get("executed_order_ids")))

    # ---- 恢复通道优先（回执恢复测试的第二次运行走这里）----
    n, head = recovery_pass(store, led, head)
    summary["recovered"] = n
    if n:
        led, head = read_led(store)

    # ---- 扫描 + known_orders 隔离 ----
    orders, raw = scan_orders()
    log("scan issue#%s: %d raw [TO-2WB][TASK], %d strict-family" % (ISSUE, raw, len(orders)))
    known = set(led.get("known_orders", []))
    orders = [o for o in orders if o["ORDER_ID"] in known]
    log("after known_orders isolation: %d" % len(orders))

    todo = []
    for o in orders:
        oid = o["ORDER_ID"]
        t = led["tasks"].get(oid) or {}
        st = t.get("state")
        if oid in led.get("executed_order_ids", []) or st in ("EXECUTED", "CLOSED"):
            continue
        if st == "CLAIMED" and t.get("claimer") != CONSUMER:
            log("SKIP claimed-by-other", oid, "claimer=%s" % t.get("claimer"))
            continue
        if st == "EXECUTED_PENDING_POST":
            continue  # 恢复通道已处理
        if st == "REJECTED":
            continue
        todo.append(o)
    if not todo:
        summary["verdict"] = "NO_UNPROCESSED_ORDER"
        log("no unprocessed order")
        print("SECTEST_SUMMARY " + json.dumps(summary, ensure_ascii=False))
        return 0

    # ---- 逐条授权校验（拒绝测试：三条恶意令全部类型化拒绝，零执行）----
    for o in todo:
        oid = o["ORDER_ID"]
        ok, rtype, detail = auth_checks(o)
        if not ok:
            log("AUTH_REJECT", rtype, oid, detail)
            note_reject(led, rtype, oid, detail)
            note_task_reject(led, oid, rtype, detail)
            note_hist(led, "CLOUD_2WB", "auth_reject", order_id=oid,
                      reject_type=rtype)
            okc, head, r = write_led(
                store, led, head, "[K55-SECTEST] auth reject %s %s" % (rtype, oid))
            summary["rejected"].append({"order_id": oid, "type": rtype})
            if not okc:
                log("commit failed after reject", r)
                return 1
            led, head = read_led(store)
            continue
        # ---------- 授权通过：至多执行一条（幂等纪律）----------
        log("AUTH_OK", oid)

        # 竞争屏障（仅 race 令设有 race_start_at）
        barrier_wait(led, oid)

        # claim：单次 CAS 抢占（SECTEST_CLAIM=0 时跳过=原始行为）
        if SECTEST_CLAIM:
            claimed, led, head, outcome = try_claim(store, led, head, oid)
            if not claimed:
                rtype = ("REJECT_CLAIM_LOST" if outcome == "CLAIMED_BY_OTHER"
                         else "REJECT_CLAIM_CONTENDED")
                log("CLAIM outcome:", outcome, "->", rtype)
                note_reject(led, rtype, oid, "outcome=%s consumer=%s" % (outcome, CONSUMER))
                note_task_claim_reject(led, oid, rtype, "outcome=%s" % outcome)
                note_hist(led, "CLOUD_2WB", "claim_not_won", order_id=oid,
                          outcome=outcome)
                okc, head, r = write_led(
                    store, led, head, "[K55-SECTEST] %s %s" % (rtype, oid))
                if not okc:
                    # 冲突：重读后合并重试（不覆盖胜者状态）
                    log("claim-lost commit conflict -> merge retry")
                    led2, head2 = read_led(store)
                    led2 = merge_ledgers(led2, led)
                    okc, head, r = write_led(
                        store, led2, head2, "[K55-SECTEST] %s(merge) %s" % (rtype, oid))
                log(rtype, oid, "commit_ok=%s" % okc)
                summary["claim_lost"] = True
                summary["verdict"] = "CLAIM_NOT_WON_NO_EXEC"
                print("SECTEST_SUMMARY " + json.dumps(summary, ensure_ascii=False))
                return 0
            log("CLAIMED", oid, "by", CONSUMER)

        # ---------- 真实执行（本 runner 独立重算 SHA）----------
        h, code = sha256_file(store, o["TARGET"])
        if h is None:
            note_reject(led, "EXEC_TARGET_READ_FAILED", oid, "http=%s" % code)
            write_led(store, led, head, "[K55-SECTEST] target read failed %s" % oid)
            log("EXEC target read failed", code)
            return 1
        match = (h == o.get("EXPECTED_SHA256"))
        t = led["tasks"].setdefault(oid, {})
        t.setdefault("exec_events", []).append(
            {"at": now_iso(), "consumer": CONSUMER, "run": RUN_ID})
        log("EXEC computed sha16=%s match=%s (exec_events=%d)" % (
            h[:16], match, len(t["exec_events"])))

        # ---------- 先 ACK 后 RESULT ----------
        ack_body = ("%s trigger_comment_id=%s received_at=%s watcher_run=%s "
                    "order_id=%s consumer=CLOUD_2WB sectest=1"
                    % (MARK_ACK, o["_comment_id"], now_iso(), RUN_ID, oid))
        s, ac2 = api("POST", "/repos/%s/issues/%s/comments" % (REPO, ISSUE),
                     {"body": ack_body})
        ack_id = ac2.get("id") if s == 201 else None
        if s != 201:
            note_reject(led, "ACK_POST_FAILED", oid, "http=%s" % s)
            write_led(store, led, head, "[K55-SECTEST] ack post failed %s" % oid)
            log("ACK POST failed", s)
            return 1
        log("ACK", oid, "comment=%s" % ack_id)

        cid = "K55-SECTEST-%s" % hashlib.sha256(
            (oid + h + str(match) + CONSUMER).encode()).hexdigest()[:12]
        executed_at = now_iso()
        res_body = "\n".join([
            MARK_RESULT,
            "ORDER_ID: %s" % oid,
            "TASK_ID: %s" % o.get("TASK_ID", ""),
            "COMPLETION_ID: %s" % cid,
            "RUN_ID: %s" % RUN_ID,
            "EXECUTED_BY: CLOUD_2WB",
            "TARGET: %s" % o["TARGET"],
            "COMPUTED_SHA256: %s" % h,
            "EXPECTED_SHA256: %s" % o.get("EXPECTED_SHA256"),
            "MATCH: %s" % ("true" if match else "false"),
            "EXECUTED_AT: %s" % executed_at,
            "ACK_COMMENT_ID: %s" % (ack_id or ""),
            "SECTEST: 1",
        ])

        if SECTEST_FAIL_RESULT_POST:
            # 故障注入：模拟 GitHub 回执失败（不真实 POST）
            log("FAULT_INJECT result POST simulated-failure", oid)
            t = led["tasks"][oid]
            t["state"] = "EXECUTED_PENDING_POST"
            t["pending_post"] = {
                "result_body": res_body, "computed_sha256": h, "match": bool(match),
                "completion_id": cid, "executed_at": executed_at,
                "ack_comment_id": ack_id, "failed_at": now_iso(),
                "fail_reason": "SIMULATED_RESULT_POST_FAILURE"}
            note_hist(led, "CLOUD_2WB", "exec_pending_post", order_id=oid,
                      fail_reason="SIMULATED")
            okc, head, r = write_led(
                store, led, head,
                "[K55-SECTEST] EXECUTED_PENDING_POST %s (result POST failed, "
                "receipt recoverable)" % oid)
            log("EXECUTED_PENDING_POST", oid, "commit_ok=%s" % okc)
            summary["executed"] = {"order_id": oid, "state": "EXECUTED_PENDING_POST",
                                   "exec_events": len(t.get("exec_events", []))}
            summary["verdict"] = "EXECUTED_PENDING_POST"
            print("SECTEST_SUMMARY " + json.dumps(summary, ensure_ascii=False))
            return 0

        s, rc = api("POST", "/repos/%s/issues/%s/comments" % (REPO, ISSUE),
                    {"body": res_body})
        if s != 201:
            note_reject(led, "RESULT_POST_FAILED", oid, "http=%s" % s)
            write_led(store, led, head, "[K55-SECTEST] result post failed %s" % oid)
            log("RESULT POST failed", s)
            return 1

        t = led["tasks"][oid]
        t.update({
            "state": "EXECUTED",
            "result": {"status": "PASS" if match else "FAIL", "computed_sha256": h,
                       "match": bool(match), "executed_by": "CLOUD_2WB",
                       "completion_id": cid, "executed_at": executed_at,
                       "consumer": CONSUMER},
            "result_written_by": "CLOUD_2WB",
            "ack_comment_id": ack_id, "result_comment_id": rc.get("id"),
            "dispatch_comment_id": o["_comment_id"],
            "auth_checks": {"anchor": ANCHOR_COMMENT_ID, "issuer": o.get("ISSUER"),
                            "scope": o.get("SCOPE"), "order_format": True,
                            "ttl_window": True},
        })
        if oid not in led["executed_order_ids"]:
            led["executed_order_ids"].append(oid)
        note_hist(led, "CLOUD_2WB", "execute", order_id=oid, match=bool(match),
                  ack_comment_id=ack_id, result_comment_id=rc.get("id"))
        okc, head, r = write_led(
            store, led, head,
            "[K55-SECTEST] EXECUTED %s -> %s (ack=%s result=%s)"
            % (oid, "PASS" if match else "FAIL", ack_id, rc.get("id")))
        if not okc:
            # 入账冲突：重读核对是否他人已入账（防双计）；否则合并本地执行结果重试
            log("EXECUTED commit conflict:", r.get("error"), "-> re-read check")
            led2, head2 = read_led(store)
            t2 = led2["tasks"].get(oid) or {}
            if t2.get("state") == "EXECUTED" and (t2.get("result") or {}).get(
                    "consumer") != CONSUMER:
                log("another consumer already EXECUTED (no double count)", oid)
                summary["executed"] = {"order_id": oid, "state": "EXECUTED_BY_OTHER"}
                summary["verdict"] = "EXECUTED_BY_OTHER"
                print("SECTEST_SUMMARY " + json.dumps(summary, ensure_ascii=False))
                return 0
            led2 = merge_ledgers(led2, led)
            okc2, head2, r2 = write_led(
                store, led2, head2, "[K55-SECTEST] EXECUTED(merge) %s" % oid)
            log("EXECUTED merge commit_ok=%s" % okc2)
        log("RESULT posted", oid, "comment=%s" % rc.get("id"))
        summary["executed"] = {
            "order_id": oid, "state": "EXECUTED", "result_comment_id": rc.get("id"),
            "ack_comment_id": ack_id, "completion_id": cid,
            "exec_events": len(t.get("exec_events", []))}
        summary["verdict"] = "EXECUTED_ONCE"
        print("SECTEST_SUMMARY " + json.dumps(summary, ensure_ascii=False))
        return 0

    summary["verdict"] = "ALL_REJECTED_NO_EXEC"
    print("SECTEST_SUMMARY " + json.dumps(summary, ensure_ascii=False))
    return 0


# ---------- 1WB 侧核验关闭 ----------
def verify():
    store = GitHubStore(TOKEN, REPO, BRANCH)
    if not TOKEN:
        log("FATAL no token")
        return 2
    led, head = read_led(store)
    out = {"mode": "verify", "closed": [], "failed": []}
    for oid, t in list(led["tasks"].items()):
        if t.get("state") != "EXECUTED":
            continue
        res = find_result_comment(oid)
        if not res:
            log("no RESULT comment for", oid)
            continue
        s, c = api("GET", "/repos/%s/issues/comments/%s" % (REPO, res["id"]))
        if s != 200:
            log("RESULT GET failed", s)
            continue
        kv = parse_kv_body(c.get("body") or "")
        checks = {
            "marker": MARK_RESULT in (c.get("body") or ""),
            "order_id": kv.get("ORDER_ID") == oid,
            "computed_sha256": kv.get("COMPUTED_SHA256") == (
                t.get("result") or {}).get("computed_sha256"),
            "match": kv.get("MATCH", "").lower() == "true",
            "executed_by": kv.get("EXECUTED_BY") == "CLOUD_2WB",
            "completion_id": bool(kv.get("COMPLETION_ID")),
        }
        if all(checks.values()):
            t["state"] = "CLOSED"
            t["verified_by"] = "CLOUD_1WB"
            t["verified_at"] = now_iso()
            t["verify_checks"] = checks
            t["result_comment_id"] = res["id"]
            note_hist(led, "CLOUD_1WB", "verify_close", order_id=oid,
                      result_comment_id=res["id"], checks=checks)
            okc, head, r = write_led(
                store, led, head,
                "[K55-SECTEST-1WB] CLOSED %s (verified via GET %s)"
                % (oid, res["id"]))
            log("CLOSED", oid, "comment=%s" % res["id"], "commit_ok=%s" % okc)
            out["closed"].append(oid)
            if okc:
                led, head = read_led(store)
        else:
            note_reject(led, "RESULT_VERIFY_FAILED", oid, json.dumps(checks))
            write_led(store, led, head, "[K55-SECTEST-1WB] verify failed %s" % oid)
            out["failed"].append(oid)
            log("VERIFY_FAILED", oid, json.dumps(checks))
    print("SECTEST_SUMMARY " + json.dumps(out, ensure_ascii=False))
    return 0


def status():
    store = GitHubStore(TOKEN, REPO, BRANCH)
    led, head = read_led(store)
    print(json.dumps({
        "ledger": SECTEST_LEDGER, "state": led.get("state"),
        "known_orders": led.get("known_orders"),
        "executed_order_ids": led.get("executed_order_ids"),
        "tasks": {oid: {"state": t.get("state"),
                        "claimer": t.get("claimer"),
                        "exec_events": len(t.get("exec_events", [])),
                        "result_comment_id": t.get("result_comment_id"),
                        "rejections": [x.get("type") for x in t.get("rejections", [])]}
                  for oid, t in led.get("tasks", {}).items()},
        "rejection_counts": led.get("rejection_counts"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "exec-all"
    fn = {"exec-all": exec_all, "verify": verify, "status": status}.get(cmd)
    if fn is None:
        print("unknown mode", cmd)
        sys.exit(2)
    sys.exit(fn())
