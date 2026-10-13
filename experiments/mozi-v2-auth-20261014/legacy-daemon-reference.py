import os, json, time, hashlib, urllib.request, pathlib, datetime, re
REPO = 'kongsonren/aisaleos-handoff-poc'
root = pathlib.Path(os.environ['STATE_DIRECTORY'])
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def log(event, **kw):
    row = dict(kw)
    row.update(at=now(), event=event, pid=os.getpid())
    with (root/'ledger.jsonl').open('a') as f:
        f.write(json.dumps(row)+'\n'); f.flush(); os.fsync(f.fileno())
    print(json.dumps(row), flush=True)
def api(method, path, data=None):
    req = urllib.request.Request('https://api.github.com/repos/'+REPO+path,
        data=None if data is None else json.dumps(data).encode(), method=method,
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],
        'Accept':'application/vnd.github+json','User-Agent':'KR-isolated-daemon-v2','Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r: return json.load(r)
def pages(path):
    out=[]
    for page in range(1,101):
        rows=api('GET',path+('&' if '?' in path else '?')+'per_page=100&page='+str(page))
        out.extend(rows)
        if len(rows)<100: return out
    raise ValueError('pagination limit')
def save(path, data):
    tmp=path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(data,f,sort_keys=True); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)
    fd=os.open(path.parent,os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
def consume(task):
    if 'pull_request' in task or task['user']['login']!='kongsonren': return
    if not task['title'].startswith('[ISOLATED-DAEMON-POC] '): return
    p=json.loads(task['body']); run=p.get('run_id',''); issue=task['number']
    if set(p)!={'protocol','run_id','action','content'} or p['protocol']!='isolated-file-v1' or p['action']!='write_read_hash': raise ValueError('protocol rejected')
    if not re.fullmatch(r'CLOUD-DAEMON-\d{8}-\d{2}',run) or task['title']!='[ISOLATED-DAEMON-POC] '+run: raise ValueError('identity rejected')
    if not isinstance(p['content'],str) or len(p['content'].encode())>4096: raise ValueError('content rejected')
    # Preserve the original successful task and its historical artifacts.
    if issue==15 and run=='CLOUD-DAEMON-20261013-01': return
    folder=root/('issue-'+str(issue)+'-'+run)
    if folder.is_symlink(): raise ValueError('symlink rejected')
    folder.mkdir(mode=0o700,exist_ok=True)
    receipt=folder/'receipt.json'; pending=folder/'pending.json'
    fingerprint=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()
    if receipt.exists():
        old=json.loads(receipt.read_text())
        if old['payload_sha256']!=fingerprint: raise ValueError('payload changed')
        log('IDLE_ALREADY_VERIFIED',issue=issue,run_id=run,comment_id=old['comment_id'],sha256=old['sha256']); return
    log('TASK_DISCOVERED',issue=issue,run_id=run)
    target=folder/'test.txt'; content=p['content'].encode()
    if target.is_symlink(): raise ValueError('symlink rejected')
    if not target.exists():
        fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f: f.write(content); f.flush(); os.fsync(f.fileno())
    actual=target.read_bytes()
    if actual!=content: raise ValueError('readback mismatch')
    if pending.exists():
        result=json.loads(pending.read_text())
        if result['payload_sha256']!=fingerprint: raise ValueError('pending payload changed')
    else:
        result=dict(type='RESULT',status='PASS',scope='isolated-file-operation-only',run_id=run,issue=issue,
            sha256=hashlib.sha256(actual).hexdigest(),bytes=len(actual),path=str(target),
            payload_sha256=fingerprint,host=os.uname().nodename,uid=os.getuid(),pid=os.getpid(),at=now())
        save(pending,result)
    body='[ISOLATED-DAEMON-RESULT]\n'+json.dumps(result,sort_keys=True)
    matches=[c for c in pages('/issues/'+str(issue)+'/comments') if c['body']==body]
    if len(matches)>1: raise ValueError('duplicate remote results')
    marker=folder/'post-attempt.json'
    if matches: posted=matches[0]
    elif marker.exists():
        log('POST_AMBIGUOUS_HOLD',issue=issue,run_id=run); return
    else:
        save(marker,dict(at=now()))
        log('POST_ATTEMPT',issue=issue,run_id=run,sha256=result['sha256'])
        posted=api('POST','/issues/'+str(issue)+'/comments',{'body':body})
    readback=api('GET','/issues/comments/'+str(posted['id']))
    if readback['body']!=body: raise ValueError('remote readback mismatch')
    result.update(comment_id=posted['id'],comment_url=posted['html_url'])
    save(receipt,result); log('RESULT_VERIFIED',**result)
log('START',uid=os.getuid(),version=2)
while True:
    try:
        tasks=pages('/issues?state=open&sort=created&direction=asc')
        log('SCAN',open_count=len(tasks))
        for task in tasks:
            try: consume(task)
            except Exception as exc: log('TASK_ERROR',issue=task.get('number'),error=type(exc).__name__)
    except Exception as exc: log('SCAN_ERROR',error=type(exc).__name__,http_status=getattr(exc,'code',None))
    time.sleep(15)
