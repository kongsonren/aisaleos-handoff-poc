"""One-shot OFFLINE launcher. Live mode has no implementation or credential path.

Local fixtures are untrusted data. Synthetic IDs/key never authorize GitHub.
OS sandboxing and trusted read-only installation are separate Linux gates.
"""
import argparse
import copy
import hashlib
import json
import os
import pathlib
import stat
import sqlite3
import sys
import types

PARENT = 'bf7eec65af9a65da065a781a5ed91b8f8038f61c'
DAEMON_SHA = '0afef212dc11f0cd6a12f4281891883694047371c850a8b80819cb131d195971'
BASE = 'https://api.github.com/repos/kongsonren/aisaleos-handoff-poc'
TASK = 'SIM-MOZI-V2-20261014-01'
TITLE = '[MOZI-V2-SIM] '+TASK
MOCK_KEY = b'local-simulation-only-key-00000000'
ISSUE_ID, ISSUE_NUMBER, ISSUER_ID = 9001, 999, 123  # MOCK ONLY; never real identity evidence

class Denied(Exception):
    pass

def safe_path(path):
    path=pathlib.Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise Denied('absolute non-traversing path required')
    for part in (*reversed(path.parents),path):
        if part.is_symlink() or part.is_junction():
            raise Denied('path alias refused')
        if part.exists():
            st=part.lstat()
            if not stat.S_ISDIR(st.st_mode) and not stat.S_ISREG(st.st_mode):
                raise Denied('special file refused')
            if stat.S_ISREG(st.st_mode) and st.st_nlink != 1:
                raise Denied('hardlink refused')
    return path

def load_pinned():
    path=safe_path(pathlib.Path(__file__).absolute().with_name('daemon.py'))
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=DAEMON_SHA:
        raise Denied('pinned source mismatch')
    # Compile the measured bytes, avoiding a second file read/import-cache race.
    module=types.ModuleType('mozi_cut1_pinned'); module.__file__=str(path)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module

def bound_issue(issue):
    if type(issue) is not dict:
        raise Denied('fixture object required')
    try: encoded=json.dumps(issue,allow_nan=False).encode()
    except (ValueError,TypeError,RecursionError): raise Denied('invalid fixture') from None
    if len(encoded)>16384: raise Denied('fixture size limit')
    if (type(issue.get('id')) is not int or issue['id']!=ISSUE_ID
        or type(issue.get('number')) is not int or issue['number']!=ISSUE_NUMBER
        or type(issue.get('user')) is not dict
        or type(issue['user'].get('id')) is not int or issue['user']['id']!=ISSUER_ID
        or issue.get('title')!=TITLE or issue.get('state')!='open'
        or 'pull_request' in issue or issue.get('repository_url')!=BASE
        or issue.get('url')!=BASE+'/issues/999'):
        raise Denied('single MOCK issue binding refused')
    return copy.deepcopy(issue)

class OfflineIssue:
    """No HTTP client, token, POST, pagination, redirect, or list endpoint."""
    def __init__(self,issue):
        self.issue=bound_issue(issue); self.calls=[]
    def __call__(self,method,path,data=None):
        if method!='GET' or path!='/issues/999' or data is not None:
            raise Denied('offline single issue GET only')
        self.calls.append((method,path))
        return copy.deepcopy(self.issue)

def offline_once(issue,scratch,current):
    if type(current) is not int or current<=0: raise Denied('integer mock time required')
    core=load_pinned()
    api=OfflineIssue(issue)  # rejects before state/ledger creation
    scratch=safe_path(scratch)
    if not scratch.is_dir(): raise Denied('existing dedicated scratch required')
    # Caller must provide a private, exclusively owned scratch. Never a deployment path.
    state=safe_path(scratch/'mozi-v2-cut1-state')
    if state.exists():
        for p in state.rglob('*'): safe_path(p)
        ledger=state/'ledger.sqlite'
        if not ledger.is_file(): raise Denied('existing state without ledger')
        # Read-only preflight: never silently repair a missing/corrupt audit table.
        db=sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True)
        try:
            if db.execute('PRAGMA integrity_check').fetchone()!=('ok',):
                raise Denied('ledger integrity')
            for event,event_hash in db.execute('SELECT event,event_hash FROM audit'):
                if hashlib.sha256(event.encode()).hexdigest()!=event_hash:
                    raise Denied('audit digest')
            db.execute('SELECT task,status FROM jobs LIMIT 1').fetchall()
        finally: db.close()
    fresh=api('GET','/issues/999')
    d=core.Daemon(state,{'sim':(ISSUER_ID,MOCK_KEY)},expected_sha256=DAEMON_SHA,
                  result_author_id=ISSUER_ID)
    try:
        d.audit(fresh,'OFFLINE_SINGLE_ISSUE_ENTER','NOT_STARTED')
        payload=core.parse(fresh.get('body'))
        if type(payload) is not dict or payload.get('task_id')!=TASK:
            d.audit(fresh,'FIXED_TASK_DENIED','NOT_STARTED')
            return {'status':'HOLD_PENDING_KR','reason':'fixed simulation task required'}
        result=d.consume(fresh,current)
        d.audit(fresh,'OFFLINE_SINGLE_ISSUE_EXIT',result['status'])
        return result  # deliberately no publish call
    finally: d.db.close()

def main(argv=None):
    parser=argparse.ArgumentParser(description='MOCK-only single issue launcher; live denied')
    parser.add_argument('--offline-fixture',required=True)
    parser.add_argument('--scratch',required=True)
    parser.add_argument('--mock-time',required=True,type=int)
    args=parser.parse_args(argv)
    try:
        scratch=safe_path(pathlib.Path(args.scratch))
        allowed=pathlib.Path(__file__).absolute().parent/'offline-workspaces'
        if scratch.parent!=allowed or scratch.name in ('','.', '..'):
            raise Denied('CLI scratch outside local offline workspaces')
        fixture=safe_path(args.offline_fixture)
        if fixture.stat().st_size>16384: raise Denied('fixture size limit')
        # Duplicate JSON keys are rejected even in the outer fixture.
        core=load_pinned(); issue=core.parse(fixture.read_text(encoding='utf-8'))
        result=offline_once(issue,scratch,args.mock_time)
        print(json.dumps({'mode':'OFFLINE_MOCK','parent':PARENT,'result':result}))
        return 0 if result['status'] in ('PASS','DUPLICATE') else 2
    except Exception:
        # No raw payloads, credentials, exception text, or fake live success.
        print(json.dumps({'mode':'OFFLINE_MOCK','status':'HOLD_PENDING_KR','reason':'entry denied'}))
        return 2

if __name__=='__main__': sys.exit(main())
