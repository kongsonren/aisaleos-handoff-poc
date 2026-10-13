"""One-shot restricted broker library; no CLI, credential discovery or daemon.

Policy must be supplied by a trusted, separately approved supervisor. This module
does not authenticate KR approval. Writable policy/state invalidates deployment.
"""
import hashlib
import http.client
import json
import os
import sqlite3
import ssl
import time
from dataclasses import dataclass
from entrypoint import safe_path

REPO = 'kongsonren/aisaleos-handoff-poc'
BASE = 'https://api.github.com/repos/' + REPO
TITLE = '[MOZI-V2-SIM] SIM-MOZI-V2-20261014-01'

class Denied(Exception): pass
def require(ok):
    if not ok: raise Denied('binding or state refused')
def digest(b): return hashlib.sha256(b).hexdigest()
def numeric(n): return type(n) is int and n > 0
def decode(raw):
    def pairs(items):
        d = {}
        for k,v in items:
            require(k not in d); d[k] = v
        return d
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: require(False))

@dataclass(frozen=True)
class Policy:
    repo: str
    number: int
    issue_id: int
    issuer_id: int
    bot_id: int
    bot_login: str
    issue_body: str
    issue_sha256: str
    result: str
    result_sha256: str
    start: int
    end: int
    def validate(self):
        require(self.repo == REPO and numeric(self.number) and self.number != 20)
        require(numeric(self.issue_id) and self.issuer_id == 259898029
                and type(self.issuer_id) is int and numeric(self.bot_id)
                and self.bot_id != self.issuer_id and bool(self.bot_login))
        require(type(self.start) is int and type(self.end) is int
                and 0 < self.end-self.start <= 900)
        require(digest(self.issue_body.encode()) == self.issue_sha256)
        require(self.result.startswith('RESULT\n') and 'TASK-REAL-042' not in self.result
                and 'TASK-REAL-042' not in self.issue_body)
        require(digest(self.result.encode()) == self.result_sha256)
        require(len(self.issue_body.encode()) <= 16384
                and len(json.dumps({'body':self.result},ensure_ascii=False).encode()) <= 4096)

class Wire:
    """Fixed origin, system TLS verification, no redirects/proxies/retries."""
    def __init__(self, token):
        require(isinstance(token,str) and token and '\r' not in token and '\n' not in token)
        self._token = token
    def request(self, method, path, body=None):
        require(not any(k.lower() in ('http_proxy','https_proxy','all_proxy','no_proxy')
                        and v for k,v in os.environ.items()))
        conn = http.client.HTTPSConnection('api.github.com', timeout=20,
                                           context=ssl.create_default_context())
        deadline = time.monotonic()+20
        try:
            conn.request(method,path,body,{'Authorization':'Bearer '+self._token,
                         'Accept':'application/vnd.github+json',
                         'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json',
                         'User-Agent':'mozi-v2-isolated-broker'})
            response = conn.getresponse()
            raw = bytearray()
            while True:
                require(time.monotonic()<deadline)
                if conn.sock is not None:
                    conn.sock.settimeout(max(0.001,deadline-time.monotonic()))
                chunk = response.read1(min(65536,1048577-len(raw)))
                raw.extend(chunk); require(len(raw)<=1048576)
                if not chunk: break
            require(response.status == (201 if method == 'POST' else 200))
            return decode(raw)
        finally: conn.close()

class Broker:
    def __init__(self, policy, ledger, wire, clock=time.time):
        policy.validate(); self.p=policy; self.wire=wire; self.clock=clock
        ledger=safe_path(ledger); require(ledger.parent.is_dir())
        self.db=sqlite3.connect(ledger, isolation_level=None, timeout=1)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS once (id INTEGER PRIMARY KEY CHECK(id=1), policy TEXT NOT NULL, status TEXT NOT NULL, comment INTEGER)')
        require(self.db.execute('PRAGMA integrity_check').fetchone()==('ok',))
        self.binding=digest(json.dumps(policy.__dict__,sort_keys=True).encode())
    def close(self): self.db.close()
    def window(self): require(self.p.start <= self.clock() < self.p.end)
    def issue(self,i):
        p=self.p; url=BASE+'/issues/'+str(p.number)
        require(type(i) is dict and 'pull_request' not in i)
        require(type(i.get('id')) is int and i['id']==p.issue_id
                and type(i.get('number')) is int and i['number']==p.number)
        require(i.get('url')==url and i.get('repository_url')==BASE
                and i.get('html_url')=='https://github.com/'+REPO+'/issues/'+str(p.number)
                and i.get('state')=='open' and i.get('title')==TITLE)
        require(type(i.get('user')) is dict and type(i['user'].get('id')) is int
                and i['user']['id']==p.issuer_id and i['user'].get('login')=='kongsonren')
        require(i.get('body')==p.issue_body and digest(i['body'].encode())==p.issue_sha256)
    def comment(self,c,cid=None):
        p=self.p
        require(type(c) is dict and numeric(c.get('id')) and (cid is None or c['id']==cid))
        require(c.get('url')==BASE+'/issues/comments/'+str(c['id'])
                and c.get('issue_url')==BASE+'/issues/'+str(p.number))
        require(type(c.get('user')) is dict and type(c['user'].get('id')) is int
                and c['user']['id']==p.bot_id and c['user'].get('login')==p.bot_login
                and c['user'].get('type')=='Bot')
        require(c.get('body')==p.result and digest(c['body'].encode())==p.result_sha256)
        return c['id']
    def run(self):
        # Existing/unknown attempts are terminal, including a changed policy.
        require(self.db.execute('SELECT count(*) FROM once').fetchone()==(0,))
        self.window()
        path='/repos/'+REPO+'/issues/'+str(self.p.number)
        self.issue(self.wire.request('GET',path))
        self.window()
        # Unique singleton and FULL synchronous COMMIT precede any network POST.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('INSERT INTO once VALUES(1,?,\'POST_ATTEMPT\',NULL)',(self.binding,))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK'); raise
        try:
            self.window()
            raw=json.dumps({'body':self.p.result},ensure_ascii=False).encode()
            c=self.wire.request('POST',path+'/comments',raw)
            cid=self.comment(c)
            self.db.execute('UPDATE once SET comment=? WHERE id=1',(cid,))
            self.window()
            self.comment(self.wire.request('GET','/repos/'+REPO+'/issues/comments/'+str(cid)),cid)
            self.db.execute("UPDATE once SET status='VERIFIED' WHERE id=1")
            return 'VERIFIED'
        except BaseException:
            # Never retry; POST_ATTEMPT plus optional ID survives uncertain outcome.
            raise Denied('HOLD: attempt consumed; independent reconciliation required') from None
