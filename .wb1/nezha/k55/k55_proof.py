# -*- coding: utf-8 -*-
"""K55 加固版 · 双轮云端自治（非生产 / 分支隔离 / K55-* 命名空间）

KR-NEZHA-CLOUD-K55-HARDEN-20261020 施工件。
两个独立云端主体（各自 workflow / runner / schedule，只经 Issue #8 + 状态账本通信）：

  tick -> 1WB 云端（k55-cloud-proof.yml, cron */5）：
          状态机 IDLE -> 派唯一只读测试令到 Issue #8 -> DISPATCHED；
          扫 Issue #8 找 [RESULT][2WB] -> GET 回读核验 -> CLOSED -> IDLE；
          每 tick 至多一个动作；周期上限 K55_MAX_CYCLES（默认 1=唯一测试令）。
  exec -> 2WB 云端（k55-cloud-2wb.yml, cron 错峰 2-59/5）：
          扫 Issue #8 未处理 [TO-2WB][TASK]；五要素授权校验；
          dedup（同 ORDER_ID 最多执行一次，重复投递类型化拒绝不重执）；
          真实重算 READONLY_SHA256；先 [ACK-2WB] 后 [RESULT][2WB]；
          连续失败 >=3 熔断（circuit_open），失败隔离不无限重试。

铁律：
  · 1WB 只发 [TO-2WB][TASK]；2WB 只发 [ACK-2WB]/[RESULT][2WB]；严禁 1WB 代 2WB 生成 ACK/RESULT
  · 仅 secrets.GITHUB_TOKEN（runner 内置，不落本地/不进仓库）
  · 仅读写分支 k55-proof 上的 K55-* 文件，绝不碰 main 上的 live 8051 循环
  · 状态读写经 GitHubStore（Git Data API，CAS）
  · PAT 不在本文件出现；本文件设计为同时在 runner（GITHUB_TOKEN）与本地（调试）运行

历史角色（K55 第二关 CLOUD_READY 取证，保留备查）：prep / legacy_exec / close
"""
from __future__ import annotations
import base64, hashlib, json, os, re, sys, time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from task_state import GitHubStore, now_iso  # noqa: E402

CN = timezone(timedelta(hours=8))
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("MOZI_GH_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY", "kongsonren/aisaleos-handoff-poc")
BRANCH = os.environ.get("K55_BRANCH", "k55-proof")
ISSUE = os.environ.get("K55_ISSUE", "8")
ANCHOR_COMMENT_ID = os.environ.get("K55_ANCHOR_COMMENT_ID", "6272173951")
TRUSTED_ISSUER = os.environ.get("K55_TRUSTED_ISSUER", "kongsonren")
PARENT_ORDER = os.environ.get("K55_PARENT_ORDER", "KR-NEZHA-CLOUD-K55-20261019")
ORDER_FAMILY = os.environ.get("K55_ORDER_FAMILY", "KR-NEZHA-CLOUD-K55-HARDEN-20261020")
MAX_CYCLES = int(os.environ.get("K55_MAX_CYCLES", "1"))
RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
SCOPE_WHITELIST = {"READONLY_SHA256"}
ORDER_ID_RE = re.compile(r"^KR-NEZHA-CLOUD-K55-HARDEN-\d{8}-DW\d+$")
CLOCK_SKEW = 300  # 允许的时钟偏差（秒）

DW_LEDGER = ".wb1/nezha/k55/k55_dualwheel.json"
TARGET = ".wb1/nezha/k55/k55_test_target.dat"
MARK_TASK = "[TO-2WB][TASK]"
MARK_ACK = "[ACK-2WB]"
MARK_RESULT = "[RESULT][2WB]"


def log(*a):
    print("[K55]", *a, flush=True)


def api(method, path, payload=None):
    """Issue/评论域 API（与 GitHubStore 同源实现，token 仅内存）。"""
    url = "https://api.github.com" + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, method=method, data=data, headers={
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "k55-hardendualwheel",
    })
    try:
        r = urllib.request.urlopen(req, timeout=40)
        return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "ignore")[:300]}
    except Exception as e:
        return 0, {"error": repr(e)[:200]}


import urllib.request, urllib.error  # noqa: E402  (置于 api 定义后仅作依赖声明)


def parse_kv_body(body):
    """'KEY: value' 行式信封 -> dict；无法识别的行忽略。"""
    out = {}
    for ln in body.splitlines():
        m = re.match(r"^([A-Z_]+):\s*(.+)$", ln.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def parse_dt(s):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def sha256_file(store, path):
    b, sha, head, code = store.read_file(path)
    if b is None:
        return None, code
    return hashlib.sha256(b).hexdigest(), code


def read_dw(store):
    d, _, head, _ = store.read_json(DW_LEDGER, default=None)
    if d is None:
        d = {"state": "IDLE", "order_seq": 0, "cycles_done": 0, "current_order": None,
             "tasks": {}, "executed_order_ids": [], "rejections": [], "rejection_counts": {},
             "circuit": {"consecutive_failures": 0, "open": False, "opened_at": None,
                         "reason": None},
             "history": []}
    d.setdefault("rejection_counts", {})
    return d, head


def write_dw(store, data, head, msg):
    r = store.commit_files({DW_LEDGER: json.dumps(data, ensure_ascii=False, indent=2).encode()},
                           msg, expected_head=head)
    return r


def note_reject(led, rtype, order_id, detail=""):
    key = "%s:%s" % (rtype, order_id)
    led["rejection_counts"][key] = {
        "count": led["rejection_counts"].get(key, {}).get("count", 0) + 1,
        "last_at": now_iso(), "last_run": RUN_ID, "detail": detail[:200],
    }
    led["rejections"] = (led.get("rejections", []) + [{
        "type": rtype, "order_id": order_id, "at": now_iso(),
        "run": RUN_ID, "detail": detail[:200]}])[-30:]


def note_hist(led, actor, action, **kw):
    led.setdefault("history", []).append(
        dict(at=now_iso(), actor=actor, action=action, run=RUN_ID, **kw))
    led["history"] = led["history"][-60:]


# ==================== 1WB 云端：状态机 tick（派令 / 核验 / 关闭） ====================
def render_order_body(o):
    return "\n".join([
        MARK_TASK,
        "ORDER_ID: %s" % o["order_id"],
        "TASK_ID: %s" % o["task_id"],
        "ANCHOR_COMMENT_ID: %s" % o["anchor_comment_id"],
        "PARENT_ORDER: %s" % o["parent_order"],
        "ISSUER: %s" % o["issuer"],
        "SCOPE: %s" % o["scope"],
        "TARGET: %s" % o["target"],
        "EXPECTED_SHA256: %s" % o["expected_sha256"],
        "ISSUED_AT: %s" % o["issued_at"],
        "TTL_SECONDS: %s" % o["ttl_seconds"],
        "NOTE: 第55刀加固令·双轮云端自治唯一只读测试令（非生产/分支隔离）。"
        "请独立云端2WB消费者完成五要素授权校验后执行 READONLY_SHA256 并回传 RESULT。",
    ])


def _get_page(p, per=100):
    s, j = api("GET", "/repos/%s/issues/%s/comments?per_page=%d&page=%d" % (REPO, ISSUE, per, p))
    if s != 200 or not isinstance(j, list):
        return None
    return j


def _last_page(per=100):
    """二分定位末页（越界页 GitHub 返回 200 空列表）。"""
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


def scan_issue8_orders(max_pages=3):
    """扫 Issue #8 评论，返回 (严格格式的派令列表, 原始 [TO-2WB][TASK] 条数)。

    末页二分定位 + 只读末 max_pages 页（K55 派令永远是最新的，避免全量翻页）。
    """
    orders, seen, total_raw = [], set(), 0
    lp = _last_page()
    if lp == 0:
        return orders, total_raw
    pages = []
    p = lp
    while p >= 1 and len(pages) < max_pages:
        pg = _get_page(p)
        if not pg:
            break
        pages.append(pg)
        p -= 1
    for pg in reversed(pages):  # 时序正序（旧->新）
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
    """扫 Issue #8 找引用该 ORDER_ID 的 [RESULT][2WB] 评论（末页起倒序，找到即止）。"""
    lp = _last_page()
    p = lp
    found = []
    while p >= 1:
        pg = _get_page(p)
        if not pg:
            break
        for c in reversed(pg):  # 新->旧
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


def role_1wb_tick():
    store = GitHubStore(TOKEN, REPO, BRANCH)
    if not TOKEN:
        log("FATAL no token"); return 2
    led, head = read_dw(store)
    st = led.get("state", "IDLE")
    log("tick state=%s cycles_done=%s/%s circuit_open=%s" % (
        st, led.get("cycles_done"), MAX_CYCLES, led["circuit"]["open"]))

    if led["circuit"]["open"]:
        log("circuit OPEN (%s) -> 隔离待命，不动作" % led["circuit"].get("reason"))
        return 0

    if st == "DISPATCHED":
        o = led["current_order"]
        oid = o["order_id"]
        # 超时隔离：TTL 内无 RESULT -> FAILED_ISOLATED（不无限等待）
        iss = parse_dt(o["issued_at"])
        ttl = int(o.get("ttl_seconds", 3600))
        if iss and datetime.now(CN) > iss + timedelta(seconds=ttl):
            led["circuit"] = {"consecutive_failures": led["circuit"].get("consecutive_failures", 0) + 1,
                              "open": True, "opened_at": now_iso(),
                              "reason": "TTL_EXPIRED_NO_RESULT:%s" % oid}
            led["state"] = "FAILED_ISOLATED"
            note_hist(led, "CLOUD_1WB", "isolate_ttl", order_id=oid)
            r = write_dw(store, led, head, "[K55-1WB] FAILED_ISOLATED ttl %s" % oid)
            log("ISOLATED ttl_expired_no_result", oid, r.get("ok"))
            return 0
        res = find_result_comment(oid)
        if not res:
            log("waiting RESULT for", oid)
            return 0
        # GET 回读精确核验（不信扫描列表，回源 API）
        s, c = api("GET", "/repos/%s/issues/comments/%s" % (REPO, res["id"]))
        if s != 200:
            note_reject(led, "RESULT_COMMENT_GET_FAILED", oid, "http=%s" % s)
            r = write_dw(store, led, head, "[K55-1WB] result get failed %s" % oid)
            log("RESULT GET failed", s)
            return 0
        kv = parse_kv_body(c.get("body") or "")
        checks = {
            "marker": MARK_RESULT in (c.get("body") or ""),
            "order_id": kv.get("ORDER_ID") == oid,
            "computed_sha256": kv.get("COMPUTED_SHA256") == o.get("expected_sha256"),
            "match": kv.get("MATCH", "").lower() == "true",
            "executed_by": kv.get("EXECUTED_BY") == "CLOUD_2WB",
            "completion_id": bool(kv.get("COMPLETION_ID")),
        }
        if all(checks.values()):
            t = led["tasks"].get(oid, {})
            t.update({"state": "CLOSED", "result_comment_id": res["id"],
                      "ack_comment_id": t.get("ack_comment_id"),
                      "verified_by": "CLOUD_1WB", "verified_at": now_iso(),
                      "verify_checks": checks, "result_kv": kv})
            led["tasks"][oid] = t
            led["state"] = "IDLE"
            led["cycles_done"] = led.get("cycles_done", 0) + 1
            led["current_order"] = dict(o, closed_at=now_iso(), result_comment_id=res["id"])
            led["circuit"]["consecutive_failures"] = 0
            note_hist(led, "CLOUD_1WB", "verify_close", order_id=oid,
                      result_comment_id=res["id"], checks=checks)
            r = write_dw(store, led, head, "[K55-1WB] CLOSED %s (verified via GET %s)" % (oid, res["id"]))
            log("CLOSED", oid, "result_comment=%s" % res["id"], "commit_ok=%s" % r.get("ok"))
            return 0
        note_reject(led, "RESULT_VERIFY_FAILED", oid, json.dumps(checks, ensure_ascii=False))
        r = write_dw(store, led, head, "[K55-1WB] verify failed %s" % oid)
        log("VERIFY_FAILED", oid, json.dumps(checks, ensure_ascii=False), "commit_ok=%s" % r.get("ok"))
        return 0

    if st == "IDLE":
        if led.get("cycles_done", 0) >= MAX_CYCLES:
            log("cycle cap reached (%s/%s) -> 不再派新令（唯一测试令纪律）" % (
                led.get("cycles_done"), MAX_CYCLES))
            return 0
        # 派发唯一只读测试令
        h, code = sha256_file(store, TARGET)
        if h is None:
            log("FATAL cannot read target", code); return 2
        seq = led.get("order_seq", 0) + 1
        oid = "%s-DW%d" % (ORDER_FAMILY, seq)
        o = {
            "order_id": oid, "task_id": "K55-HARDEN-2WB-DW%d" % seq,
            "anchor_comment_id": ANCHOR_COMMENT_ID, "parent_order": PARENT_ORDER,
            "issuer": "CLOUD_1WB", "scope": "READONLY_SHA256", "target": TARGET,
            "expected_sha256": h, "issued_at": now_iso(), "ttl_seconds": 3600,
            "target_sha16": h[:16],
        }
        s, c = api("POST", "/repos/%s/issues/%s/comments" % (REPO, ISSUE),
                   {"body": render_order_body(o)})
        if s != 201:
            led["circuit"]["consecutive_failures"] += 1
            if led["circuit"]["consecutive_failures"] >= 3:
                led["circuit"].update({"open": True, "opened_at": now_iso(),
                                       "reason": "DISPATCH_POST_FAILED"})
                led["state"] = "FAILED_ISOLATED"
            note_reject(led, "DISPATCH_POST_FAILED", oid, "http=%s" % s)
            r = write_dw(store, led, head, "[K55-1WB] dispatch post failed %s http=%s" % (oid, s))
            log("DISPATCH POST failed", s, r.get("ok"))
            return 1
        # POST 自核：GET 回读派令评论
        s2, c2 = api("GET", "/repos/%s/issues/comments/%s" % (REPO, c["id"]))
        post_ok = (s2 == 200 and oid in (c2.get("body") or "") and MARK_TASK in (c2.get("body") or ""))
        o["dispatch_comment_id"] = c["id"]
        led["state"] = "DISPATCHED"
        led["current_order"] = o
        led["order_seq"] = seq
        led["tasks"][oid] = {"state": "DISPATCHED", "dispatched_by": "CLOUD_1WB",
                             "dispatched_at": now_iso(), "dispatch_comment_id": c["id"],
                             "expected_sha256": h, "target": TARGET,
                             "post_selfcheck": {"get_status": s2, "order_in_body": post_ok}}
        note_hist(led, "CLOUD_1WB", "dispatch", order_id=oid, comment_id=c["id"],
                  target_sha16=h[:16], post_selfcheck=post_ok)
        r = write_dw(store, led, head, "[K55-1WB] DISPATCHED %s (comment %s, selfcheck=%s)" % (
            oid, c["id"], post_ok))
        log("DISPATCHED", oid, "comment=%s" % c["id"], "target_sha16=%s" % h[:16],
            "selfcheck=%s" % post_ok, "commit_ok=%s" % r.get("ok"))
        return 0 if r.get("ok") else 1

    if st == "FAILED_ISOLATED":
        log("FAILED_ISOLATED -> 待命不动作"); return 0
    log("unknown state", st); return 0


# ==================== 2WB 云端：独立消费者 exec（验权 / 执行 / 回传） ====================
def role_2wb_exec():
    store = GitHubStore(TOKEN, REPO, BRANCH)
    if not TOKEN:
        log("FATAL no token"); return 2
    led, head = read_dw(store)
    if led["circuit"]["open"]:
        log("circuit OPEN (%s) -> 消费者隔离，不接令" % led["circuit"].get("reason"))
        return 0

    orders, raw = scan_issue8_orders(max_pages=3)
    log("scan issue#%s: %d raw [TO-2WB][TASK], %d strict-family" % (ISSUE, raw, len(orders)))
    if not orders:
        return 0

    # 重复投递拒绝（已执行/已关闭的同 ORDER_ID，不重执）——逐条记录
    dups = []
    for o in orders:
        oid = o["ORDER_ID"]
        t = led["tasks"].get(oid) or {}
        if oid in led.get("executed_order_ids", []) or t.get("state") in ("EXECUTED", "CLOSED"):
            dups.append(oid)
            note_reject(led, "REJECT_DUPLICATE_ORDER", oid,
                        "state=%s executed_before=%s" % (t.get("state"), oid in led.get("executed_order_ids", [])))
    if dups:
        r = write_dw(store, led, head, "[K55-2WB] duplicate orders rejected (no re-exec): %s" % ",".join(dups))
        log("REJECT_DUPLICATE_ORDER", dups, "commit_ok=%s" % r.get("ok"))
        if r.get("ok"):
            led, head = read_dw(store)
        # 继续尝试执行未处理的新令（若有）

    todo = [o for o in orders
            if o["ORDER_ID"] not in led.get("executed_order_ids", [])
            and (led["tasks"].get(o["ORDER_ID"]) or {}).get("state") not in ("EXECUTED", "CLOSED")]
    if not todo:
        log("no unprocessed order (dups rejected above if any)")
        return 0

    o = todo[0]  # FIFO：最旧未处理令优先；每次运行至多执行一次（幂等）
    oid = o["ORDER_ID"]

    # ---------- 五要素授权校验 ----------
    def reject(rtype, detail):
        note_reject(led, rtype, oid, detail)
        r = write_dw(store, led, head, "[K55-2WB] auth reject %s %s" % (rtype, oid))
        log("AUTH_REJECT", rtype, oid, detail, "commit_ok=%s" % r.get("ok"))
        return 0

    # ① 授权锚点：锚评论存在 + 作者为可信发令者 + 含父 ORDER_ID（且锚 ID 在允许清单）
    if o.get("ANCHOR_COMMENT_ID") != ANCHOR_COMMENT_ID:
        return reject("ANCHOR_NOT_ALLOWLISTED", "anchor=%s allow=%s" % (
            o.get("ANCHOR_COMMENT_ID"), ANCHOR_COMMENT_ID))
    s, ac = api("GET", "/repos/%s/issues/comments/%s" % (REPO, ANCHOR_COMMENT_ID))
    if s != 200:
        return reject("ANCHOR_MISSING", "http=%s" % s)
    if (ac.get("user") or {}).get("login") != TRUSTED_ISSUER:
        return reject("ANCHOR_UNAUTHORIZED", "author=%s" % (ac.get("user") or {}).get("login"))
    if PARENT_ORDER not in (ac.get("body") or ""):
        return reject("PARENT_ORDER_MISMATCH", "parent=%s" % o.get("PARENT_ORDER"))
    # ② ORDER_ID 格式 + 家族绑定
    if not ORDER_ID_RE.match(oid) or not oid.startswith(ORDER_FAMILY):
        return reject("ORDER_FORMAT", oid)
    # ③ 发令者字段
    if o.get("ISSUER") != "CLOUD_1WB":
        return reject("ISSUER_MISMATCH", o.get("ISSUER"))
    # ④ scope 白名单
    if o.get("SCOPE") not in SCOPE_WHITELIST:
        return reject("SCOPE_VIOLATION", o.get("SCOPE"))
    # ⑤ 有效期窗
    iss = parse_dt(o.get("ISSUED_AT", ""))
    ttl = int(o.get("TTL_SECONDS", "0") or 0)
    if not iss or ttl <= 0:
        return reject("VALIDITY_MALFORMED", "issued_at=%s ttl=%s" % (o.get("ISSUED_AT"), ttl))
    now = datetime.now(CN)
    if now < iss - timedelta(seconds=CLOCK_SKEW):
        return reject("NOT_YET_VALID", "issued_at=%s" % o["ISSUED_AT"])
    if now > iss + timedelta(seconds=ttl):
        return reject("TTL_EXPIRED", "issued_at=%s ttl=%s" % (o["ISSUED_AT"], ttl))
    # ⑥ 目标与预期 SHA 存在性
    if not o.get("TARGET") or not o.get("EXPECTED_SHA256"):
        return reject("TARGET_MALFORMED", "target=%s" % o.get("TARGET"))

    log("AUTH_OK", oid, "(anchor=%s issuer=%s scope=%s ttl=%s)" % (
        ANCHOR_COMMENT_ID, o.get("ISSUER"), o.get("SCOPE"), ttl))

    # ---------- 真实执行：本 runner 独立重算 SHA ----------
    h, code = sha256_file(store, o["TARGET"])
    if h is None:
        led["circuit"]["consecutive_failures"] += 1
        if led["circuit"]["consecutive_failures"] >= 3:
            led["circuit"].update({"open": True, "opened_at": now_iso(),
                                   "reason": "TARGET_READ_FAILED"})
            led["state"] = "FAILED_ISOLATED"
        note_reject(led, "EXEC_TARGET_READ_FAILED", oid, "http=%s" % code)
        r = write_dw(store, led, head, "[K55-2WB] target read failed %s http=%s" % (oid, code))
        log("EXEC target read failed", code, "commit_ok=%s" % r.get("ok"))
        return 1
    match = (h == o.get("EXPECTED_SHA256"))

    # ---------- 先 ACK 后 RESULT（2WB 专属标记，1WB 永不代写） ----------
    ack_body = ("%s trigger_comment_id=%s received_at=%s watcher_run=%s order_id=%s consumer=CLOUD_2WB"
                % (MARK_ACK, o["_comment_id"], now_iso(), RUN_ID, oid))
    s, ac2 = api("POST", "/repos/%s/issues/%s/comments" % (REPO, ISSUE), {"body": ack_body})
    ack_id = ac2.get("id") if s == 201 else None
    if s != 201:
        led["circuit"]["consecutive_failures"] += 1
        note_reject(led, "ACK_POST_FAILED", oid, "http=%s" % s)
        r = write_dw(store, led, head, "[K55-2WB] ack post failed %s http=%s" % (oid, s))
        log("ACK POST failed", s, "commit_ok=%s" % r.get("ok"))
        return 1
    log("ACK", oid, "comment=%s" % ack_id)

    cid = "K55-2WB-%s" % hashlib.sha256((oid + h + str(match) + RUN_ID).encode()).hexdigest()[:12]
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
        "EXECUTED_AT: %s" % now_iso(),
        "ACK_COMMENT_ID: %s" % (ack_id or ""),
    ])
    s, rc = api("POST", "/repos/%s/issues/%s/comments" % (REPO, ISSUE), {"body": res_body})
    if s != 201:
        led["circuit"]["consecutive_failures"] += 1
        if led["circuit"]["consecutive_failures"] >= 3:
            led["circuit"].update({"open": True, "opened_at": now_iso(),
                                   "reason": "RESULT_POST_FAILED"})
            led["state"] = "FAILED_ISOLATED"
        note_reject(led, "RESULT_POST_FAILED", oid, "http=%s" % s)
        r = write_dw(store, led, head, "[K55-2WB] result post failed %s http=%s" % (oid, s))
        log("RESULT POST failed", s, "commit_ok=%s" % r.get("ok"))
        return 1

    t = led["tasks"].get(oid, {})
    t.update({
        "state": "EXECUTED",
        "result": {"status": "PASS" if match else "FAIL", "computed_sha256": h,
                   "match": bool(match), "executed_by": "CLOUD_2WB",
                   "completion_id": cid, "executed_at": now_iso(), "run_id": RUN_ID},
        "result_written_by": "CLOUD_2WB",
        "ack_comment_id": ack_id, "result_comment_id": rc.get("id"),
        "dispatch_comment_id": o["_comment_id"],
        "auth_checks": {"anchor": ANCHOR_COMMENT_ID, "issuer": o.get("ISSUER"),
                        "scope": o.get("SCOPE"), "order_format": True, "ttl_window": True},
    })
    led["tasks"][oid] = t
    led.setdefault("executed_order_ids", [])
    if oid not in led["executed_order_ids"]:
        led["executed_order_ids"].append(oid)
    led["circuit"]["consecutive_failures"] = 0
    note_hist(led, "CLOUD_2WB", "execute", order_id=oid, match=bool(match),
              ack_comment_id=ack_id, result_comment_id=rc.get("id"))
    r = write_dw(store, led, head, "[K55-2WB] EXECUTED %s -> %s (ack=%s result=%s)" % (
        oid, "PASS" if match else "FAIL", ack_id, rc.get("id")))
    log("RESULT:", json.dumps(t["result"], ensure_ascii=False))
    print(json.dumps({"role": "2WB_EXEC", "order_id": oid, "status": t["result"]["status"],
                      "ack_comment_id": ack_id, "result_comment_id": rc.get("id"),
                      "completion_id": cid}, ensure_ascii=False))
    return 0 if r.get("ok") else 1


# ==================== 历史角色（K55 第二关 CLOUD_READY 取证，保留备查） ====================
LEDGER = ".wb1/nezha/k55/k55_ledger.json"
EVIDENCE = ".wb1/nezha/k55/k55_proof_evidence.json"
ORDER_ID = os.environ.get("K55_ORDER_ID", "KR-NEZHA-CLOUD-K55-20261019-PROOF")
TASK_ID = "K55-PROOF-2WB-001"


def legacy_prep():
    store = GitHubStore(TOKEN, REPO, BRANCH)
    h, code = sha256_file(store, TARGET)
    if h is None:
        log("FATAL cannot read target", code); return 2
    led, _, _, _ = store.read_json(LEDGER, default={"tasks": {}, "order": {}})
    led["tasks"][TASK_ID] = {"order_id": ORDER_ID, "role": "2WB", "state": "DISPATCHED",
                             "assigned_to": "CLOUD_2WB", "target": TARGET, "expected_sha256": h,
                             "dispatched_by": "CLOUD_1WB", "dispatched_at": now_iso()}
    led["order"] = {"id": ORDER_ID, "state": "1WB_PREP_DONE", "prepared_at": now_iso()}
    r = store.commit_files({LEDGER: json.dumps(led, ensure_ascii=False, indent=2).encode()},
                           "[K55-1WB] legacy prep")
    return 0 if r.get("ok") else 1


def legacy_exec():
    store = GitHubStore(TOKEN, REPO, BRANCH)
    led, _, _, _ = store.read_json(LEDGER, default={"tasks": {}, "order": {}})
    t = led["tasks"].get(TASK_ID)
    if not t or t.get("state") != "DISPATCHED":
        return 3
    h, code = sha256_file(store, t["target"])
    if h is None:
        return 4
    ok = (h == t["expected_sha256"])
    t["state"] = "EXECUTED"
    t["result"] = {"status": "PASS" if ok else "FAIL", "computed_sha256": h, "match": bool(ok),
                   "executed_by": "CLOUD_2WB", "executed_at": now_iso()}
    t["result_written_by"] = "CLOUD_2WB"
    r = store.commit_files({LEDGER: json.dumps(led, ensure_ascii=False, indent=2).encode()},
                           "[K55-2WB] legacy exec")
    return 0 if r.get("ok") else 1


def legacy_close():
    store = GitHubStore(TOKEN, REPO, BRANCH)
    led, _, _, _ = store.read_json(LEDGER, default={"tasks": {}, "order": {}})
    t = led["tasks"].get(TASK_ID)
    if not t or t.get("state") != "EXECUTED" or not t.get("result"):
        return 5
    res = t["result"]
    verified = (res.get("computed_sha256") == t.get("expected_sha256")
                and res.get("match") is True and res.get("executed_by") == "CLOUD_2WB")
    t["state"] = "CLOSED" if verified else "VERIFY_FAILED"
    led["order"]["state"] = t["state"]
    ev = {"order_id": ORDER_ID, "verdict": t["state"], "tier": "CLOUD_READY",
          "computed_sha256": res["computed_sha256"], "closed_at": now_iso()}
    r = store.commit_files({LEDGER: json.dumps(led, ensure_ascii=False, indent=2).encode(),
                            EVIDENCE: json.dumps(ev, ensure_ascii=False, indent=2).encode()},
                           "[K55-1WB] legacy close")
    return 0 if verified else 6


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tick"
    fn = {"tick": role_1wb_tick, "exec": role_2wb_exec,
          "prep": legacy_prep, "legacy_exec": legacy_exec, "close": legacy_close}.get(cmd)
    if fn is None:
        print("unknown role", cmd); sys.exit(2)
    sys.exit(fn())
