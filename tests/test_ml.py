"""Real small-model training, held-out evaluation, provenance and artifact isolation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import block_contracts as bc
import ml_operations as ml
import pipeline_runner as pr

ROOT = Path(__file__).resolve().parents[1]


def iris_graph():
    kinds = ['kaggle','csv','ml_prepare','ml_split','ml_train','ml_evaluate','ml_save']
    graph = {'format':'architect','version':3,'name':'Iris · обучение','types':[], 'nodes':[], 'edges':[]}
    for i, kind in enumerate(kinds):
        graph['types'].append({'id':'type-'+kind,'name':bc.CONTRACTS[kind]['label'],'description':'','color':'#275fe8','block':{'kind':kind,'version':1}})
        block = bc.normalize_block({'kind':kind,'version':1})
        if kind == 'kaggle': block['inputs']['source'] = 'uciml/iris/versions/2'
        if kind == 'csv': block['inputs']['file'] = 'Iris.csv'; block['settings']['max_rows'] = 1000
        if kind == 'ml_prepare': block['settings'].update(target='Species', features='SepalLengthCm,SepalWidthCm,PetalLengthCm,PetalWidthCm')
        graph['nodes'].append({'id':kind,'typeId':'type-'+kind,'name':bc.CONTRACTS[kind]['label'],'description':'','x':(i%4)*280,'y':(i//4)*250,'block':block})
    for i, (a, ap, b, bp) in enumerate([('kaggle','dataset','csv','dataset'),('csv','rows','ml_prepare','rows'),('ml_prepare','table','ml_split','table'),
        ('ml_split','train','ml_train','train'),('ml_split','test','ml_evaluate','test'),('ml_train','model','ml_evaluate','model'),
        ('ml_evaluate','model','ml_save','model'),('ml_evaluate','metrics','ml_save','metrics')]):
        graph['edges'].append({'id':'e'+str(i),'from':a,'fromPort':ap,'to':b,'toPort':bp,'kind':'data'})
    return graph


class MLTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.rows = [{'x':str(i), 'z':str(i%3), 'Id':i, 'label':'low' if i < 20 else 'high'} for i in range(40)]

    def tearDown(self): self.temp.cleanup()

    def execute(self, kind, inputs, **settings):
        block = bc.normalize_block({'kind':kind,'version':1,'inputs':inputs,'settings':settings}, required=True)
        return ml.execute(block, self.root)

    def test_end_to_end_real_forest_and_saved_package(self):
        table = self.execute('ml_prepare', {'rows':self.rows}, target='label')['outputs']['table']
        split = self.execute('ml_split', {'table':table})
        repeated = self.execute('ml_split', {'table':table})
        self.assertEqual(split, repeated)
        train, test = (ml.load(self.root, split['outputs'][side], 'table') for side in ('train','test'))
        self.assertEqual((len(train['y']),len(test['y'])), (32,8))
        self.assertFalse(set(train['row_ids']) & set(test['row_ids']))
        model = self.execute('ml_train', {'train':split['outputs']['train']}, n_estimators=10)['outputs']['model']
        evaluated = self.execute('ml_evaluate', {'model':model,'test':split['outputs']['test']})
        self.assertGreaterEqual(evaluated['details']['accuracy'], .75)
        self.assertEqual(sum(map(sum,evaluated['details']['confusion_matrix'])), 8)
        saved = self.execute('ml_save', {'model':model,'metrics':evaluated['outputs']['metrics']})
        package = ml.load(self.root, saved['outputs']['bundle'], 'model_bundle')
        self.assertEqual(package['model']['versions']['scikit-learn'], '1.7.2')
        self.assertEqual(package['model']['features'], ['x','z'])
        self.assertEqual(len(package['model']['trees']), 10)
        self.assertNotIn('X', package['model'])
        with self.assertRaises(bc.ContractError):
            self.execute('ml_train', {'train':split['outputs']['test']})
        with self.assertRaises(bc.ContractError):
            self.execute('ml_evaluate', {'model':model,'test':split['outputs']['train']})
        other = self.execute('ml_split', {'table':table},seed=99)['outputs']['test']
        with self.assertRaises(bc.ContractError):
            self.execute('ml_evaluate', {'model':model,'test':other})
        with self.assertRaises(bc.ContractError): ml.load(self.root/'other-account', model, 'trained_model')
        path = self.root/'workspace/ml-artifacts'/ (model['id']+'.json');path.write_text('{}')
        with self.assertRaises(bc.ContractError): ml.load(self.root,model,'trained_model')

    def test_preparation_errors_and_cleaning(self):
        invalid = deepcopy(self.rows);invalid[0]['x']='NaN';invalid.append(deepcopy(invalid[1]))
        with self.assertRaises(bc.ContractError): self.execute('ml_prepare', {'rows':invalid},target='label')
        result = self.execute('ml_prepare', {'rows':invalid},target='label',missing='drop',duplicates='drop')
        self.assertEqual(result['details']['dropped_rows'],1)
        self.assertEqual(result['details']['duplicates_removed'],1)
        self.assertEqual(result['details']['rows'],39)
        with self.assertRaises(bc.ContractError): self.execute('ml_prepare', {'rows':self.rows},target='label',features='label,x')
        with self.assertRaises(bc.ContractError): self.execute('ml_prepare', {'rows':self.rows},target='unknown')
        with self.assertRaises(bc.ContractError): bc.validate_value([{'x':float('inf')}],{'type':'rows'})
        self.assertEqual(len(bc.validate_value(self.rows*26, {'type':'rows'})), 1040)
        with self.assertRaises(bc.ContractError): bc.artifact('trained_model','local','../secret')
        with self.assertRaises(bc.ContractError): self.execute('ml_train',{}, n_estimators=10000)

    def test_schema_order_and_account_scope(self):
        graph=iris_graph();snapshot,order=pr.validate(graph)
        self.assertEqual(order,['kaggle','csv','ml_prepare','ml_split','ml_train','ml_evaluate','ml_save'])
        block=bc.normalize_block({'kind':'ml_prepare','version':1,'inputs':{'rows':self.rows},'settings':{'target':'label'}})
        with patch.object(ml,'execute',return_value={}) as operation:
            bc.execute({'block':block},None,SimpleNamespace(ROOT=self.root),None)
            self.assertEqual(operation.call_args.kwargs['root'], self.root)
        graph['edges'][1]['fromPort']='row'
        with self.assertRaises(bc.ContractError): pr.validate(graph)

    def test_worker_timeout_and_missing_runtime(self):
        import subprocess
        with patch.object(ml.subprocess,'run',side_effect=subprocess.TimeoutExpired('worker',120)):
            with self.assertRaises(bc.ContractError): ml.worker('split')
        self.assertFalse(ml.WORKER_LOCK.locked())
        with patch.object(ml.subprocess,'run',side_effect=FileNotFoundError()):
            with self.assertRaises(bc.ContractError): ml.worker('split')

