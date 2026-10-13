"""CUT41 isolated outbox. ACK is receipt; only a correlated result completes it."""
import base64, json, time, urllib.parse

BRANCH='kr-cut41-isolated-20261014'
WORKFLOW='nezha-auto.yml'
PATH='.wb1/kr-cut41/schedule.json'
LIMIT=3
STATES={'PENDING','INFLIGHT','SENT','UNKNOWN','BLOCKED','ACK','EXECUTION_COMPLETE','EXECUTION_FAILED'}

def validate(state):
    if not isinstance(state,dict): raise ValueError('INVALID_LEDGER')
    for key,row in state.items():
        if not isinstance(row,dict): raise ValueError('INVALID_ROW')
        seq=row.get('seq')
        if (type(seq) is not int or seq<1 or row.get('branch')!=BRANCH or
            row.get('workflow')!=WORKFLOW or key!=BRANCH+':'+str(seq) or row.get('key')!=key):
            raise ValueError('SCOPE_REJECTED')
        if row.get('status') not in STATES or type(row.get('attempts')) is not int or not 0<=row['attempts']<=LIMIT:
            raise ValueError('INVALID_STATE')
        if type(row.get('due')) not in (int,float) or not 0<=row['due']<float('inf'):
            raise ValueError('INVALID_DUE')
        if row['status'] in {'ACK','EXECUTION_COMPLETE','EXECUTION_FAILED'} and not row.get('run_id'):
            raise ValueError('MISSING_RUN')
        if row['status'].startswith('EXECUTION_'):
            result=row.get('result',{})
            if any(result.get(k)!=row.get(k) for k in ('key','branch','workflow','run_id')):
                raise ValueError('RESULT_CORRELATION')
            if type(result.get('exit_code')) is not int or (result['exit_code']==0)!=(row['status']=='EXECUTION_COMPLETE'):
                raise ValueError('RESULT_STATUS')
    return state

class GitHubLedger:
    def __init__(self,api,branch):
        if branch!=BRANCH: raise ValueError('SCOPE_REJECTED')
        self.api,self.branch=api,branch
    def load(self):
        code,data=self.api('GET','/contents/'+PATH+'?ref='+urllib.parse.quote(self.branch,safe=''))
        if code==404: return {},None
        if code!=200: raise RuntimeError('LEDGER_READ_'+str(code))
        return validate(json.loads(base64.b64decode(data['content']))),data['sha']
    def cas(self,state,version):
        validate(state)
        data={'branch':self.branch,'message':'CUT41 isolated ledger transition',
              'content':base64.b64encode(json.dumps(state,sort_keys=True).encode()).decode()}
        if version: data['sha']=version
        code,_=self.api('PUT','/contents/'+PATH,data)
        if code in (409,422): return False
        if code not in (200,201): raise RuntimeError('LEDGER_WRITE_'+str(code))
        return True

def load(store):
    state,version=store.load(); return validate(state),version

def mutate(store,fn):
    for _ in range(LIMIT):
        state,version=load(store); result=fn(state); validate(state)
        if store.cas(state,version): return result
    raise RuntimeError('CAS_RETRY_EXHAUSTED')

def enqueue(store,seq,due,workflow,branch):
    if branch!=BRANCH or workflow!=WORKFLOW or type(seq) is not int: raise ValueError('SCOPE_REJECTED')
    key=branch+':'+str(seq+1)
    def add(state):
        state.setdefault(key,dict(key=key,seq=seq+1,due=due,status='PENDING',attempts=0,workflow=workflow,branch=branch))
        return key
    return mutate(store,add)

def ack(store,key,run_id):
    if not str(run_id): raise ValueError('MISSING_RUN')
    def apply(state):
        row=state[key]
        if row.get('run_id'):
            if row['run_id']!=str(run_id): raise RuntimeError('DUPLICATE_EXECUTION')
            return False # same-run replay also must not repeat side effects
        if row['status'] not in {'PENDING','INFLIGHT','SENT','UNKNOWN'}: raise RuntimeError('INVALID_ACK_STATE')
        row.update(status='ACK',run_id=str(run_id)); return True
    return mutate(store,apply)

def complete(store,key,run_id,exit_code,sha):
    def apply(state):
        row=state[key]
        if row.get('run_id')!=str(run_id): raise RuntimeError('RESULT_CORRELATION')
        result=dict(key=key,branch=BRANCH,workflow=WORKFLOW,run_id=str(run_id),exit_code=exit_code,sha=sha)
        if row['status'].startswith('EXECUTION_'):
            if row['result']!=result: raise RuntimeError('CONFLICTING_RESULT')
            return
        if row['status']!='ACK': raise RuntimeError('ACK_REQUIRED')
        row.update(status='EXECUTION_COMPLETE' if exit_code==0 else 'EXECUTION_FAILED',result=result)
    mutate(store,apply)

def pump(store,key,dispatch,reconcile,now=None):
    now=time.time() if now is None else now
    state,_=load(store); item=state[key]
    status=item['status']
    if status=='EXECUTION_COMPLETE': return 0
    if status in {'BLOCKED','EXECUTION_FAILED'}: return 3
    if status in {'ACK','INFLIGHT','SENT','UNKNOWN'}:
        result=reconcile(key)
        if result:
            if any(result.get(k)!=item.get(k) for k in ('key','branch','workflow')): raise ValueError('RESULT_CORRELATION')
            ack(store,key,result['run_id'])
            if 'exit_code' in result: complete(store,key,result['run_id'],result['exit_code'],result['sha'])
            return 0 if load(store)[0][key]['status']=='EXECUTION_COMPLETE' else 4
        return 4
    if item['due']>now: return 5
    def claim(state):
        row=state[key]
        if row['status']!='PENDING' or row['due']>now: return False
        if row['attempts']>=LIMIT: row['status']='BLOCKED'; return False
        row.update(status='INFLIGHT',attempts=row['attempts']+1); return True
    if not mutate(store,claim): return 4
    # Re-read persisted data after claiming, not the stale pre-claim row.
    item=load(store)[0][key]
    if item['status']!='INFLIGHT': return 4
    try: code=dispatch(dict(item))
    except Exception: code=0
    def finish(state):
        row=state[key]
        if row['status'] in {'ACK','EXECUTION_COMPLETE','EXECUTION_FAILED'}: return
        if code==204: row['status']='SENT'
        elif code==429: row.update(status='BLOCKED' if row['attempts']>=LIMIT else 'PENDING',due=now+2**row['attempts'])
        elif code in (400,401,403,404,422): row['status']='BLOCKED'
        else: row['status']='UNKNOWN'
        row['http']=code
    mutate(store,finish)
    return 4 if code in (0,204) or code>=500 else 3
