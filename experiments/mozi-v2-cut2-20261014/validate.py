"""Real guard-removal mutations, isolated copies; synthetic network only."""
import pathlib, shutil, subprocess, sys, tempfile, json
root=pathlib.Path(__file__).resolve().parent
mutants={
 'issue':("        require(i.get('body')==p.issue_body and digest(i['body'].encode())==p.issue_sha256)","        pass",'test_proxy.Tests.test_issue_binding'),
 'attempt':("        require(self.db.execute('SELECT count(*) FROM once').fetchone()==(0,))","        self.db.execute('DELETE FROM once')",'test_proxy.Tests.test_success_and_restart'),
 'readback':("            self.comment(self.wire.request('GET','/repos/'+REPO+'/issues/comments/'+str(cid)),cid)","            self.wire.request('GET','/repos/'+REPO+'/issues/comments/'+str(cid))",'test_proxy.Tests.test_wrong_readback_no_retry')}
results={}
for name,(old,new,test) in mutants.items():
    with tempfile.TemporaryDirectory() as tmp:
        dst=pathlib.Path(tmp)
        for f in ('proxy.py','entrypoint.py','test_proxy.py'): shutil.copyfile(root/f,dst/f)
        source=(dst/'proxy.py').read_text(); assert old in source
        (dst/'proxy.py').write_text(source.replace(old,new),encoding='utf-8')
        p=subprocess.run([sys.executable,'-m','unittest',test,'-v'],cwd=dst,capture_output=True)
        (root/('red-mutant-'+name+'.log')).write_bytes(p.stdout+p.stderr)
        results[name]=p.returncode
(root/'mutation-results.json').write_text(json.dumps(results,indent=2)+'\n')
assert all(results.values()),results
print(results)
