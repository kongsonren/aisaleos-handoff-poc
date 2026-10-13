"""Cut 1 contracts: synthetic IDs, synthetic key, no network."""
import copy
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import entrypoint as e
from test_daemon import Tests as Fixture, NOW

class EntryTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.issue = self.f.issue()
        p = json.loads(self.issue['body'])
        p['task_id'] = e.TASK
        from daemon import digest
        p.pop('auth_digest'); p['auth_digest'] = digest(p, e.MOCK_KEY)
        self.issue.update(title=e.TITLE, body=json.dumps(p), url=e.BASE+'/issues/999',
                          repository_url=e.BASE)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def test_default_and_live_deny(self):
        for args in ([], ['--live'], ['--token','fake'], ['--issue','20']):
            p = subprocess.run([sys.executable, 'entrypoint.py', *args], capture_output=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertNotIn(b'PASS', p.stdout)

    def test_good_duplicate_restart_audit(self):
        a=e.offline_once(self.issue,self.root,NOW)
        b=e.offline_once(self.issue,self.root,NOW+1)
        self.assertEqual(a['status'],'PASS'); self.assertEqual(b['status'],'DUPLICATE')
        files=list(self.root.rglob('test.txt')); self.assertEqual(len(files),1)
        self.assertEqual(files[0].read_bytes(),b'simulation bytes\n')
        import sqlite3
        db=sqlite3.connect(self.root/'mozi-v2-cut1-state'/'ledger.sqlite')
        try:
            rows=db.execute('SELECT event,event_hash FROM audit').fetchall()
            self.assertGreaterEqual(len(rows),4)
            for raw,h in rows: self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),h)
        finally: db.close()

    def test_issue_metadata_and_principal(self):
        for field,value in [('number',20),('number',998),('number',True),('id',9002),('user',None),('user',{'id':True}),('user',{'id':259898029}),('url',e.BASE+'/issues/20'),('repository_url','https://evil.invalid'),('pull_request',{})]:
            with self.subTest(field=field,value=value):
                i=copy.deepcopy(self.issue); i[field]=value
                with self.assertRaises(e.Denied): e.offline_once(i,self.root,NOW)
                self.assertFalse((self.root/'mozi-v2-cut1-state').exists())

    def test_payload_boundary(self):
        for field,value in [('task_id','TASK-REAL-042'),('task_id','SIM-other'),('repository','evil/repo'),('filename','../test.txt'),('action','shell'),('issuer_id',True),('execution_authorized',False),('auth_digest','0'*64),('content','x'*4097)]:
            i=copy.deepcopy(self.issue); p=json.loads(i['body']); p[field]=value; i['body']=json.dumps(p)
            with self.subTest(field=field):
                result=e.offline_once(i,self.root,NOW)
                self.assertEqual(result['status'],'HOLD_PENDING_KR')
                self.assertEqual(list(self.root.rglob('test.txt')),[])

    def test_clock_replay_conflict(self):
        self.assertEqual(e.offline_once(self.issue,self.root,NOW+300)['status'],'HOLD_PENDING_KR')
        self.assertEqual(e.offline_once(self.issue,self.root,NOW-1)['status'],'HOLD_PENDING_KR')
        self.assertEqual(e.offline_once(self.issue,self.root,NOW)['status'],'PASS')
        i=copy.deepcopy(self.issue); p=json.loads(i['body']); p['content']='changed'
        from daemon import digest
        p.pop('auth_digest'); p['auth_digest']=digest(p,e.MOCK_KEY); i['body']=json.dumps(p)
        self.assertEqual(e.offline_once(i,self.root,NOW)['status'],'HOLD_PENDING_KR')

    def test_source_digest_before_import(self):
        with patch.object(e,'DAEMON_SHA','0'*64):
            with self.assertRaises(e.Denied): e.offline_once(self.issue,self.root,NOW)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_path_alias_and_hardlink(self):
        state=self.root/'mozi-v2-cut1-state'; state.mkdir()
        import os
        target=self.root/'other'; target.write_bytes(b'untouched')
        os.link(target,state/'ledger.sqlite')
        with self.assertRaises(e.Denied): e.offline_once(self.issue,self.root,NOW)
        self.assertEqual(target.read_bytes(),b'untouched')

    def test_audit_failure_stops(self):
        e.offline_once(self.issue,self.root,NOW+300)
        import sqlite3
        db=sqlite3.connect(self.root/'mozi-v2-cut1-state'/'ledger.sqlite')
        db.execute('DROP TABLE audit'); db.commit(); db.close()
        with self.assertRaises(Exception): e.offline_once(self.issue,self.root,NOW)
        self.assertEqual(list(self.root.rglob('test.txt')),[])

    def test_broker_paths_and_zero_post(self):
        api=e.OfflineIssue(self.issue)
        for method,path in [('GET','/issues'),('GET','/issues?state=open'),('GET','/issues/20'),('GET','/issues/998'),('GET','/issues/999/comments'),('POST','/issues/999/comments'),('PATCH','/issues/999'),('GET','/issues/999?x=1'),('GET','/issues/../999')]:
            with self.assertRaises(e.Denied): api(method,path)
        self.assertEqual(api('GET','/issues/999'),self.issue)
        self.assertEqual(api.calls,[('GET','/issues/999')])

    def test_fixture_size_and_schema(self):
        for i in (None,[],{'body':'x'*20000}):
            with self.assertRaises(e.Denied): e.offline_once(i,self.root,NOW)

    def test_cli_offline_and_path_denial(self):
        fixture=self.root/'issue.json'; fixture.write_text(json.dumps(self.issue),encoding='utf-8')
        args=[sys.executable,'entrypoint.py','--offline-fixture',str(fixture),'--mock-time',str(NOW),'--scratch']
        p=subprocess.run(args+[str(self.root)],capture_output=True)
        self.assertEqual(p.returncode,2)
        allowed=pathlib.Path(e.__file__).absolute().parent/'offline-workspaces'
        allowed.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=allowed) as scratch:
            for status in ('PASS','DUPLICATE'):
                p=subprocess.run(args+[scratch],capture_output=True)
                self.assertEqual(p.returncode,0,p.stderr)
                data=json.loads(p.stdout); self.assertEqual(data['mode'],'OFFLINE_MOCK')
                self.assertEqual(data['result']['status'],status)

    def test_audit_digest_tamper(self):
        e.offline_once(self.issue,self.root,NOW+300)
        import sqlite3
        db=sqlite3.connect(self.root/'mozi-v2-cut1-state'/'ledger.sqlite')
        db.execute("UPDATE audit SET event_hash='forged'"); db.commit(); db.close()
        with self.assertRaises(e.Denied): e.offline_once(self.issue,self.root,NOW)
        self.assertEqual(list(self.root.rglob('test.txt')),[])

    def test_no_network_or_scan(self):
        with patch('socket.socket',side_effect=AssertionError('network forbidden')), patch('daemon.scan',side_effect=AssertionError('scan forbidden')):
            self.assertEqual(e.offline_once(self.issue,self.root,NOW)['status'],'PASS')

if __name__=='__main__': unittest.main(verbosity=2)
