"""CUT40 deployment review. No credentials, network, production imports or writes."""
import ast, copy, importlib.util, json, os, pathlib, sys, types
ROOT=pathlib.Path(__file__).resolve().parent
OLD=ROOT.parent/'kr-cut39-20261014'
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
D=module('cut39_durable',OLD/'durable_schedule.py')
sys.modules['durable_schedule']=D
C=module('cut39_cloud',OLD/'cloud_accept.py')
class Store:
    def __init__(self,state): self.state=copy.deepcopy(state); self.v=0
    def load(self): return copy.deepcopy(self.state),self.v
    def cas(self,s,v):
        if v!=self.v: return False
        self.state=copy.deepcopy(s); self.v+=1; return True
def emit(name,**kw): print(json.dumps(dict(case=name,**kw),sort_keys=True),flush=True)
B=C.BRANCH
def row(seq=243,branch=B):
    key=branch+':'+str(seq)
    return dict(key=key,seq=seq,due=0,status='PENDING',attempts=0,workflow='nezha-auto.yml',branch=branch)
# Real dispatch function, replace only HTTP. A different prefix-valid branch is misrouted.
calls=[]; C.api=lambda method,path,data: calls.append(data) or (204,None)
r=row(branch='kr-cut39-isolated-other'); C.dispatch(r)
assert calls[0]['ref']==B and calls[0]['ref']!=r['branch']
emit('adapter branch mismatch reproduced',verdict='FAIL',requested=r['branch'],actual=calls[0]['ref'],network=False)
# Real receiver rejects next sequence before ACK: scanner cannot advance this executor.
r=row(); s=Store({r['key']:r}); C.GitHubLedger=lambda *a:s
os.environ['GITHUB_REF']='refs/heads/'+B
try: C.run(r['key']); raise RuntimeError('expected rejection')
except AssertionError: pass
assert s.state[r['key']]['status']=='PENDING'
emit('receiver rejects seq243',verdict='FAIL',ack_written=False)
# ACK survives an executor failure because it is written before subprocess execution.
r=row(seq=242); s=Store({r['key']:r}); C.GitHubLedger=lambda *a:s
os.environ['GITHUB_RUN_ID']='CUT40-INJECTED-FAILED-RUN'
C.subprocess=types.SimpleNamespace(run=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('injected executor failure')))
try: C.run(r['key']); raise AssertionError('expected execution failure')
except RuntimeError as e: assert str(e)=='injected executor failure'
assert s.state[r['key']]['status']=='ACK'
emit('ACK is start-only, not completion',verdict='PASS_FINDING',status='ACK',execution='FAILED',fault_injection=True)
# pump trusts stored row scope; construction-time branch guard is insufficient for a scanner.
r=row(branch='main'); s=Store({r['key']:r}); posts=[]
code=D.pump(s,r['key'],lambda item:posts.append(item) or 204,lambda key:None,now=1)
assert len(posts)==1 and posts[0]['branch']=='main'
emit('pump lacks per-row scope guard',verdict='FAIL',dispatch_observer_calls=1,exit=code,network=False)
# Review actual GitHubStore constructor, not CUT39's permissive test double.
raw=json.loads((ROOT/'task-state.json').read_text(encoding='utf-8'))
source=raw['structuredContent']['content']; tree=ast.parse(source)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='GitHubStore')
init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
emit('actual GitHubStore constructor',parameters=[a.arg for a in init.args.args])
print('PASS CUT40 review reproductions; FAIL findings are deployment blockers, not failed test assertions')
