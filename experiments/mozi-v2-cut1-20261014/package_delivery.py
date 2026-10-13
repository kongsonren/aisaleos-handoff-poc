"""Prepare exact UTF-8 Git tree entries; no network or credentials."""
import difflib
import hashlib
import json
import pathlib
ROOT=pathlib.Path(__file__).resolve().parent
names=['daemon.py','test_daemon.py','test_security.py','run_tests.py','entrypoint.py',
       'test_entrypoint.py','validate.py','package_delivery.py','.gitignore','REPORT.md','KR_GATE.md',
       'identity-verification.json','validation.json','green-original20.log','green-entry.log',
       'red-entry.log','red-audit.log','red-mutant-identity.log','red-mutant-digest.log','red-mutant-audit.log']
prefix='experiments/mozi-v2-cut1-20261014/'
patch=[]
for name in names:
    text=(ROOT/name).read_bytes().decode('utf-8')
    patch.extend(difflib.unified_diff([],text.splitlines(keepends=True),fromfile='/dev/null',tofile='b/'+prefix+name))
(ROOT/'changes.diff').write_bytes(''.join(patch).encode('utf-8'))
names.append('changes.diff')
manifest={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
(ROOT/'SHA256SUMS.json').write_bytes((json.dumps(manifest,indent=2)+'\n').encode())
names.append('SHA256SUMS.json')
entries=[dict(path=prefix+n,mode='100644',type='blob',content=(ROOT/n).read_bytes().decode('utf-8')) for n in names]
out=ROOT.parent/'evidence'/'mozi-v2-cut1-delivery-20261014'; out.mkdir(exist_ok=True)
(out/'tree-payload.json').write_bytes(json.dumps(entries,ensure_ascii=False).encode('utf-8'))
print(json.dumps(dict(files=len(names),manifest_sha256=hashlib.sha256((ROOT/'SHA256SUMS.json').read_bytes()).hexdigest(),bytes=sum((ROOT/n).stat().st_size for n in names))))
