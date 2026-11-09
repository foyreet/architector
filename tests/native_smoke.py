"""Real pipeline test in a disposable local workspace."""
from pathlib import Path
import os, socket, subprocess, sys, tempfile
import json,time
from urllib.request import Request,urlopen

def api(route,body=None):
    req=Request(origin+'/api/'+route,json.dumps(body or {}).encode(),{'Content-Type':'application/json','X-Architect-Request':'1'})
    with urlopen(req,timeout=90) as r:return json.load(r)

root=Path(__file__).resolve().parents[1]
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
origin=f'http://127.0.0.1:{port}'
with tempfile.TemporaryDirectory(prefix='native-pipeline-') as data:
    env={**os.environ,'ARCHITECT_DATA_DIR':data,'ARCHITECTOR_PYTHON_MEMORY_MB':'1024'}
    env.pop('ARCHITECT_CODE_SOCKET',None)
    app=subprocess.Popen([sys.executable,str(root/'serve.py'),'--port',str(port)],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(120):
            try:api('local/info');break
            except OSError:time.sleep(1)
        else:raise AssertionError('Application failed to start')
        code='''import numpy as np
from sklearn.linear_model import LogisticRegression
def run(inputs, params):
    model=LogisticRegression().fit([[0],[1],[9],[10]],[0,0,1,1])
    print("native-python-ok")
    return {"report":{"accuracy":float(model.score([[0],[10]],[0,1]))},"rows":[{"x":int(np.sum([1,2]))}]}
'''
        graph={'format':'architect','version':3,'name':'CI native Python','types':[{'id':'python','name':'Python','description':'','color':'#6366f1','block':{'kind':'python_code','version':1}}], 'nodes':[{'id':'code','typeId':'python','name':'Python','description':'','x':80,'y':80,'block':{'kind':'python_code','version':1,'settings':{'code':code,'params':'{}','timeout':30}}}],'edges':[]}
        created=api('projects/create',{'name':'CI native Python','diagram':graph})
        project_id=created['project']['id'];run=api('pipelines/start',{'project_id':project_id,'revision':created['project']['revision']})
        for _ in range(90):
            run=api('pipelines/run',{'project_id':project_id,'run_id':run['id']})
            if run['status'] not in ('queued','running','waiting'):break
            time.sleep(1)
        assert run['status']=='ready',run
        step=api('pipelines/step',{'project_id':project_id,'run_id':run['id'],'node_id':'code'})
        assert step['outputs']['report']['accuracy']==1,step
        assert step['outputs']['rows']==[{'x':3}],step
        assert step['details']['runtime']['memory_mb']==1024,step
        assert step['details']['runtime']['executor'] == 'local-process',step
        assert 'native-python-ok' in step['details']['logs'],step
        print('PASS: local project, real native Python process and sklearn training')
    finally:
        app.terminate();app.wait(timeout=10)
