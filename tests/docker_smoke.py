"""Run only against an isolated Docker Compose installation in CI."""
import json,time
from urllib.request import Request,urlopen

def api(route,body=None):
    req=Request('http://127.0.0.1:8770/api/'+route,json.dumps(body or {}).encode(),{'Content-Type':'application/json','X-Architect-Request':'1'})
    with urlopen(req,timeout=90) as r:return json.load(r)
for _ in range(120):
    try:api('local/info');break
    except OSError:time.sleep(1)
else:raise AssertionError('Application failed to start')
code='''import numpy as np
from sklearn.linear_model import LogisticRegression
def run(inputs, params):
    model=LogisticRegression().fit([[0],[1],[9],[10]],[0,0,1,1])
    print("isolated-python-ok")
    return {"report":{"accuracy":float(model.score([[0],[10]],[0,1]))},"rows":[{"x":int(np.sum([1,2]))}]}
'''
graph={'format':'architect','version':3,'name':'CI isolated Python','types':[{'id':'python','name':'Python','description':'','color':'#6366f1','block':{'kind':'python_code','version':1}}], 'nodes':[{'id':'code','typeId':'python','name':'Python','description':'','x':80,'y':80,'block':{'kind':'python_code','version':1,'settings':{'code':code,'params':'{}','timeout':30}}}],'edges':[]}
created=api('projects/create',{'name':'CI isolated Python','diagram':graph})
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
assert step['details']['runtime']['network'] is False,step
assert 'isolated-python-ok' in step['details']['logs'],step
print('PASS: compose, local project, real Python container and sklearn training')
