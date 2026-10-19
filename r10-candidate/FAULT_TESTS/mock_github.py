# -*- coding: utf-8 -*-
"""R9 P0-B 隔离 mock GitHub (供 watcher 故障测试, 零生产污染)。
GET  /repos/.../issues/8/comments  -> 按 mode 文件返回 评论列表 / 403 / 429 / 超时
POST /repos/.../issues/8/comments  -> 返回 200 {id: N} (模拟 ACK 成功)
mode 文件: <ctrl> = 普通 | 403 | 429 | timeout
comments 文件: <ctrl>.comments = JSON 数组
"""
import json, os, sys, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

CTRL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_ctrl.txt")
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8731
_counter = [1000]
_lock = threading.Lock()

def read_mode():
    try:
        return open(CTRL, "r", encoding="utf-8").read().strip()
    except Exception:
        return "normal"

def read_comments():
    p = CTRL + ".comments"
    try:
        return open(p, "r", encoding="utf-8").read()
    except Exception:
        return "[]"

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        mode = read_mode()
        if mode == "403":
            self.send_response(403); self.end_headers(); self.wfile.write(b'{"message":"rate limited"}'); return
        if mode == "429":
            self.send_response(429); self.end_headers(); self.wfile.write(b'{"message":"too many"}'); return
        if mode == "timeout":
            time.sleep(40)  # 超过 watcher TimeoutSec=30 -> 触发超时
            self.send_response(200); self.end_headers(); self.wfile.write(b'[]'); return
        body = read_comments().encode("utf-8")
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        with _lock:
            _counter[0] += 1
            cid = _counter[0]
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.end_headers(); self.wfile.write(json.dumps({"id": cid}).encode("utf-8"))

if __name__ == "__main__":
    srv = HTTPServer(("127.0.0.1", PORT), H)
    print(f"MOCK_UP port={PORT} ctrl={CTRL}", flush=True)
    srv.serve_forever()
