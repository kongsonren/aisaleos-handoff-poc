import copy
import hashlib
import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from test_daemon import Tests, KEY, NOW
from daemon import Daemon, GitHubAPI, Hold, REPO, scan

BASE = 'https://api.github.com/repos/' + REPO

class Security(unittest.TestCase):
    def setUp(self):
        self.t = Tests(); self.t.setUp(); self.addCleanup(self.t.doCleanups)

    def test_R1_wrong_result_metadata(self):
        for field, value in [('id',999),('id',True),('user',None),('user',{'id':True}),('user',{'id':666}),('issue_url',BASE+'/issues/1'),('url','https://evil.invalid/comments/12')]:
            with self.subTest(field=field,value=value):
                t=Tests(); t.setUp()
                try:
                    t.d.result_author_id=123
                    result=t.d.consume(t.issue(),NOW)
                    def api(method,path,data=None):
                        if method=='POST':
                            api.body=data['body']
                        meta=dict(id=12,user={'id':123},issue_url=BASE+'/issues/999',url=BASE+'/issues/comments/12',body=api.body)
                        if method=='GET': meta[field]=value
                        return meta
                    try: t.d.publish(result,api)
                    except Hold: pass
                    self.assertEqual(t.d.db.execute("SELECT count(*) FROM jobs WHERE status='VERIFIED'").fetchone()[0],0)
                finally: t.doCleanups()

    def test_R2_malformed(self):
        for field,value in [('user',None),('user',[]),('user',{'id':True}),('id',True),('number','999'),('title',None)]:
            i=self.t.issue(); i[field]=value
            self.assertEqual(self.t.d.consume(i,NOW)['status'],'HOLD_PENDING_KR')
        self.assertEqual(self.t.d.db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)

    def test_R2_scan_continues(self):
        bad=self.t.issue(); bad['user']=None; bad['number']=998
        good=self.t.issue()
        def api(method,path,data=None):
            if '?' in path: return [dict(number=998,title='[MOZI-V2-SIM] bad'),dict(number=999,title=good['title'])]
            if path=='/issues/998': return bad
            if path=='/issues/999': return good
            raise TimeoutError('local-only')
        with patch('daemon.time.time',return_value=NOW): scan(self.t.d,api)
        self.assertEqual(self.t.d.db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)

    def test_R2_global_failure(self):
        with self.assertRaises(Exception): scan(self.t.d,lambda *a: None)
        with self.assertRaises(TimeoutError): scan(self.t.d,lambda *a: (_ for _ in ()).throw(TimeoutError('local outage')))

    def test_R1_transport_endpoint(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def geturl(self): return 'https://evil.invalid/'
        class Opener:
            def open(self,*args,**kwargs): return Response()
        with patch('daemon.urllib.request.build_opener',return_value=Opener()):
            with self.assertRaises(Hold): GitHubAPI('local-fake-token')('GET','/issues/999')
        for path in ['/issues/20','/issues/20/comments','/issues/../secrets','/issues@evil.invalid']:
            with self.assertRaises(Hold): GitHubAPI('local-fake-token')('GET',path)

    def test_R3_no_override(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(TypeError):
                d=Daemon(root,{'sim':(123,KEY)},executor_sha256='0'*64)
                d.db.close()

    def test_R3_expected_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(Hold): Daemon(root,{'sim':(123,KEY)},expected_sha256='0'*64)
            self.assertEqual(list(pathlib.Path(root).iterdir()),[])

    def test_R4_persistent_secret_free(self):
        issue=self.t.issue(signed=False)
        self.t.d.consume(issue,NOW)
        db=sqlite3.connect(pathlib.Path(self.t.tmp.name)/'ledger.sqlite')
        try: rows=db.execute('SELECT event,event_hash FROM audit').fetchall()
        finally: db.close()
        self.assertEqual(len(rows),1)
        event=json.loads(rows[0][0]); self.assertEqual(event['execution_state'],'NOT_STARTED')
        self.assertEqual(hashlib.sha256(rows[0][0].encode()).hexdigest(),rows[0][1])
        self.assertNotIn(KEY.decode(),rows[0][0]); self.assertNotIn(issue['body'],rows[0][0])

    def test_R4_audit_failure_zero_execution(self):
        self.t.d.db.execute('DROP TABLE audit'); self.t.d.db.commit()
        with self.assertRaises(Hold): self.t.d.consume(self.t.issue(),NOW)
        self.assertEqual(list(pathlib.Path(self.t.tmp.name).rglob('test.txt')),[])

if __name__=='__main__': unittest.main(verbosity=2)
