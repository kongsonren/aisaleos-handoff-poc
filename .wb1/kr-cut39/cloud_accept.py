"""Isolated finite acceptance executor; sequence is identity, not a budget."""
import json, os, pathlib, subprocess, sys, urllib.request, urllib.error
from durable_schedule import BRANCH,WORKFLOW,GitHubLedger,ack,complete,validate,load,enqueue,pump
REPO='kongsonren/aisaleos-handoff-poc'

def api(method,path,data=None):
    req=urllib.request.Request('https://api.github.com/repos/'+REPO+path,method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json',
                 'Content-Type':'application/json','User-Agent':'kr-cut41-isolated'})
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read(); return r.status,json.loads(raw) if raw else None
    except urllib.error.HTTPError as e: return e.code,None

def dispatch(item):
    validate({item['key']:item}) # POST boundary, independent of caller validation
    return api('POST','/actions/workflows/'+item['workflow']+'/dispatches',
        {'ref':item['branch'],'inputs':{'schedule_key':item['key']}})[0]

def execute(store,key,run_id,sha,executor):
    load(store)
    if not ack(store,key,run_id): return 'REPLAY_SKIPPED'
    print(json.dumps({'event':'ACK','key':key,'run_id':str(run_id)}),flush=True)
    try: code=executor()
    except Exception:
        complete(store,key,run_id,1,sha)
        raise
    complete(store,key,run_id,code,sha)
    event='EXECUTION_COMPLETE' if code==0 else 'EXECUTION_FAILED'
    print(json.dumps({'event':event,'key':key,'run_id':str(run_id),'sha':sha,'exit_code':code}),flush=True)
    if code: raise RuntimeError(event)
    return event

def run(key):
    if os.environ['GITHUB_REF']!='refs/heads/'+BRANCH: raise ValueError('SCOPE_REJECTED')
    store=GitHubLedger(api,BRANCH)
    return execute(store,key,os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_SHA'],
        lambda:subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('test_schedule.py'))]).returncode)

if __name__=='__main__':
    store=GitHubLedger(api,BRANCH)
    key=os.environ.get('SCHEDULE_KEY')
    if not key:
        key=enqueue(store,242,0,WORKFLOW,BRANCH)
        run(key)
        nxt=enqueue(store,243,0,WORKFLOW,BRANCH)
        code=pump(store,nxt,dispatch,lambda key:None)
        print(json.dumps({'event':'DISPATCH','requested':BRANCH,'actual':BRANCH,'key':nxt,'exit':code}),flush=True)
        if code!=4: raise RuntimeError('DISPATCH_FAILED')
    else: run(key)
