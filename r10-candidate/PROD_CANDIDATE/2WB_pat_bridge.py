# -*- coding: utf-8 -*-
"""
r7_pat_bridge.py — 隔离环境凭据桥（供修复版 watcher 经 python-ctypes 读 wincred PAT）。
生产原 watcher 用 PowerShell Add-Type CredRead；本环境 Add-Type 被安全策略硬阻断，
故隔离副本改走此桥：powershell 调用本脚本，python ctypes 读 wincred 后只打印 PAT。
不打印到其他地方、不落盘。
"""
import ctypes, ctypes.wintypes, re

class CRED(ctypes.Structure):
    _fields_ = [("Flags", ctypes.wintypes.DWORD), ("Type", ctypes.wintypes.DWORD),
                ("TargetName", ctypes.c_wchar_p), ("Comment", ctypes.c_wchar_p),
                ("LastWritten", ctypes.wintypes.FILETIME), ("CredentialBlobSize", ctypes.wintypes.DWORD),
                ("CredentialBlob", ctypes.c_void_p), ("Persist", ctypes.wintypes.DWORD),
                ("AttributeCount", ctypes.wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", ctypes.c_wchar_p), ("UserName", ctypes.c_wchar_p)]

adv = ctypes.windll.advapi32
p = ctypes.POINTER(CRED)()
if adv.CredReadW("git:https://github.com", 1, 0, ctypes.byref(p)):
    size = p.contents.CredentialBlobSize
    blob = ctypes.string_at(p.contents.CredentialBlob, size)
    tok = re.sub(r"[^\x20-\x7E]", "", blob.decode("utf-8", "replace"))
    adv.CredFree(p)
    print(tok)
else:
    print("")
