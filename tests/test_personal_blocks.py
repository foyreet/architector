"""Personal catalog provenance, private scope and snapshot reuse."""
from pathlib import Path
import sys, tempfile, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import personal_blocks as personal
import project_store, subgraphs


def graph():
    return {'format':'architect','version':3,'name':'Исходная схема','types':[
        {'id':'my','name':'Моя обработка','description':'Создано пользователем','color':'#123456',
         'block':{'kind':'python_code','version':1}}], 'nodes':[], 'edges':[]}


class PersonalBlocksTests(unittest.TestCase):
    def test_legacy_and_imports_do_not_claim_authorship(self):
        with tempfile.TemporaryDirectory() as root:
            project_store.ProjectStore(root).save({'diagram':graph()}, create=True)
            self.assertEqual(personal.listing(root), {'blocks':[]})

    def test_explicit_creation_is_scoped_deduplicated_and_portable(self):
        with tempfile.TemporaryDirectory() as root:
            alice, bob = Path(root)/'alice', Path(root)/'bob'
            result = personal.create(alice, {'diagram':graph(), 'type_id':'my'})['block']
            other = graph(); other['types'][0]['id']='another'
            self.assertEqual(personal.create(alice, {'diagram':other, 'type_id':'another'})['block']['id'], result['id'])
            self.assertEqual(len(personal.listing(alice)['blocks']), 1)
            self.assertEqual(personal.listing(bob)['blocks'], [])
            snapshot = dict(graph(), types=[result['type']], definitions=result['definitions'])
            self.assertEqual(subgraphs.normalize(snapshot)[0]['types'][0]['name'], 'Моя обработка')
            # Merely opening/saving another project doesn't change the catalog.
            project_store.ProjectStore(alice).save({'diagram':dict(graph(),name='Другой проект')}, create=True)
            self.assertEqual(personal.listing(alice)['blocks'][0]['origin_name'], 'Исходная схема')
            target = bob/'personal-blocks';target.parent.mkdir(exist_ok=True)
            target.symlink_to(alice/'personal-blocks')
            with self.assertRaises(Exception): personal.listing(bob)

    def test_packed_code_keeps_definition_but_not_unrelated_types(self):
        with tempfile.TemporaryDirectory() as root:
            source = graph()
            source['nodes'] = [{'id':'node','typeId':'my','name':'Код','description':'','x':0,'y':0,
                               'block':{'kind':'python_code','version':1,'settings':{'code':'outputs["result"] = {"score": 1}'}}}]
            packed = subgraphs.pack({'diagram':source,'selected':['node'],'name':'Мой алгоритм','description':'','labels':{}})
            node = next(n for n in packed['diagram']['nodes'] if n['id']==packed['node_id'])
            result = personal.create(root, {'diagram':packed['diagram'],'type_id':node['typeId']})['block']
            self.assertEqual(len(result['definitions']), 1)
            self.assertIn('score', str(result['definitions']))
            self.assertNotIn('nodes', result)
            subgraphs.normalize(dict(graph(),version=4,types=[result['type']],definitions=result['definitions']))

if __name__=='__main__': unittest.main()

