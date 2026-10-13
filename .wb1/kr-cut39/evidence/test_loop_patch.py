import ast,os,sys,types,tempfile,pathlib,json
import durable_schedule as D
from test_schedule import DiskLedger
root=pathlib.Path(__file__).parent
tree=ast.parse((root/'loop_candidate.py').read_text(encoding='utf-8'))
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='wait_and_schedule')
with tempfile.TemporaryDirectory() as folder:
    ledger=DiskLedger(pathlib.Path(folder)/'store.db'); posts=[]
    D.GitHubLedger=lambda api,branch:ledger
    sys.modules['cloud_accept']=types.SimpleNamespace(api=None,dispatch=lambda row:posts.append(row['key']) or 204)
    class Store:
        def __init__(self,*args,**kwargs): pass
        def read_json(self,*args,**kwargs): return {'round_seq':seq},None,None,200
    ns=dict(os=os,sys=sys,__file__=str(root/'loop_candidate.py'),GitHubStore=Store,
        TOKEN='NO-CREDENTIAL',REPO='isolated',HEARTBEAT_PATH='isolated',log=print)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'patched-loop-function','exec'),ns)
    os.environ['NEZHA_SCHEDULE_BRANCH']='kr-cut39-isolated-20261014'
    for seq in (240,241,1000):
        before=len(posts); code=ns['wait_and_schedule']()
        assert code==4 and len(posts)==before+1
        assert ns['wait_and_schedule']()==4 and len(posts)==before+1
        print(json.dumps({'actual_patched_loop_seq':seq,'exit':code,'posts':1,'duplicate_posts':0}))
    os.environ['NEZHA_SCHEDULE_BRANCH']='main'
    assert ns['wait_and_schedule']()==3
print('PASS actual patched wait_and_schedule function; no network calls')
