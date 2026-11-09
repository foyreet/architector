from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import block_contracts as bc
import code_sandbox
import data_preview as dp
import kaggle_data as kg
import ml_operations as ml
import python_blocks as pb
import subgraphs
from test_ml import iris_graph, ROOT


class PythonBlockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.kgpatch=patch.object(kg,'ROOT',self.root);self.kgpatch.start()
        self.jobpatch=patch.object(kg,'JOBS',{});self.jobpatch.start()
        archive=kg.archive_path('uciml/iris/versions/2');archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive,'w') as out:
            out.writestr('Iris.csv','Id,SepalLengthCm,SepalWidthCm,PetalLengthCm,PetalWidthCm,Species\n1,1,2,3,4,A\n2,2,3,4,5,A\n3,5,6,7,8,B\n4,6,7,8,9,B\n5,,2,3,4,B\n')

    def tearDown(self): self.jobpatch.stop();self.kgpatch.stop();self.temp.cleanup()

    def block(self, **settings):
        return bc.normalize_block({'kind':'python_code','version':1,'settings':settings})

    def test_json_and_code_validation(self):
        for value in (float('nan'), {'x':float('inf')}, {'nested':object()}):
            with self.assertRaises(bc.ContractError): bc.validate_value(value,{'type':'json'})
        for params in ('[1]','{bad'):
            with self.assertRaises(bc.ContractError):pb.check_settings(self.block(params=params)['settings'])
        with self.assertRaises(bc.ContractError):pb.check_settings(self.block(code='def bad(')['settings'])
        with patch.object(pb,'sandbox') as sandbox:
            with self.assertRaises(bc.ContractError): pb.execute(self.block(code='def bad('),self.root)
            sandbox.assert_not_called()
        payload={'code':'def run(inputs, params): return {}','params':{},'inputs':{},'timeout':30}
        code_sandbox.validate(payload)
        for replacement in ({'timeout':1000},{'image':'evil'},{'mount':'/'},{'timeout':True}):
            with self.assertRaises(ValueError):code_sandbox.validate(dict(payload,**replacement))

    def test_artifacts_and_output_contracts(self):
        artifact=ml.save(self.root,'python_data',{'model':'opaque JSON'})
        block=self.block();block['inputs']['data']=artifact
        response={'result':{'rows':[{'x':2}],'data':{'any':[1,2,3]},'report':{'scores':[.8,.9]}},'logs':'hello','runtime':{'image':'sha256:test'}}
        with patch.object(pb,'sandbox',return_value=response) as sandbox:
            result=pb.execute(block,self.root)
            self.assertEqual(sandbox.call_args.args[0]['inputs']['data'],{'model':'opaque JSON'})
            self.assertNotIn('secrets',sandbox.call_args.args[0])
            self.assertEqual(result['details']['logs'],'hello')
            self.assertEqual(ml.load(self.root,result['outputs']['data'],'python_data'),{'any':[1,2,3]})
        with self.assertRaises(bc.ContractError):ml.load(self.root/'another-account',artifact,'python_data')
        for outputs in ({'unexpected':1},{'rows':[{'x':{'nested':1}}]},{'report':float('nan')}):
            with patch.object(pb,'sandbox',return_value={'result':outputs}):
                with self.assertRaises(bc.ContractError):pb.execute(block,self.root)

    def test_preview_profiles_and_applies_cleaning_without_execution(self):
        graph=iris_graph()
        with patch.object(bc,'execute') as execute:
            result=dp.preview({'diagram':graph,'node_id':'ml_prepare'},kg)
            execute.assert_not_called()
        self.assertEqual(result['profile']['rows'],5)
        self.assertEqual(result['profile']['columns'][1]['missing'],1)
        self.assertIn('preparation_error',result)
        graph['nodes'][2]['block']['settings']['missing']='drop'
        result=dp.preview({'diagram':graph,'node_id':'ml_prepare'},kg)
        self.assertEqual(result['prepared']['profile']['rows'],4)
        self.assertNotIn('Id',result['prepared']['rows'][0])
        self.assertEqual(result['sources'][0]['file'],'Iris.csv')
        with self.assertRaises(bc.ContractError):dp.preview({'diagram':graph,'node_id':'ml_prepare','page':-1},kg)

    def test_saved_python_source_is_pinned_and_preview_rejects_stale_run(self):
        graph=iris_graph();graph['nodes']=graph['nodes'][:3];graph['edges']=graph['edges'][:2]
        graph['nodes'][2]['block']=self.block()
        graph['types'][2]['block']={'kind':'python_code','version':1}
        normalized,_=subgraphs.normalize(graph)
        packed=subgraphs.pack({'diagram':normalized,'selected':['ml_prepare'],'name':'Custom Python'})
        definition=packed['diagram']['definitions'][0]
        self.assertFalse(any(binding['target']['port']=='code' for binding in definition['settings']))
        self.assertEqual(definition['graph']['nodes'][0]['block']['settings']['code'],self.block()['settings']['code'])
        restored=subgraphs.unpack({'diagram':packed['diagram'],'node_id':packed['node_id']})
        self.assertEqual(restored['diagram']['nodes'][-1]['block']['settings']['code'],self.block()['settings']['code'])
        resolver=dp.Resolver({'diagram':normalized},kg)
        self.assertTrue(resolver.same_source('ml_prepare',normalized))
        changed=deepcopy(normalized);changed['nodes'][0]['block']['inputs']['source']='other/data'
        self.assertFalse(resolver.same_source('ml_prepare',changed))
        with self.assertRaises(bc.ContractError): resolver.outputs('ml_prepare')
        expanded,groups=subgraphs.expand(*subgraphs.normalize(packed['diagram']))
        leaf=groups[packed['node_id']][0]
        def history(action, fields):
            if action=='run': return {'source_diagram':packed['diagram'],'diagram':expanded}
            self.assertEqual(fields['node_id'],leaf)
            return {'status':'ready','outputs':{'rows':[{'x':1}],'data':{'id':'opaque'},'report':{}}}
        resolved=dp.Resolver({'diagram':packed['diagram'],'run_id':'test'},kg,history).outputs(packed['node_id'])
        port=next(p['id'] for p in definition['outputs'] if p['target']['port']=='rows')
        self.assertEqual(resolved[port],[{'x':1}])


    def test_broker_always_uses_fixed_container_restrictions(self):
        payload={'code':'def run(inputs, params): return {}','inputs':{},'params':{},'timeout':1}
        info=SimpleNamespace(returncode=0,stdout=b'sha256:trusted')
        with patch.object(code_sandbox.subprocess,'run',return_value=info), patch.object(code_sandbox.subprocess,'Popen',side_effect=OSError()) as start:
            code_sandbox.run(payload)
        command=start.call_args.args[0]
        for option in ['--network=none','--read-only','--user=10001:10001','--cap-drop=ALL','--security-opt=no-new-privileges',
                       '--pids-limit=64','--memory=1024m','--memory-swap=1024m','--cpus=2.0','--pull=never']:
            self.assertIn(option,command)
        self.assertNotIn('--privileged',command)
        self.assertNotIn('--volume',command)
        self.assertEqual(command[-1],'sha256:trusted')

    def test_sandbox_fails_closed(self):
        with patch.dict('os.environ',{'ARCHITECT_CODE_SOCKET':str(self.root/'missing.sock')}):
            with self.assertRaises(bc.ContractError) as caught:pb.execute(self.block(),self.root)
        self.assertEqual(caught.exception.status,503)

