import hashlib,json,pathlib
P=pathlib.Path(__file__).parent
def content(name):
    x=json.loads((P/name).read_text(encoding='utf-8-sig'))
    if 'value' in x: x=x['value']['value']
    return x['structuredContent']['content']
out=[]
for job,sha in [(115458934404,'76253379d9569ce190ac9e3246dd24dbf1905651'),(115459048778,'045967553eab2d370a40e4ec54e0ed61fa812af9')]:
    log=content('job-'+str(job)+'.json')
    assert 'REAL_EXECUTOR_COMPLETE' in log and sha in log
    if job==115458934404: assert 'NEXT_RUN_ACK' in log
    out.append(dict(job=job,head_sha=sha,completion_marker=True,log_sha256=hashlib.sha256(log.encode()).hexdigest()))
pinned=content('pinned-module.json').replace('\r\n','\n')
local=(P.parent/'kr-cut39-20261014/durable_schedule.py').read_text(encoding='utf-8').replace('\r\n','\n')
assert pinned==local
out.append(dict(pinned_module_matches_local=True,normalized_sha256=hashlib.sha256(pinned.encode()).hexdigest()))
print(json.dumps(dict(verdict='PASS',evidence=out),indent=2))
