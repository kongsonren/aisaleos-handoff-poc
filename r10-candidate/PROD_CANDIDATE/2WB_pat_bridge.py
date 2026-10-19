# -*- coding: utf-8 -*-
"""
2WB_pat_bridge.py — 凭据诊断工具 (KR R10 V5 修复令后：绝不打印明文)。

历史：原设计负责向 watcher 经 stdout 输出明文 PAT，构成泄漏点，已废除。
现定位：独立诊断工具，仅用于验证 Windows Credential Manager 中 GitHub PAT 是否可取。
  --check : 输出 CRED_STATUS=FOUND TOKEN_LEN=N 或 CRED_STATUS=NOT_FOUND，绝不输出明文。

安全约束 (KR R10 V5 修复令)：不得将密钥写入
  stdout / stderr / 日志 / 命令行 / 仓库 / 测试证据 / 异常报告。
  watcher 现改为进程内自行获取凭据(见 2WB_inbox_watcher.ps1)，不再依赖本文件传递明文。

测试钩子 (仅当对应环境变量存在时生效, 生产不设置)：
  - R10_TEST_FAKE_PAT     : 返回该值(模拟凭据), 用于泄漏测试, 不涉及真实密钥。
  - R10_TEST_FORCE_NO_CRED: 返回空, 用于鉴权失败测试。
"""
import os
import sys
import ctypes
import ctypes.wintypes
import re


def read_pat():
    """读取 GitHub PAT。测试钩子优先(仅测试), 否则从 wincred 读取。"""
    fake = os.environ.get("R10_TEST_FAKE_PAT")
    if fake:
        return fake
    if os.environ.get("R10_TEST_FORCE_NO_CRED") == "1":
        return ""
    adv = ctypes.windll.advapi32

    class CRED(ctypes.Structure):
        _fields_ = [
            ("Flags", ctypes.wintypes.DWORD),
            ("Type", ctypes.wintypes.DWORD),
            ("TargetName", ctypes.c_wchar_p),
            ("Comment", ctypes.c_wchar_p),
            ("LastWritten", ctypes.wintypes.FILETIME),
            ("CredentialBlobSize", ctypes.wintypes.DWORD),
            ("CredentialBlob", ctypes.c_void_p),
            ("Persist", ctypes.wintypes.DWORD),
            ("AttributeCount", ctypes.wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", ctypes.c_wchar_p),
            ("UserName", ctypes.c_wchar_p),
        ]

    p = ctypes.POINTER(CRED)()
    if adv.CredReadW("git:https://github.com", 1, 0, ctypes.byref(p)):
        size = p.contents.CredentialBlobSize
        blob = ctypes.string_at(p.contents.CredentialBlob, size)
        tok = re.sub(r"[^\x20-\x7E]", "", blob.decode("utf-8", "replace"))
        adv.CredFree(p)
        return tok
    return ""


def check_mode():
    """诊断模式：仅输出状态与长度，绝不输出明文。"""
    tok = read_pat()
    if tok:
        # 仅长度，绝不明文
        print("CRED_STATUS=FOUND TOKEN_LEN=%d SRC=wincred_or_test_fake" % len(tok))
    else:
        print("CRED_STATUS=NOT_FOUND")


if __name__ == "__main__":
    # 默认与 --check 等价：仅做无副作用的状态诊断，绝不向 stdout 输出明文 PAT。
    check_mode()
    sys.exit(0)
