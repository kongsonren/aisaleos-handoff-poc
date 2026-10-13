import json, pathlib, sqlite3, subprocess, sys, tempfile
from contextlib import closing
from durable_schedule import enqueue,pump,ack,wait_and_schedule,GitHubLedger
BRANCH='kr-cut39-isolated-20261014'
class DiskLedger:
    def __init__(self,path):
        self.path=str(path)
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('create table if not exists ledger(id integer primary key, v integer, data text)')
            c.execute("insert or ignore into ledger values(1,0,'{}')")
    def load(self):
        with closing(sqlite3.connect(self.path)) as c: v,data=c.execute('select v,data from ledger where id=1').fetchone()
        return json.loads(data),v
    def cas(self,state,v):
        with closing(sqlite3.connect(self.path)) as c, c:
            return c.execute('update ledger set v=v+1,data=? where id=1 and v=?',(json.dumps(state),v)).rowcount==1
def emit(case,**data): print(json.dumps(dict(case=case,**data),sort_keys=True),flush=True)
if len(sys.argv)>1 and sys.argv[1]=='child':
    store=DiskLedger(sys.argv[2]); key=sys.argv[3]
    calls=[]
    assert pump(store,key,lambda item:calls.append(item['key']) or 204,lambda key:None,now=10)==4
    emit('fresh process resumed durable intent',dispatches=calls)
    sys.exit(0)
with tempfile.TemporaryDirectory() as folder:
    store=DiskLedger(pathlib.Path(folder)/'ledger.db')
    for seq in (239,240,241,1000):
        calls=[]; key=enqueue(store,seq,0,'nezha-auto.yml',BRANCH)
        code=pump(store,key,lambda item:calls.append(item['key']) or 204,lambda key:None,now=10)
        assert calls==[key] and code==4
        assert pump(store,key,lambda item: (_ for _ in ()).throw(AssertionError('duplicate')),lambda key:'run-'+str(seq),now=10)==0
        assert pump(store,key,lambda item: (_ for _ in ()).throw(AssertionError('duplicate')),lambda key:None,now=10)==0
        emit('cumulative boundary + receiver ACK',seq=seq,dispatches=len(calls),submitted_exit=code,status=store.load()[0][key]['status'])
    key=enqueue(store,2000,0,'nezha-auto.yml',BRANCH)
    subprocess.run([sys.executable,__file__,'child',store.path,key],check=True)
    assert store.load()[0][key]['status']=='SENT'
    assert pump(DiskLedger(store.path),key,lambda item:999,lambda key:'restart-run',now=10)==0
    key=enqueue(store,3000,0,'nezha-auto.yml',BRANCH); calls=[]
    for now in (10,12,16,24): pump(store,key,lambda item:calls.append(429) or 429,lambda key:None,now=now)
    assert len(calls)==3 and store.load()[0][key]['status']=='BLOCKED'
    emit('bounded retries',attempts=len(calls),status='BLOCKED')
    key=enqueue(store,4000,0,'nezha-auto.yml',BRANCH); calls=[]
    def ambiguous(item): calls.append(item['key']); raise TimeoutError('response lost after acceptance')
    for _ in range(5): assert pump(store,key,ambiguous,lambda key:None,now=10)==4
    assert len(calls)==1 and store.load()[0][key]['status']=='UNKNOWN'
    emit('response loss no blind resend',posts=len(calls),status='UNKNOWN')
    key=enqueue(store,5000,0,'nezha-auto.yml',BRANCH)
    state,v=store.load(); state[key]['status']='INFLIGHT'; assert store.cas(state,v)
    assert pump(DiskLedger(store.path),key,lambda item:999,lambda key:None,now=10)==4
    assert pump(store,key,lambda item:999,lambda key:'accepted-before-crash',now=10)==0
    emit('crash after durable claim',status=store.load()[0][key]['status'])
    state,v=store.load(); assert store.cas(state,v); assert not store.cas(state,v)
    emit('stale CAS',rejected=True)
    try: GitHubLedger(None,'main'); raise AssertionError('scope')
    except ValueError: pass
    emit('production branch guard',rejected=True)
print('PASS isolated durable scheduler tests; remote recovery cadence is separately required',flush=True)
