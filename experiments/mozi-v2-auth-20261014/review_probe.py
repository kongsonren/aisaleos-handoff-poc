"""Adversarial review of fixed candidate; local mocks only, no network."""
import json
import pathlib
import tempfile
from test_daemon import KEY, NOW, Tests
from daemon import Daemon, scan

findings=[]
t=Tests(); t.setUp()
try:
    result=t.d.consume(t.issue(),NOW)
    body={}
    def spoof(method,path,data=None):
        if method=='POST':
            body['value']=data['body']; return {'id':12,'user':{'id':123}}
        return {'id':999,'user':{'id':666},'body':body['value'],
                'issue_url':'https://api.github.com/repos/untrusted/other/issues/1'}
    observed=t.d.publish(result,spoof)
    assert observed['status']=='RESULT_VERIFIED', observed
    findings.append({'id':'R1','severity':'P1','observed':observed,
        'problem':'RESULT readback validates body only; wrong comment ID, author and repository/issue accepted as VERIFIED'})
finally: t.doCleanups()

t=Tests(); t.setUp()
try:
    bad=t.issue(); bad['user']=None
    try:
        t.d.consume(bad,NOW)
    except AttributeError as exc:
        findings.append({'id':'R2','severity':'P2','observed':type(exc).__name__,
            'problem':'malformed metadata escapes HOLD handling; scan has no per-issue exception boundary'})
    else: raise AssertionError('R2 no longer reproduced')
finally: t.doCleanups()

with tempfile.TemporaryDirectory() as root:
    d=Daemon(root,{'sim':(123,KEY)},executor_sha256='0'*64)
    try:
        assert d.code=='0'*64
        findings.append({'id':'R3','severity':'P2','observed':d.code,
            'problem':'caller can override measured executor hash; signed executor_sha256 does not necessarily identify running bytes'})
    finally: d.db.close()

t=Tests(); t.setUp()
try:
    bad=t.issue(signed=False)
    assert t.d.consume(bad,NOW)['status']=='HOLD_PENDING_KR'
    assert t.d.db.execute('SELECT count(*) FROM jobs').fetchone()[0]==0
    assert not list(pathlib.Path(t.tmp.name).glob('*.jsonl'))
    findings.append({'id':'R4','severity':'P2','observed':'no durable rejection record',
        'problem':'authorization rejection is returned/printed only; no persistent audit event with trusted source and reason'})
finally: t.doCleanups()

print(json.dumps({'candidate':'0cec724f29455e5bf14c7efe0bf605eca0fd9c29',
    'scope':'local adversarial mocks only','decision':'HOLD_NOT_READY_FOR_CLOUD_ACCEPTANCE',
    'reproduced':findings},ensure_ascii=False,indent=2))
