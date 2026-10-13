import pathlib,json,hashlib,difflib
r=pathlib.Path(__file__).resolve().parent
names=['daemon.py','entrypoint.py','test_daemon.py','test_security.py','test_entrypoint.py','proxy.py','test_proxy.py','validate.py','package.py','REPORT.md','KR_GATE.md','identity-verification.json','green-all.log','initial-failure.log','mutation-results.json','red-mutant-issue.log','red-mutant-attempt.log','red-mutant-readback.log']
prefix='experiments/mozi-v2-cut2-20261014/'
diff=''.join(''.join(difflib.unified_diff([], (r/n).read_bytes().decode('utf-8',errors='replace').splitlines(True),fromfile='/dev/null',tofile='b/'+prefix+n)) for n in names)
(r/'changes.diff').write_bytes(diff.encode()); names.append('changes.diff')
(r/'SHA256SUMS.json').write_text(json.dumps({n:hashlib.sha256((r/n).read_bytes()).hexdigest() for n in names},indent=2)+'\n',encoding='utf-8'); names.append('SHA256SUMS.json')
# Git blob upload is base64 to preserve exact bytes, including native log encoding.
(r/'upload.json').write_text(json.dumps(names),encoding='utf-8')
print(len(names))
