import json,pathlib,re,hashlib
p=pathlib.Path(__file__).parent
ledger=json.loads((p/'ledger.json').read_text())
expected={243:('38450675509','115480439945','a1868a25f9574fe66b4c7c67e7092b1f399eaaaa'),244:('38450710846','115480595991','cf5bb07028cfb3f3f6dc1e81ee566d947264e50d')}
for seq,(run,job,sha) in expected.items():
    key='kr-cut41-isolated-20261014:'+str(seq); row=ledger[key]
    assert row['status']=='EXECUTION_COMPLETE' and row['run_id']==run
    assert row['result']==dict(branch=row['branch'],workflow='nezha-auto.yml',key=key,run_id=run,sha=sha,exit_code=0)
    log=(p/('job-'+job+'.log')).read_text(encoding='utf-8-sig')
    events=[]
    for line in log.splitlines():
        match=re.search(r'\{.*\}$',line)
        if match:
            try: events.append(json.loads(match.group()))
            except json.JSONDecodeError: pass
    actual=[e for e in events if e.get('run_id')==run and e.get('key')==key]
    assert [e['event'] for e in actual]==['ACK','EXECUTION_COMPLETE']
    assert actual[-1]['sha']==sha and actual[-1]['exit_code']==0
    assert 'Ran 11 tests' in log
    print(json.dumps(dict(seq=seq,run=run,job=job,sha=sha,verdict='PASS',source='real run events; synthetic run IDs excluded')))
print('PASS independent evidence correlation')
