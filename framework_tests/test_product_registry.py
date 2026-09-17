import json
import tempfile
import unittest
from pathlib import Path
from studio.runner import registry

class ProductRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);cases=self.root/'cases';cases.mkdir()
        for name in ['first','second']:
            folder=cases/name;folder.mkdir()
            (folder/'test_pairing.py').write_text('def test_bind(): pass')
            (folder/'registry.json').write_text(json.dumps([{'sheet':'G01_配对','id':'PAIR_001','node':f'cases/{name}/test_pairing.py::test_bind'}]))
        (cases/'registry.json').write_text(json.dumps({'products':{'P1':'first/registry.json','P2':'second/registry.json'}}))

    def test_same_id_is_isolated_by_product(self):
        first=registry(self.root,'P1');second=registry(self.root,'P2')
        key=('G01_配对','PAIR_001')
        self.assertIn('/first/',first[key]['node']);self.assertIn('/second/',second[key]['node'])
        self.assertEqual(first[key]['products'],['P1'])
        self.assertEqual(registry(self.root,'unknown'),{})

    def test_cross_product_code_reference_rejected(self):
        path=self.root/'cases/first/registry.json'
        data=json.loads(path.read_text());data[0]['node']='cases/second/test_pairing.py::test_bind'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'所属产品目录'):registry(self.root,'P1')
