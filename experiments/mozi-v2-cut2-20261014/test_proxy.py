import dataclasses
import http.client
import http.server
import json
import pathlib
import tempfile
import threading
import unittest
from unittest.mock import patch
import proxy as m

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=pathlib.Path(self.tmp.name)/'ledger.db'
        self.p=m.Policy(m.REPO,999,9001,259898029,888,'result-test[bot]',
                        'SIM ONLY',m.digest(b'SIM ONLY'),'RESULT\nSIM PASS',m.digest(b'RESULT\nSIM PASS'),100,200)
        self.i=dict(id=9001,number=999,user=dict(id=259898029,login='kongsonren'),
                    url=m.BASE+'/issues/999',repository_url=m.BASE,
                    html_url='https://github.com/'+m.REPO+'/issues/999',state='open',title=m.TITLE,body='SIM ONLY')
        self.c=dict(id=777,user=dict(id=888,login='result-test[bot]',type='Bot'),
                    url=m.BASE+'/issues/comments/777',issue_url=m.BASE+'/issues/999',body=self.p.result)
        self.calls=[]; self.mode='ok'; outer=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def do_GET(self): self.handle_call()
            def do_POST(self): self.handle_call()
            def handle_call(self):
                body=self.rfile.read(int(self.headers.get('Content-Length','0')))
                outer.calls.append((self.command,self.path,body))
                post=self.command=='POST'; comment='/comments/' in self.path
                if post and outer.mode=='disconnect': self.connection.close(); return
                value=dict(outer.c if post or comment else outer.i)
                if outer.mode=='wrong_id' and comment: value['id']=778
                if outer.mode=='wrong_bot' and post: value['user']=dict(id=259898029,login='kongsonren',type='User')
                status=302 if outer.mode=='redirect' else 201 if post else 200
                self.send_response(status); self.send_header('Location','http://127.0.0.1:1/issues/20'); self.end_headers()
                raw=b'x'*1048577 if outer.mode=='oversize' else json.dumps(value).encode()
                try: self.wfile.write(raw)
                except (BrokenPipeError,ConnectionResetError): pass
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        port=self.server.server_port
        class Local(http.client.HTTPConnection):
            def __init__(self,host,timeout,context):
                assert host=='api.github.com' and timeout==20
                super().__init__('127.0.0.1',port,timeout=timeout)
        self.patch=patch.object(m.http.client,'HTTPSConnection',Local); self.patch.start()
        self.tls=patch.object(m.ssl,'create_default_context',return_value=None); self.tls.start()
        self.env=patch.dict(m.os.environ,{},clear=True); self.env.start()
    def tearDown(self):
        for b in getattr(self,'brokers',[]): b.close()
        self.env.stop(); self.tls.stop(); self.patch.stop(); self.server.shutdown(); self.server.server_close(); self.tmp.cleanup()
    def broker(self,p=None):
        b=m.Broker(p or self.p,self.path,m.Wire('synthetic-test-only'),lambda:150)
        if not hasattr(self,'brokers'): self.brokers=[]
        self.brokers.append(b)
        return b
    def run_once(self):
        b=self.broker()
        try: return b.run()
        finally: b.close()
    def test_success_and_restart(self):
        self.assertEqual(self.run_once(),'VERIFIED')
        with self.assertRaises(Exception): self.run_once()
        self.assertEqual([(x[0],x[1]) for x in self.calls],[('GET','/repos/'+m.REPO+'/issues/999'),('POST','/repos/'+m.REPO+'/issues/999/comments'),('GET','/repos/'+m.REPO+'/issues/comments/777')])
        self.assertEqual(json.loads(self.calls[1][2]),{'body':self.p.result})
    def test_issue_binding(self):
        for key,value in [('id',1),('number',20),('url',m.BASE+'/issues/20'),('repository_url','https://evil'),('body','altered'),('title','other'),('state','closed'),('pull_request',{})]:
            with self.subTest(key=key):
                b=self.broker(); obj=dict(self.i); obj[key]=value
                with self.assertRaises(Exception): b.issue(obj)
                b.close()
        self.assertEqual(self.calls,[])
    def test_policy_binding(self):
        for key,value in [('number',20),('repo','evil/repo'),('issuer_id',True),('bot_id',259898029),('result','altered'),('issue_sha256','0'*64),('end',1001),('issue_body','TASK-REAL-042')]:
            with self.subTest(key=key),self.assertRaises(Exception): dataclasses.replace(self.p,**{key:value}).validate()
        self.assertEqual(self.calls,[])
    def test_disconnect_consumes_attempt(self):
        self.mode='disconnect'
        with self.assertRaises(Exception): self.run_once()
        b=self.broker(); self.assertEqual(b.db.execute('SELECT status FROM once').fetchone(),('POST_ATTEMPT',)); b.close()
        with self.assertRaises(Exception): self.run_once()
        self.assertEqual(len(self.calls),2)
    def test_wrong_readback_no_retry(self):
        self.mode='wrong_id'
        with self.assertRaises(Exception): self.run_once()
        with self.assertRaises(Exception): self.run_once()
        self.assertEqual(len(self.calls),3)
    def test_wrong_bot_no_readback(self):
        self.mode='wrong_bot'
        with self.assertRaises(Exception): self.run_once()
        self.assertEqual(len(self.calls),2)
    def test_redirect(self):
        self.mode='redirect'
        with self.assertRaises(Exception): self.run_once()
        self.assertEqual(len(self.calls),1)
    def test_oversize(self):
        self.mode='oversize'
        with self.assertRaises(Exception): self.run_once()
        self.assertEqual(len(self.calls),1)
    def test_proxy_environment(self):
        m.os.environ['HTTPS_PROXY']='http://127.0.0.1:1'
        with self.assertRaises(Exception): self.run_once()
        self.assertEqual(self.calls,[])
    def test_expired(self):
        b=self.broker(); b.clock=lambda:200
        with self.assertRaises(Exception): b.run()
        b.close(); self.assertEqual(self.calls,[])
    def test_disk_failure_before_post(self):
        b=self.broker(); b.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(Exception): b.run()
        b.close(); self.assertEqual(len(self.calls),1)
    def test_timeout_consumes_attempt(self):
        b=self.broker(); original=b.wire.request
        def fault(method,path,body=None):
            if method=='POST': raise TimeoutError()
            return original(method,path,body)
        b.wire.request=fault
        with self.assertRaises(Exception): b.run()
        b.close()
        with self.assertRaises(Exception): self.run_once()
        self.assertEqual(len(self.calls),1)
    def test_duplicate_json(self):
        with self.assertRaises(Exception): m.decode(b'{"id":1,"id":2}')
    def test_concurrent_reservation(self):
        a=self.broker(); b=self.broker(); self.assertEqual(a.run(),'VERIFIED')
        with self.assertRaises(Exception): b.run()
        a.close(); b.close(); self.assertEqual(len(self.calls),3)

if __name__=='__main__': unittest.main()
