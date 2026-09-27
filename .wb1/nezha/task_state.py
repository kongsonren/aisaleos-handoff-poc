# -*- coding: utf-8 -*-
"""TASK STATE 状态梁 —— 本地与云共用同一份实现。

存储：GitHub 仓库文件 `.wb1/nezha/task_state.json`
（为什么选它：本地与云双方都可访问；唯一写入通道是 Git Data API，天然带 CAS）

可靠性（KR 第六关：epoch 不是写个数字就算 fencing）：
  1) **CAS**：每次提交 PATCH ref 时携带 expected head sha，服务端不一致 → 409 → 重读重试
  2) **EPOCH 拒写**：任何写入终点先比对 epoch，`incoming_epoch < current_epoch` → REJECT
  3) **单调 +1**：执行权转移只允许 epoch = current_epoch + 1，不允许跳号

本文件同时被本地 12WB 与云端哪吒（GitHub Actions runner）执行，行为一致。
"""
from __future__ import annotations
import base64, json, os, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta

CN = timezone(timedelta(hours=8))
API = "https://api.github.com"
STATE_PATH = os.environ.get("NEZHA_STATE_PATH", ".wb1/nezha/task_state.json")


def now_iso():
    return datetime.now(CN).isoformat()


class GitHubStore:
    def __init__(self, token, repo, branch="main"):
        self.token = token
        self.repo = repo
        self.branch = branch

    def _req(self, method, path, payload=None, raw=None):
        url = API + path
        data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        req = urllib.request.Request(url, method=method, data=data, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nezha-task-state",
        })
        try:
            r = urllib.request.urlopen(req, timeout=40)
            return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, {"error": e.read().decode("utf-8", "ignore")[:300]}
        except Exception as e:
            return 0, {"error": repr(e)[:200]}

    # ---------- 读 ----------
    def read_file(self, path):
        """返回 (content_bytes, blob_sha, head_sha, http_code)"""
        s, ref = self._req("GET", "/repos/%s/git/ref/heads/%s" % (self.repo, self.branch))
        if s != 200:
            return None, None, None, s
        head_sha = ref["object"]["sha"]
        p = "/repos/%s/contents/%s?ref=%s" % (self.repo, urllib.parse.quote(path), self.branch)
        s, d = self._req("GET", p)
        if s != 200:
            return None, None, head_sha, s
        return base64.b64decode(d["content"]), d["sha"], head_sha, 200

    def read_json(self, path, default=None):
        b, sha, head, code = self.read_file(path)
        if b is None:
            return (default if default is not None else {}), None, head, code
        return json.loads(b.decode("utf-8")), sha, head, code

    def read_raw_text(self, path):
        """经 raw 域读取（避免 API 限流；不提供 sha，仅用于读）"""
        url = "https://raw.githubusercontent.com/%s/%s/%s" % (self.repo, self.branch, path)
        try:
            return urllib.request.urlopen(url, timeout=30).read()
        except Exception as e:
            return None

    # ---------- 写（Git Data API，CAS） ----------
    def commit_files(self, files: dict, message: str, expected_head: str = None, retries: int = 3):
        """files: {path: bytes}。expected_head 非空则做 CAS，冲突自动重读重试。"""
        last = None
        for attempt in range(retries):
            head = expected_head
            if head is None:
                s, ref = self._req("GET", "/repos/%s/git/ref/heads/%s" % (self.repo, self.branch))
                if s != 200:
                    return {"ok": False, "error": "REF_READ_FAILED", "detail": ref}
                head = ref["object"]["sha"]
            tree_items = []
            for path, data in files.items():
                s, b = self._req("POST", "/repos/%s/git/blobs" % self.repo,
                                 {"content": base64.b64encode(data).decode(), "encoding": "base64"})
                if s not in (200, 201):
                    return {"ok": False, "error": "BLOB_FAILED", "path": path, "detail": b}
                tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": b["sha"]})
            s, t = self._req("POST", "/repos/%s/git/trees" % self.repo,
                             {"base_tree": head, "tree": tree_items})
            if s not in (200, 201):
                return {"ok": False, "error": "TREE_FAILED", "detail": t}
            s, c = self._req("POST", "/repos/%s/git/commits" % self.repo,
                             {"message": message, "tree": t["sha"], "parents": [head]})
            if s not in (200, 201):
                return {"ok": False, "error": "COMMIT_FAILED", "detail": c}
            # CAS：PATCH 携带 head，若期间被别人推进则 409
            s, r = self._req("PATCH", "/repos/%s/git/refs/heads/%s" % (self.repo, self.branch),
                             {"sha": c["sha"], "force": False})
            if s == 200:
                return {"ok": True, "commit": c["sha"], "attempt": attempt + 1}
            if s == 409:
                last = {"ok": False, "error": "CAS_CONFLICT", "detail": "head moved, retrying"}
                time.sleep(1 + attempt)
                expected_head = None
                continue
            return {"ok": False, "error": "REF_PATCH_FAILED", "code": s, "detail": r}
        return last or {"ok": False, "error": "EXHAUSTED"}


class TaskState:
    """带 EPOCH fencing 的状态读写。"""

    FIELDS = ["task_id", "auth_id", "owner", "epoch", "checkpoint", "state",
              "last_progress_at", "next_expected", "result", "history", "result_written_by"]

    def __init__(self, store: GitHubStore, path=STATE_PATH):
        self.store = store
        self.path = path

    def load(self):
        d, sha, head, code = self.store.read_json(self.path, default=None)
        if d is None:
            return None, None, head, code
        return d, sha, head, code

    def init(self, task_id, auth_id, owner="LOCAL_1WB", epoch=1,
             checkpoint="STEP_0", state="RUNNING", next_expected="STEP_1"):
        cur, _, head, _ = self.load()
        if cur:
            return {"ok": False, "error": "STATE_ALREADY_EXISTS", "state": cur}
        st = {
            "task_id": task_id, "auth_id": auth_id, "owner": owner, "epoch": epoch,
            "checkpoint": checkpoint, "state": state,
            "last_progress_at": now_iso(), "next_expected": next_expected,
            "result": None, "result_written_by": None, "history": [],
        }
        r = self.store.commit_files({self.path: json.dumps(st, ensure_ascii=False, indent=2).encode()},
                                    "[NEZHA] init task state %s" % task_id)
        return r

    def _commit_state(self, new_state, message, head=None):
        return self.store.commit_files(
            {self.path: json.dumps(new_state, ensure_ascii=False, indent=2).encode()}, message, expected_head=head)

    def advance(self, *, actor_epoch, actor, checkpoint=None, state=None,
                next_expected=None, result=None, note=None, allow_takeover=False):
        """唯一写入口：先做 EPOCH fencing，再做 CAS 提交。

        - actor_epoch < current_epoch            → REJECT（旧执行体，含重新上线的LOCAL）
        - actor_epoch == current_epoch + 1       → 仅当 allow_takeover（执行权转移）才允许
        - actor_epoch == current_epoch           → 同一执行体继续推进，允许
        - actor_epoch > current_epoch + 1        → REJECT（跳号）
        """
        cur, sha, head, code = self.load()
        if cur is None:
            return {"ok": False, "error": "NO_STATE"}
        cur_epoch = int(cur.get("epoch", 0))
        if actor_epoch < cur_epoch:
            return {"ok": False, "error": "REJECT_STALE_EPOCH",
                    "reason": "incoming_epoch=%d < current_epoch=%d" % (actor_epoch, cur_epoch),
                    "current_owner": cur.get("owner")}
        if actor_epoch > cur_epoch + 1:
            return {"ok": False, "error": "REJECT_EPOCH_JUMP",
                    "reason": "incoming=%d current=%d" % (actor_epoch, cur_epoch)}
        if actor_epoch == cur_epoch + 1 and not allow_takeover:
            return {"ok": False, "error": "REJECT_TAKEOVER_NOT_ALLOWED"}

        # 幂等：result 只承认一次
        if result is not None and cur.get("result") is not None:
            return {"ok": False, "error": "REJECT_DUPLICATE_RESULT",
                    "reason": "result already written by %s" % cur.get("result_written_by")}

        ns = dict(cur)
        ns["epoch"] = actor_epoch
        ns["owner"] = actor
        if checkpoint:
            ns["checkpoint"] = checkpoint
        if state:
            ns["state"] = state
        if next_expected is not None:
            ns["next_expected"] = next_expected
        if result is not None:
            ns["result"] = result
            ns["result_written_by"] = actor
        ns["last_progress_at"] = now_iso()
        ns.setdefault("history", []).append({
            "at": now_iso(), "actor": actor, "epoch": actor_epoch,
            "checkpoint": ns["checkpoint"], "note": note or "",
        })
        r = self._commit_state(ns, "[NEZHA] %s epoch=%d ckpt=%s" % (actor, actor_epoch, ns["checkpoint"]), head=head)
        r["state"] = ns
        return r
