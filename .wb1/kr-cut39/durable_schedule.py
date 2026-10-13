"""Isolated durable outbox. A periodic worker must call pump independently.

No cumulative heartbeat cap. MAX_BEATS bounds a recursive chain only; this
replacement does not recurse. Delivery is at most one ambiguous POST per key.
Receiver ACK (not HTTP 204) proves a next beat actually started.
"""
import base64, json, time, urllib.parse

PATH='.wb1/kr-cut39/schedule.json'
LIMIT=3

class GitHubLedger:
    def __init__(self, api, branch):
        if not branch.startswith('kr-cut39-isolated-'):
            raise ValueError('isolated branch required')
        self.api,self.branch=api,branch
    def load(self):
        s,d=self.api('GET','/contents/'+PATH+'?ref='+urllib.parse.quote(self.branch,safe=''))
        if s==404: return {},None
        if s!=200: raise RuntimeError('ledger read HTTP '+str(s))
        return json.loads(base64.b64decode(d['content'])),d['sha']
    def cas(self, state, version):
        payload={'branch':self.branch,'message':'[CUT39 isolated] durable schedule transition',
            'content':base64.b64encode(json.dumps(state,sort_keys=True).encode()).decode()}
        if version: payload['sha']=version
        s,d=self.api('PUT','/contents/'+PATH,payload)
        if s in (409,422): return False
        if s not in (200,201): raise RuntimeError('ledger write HTTP '+str(s))
        return True

def mutate(store, fn):
    for _ in range(LIMIT):
        state,version=store.load()
        result=fn(state)
        if store.cas(state,version): return result
    raise RuntimeError('CAS_RETRY_EXHAUSTED')

def enqueue(store, seq, due, workflow, branch):
    if not branch.startswith('kr-cut39-isolated-') or workflow!='nezha-auto.yml':
        raise ValueError('scope rejected')
    key=branch+':'+str(int(seq)+1)
    def add(state):
        state.setdefault(key,dict(key=key,seq=int(seq)+1,due=due,status='PENDING',
            attempts=0,workflow=workflow,branch=branch))
        return key
    return mutate(store,add)

def ack(store,key,run_id):
    def apply(state):
        item=state[key]
        if item.get('run_id') and item['run_id']!=str(run_id):
            raise RuntimeError('DUPLICATE_EXECUTION')
        item.update(status='ACK',run_id=str(run_id))
    mutate(store,apply)

def pump(store,key,dispatch,reconcile,now=None):
    now=time.time() if now is None else now
    state,_=store.load(); item=state[key]
    if item['status']=='ACK': return 0
    if item['status'] in ('INFLIGHT','UNKNOWN','SENT'):
        run_id=reconcile(key)
        if run_id: ack(store,key,run_id); return 0
        # Never resend a request that might have been accepted.
        return 4
    if item['status']=='BLOCKED': return 3
    if item['due']>now: return 5
    def claim(state):
        row=state[key]
        if row['status']!='PENDING' or row['due']>now: return False
        row.update(status='INFLIGHT',attempts=row['attempts']+1)
        return True
    if not mutate(store,claim): return 4
    try: code=dispatch(item)
    except Exception: code=0
    def finish(state):
        row=state[key]
        if row['status']=='ACK': return
        if code==204: row['status']='SENT'
        elif code==429: # definite rejection; bounded backoff
            row.update(status='BLOCKED' if row['attempts']>=LIMIT else 'PENDING',
                due=now+min(60,2**row['attempts']))
        elif code in (400,401,403,404,422): row['status']='BLOCKED'
        else: row['status']='UNKNOWN'
        row['http']=code
    mutate(store,finish)
    # Even 204 means submitted, not executed. Require receiver ACK.
    return 4 if code==204 or code==0 or code>=500 else 3

def wait_and_schedule(store,seq,workflow,branch,dispatch,reconcile,now=None):
    now=time.time() if now is None else now
    key=enqueue(store,seq,now,workflow,branch)
    result=pump(store,key,dispatch,reconcile,now)
    print(json.dumps({'key':key,'exit':result,'record':store.load()[0][key]},sort_keys=True))
    return result
