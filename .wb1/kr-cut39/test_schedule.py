import copy, json, os, pathlib, subprocess, sys, tempfile, unittest
import durable_schedule as D
import cloud_accept as C

class Store:
    def __init__(self,state=None): self.state=copy.deepcopy(state or {}); self.v=0
    def load(self): return copy.deepcopy(self.state),self.v
    def cas(self,state,v):
        if self.v!=v: return False
        self.state=copy.deepcopy(state); self.v+=1; return True

class Disk(Store):
    def __init__(self,path): self.path=pathlib.Path(path)
    def load(self):
        if not self.path.exists(): return {},0
        obj=json.loads(self.path.read_text()); return obj['state'],obj['v']
    def cas(self,state,v):
        if self.load()[1]!=v: return False
        tmp=self.path.with_suffix('.tmp'); tmp.write_text(json.dumps({'state':state,'v':v+1}))
        os.replace(tmp,self.path); return True

def seed(store=None,seq=242):
    store=store or Store(); key=D.enqueue(store,seq,0,D.WORKFLOW,D.BRANCH); return store,key

class Tests(unittest.TestCase):
    def test_seq243_and_higher_execute(self):
        for seq in (242,9999):
            s,k=seed(seq=seq); effects=[]
            self.assertEqual(C.execute(s,k,'run','sha',lambda:effects.append(k) or 0),'EXECUTION_COMPLETE')
            self.assertEqual(effects,[k]); self.assertEqual(s.state[k]['result']['key'],k)
    def test_dispatch_exact_and_post_guard(self):
        s,k=seed(); calls=[]; old=C.api
        C.api=lambda m,p,d:calls.append((m,p,d)) or (204,None)
        try:
            C.dispatch(s.state[k]); self.assertEqual(calls[0][2]['ref'],s.state[k]['branch'])
            self.assertEqual(calls[0][1],'/actions/workflows/'+D.WORKFLOW+'/dispatches')
            for field,value in [('branch','main'),('workflow','mozi.yml'),('key','bad')]:
                row=copy.deepcopy(s.state[k]); row[field]=value
                with self.assertRaises(ValueError): C.dispatch(row)
            self.assertEqual(len(calls),1)
        finally: C.api=old
    def test_every_row_rejected_before_any_write_or_dispatch(self):
        for field,value in [('branch','main'),('workflow','mozi.yml'),('key','bad'),('seq',True),('attempts',4),('due',float('nan'))]:
            s,k=seed(); other=copy.deepcopy(s.state[k]); other[field]=value
            s.state['corrupt']=other; before=s.v; posts=[]
            with self.assertRaises(ValueError): D.pump(s,k,lambda r:posts.append(r),lambda k:None,now=1)
            self.assertEqual(posts,[]); self.assertEqual(s.v,before)
    def test_ack_is_not_complete(self):
        s,k=seed(); D.ack(s,k,'run')
        self.assertEqual(D.pump(s,k,lambda r:self.fail('resend'),lambda k:None),4)
        self.assertEqual(s.state[k]['status'],'ACK')
        with self.assertRaisesRegex(RuntimeError,'REPLAY_ACK'):
            C.execute(s,k,'run','sha',lambda:self.fail('repeat unknown work'))
    def test_duplicate_and_conflicting_result(self):
        s,k=seed(); effects=[]; executor=lambda:effects.append(k) or 0
        C.execute(s,k,'run','sha',executor)
        self.assertEqual(C.execute(s,k,'run','sha',executor),'REPLAY_SKIPPED')
        with self.assertRaises(RuntimeError): C.execute(s,k,'other','sha',executor)
        with self.assertRaises(RuntimeError): D.complete(s,k,'run',1,'sha')
        self.assertEqual(effects,[k])
    def test_failures_never_complete(self):
        for throws in (False,True):
            s,k=seed()
            def executor():
                if throws: raise RuntimeError('injected')
                return 7
            with self.assertRaises(RuntimeError): C.execute(s,k,'run','sha',executor)
            self.assertEqual(s.state[k]['status'],'EXECUTION_FAILED')
            with self.assertRaisesRegex(RuntimeError,'REPLAY_EXECUTION_FAILED'):
                C.execute(s,k,'run','sha',lambda:self.fail('repeat failed work'))
            self.assertEqual(D.pump(s,k,lambda r:self.fail('resend'),lambda k:None),3)
    def test_ambiguous_restart_no_resend(self):
        for response in (204,500,0):
            s,k=seed(); posts=[]
            D.pump(s,k,lambda r:posts.append(r) or response,lambda k:None,now=1)
            restarted=Store(s.state)
            self.assertEqual(D.pump(restarted,k,lambda r:self.fail('resend'),lambda k:None),4)
            self.assertEqual(len(posts),1)
            result=dict(key=k,branch=D.BRANCH,workflow=D.WORKFLOW,run_id='real',exit_code=0,sha='sha')
            self.assertEqual(D.pump(restarted,k,lambda r:self.fail('resend'),lambda k:result),0)
    def test_reconcile_wrong_task(self):
        s,k=seed(); D.pump(s,k,lambda r:204,lambda k:None,now=1)
        with self.assertRaises(ValueError): D.pump(s,k,lambda r:204,lambda k:dict(key='other',branch=D.BRANCH,workflow=D.WORKFLOW))
        self.assertEqual(s.state[k]['status'],'SENT')
    def test_retry_budget_and_cas_exhaustion(self):
        s,k=seed(); posts=[]
        for now in (1,10,100): D.pump(s,k,lambda r:posts.append(r) or 429,lambda k:None,now=now)
        self.assertEqual(len(posts),3); self.assertEqual(s.state[k]['status'],'BLOCKED')
        s.cas=lambda state,v:False
        with self.assertRaisesRegex(RuntimeError,'CAS_RETRY_EXHAUSTED'): D.enqueue(s,100,0,D.WORKFLOW,D.BRANCH)
    def test_cross_process_crash_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(pathlib.Path(tmp)/'ledger.json'); s,k=seed(Disk(path))
            command=[sys.executable,__file__,'crash',path,k]
            child=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(child.returncode,23)
            self.assertEqual(Disk(path).load()[0][k]['status'],'ACK')
            child=subprocess.run([sys.executable,__file__,'recover',path,k],capture_output=True,text=True)
            print(child.stdout,flush=True); self.assertEqual(child.returncode,0)
            self.assertEqual(Disk(path).load()[0][k]['status'],'EXECUTION_COMPLETE')
    def test_store_validates_read_and_write(self):
        import base64
        s,k=seed(); s.state[k]['branch']='main'; calls=[]
        api=lambda m,p,d=None:(200,dict(content=base64.b64encode(json.dumps(s.state).encode()).decode(),sha='v'))
        store=D.GitHubLedger(api,D.BRANCH)
        with self.assertRaises(ValueError): store.load()
        with self.assertRaises(ValueError): store.cas(s.state,'v')
        with self.assertRaises(ValueError): D.GitHubLedger(api,'main')

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='crash':
        D.ack(Disk(sys.argv[2]),sys.argv[3],'crashed-run'); os._exit(23)
    elif len(sys.argv)>1 and sys.argv[1]=='recover':
        s=Disk(sys.argv[2]); k=sys.argv[3]
        assert D.pump(s,k,lambda r:(_ for _ in ()).throw(AssertionError('resend')),lambda k:None)==4
        D.complete(s,k,'crashed-run',0,'verified-result-sha')
        print(json.dumps({'event':'RESTART_RECOVERY','key':k,'status':s.load()[0][k]['status'],'source':'injected verified result; no inferred completion'}))
    else: unittest.main(verbosity=2)
