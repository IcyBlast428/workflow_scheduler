"""HTML cache invalidation and complete deploy-time lazy asset availability."""
import json
from pathlib import Path
import unittest
import test_local_integration
from app import create_app

class FrontendAssetsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.client=create_app().test_client()
 def test_entry_points_ignore_old_validators_and_never_store_html(self):
  for path in ('/','/admin/','/viewer/','/admin/deep-link'):
   with self.subTest(path=path):
    result=self.client.get(path,headers={'If-None-Match':'*','If-Modified-Since':'Wed, 31 Dec 2099 23:59:59 GMT'})
    self.assertEqual(result.status_code,200)
    self.assertIn('no-store',result.headers['Cache-Control'])
    self.assertNotIn('ETag',result.headers);self.assertNotIn('Last-Modified',result.headers)
 def test_every_manifest_asset_exists_and_is_served_as_asset(self):
  manifest=json.loads((Path(__file__).resolve().parents[1]/'app/dist/.vite/manifest.json').read_text())
  files=set()
  for item in manifest.values():
   files.add(item['file']);files.update(item.get('css',[]));files.update(item.get('assets',[]))
  self.assertGreater(len(files),10)
  for file in files:
   with self.subTest(file=file):
    result=self.client.get('/'+file)
    self.assertEqual(result.status_code,200);self.assertNotEqual(result.mimetype,'text/html')
 def test_missing_chunk_is_not_cached(self):
  result=self.client.get('/static/missing-build-asset.js')
  self.assertEqual(result.status_code,404);self.assertIn('no-store',result.headers['Cache-Control'])
if __name__=='__main__':unittest.main()
