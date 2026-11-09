from fixtures import sample_project
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import analysis_tools as at
import block_contracts as bc
import local_workspace as community
import experiment_queue as eq
import huggingface_models as hf
import kaggle_data as kg
import ml_operations as ml
import pipeline_runner as pr
import project_insights as pi
import project_store as ps
import resource_store as rs
import subgraphs

ROOT=Path(__file__).resolve().parents[1]


class LabTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patches=[patch.object(ps,'ROOT',self.root),patch.object(pr,'ROOT',self.root),patch.object(kg,'ROOT',self.root),patch.object(hf,'ROOT',self.root)]
        for p in self.patches:p.start()
        self.server=SimpleNamespace();self.context=SimpleNamespace(root=self.root,server=self.server,pipeline=pr,kaggle=kg,huggingface=hf,completion=None)
        self.project=sample_project(self.root);self.ref={'project_id':self.project['project']['id'],'revision':1}
    def tearDown(self):
        queue=getattr(self.server,'experiment_queue',None)
        if queue:
            for c,i,_ in list(queue.jobs):queue.cancel(c,i)
            if queue.thread:queue.thread.join(20)
        for runner in getattr(self.server,'project_runners',{}).values():
            if runner.thread:runner.thread.join(10)
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def batch(self):
        return {**self.ref,'axes':[{'node_id':'ml_train','setting':'n_estimators','values':[10,20]},{'node_id':'ml_train','setting':'max_depth','values':[2,3]}], 'metric':'ml_evaluate/accuracy','direction':'max'}
    def start_batch(self,body=None):
        body=body or self.batch();preview=eq.request(self.server,self.context,body,'preview')
        body={**body,'digest':preview['digest'],'request_id':str(uuid.uuid4())}
        return eq.request(self.server,self.context,body,'start'),body
    def train(self):
        run=pr.request(self.server,self.ref,'start',None,kg,hf);runner=self.server.project_runners[self.ref['project_id']];runner.thread.join(60)
        self.assertEqual(runner.get(run['id'])['status'],'ready')
        return runner,run,runner.step(run['id'],'ml_save')['outputs']['bundle']
    def test_series_sequential_snapshots_metrics_and_idempotency(self):
        batch,body=self.start_batch();self.server.experiment_queue.thread.join(60)
        finished=eq.request(self.server,self.context,{'id':batch['id']},'get')
        self.assertEqual(finished['status'],'finished');self.assertEqual(len(finished['items']),4)
        self.assertTrue(all(i['status']=='ready' for i in finished['items']),finished)
        self.assertIn(finished['best_run_id'],[i['run_id'] for i in finished['items']])
        self.assertNotIn('diagram',finished['items'][0]);self.assertNotIn('secrets',json.dumps(self.server.experiment_queue.read(self.context,batch['id'])))
        self.assertEqual(eq.request(self.server,self.context,body,'start')['id'],batch['id'])
        self.assertEqual(ps.ProjectStore(self.root).get(self.ref['project_id']),self.project)
        runner=self.server.project_runners[self.ref['project_id']]
        records=[runner.get(i['run_id']) for i in finished['items']]
        for a,b in zip(records,records[1:]):self.assertLessEqual(a['finished_at'],b['started_at'])
        other=SimpleNamespace(root=self.root/'other',kaggle=SimpleNamespace(ROOT=self.root/'other'))
        with self.assertRaises(bc.ContractError):eq.request(self.server,other,{'id':batch['id']},'get')
    def test_cancel_pending_restart_and_limits(self):
        self.server.pipeline_runner=SimpleNamespace(current={'status':'running'})
        batch,_=self.start_batch();cancelled=eq.request(self.server,self.context,{'id':batch['id']},'cancel')
        self.assertTrue(all(i['status']=='cancelled' for i in cancelled['items']))
        self.server.experiment_queue.thread.join(5)
        self.assertFalse(getattr(self.server,'project_runners',{}))
        record=self.server.experiment_queue.read(self.context,batch['id']);record['status']='running';record['items'][0]['status']='running';record['items'][1]['status']='queued';self.server.experiment_queue.write(self.context,record)
        restarted=eq.Queue(self.server);result=restarted.get(self.context,batch['id']);self.assertEqual(result['status'],'interrupted');self.assertEqual(result['items'][0]['status'],'error');self.assertEqual(result['items'][1]['status'],'queued')
        self.server.pipeline_runner.current=None;self.server.experiment_queue=restarted
        restarted.resume(self.context,{'id':batch['id']});restarted.thread.join(30)
        resumed=restarted.get(self.context,batch['id'])
        self.assertEqual([i['status'] for i in resumed['items']],['error','ready','cancelled','cancelled'])
        self.assertEqual(len(self.server.project_runners[self.ref['project_id']].history()['runs']),1)
        invalid=self.batch();invalid['axes'][0]['values']=list(range(10,20));invalid['axes'][1]['values']=list(range(1,5))
        with self.assertRaises(bc.ContractError):eq.prepare(self.context,invalid)
        body=self.batch();body['revision']=0
        with self.assertRaises(bc.ContractError):eq.prepare(self.context,body)
        with self.assertRaises(bc.ContractError):eq.request(self.server,self.context,{**self.batch(),'digest':'stale','request_id':str(uuid.uuid4())},'start')
    def test_analysis_and_csv_validation(self):
        data=at.analyze([{'x':i,'y':2*i,'class':'a' if i<5 else 'b','missing':None} for i in range(10)]+[{'x':100,'y':200,'class':'b','missing':''}],'class')
        self.assertAlmostEqual(next(c['value'] for c in data['correlations'] if c['a']=='x' and c['b']=='y'),1)
        self.assertEqual(data['statistics'][0]['outliers']['rows'],[11]);self.assertEqual(data['statistics'][3]['missing'],11)
        self.assertEqual(sum(c['count'] for c in data['balance']),11)
        for csv in ['x,x\n1,2','x,y\n1','x\n"unclosed']:
            with self.assertRaises(bc.ContractError):at.read_csv(csv)
        self.assertIsNone(at.analyze([{'x':1,'y':2},{'x':1,'y':3}])['correlations'][0]['value'])
    def test_predictions_pins_and_safe_cleanup(self):
        runner,run,model=self.train();origin={**self.ref,'run_id':run['id'],'node_id':'ml_save','port':'bundle'}
        value=at.predict(self.context,{'artifact':model,'origin':origin,'csv':'z,x\n0,1\n1,38'})
        self.assertEqual([r['prediction'] for r in value['rows']],['low','high'])
        self.assertEqual(len(at.prediction_list(self.context)['predictions']),1)
        with self.assertRaises(bc.ContractError):at.predict(self.context,{'artifact':model,'csv':'x\n1'})
        other=SimpleNamespace(kaggle=SimpleNamespace(ROOT=self.root/'other'),root=self.root/'other')
        with self.assertRaises(bc.ContractError):at.predict(other,{'artifact':model,'csv':'x,z\n1,1'})
        rs.request(self.server,self.context,{'artifact':model,'pinned':True,'label':'Important'},'pin')
        orphan=ml.save(self.root,'python_data',{'unused':True});path=ml.artifact_dir(self.root)/(orphan['id']+'.json');os.utime(path,(time.time()-120,)*2)
        pinned=ml.save(self.root,'python_data',{'important':True});pinned_path=ml.artifact_dir(self.root)/(pinned['id']+'.json');os.utime(pinned_path,(time.time()-120,)*2)
        rs.request(self.server,self.context,{'artifact':pinned,'pinned':True},'pin')
        plan=rs.request(self.server,self.context,{},'cleanup-preview');self.assertEqual(plan['count'],1)
        with self.assertRaises(bc.ContractError):rs.request(self.server,self.context,{'digest':'forged'},'cleanup')
        rs.request(self.server,self.context,{'digest':plan['digest']},'cleanup');self.assertFalse(path.exists());self.assertTrue(pinned_path.exists());self.assertTrue(ml.load(self.root,model,'model_bundle'))
        rs.request(self.server,self.context,{**self.ref,'run_id':run['id'],'confirm':run['id']},'delete-run')
        inventory=rs.inventory(self.context);self.assertTrue(next(a for a in inventory['artifacts'] if a['id']==model['id'])['pinned'])
        self.assertEqual(rs.request(self.server,self.context,{'artifact':model},'asset')['model']['features'],['x','z'])
    def test_old_contract_pin_and_200_trees(self):
        old=deepcopy(bc.CONTRACTS['ml_train']);next(s for s in old['settings'] if s['id']=='n_estimators')['maximum']=100
        community.Community.check_pins({'builtins':{'ml_train':{'version':1,'digest':subgraphs.digest(old)}}})
        with self.assertRaises(bc.ContractError):community.Community.check_pins({'builtins':{'ml_train':{'version':1,'digest':'wrong'}}})
        bc.normalize_block({'kind':'ml_train','version':1,'settings':{'n_estimators':200}})

