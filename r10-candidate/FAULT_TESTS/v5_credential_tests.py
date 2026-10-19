# -*- coding: utf-8 -*-
"""
R10 V5 凭据安全测试 (Plan A 最终实现：watcher 进程内获取凭据, bridge 仅作不打印明文诊断)：
  V5a-1  假凭据泄漏测试：bridge --check 仅输出状态/长度，不得把 secret 输出到 stdout/stderr。
  V5a-2  假凭据经测试钩子进程内流入 watcher：watcher 取得 fake(长度匹配)，且 fake 不出现在 watcher 日志/stdout/stderr。
  V5b    鉴权失败测试：无凭据 -> watcher CRED_FOUND=NO 并 exit 0，无 secret 泄漏。
全部封闭化(不触碰 GitHub)，通过 R10_TEST_NO_OP 钩子使 watcher 在凭据核验后立即退出。
"""
import os
import sys
import json
import time
import shutil
import subprocess
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATE = os.path.join(REPO_ROOT, "PROD_CANDIDATE")
WATCHER = os.path.join(CANDIDATE, "2WB_inbox_watcher.ps1")
BRIDGE = os.path.join(CANDIDATE, "2WB_pat_bridge.py")
PYEXE = r"C:\Users\59605\.workbuddy\binaries\python\versions\3.13.12\python.exe"
FAKE = "FAKE_PAT_LEAKTEST_9f3c2a1b8e7d4650ac12"

results = []


def record(tid, verdict, note):
    results.append({"test_id": tid, "verdict": verdict, "note": note})
    print(f"[{tid}] {verdict} :: {note}")


def base_env():
    env = os.environ.copy()
    env.pop("GITHUB_PAT", None)          # 清掉真实 token，迫使走 bridge
    env.pop("R10_TEST_FAKE_PAT", None)
    env.pop("R10_TEST_FORCE_NO_CRED", None)
    env.pop("R10_TEST_NO_OP", None)
    return env


def run_watcher_dryrun(tmp_dir, extra_env):
    env = base_env()
    env["USERPROFILE"] = tmp_dir          # 隔离工作目录(日志/队列)到临时区
    env["R10_TEST_NO_OP"] = "1"
    env.update(extra_env)
    p = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", WATCHER, "-DryRun"],
        env=env, capture_output=True, text=True, timeout=40)
    log_path = os.path.join(tmp_dir, ".workbuddy", "github_inbox_watcher", "watcher.log")
    log_text = ""
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            log_text = f.read()
    return p, log_text


# ---------- V5a-1: bridge --check 不输出 secret ----------
def test_v5a1():
    env = base_env()
    env["R10_TEST_FAKE_PAT"] = FAKE
    # --check 模式仅打印状态与长度, 绝不打印明文; 确定性, 无需超时/kill。
    p = subprocess.run([PYEXE, BRIDGE, "--check"], env=env, capture_output=True, text=True, timeout=10)
    out = (p.stdout or "") + (p.stderr or "")
    leaked = FAKE in out
    record("V5a-1", "FAIL" if leaked else "PASS",
           f"bridge --check stdout/stderr 含 secret={leaked}; rc={p.returncode}; out={out.strip()[:90]!r}")


# ---------- V5a-2: fake 经管道流入 watcher ----------
def test_v5a2():
    tmp = tempfile.mkdtemp(prefix="r10v5a2_")
    try:
        p, log_text = run_watcher_dryrun(tmp, {"R10_TEST_FAKE_PAT": FAKE})
        stdout = (p.stdout or "") + (p.stderr or "")
        has_len = f"TOKEN_LEN={len(FAKE)}" in log_text
        leaked = (FAKE in log_text) or (FAKE in stdout)
        ok = has_len and (not leaked) and (p.returncode == 0)
        verdict = "PASS" if ok else "FAIL"
        record("V5a-2", verdict,
               f"watcher CRED_FOUND length匹配={has_len}; fake泄漏={leaked}; rc={p.returncode}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- V5b: 鉴权失败 ----------
def test_v5b():
    tmp = tempfile.mkdtemp(prefix="r10v5b_")
    try:
        p, log_text = run_watcher_dryrun(tmp, {"R10_TEST_FORCE_NO_CRED": "1"})
        stdout = (p.stdout or "") + (p.stderr or "")
        no_cred = "CRED_FOUND=NO" in log_text
        leaked = (FAKE in log_text) or (FAKE in stdout)
        ok = no_cred and (not leaked) and (p.returncode == 0)
        verdict = "PASS" if ok else "FAIL"
        record("V5b", verdict,
               f"watcher CRED_FOUND=NO={no_cred}; 泄漏={leaked}; rc={p.returncode}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_v5a1()
    test_v5a2()
    test_v5b()
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    print(f"\nV5 SUMMARY: {passed}/{len(results)} PASS")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "V5_CREDENTIAL_RESULTS.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    sys.exit(0 if passed == len(results) else 1)
