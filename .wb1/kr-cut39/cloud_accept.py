"""Two-beat isolated cloud acceptance, never imports production executors."""
import json, os, pathlib, subprocess, sys, time, urllib.request, urllib.error
from durable_schedule import GitHubLedger,ack,enqueue,pump
BRANCH='kr-cut39-isolated-20261014'
REPO='kongsonren/aisaleos-handoff-poc'
def api(method,path,data=None):
    req=urllib.request.Request('https://api.github.com/repos/'+REPO+path,method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json',
                 'Content-Type':'application/json','User-Agent':'kr-cut39-isolated-cloud'})
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read(); return r.status,json.loads(raw) if raw else None
    except urllib.error.HTTPError as e: return e.code,e.read().decode()[:300]
def dispatch(item):
    return api('POST','/actions/workflows/nezha-auto.yml/dispatches',
        {'ref':BRANCH,'inputs':{'schedule_key':item['key']}})[0]
def run(key):
    assert os.environ['GITHUB_REF']=='refs/heads/'+BRANCH
    store=GitHubLedger(api,BRANCH)
    item=store.load()[0][key]
    assert item['branch']==BRANCH and item['seq'] in (241,242)
    ack(store,key,os.environ['GITHUB_RUN_ID'])
    subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('test_schedule.py'))],check=True)
    print(json.dumps({'event':'REAL_EXECUTOR_COMPLETE','seq':item['seq'],'run_id':os.environ['GITHUB_RUN_ID'],
        'sha':os.environ['GITHUB_SHA'],'scope':'isolated-scheduler-regression','host':os.uname().nodename}),flush=True)
    if item['seq']==241:
        nxt=enqueue(store,241,time.time(),'nezha-auto.yml',BRANCH)
        code=pump(store,nxt,dispatch,lambda key:None)
        print(json.dumps({'event':'NEXT_DURABLE_INTENT','key':nxt,'dispatch_exit':code}),flush=True)
        if code!=4: raise RuntimeError('next beat dispatch failed')
        # 204 is only SUBMITTED; independently observe receiver ACK from next runner.
        for _ in range(20):
            state=store.load()[0][nxt]
            if state['status']=='ACK':
                print(json.dumps({'event':'NEXT_RUN_ACK','record':state}),flush=True); break
            time.sleep(3)
        else: raise RuntimeError('NEXT_BEAT_UNCONFIRMED')
    else:
        print('ISOLATED_ACCEPTANCE_BUDGET_COMPLETE: two cloud executions; no indefinite recursion',flush=True)
if __name__=='__main__': run(os.environ['SCHEDULE_KEY'])
