from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import block_contracts as bc
import experiment_wizard as wizard
import kaggle_data as kg
import huggingface_models as hf
import local_operations
import ml_operations as ml
import pipeline_runner as pr
import project_store as ps
import resource_store


CSV='id,x,z,label\n'+''.join(f'{i},{i},{i%3},{"low" if i<20 else "high"}\n' for i in range(40))


class ExperimentWizardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.patches=[patch.object(ps,'ROOT',self.root),patch.object(pr,'ROOT',self.root),patch.object(kg,'ROOT',self.root),patch.object(hf,'ROOT',self.root)]
        for p in self.patches:p.start()
        self.body={'csv':CSV,'filename':'sample.csv','delimiter':'auto','config':{'name':'My classification','target':'label','features':['x','z'],'missing':'error','duplicates':'drop','test_size':.2,'seed':42}}
        self.server=SimpleNamespace()
    def tearDown(self):
        for r in getattr(self.server,'project_runners',{}).values():
            if r.thread:r.cancel_event.set();r.thread.join(10)
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def create(self,body=None):
        body=body or self.body;preview=wizard.request(self.root,body,'preview')
        request={**body,'digest':preview['digest'],'request_id':str(uuid.uuid4())}
        return wizard.request(self.root,request,'create'),request
    def test_preview_readonly_columns_and_split_feasibility(self):
        view=wizard.request(self.root,self.body,'inspect');self.assertEqual(view['profile']['rows'],40)
        self.assertFalse(next(c for c in view['profile']['columns'] if c['name']=='id')['recommended'])
        preview=wizard.request(self.root,self.body,'preview');self.assertEqual((preview['train_rows'],preview['test_rows']),(32,8))
        self.assertEqual(len(preview['steps']),6);self.assertEqual(list(self.root.iterdir()),[])
        small={**self.body,'csv':'x,label\n1,a\n2,a\n3,b\n4,b\n','config':{**self.body['config'],'features':['x']}}
        with self.assertRaisesRegex(bc.ContractError,'слишком мало'):wizard.request(self.root,small,'preview')
        small['config']['test_size']=.5;self.assertEqual(wizard.request(self.root,small,'preview')['test_rows'],2)
    def test_uploaded_dataset_runs_on_cpu_and_is_not_in_portable_graph(self):
        project,body=self.create();diagram=project['diagram'];self.assertEqual(len(diagram['nodes']),6)
        source=next(n for n in diagram['nodes'] if n['id']=='csv')['block'];ref=source['inputs']['dataset']
        self.assertEqual(ref['provider'],'local')
        exported=json.dumps(ps.ProjectStore(self.root).export(project['project']['id']))
        self.assertNotIn(json.dumps(CSV),exported)
        self.assertNotIn('rows',next(n for n in diagram['nodes'] if n['id']=='ml_prepare')['block']['inputs'])
        self.assertEqual(set(source['inputs']),{'dataset','file'})
        self.assertEqual(local_operations.read_csv(source,kg)['details']['row_count'],40)
        run=pr.request(self.server,{'project_id':project['project']['id'],'revision':1,'compute':{'mode':'cpu'}},'start',None,kg,hf)
        runner=self.server.project_runners[project['project']['id']];runner.thread.join(30)
        self.assertEqual(runner.get(run['id'])['status'],'ready',runner.get(run['id']).get('error'))
        saved=runner.step(run['id'],'ml_save');self.assertEqual(saved['outputs']['bundle']['kind'],'model_bundle')
        context=SimpleNamespace(root=self.root);asset=next(a for a in resource_store.inventory(context)['artifacts'] if a['id']==ref['id']);self.assertFalse(asset['removable'])
        self.assertEqual(wizard.request(None,body,'create')['project']['id'],project['project']['id'])
        changed=deepcopy(body);changed['config']['name']='Different';changed['digest']=wizard.request(self.root,changed,'preview')['digest']
        with self.assertRaisesRegex(bc.ContractError,'уже создал'):wizard.request(self.root,changed,'create')
    def test_local_csv_is_private_hash_checked_and_has_no_path_access(self):
        project,_=self.create();source=project['diagram']['nodes'][0]['block'];ref=source['inputs']['dataset']
        with self.assertRaises(bc.ContractError):local_operations.read_csv(source,SimpleNamespace(ROOT=self.root/'other'))
        bad=deepcopy(source);bad['inputs']['file']='../../README.md'
        with self.assertRaises(bc.ContractError):local_operations.read_csv(bad,kg)
        path=ml.artifact_dir(self.root)/(ref['id']+'.json');path.write_text('{}')
        with self.assertRaisesRegex(bc.ContractError,'контрольная сумма'):local_operations.read_csv(source,kg)
        with self.assertRaises(bc.ContractError):bc.validate_artifact({**ref,'id':'../../file'},'dataset')
    def test_missing_duplicates_classes_and_digest_validation(self):
        body=deepcopy(self.body);body['csv']=CSV+'41,,1,low\n0,0,0,low\n'
        with self.assertRaisesRegex(bc.ContractError,'Строка'):wizard.request(self.root,body,'preview')
        body['config']['missing']='drop';view=wizard.request(self.root,body,'preview')
        self.assertEqual(view['preparation']['dropped_rows'],1);self.assertEqual(view['preparation']['duplicates_removed'],1)
        with self.assertRaises(bc.ContractError):wizard.request(self.root,{**body,'digest':'old','request_id':str(uuid.uuid4())},'create')
        for config in [{'task':'regression'},{'target':['bad']},{'features':['label']},{'features':[]},{'test_size':True}]:
            with self.assertRaises(bc.ContractError):wizard.request(self.root,{**self.body,'config':{**self.body['config'],**config}},'preview')
    def test_auto_delimiter_with_wide_rows(self):
        header = ','.join(f'feature{i}' for i in range(101))
        row = ','.join(['1234567890'] * 101)
        view = wizard.inspect({'csv': header + '\n' + (row + '\n') * 30})[0]
        self.assertEqual(view['delimiter'], ',')
        self.assertEqual(len(view['profile']['columns']), 101)

    def test_csv_limits_quoted_semicolon_unicode_and_bad_headers(self):
        view=wizard.request(self.root,{**self.body,'csv':'\ufeffчисло;класс\n1;"a;b"\n2;c\n'},'inspect');self.assertEqual(view['delimiter'],';');self.assertEqual(view['sample'][0]['класс'],'a;b')
        for text in ['x,x\n1,2\n',' x,y\n1,a\n','x,y\n1,2,3\n']:
            with self.assertRaises(bc.ContractError):wizard.request(self.root,{**self.body,'csv':text,'delimiter':','},'inspect')


if __name__=='__main__':unittest.main()

