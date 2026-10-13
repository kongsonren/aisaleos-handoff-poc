"""Capture raw byte logs and reproducible red mutation/green results offline."""
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT=pathlib.Path(__file__).resolve().parent
started=datetime.now(timezone.utc).isoformat()
results=[]
def run(name,args,cwd=ROOT):
    p=subprocess.run([sys.executable,'-B',*args],cwd=cwd,capture_output=True)
    (ROOT/name).write_bytes(p.stdout+p.stderr)
    results.append(dict(log=name,exit=p.returncode,sha256=hashlib.sha256(p.stdout+p.stderr).hexdigest()))
    return p.returncode

# Remove one real guard at a time; the same security assertions must detect it.
source=(ROOT/'entrypoint.py').read_text(encoding='utf-8')
mutants=[('identity',"    if type(issue) is not dict:","    return copy.deepcopy(issue)\n    if type(issue) is not dict:",'test_issue_metadata_and_principal'),
         ('digest',"if hashlib.sha256(raw).hexdigest()!=DAEMON_SHA:","if False:",'test_source_digest_before_import'),
         ('audit',"for event,event_hash in db.execute('SELECT event,event_hash FROM audit'):","for event,event_hash in []:",'test_audit_digest_tamper')]
for name,old,new,test in mutants:
    assert old in source
    with tempfile.TemporaryDirectory() as tmp:
        dst=pathlib.Path(tmp)
        for file in ('daemon.py','test_daemon.py','test_entrypoint.py'):
            (dst/file).write_bytes((ROOT/file).read_bytes())
        (dst/'entrypoint.py').write_text(source.replace(old,new,1),encoding='utf-8')
        assert run('red-mutant-'+name+'.log',['-m','unittest','test_entrypoint.EntryTests.'+test,'-v'],dst)!=0
assert run('green-original20.log',['-m','unittest','test_security.Security','test_daemon.Tests','-v'])==0
assert run('green-entry.log',['-m','unittest','test_entrypoint.EntryTests','-v'])==0
(ROOT/'validation.json').write_text(json.dumps(dict(started_utc=started,ended_utc=datetime.now(timezone.utc).isoformat(),
    python=sys.version,mode='OFFLINE_MOCK',results=results),indent=2),encoding='utf-8')
print(json.dumps(results,indent=2))
