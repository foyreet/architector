"""Saved-data discovery stays scoped and never returns CSV contents."""
from pathlib import Path
import json,tempfile,unittest,zipfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import data_catalog as catalog
import ml_operations as ml
import kaggle_data as kg

class DataCatalogTests(unittest.TestCase):
    def test_uploaded_csv_and_kaggle_preserve_exact_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            ref=ml.save(root,'dataset',{'format':'architect.uploaded-csv','name':'Данные.csv','csv':'x;y\n1;2\n'})
            path=kg.archive_path('owner/data/versions/2',root);path.parent.mkdir(parents=True)
            with zipfile.ZipFile(path,'w') as z:z.writestr('Nested/Train.CSV','x,y\n3,4\n')
            result=catalog.listing(root)
            self.assertEqual(len(result['datasets']),2)
            local=next(i for i in result['datasets'] if i['artifact']['provider']=='local')
            self.assertEqual(local['artifact'],ref);self.assertEqual(local['delimiter'],';')
            self.assertEqual(local['files'],['Данные.csv'])
            remote=next(i for i in result['datasets'] if i['artifact']['provider']=='kaggle')
            self.assertEqual(remote['files'],['Nested/Train.CSV'])
            self.assertNotIn('1;2',json.dumps(result));self.assertNotIn('3,4',json.dumps(result))
    def test_private_scope_and_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            a,b=Path(folder)/'alice',Path(folder)/'bob'
            ref=ml.save(a,'dataset',{'format':'architect.uploaded-csv','name':'Private.csv','csv':'secret\nvalue\n'})
            self.assertEqual(catalog.listing(b)['datasets'],[])
            target=ml.artifact_dir(b)/(ref['id']+'.json');target.symlink_to(ml.artifact_dir(a)/target.name)
            self.assertEqual(catalog.listing(b)['datasets'],[])
            path=kg.archive_path('owner/data',b);path.parent.mkdir(parents=True)
            path.symlink_to(ml.artifact_dir(a)/(ref['id']+'.json'))
            self.assertEqual(catalog.listing(b)['datasets'],[])
    def test_corrupt_and_non_dataset_artifacts_are_not_offered(self):
        with tempfile.TemporaryDirectory() as folder:
            ml.save(folder,'metrics',{'accuracy':1})
            path=ml.artifact_dir(folder)/('0'*64+'.json');path.write_text('{broken')
            self.assertEqual(catalog.listing(folder)['datasets'],[])
if __name__=='__main__':unittest.main()

