import copy
import hashlib
import json
import pathlib
import tempfile
import unittest
import concurrent.futures
import subprocess
import sys
from daemon import Daemon, REPO, digest, scan

KEY = b'local-simulation-only-key-00000000'
NOW = 1791936000

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Daemon(self.tmp.name, {'sim': (123, KEY)}, result_author_id=123)
        self.addCleanup(self.d.db.close)
        self.p = dict(protocol='mozi-v2-auth', repository=REPO, issue_id=9001, issue_number=999,
                      issuer_id=123, key_id='sim', task_id='SIM-001', run_id='SIM-RUN-001',
                      state='READY', execution_authorized=True, scope='simulation-only',
                      executor='isolated-file-v2', action='write_read_hash', filename='test.txt',
                      content='simulation bytes\n', issued_at=NOW, expires_at=NOW+300,
                      nonce='a'*32, executor_sha256=self.d.code)

    def issue(self, p=None, signed=True):
        p = copy.deepcopy(self.p if p is None else p)
        p['auth_digest'] = digest(p, KEY) if signed else '0'*64
        return dict(id=9001, number=999, user={'id':123}, title='[MOZI-V2-SIM] SIM-001', state='open', body=json.dumps(p))

    def reject(self, issue, now=NOW):
        result = self.d.consume(issue, now)
        print(json.dumps(result))
        self.assertEqual(result['status'], 'HOLD_PENDING_KR')
        self.assertEqual(list(pathlib.Path(self.tmp.name).rglob('test.txt')), [])
        self.assertEqual(self.d.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0)

    def test_false_missing_forged_true_wrong_signature(self):
        for value in (False, 'true', 1, None):
            p=copy.deepcopy(self.p); p['execution_authorized']=value
            self.reject(self.issue(p))
        p=copy.deepcopy(self.p); del p['execution_authorized']; self.reject(self.issue(p))
        self.reject(self.issue(signed=False))

    def test_every_field_tamper(self):
        issue=self.issue()
        for field in self.p:
            with self.subTest(field=field):
                q=json.loads(issue['body'])
                q[field] = q[field]+1 if type(q[field]) is int else (False if type(q[field]) is bool else q[field]+'X')
                changed=copy.deepcopy(issue); changed['body']=json.dumps(q)
                self.reject(changed)

    def test_expired_future_and_window(self):
        self.reject(self.issue(), NOW+300)
        self.reject(self.issue(), NOW-1)
        p=copy.deepcopy(self.p); p['expires_at']=NOW+301; self.reject(self.issue(p))

    def test_principal_and_issue_binding(self):
        for field,value in [('user',{'id':456}),('id',9002),('number',998),('state','closed'),('title','[KR-ISOLATED-HOLD] SIM-001'),('pull_request',{})]:
            i=self.issue(); i[field]=value; self.reject(i)

    def test_legacy_and_protected_task(self):
        i=self.issue(); i['body']=json.dumps(dict(protocol='isolated-file-v1',action='write_read_hash',content='x',run_id='CLOUD-DAEMON-20261013-02')); self.reject(i)
        i=self.issue(); i['number']=20; self.reject(i)
        p=copy.deepcopy(self.p); p['task_id']='TASK-REAL-042'; self.reject(self.issue(p))
        i=self.issue(); i['body']=i['body'][:-1]+',"execution_authorized":true}'; self.reject(i)

    def test_legal_restart_duplicate_and_result(self):
        result=self.d.consume(self.issue(), NOW)
        print(json.dumps(result))
        self.assertEqual(result['status'],'PASS')
        target=pathlib.Path(result['path']); before=target.stat().st_mtime_ns
        self.assertEqual(target.read_bytes(),self.p['content'].encode())
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),result['sha256'])
        other=Daemon(self.tmp.name,{'sim':(123,KEY)},result_author_id=123)
        try:
            duplicate=other.consume(self.issue(),NOW+1)
            self.assertEqual(duplicate['status'],'DUPLICATE')
            self.assertEqual(target.stat().st_mtime_ns,before)
            calls=[]
            def api(method,path,data=None):
                calls.append((method,path,data))
                return dict(id=12,user={'id':123},body=calls[0][2]['body'],
                    issue_url='https://api.github.com/repos/'+REPO+'/issues/999',
                    url='https://api.github.com/repos/'+REPO+'/issues/comments/12')
            self.assertEqual(other.publish(duplicate,api)['status'],'RESULT_VERIFIED')
            self.assertEqual(other.publish(other.consume(self.issue(),NOW+2),api)['status'],'ALREADY_VERIFIED')
            self.assertEqual(len(calls),2)
            self.assertEqual(other.consume(self.issue(),NOW+301)['status'],'HOLD_PENDING_KR')
        finally: other.db.close()

    def test_crash_claim_never_reexecutes(self):
        p,fp=self.d.validate(self.issue(),NOW)
        with self.d.db:
            self.d.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',(p['task_id'],p['run_id'],p['nonce'],p['issue_id'],fp,'CLAIMED',None))
        self.assertEqual(self.d.consume(self.issue(),NOW)['status'],'HOLD_PENDING_KR')
        self.assertEqual(list(pathlib.Path(self.tmp.name).rglob('test.txt')),[])

    def test_post_timeout_no_retry(self):
        result=self.d.consume(self.issue(),NOW)
        calls=[]
        def fail(*args):
            calls.append(args); raise TimeoutError('simulated ambiguous POST')
        with self.assertRaises(TimeoutError): self.d.publish(result,fail)
        self.assertEqual(self.d.publish(self.d.consume(self.issue(),NOW),fail)['status'],'HOLD_PENDING_KR')
        self.assertEqual(len(calls),1)

    def test_conflicting_nonce_run_issue(self):
        self.assertEqual(self.d.consume(self.issue(),NOW)['status'],'PASS')
        for field in ('task_id','run_id','nonce','content'):
            p=copy.deepcopy(self.p); p[field]+='b'
            i=self.issue(p); i['title']='[MOZI-V2-SIM] '+p['task_id']
            self.assertEqual(self.d.consume(i,NOW)['status'],'HOLD_PENDING_KR')
        self.assertEqual(len(list(pathlib.Path(self.tmp.name).rglob('test.txt'))),1)

    def test_scan_only_refreshes_simulation(self):
        calls=[]
        def api(method,path,data=None):
            calls.append((method,path))
            return [{'number':20,'title':'[MOZI-V2-SIM] SIM-X'}, {'number':1,'title':'[ISOLATED-DAEMON-POC] old'}]
        scan(self.d,api)
        self.assertEqual(len(calls),1)

    def test_concurrent_claim_and_process_restart(self):
        issue=self.issue()
        def work(_):
            d=Daemon(self.tmp.name,{'sim':(123,KEY)})
            try: return d.consume(issue,NOW)['status']
            finally: d.db.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            statuses=list(pool.map(work,range(4)))
        self.assertEqual(statuses.count('PASS'),1)
        self.assertEqual(len(list(pathlib.Path(self.tmp.name).rglob('test.txt'))),1)
        script='from daemon import *; import sys; d=Daemon(sys.argv[1], {"sim":(123,bytes.fromhex(sys.argv[2]))}); print(d.consume(json.loads(sys.argv[3]),int(sys.argv[4]))["status"]); d.db.close()'
        result=subprocess.run([sys.executable,'-c',script,self.tmp.name,KEY.hex(),json.dumps(issue),str(NOW)],capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.strip(),'DUPLICATE')
        print('concurrent statuses:',statuses,'new process:',result.stdout.strip())

if __name__=='__main__': unittest.main(verbosity=2)
