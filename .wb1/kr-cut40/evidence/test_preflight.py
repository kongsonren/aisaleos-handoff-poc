import copy, json
from recovery_preflight import inspect,BRANCH
def row(seq=241,**changes):
    r=dict(key=BRANCH+':'+str(seq),seq=seq,branch=BRANCH,workflow='nezha-auto.yml',due=0,attempts=0,status='PENDING')
    r.update(changes); return {r['key']:r}
cases=[('eligible is still deployment gated',row(),'ELIGIBLE_AFTER_DEPLOYMENT_GATES'),
 ('future',row(due=100),'WAIT'),('exhausted',row(attempts=3),'BLOCKED'),
 ('seq243',row(seq=243),'BLOCKED'),('main row',row(branch='main'),'BLOCKED'),
 ('wrong workflow',row(workflow='mozi-auto.yml'),'BLOCKED'),
 ('unknown',row(status='UNKNOWN',attempts=1),'RECONCILE_ONLY_NO_POST'),
 ('crashed claim',row(status='INFLIGHT',attempts=1),'RECONCILE_ONLY_NO_POST'),
 ('submitted',row(status='SENT',attempts=1),'RECONCILE_ONLY_NO_POST'),
 ('ack is not result',row(status='ACK',attempts=1,run_id='38444409084'),'VERIFY_EXECUTION_SEPARATELY'),
 ('invalid ack',row(status='ACK'),'BLOCKED'),('invalid due',row(due=float('nan')),'BLOCKED')]
for name,state,expected in cases:
    before=copy.deepcopy(state); out=inspect(state,10)
    assert out['rows'][0]['decision']==expected and out['writes']==out['dispatches']==0
    # JSON handles NaN for this equality comparison without NaN != NaN false positives.
    assert json.dumps(state,sort_keys=True)==json.dumps(before,sort_keys=True)
    print(json.dumps(dict(case=name,verdict='PASS',decision=expected)))
print('PASS 12 preflight cases; no deployment or remote execution')
