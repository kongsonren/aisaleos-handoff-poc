"""Read-only recovery planner. No network, imports of daemon, dispatch or writes."""
import argparse, json, math
BRANCH='kr-cut39-isolated-20261014'
WORKFLOW='nezha-auto.yml'
STATES={'PENDING','INFLIGHT','UNKNOWN','SENT','ACK','BLOCKED'}
def inspect(state,now):
    if not isinstance(state,dict): raise ValueError('ledger must be object')
    decisions=[]
    for key,row in sorted(state.items()):
        reason=[]
        if not isinstance(row,dict):
            decisions.append(dict(key=key,decision='BLOCKED',reasons=['row must be object'])); continue
        seq=row.get('seq'); due=row.get('due'); attempts=row.get('attempts')
        if row.get('branch')!=BRANCH or row.get('workflow')!=WORKFLOW: reason.append('exact scope mismatch')
        if type(seq)!=int or seq<1 or key!=BRANCH+':'+str(seq) or row.get('key')!=key: reason.append('identity mismatch')
        if type(due) not in (int,float) or not math.isfinite(due): reason.append('invalid due')
        if type(attempts)!=int or not 0<=attempts<=3: reason.append('invalid attempt count')
        status=row.get('status')
        if status not in STATES: reason.append('invalid state')
        if status=='ACK' and not str(row.get('run_id','')).isdigit(): reason.append('missing numeric run id')
        if reason: decision='BLOCKED'
        elif status=='ACK': decision='VERIFY_EXECUTION_SEPARATELY'
        elif status=='BLOCKED': decision='BLOCKED'
        elif status in ('INFLIGHT','UNKNOWN','SENT'): decision='RECONCILE_ONLY_NO_POST'
        elif attempts>=3: decision='BLOCKED'; reason.append('attempt budget exhausted')
        elif due>now: decision='WAIT'
        elif seq not in (241,242): decision='BLOCKED'; reason.append('current receiver only accepts seq241/242')
        else: decision='ELIGIBLE_AFTER_DEPLOYMENT_GATES'
        decisions.append(dict(key=key,decision=decision,reasons=reason))
    return dict(mode='READ_ONLY_PLAN',deployment='BLOCKED',writes=0,dispatches=0,rows=decisions)
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('ledger'); p.add_argument('--now',type=float,required=True)
    args=p.parse_args()
    with open(args.ledger,encoding='utf-8-sig') as f: state=json.load(f)
    print(json.dumps(inspect(state,args.now),indent=2,sort_keys=True))
