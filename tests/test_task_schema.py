import json
import unittest
from unittest.mock import patch,MagicMock
import test_operational_workflows as fixture
from app.bootstrap import task_schema as schema,admission

class SchemaTests(unittest.TestCase):
 def setUp(self):
  self.f=fixture.OperationalTests();self.f.setUp()
  data=self.f.ready(self.f.new({'main.py':'print("DDL")','ddl/schema.sql':'CREATE TABLE original(id int);\n'}));self.f.activate(data);self.pid=data['pid']
 def tearDown(self):self.f.tearDown()
 def save(self,**values):return schema.save(self.pid,dict(revision=schema.current(self.pid)['revision'],content='CREATE TABLE edited(id int);\n',note='新增表',**values),'admin')
 def test_published_source_draft_history_and_stale_revision(self):
  original=schema.current(self.pid);self.assertIn('original',original['content'])
  saved=self.save();self.assertEqual(saved['revision'],1)
  self.assertIn('original',schema.published(self.pid));self.assertIn('edited',schema.current(self.pid)['content'])
  self.assertEqual(len(schema.history(self.pid)),1)
  with self.assertRaises(RuntimeError):schema.save(self.pid,dict(revision=0,content='drop',note='stale'),'admin')
  self.assertIn('+CREATE TABLE edited',schema.diff(original['content'],saved['content']))
 def test_tags_validate_deduplicate_cas_and_list_filter(self):
  result=schema.save_tags(self.pid,dict(revision=0,tags=[' 财务 ','日报','日报']),'admin')
  self.assertEqual(result['tags'],['财务','日报'])
  response=self.f.client.get('/api/taskinfo/state?tag=财务');self.assertIn(self.pid,str(response.json))
  response=self.f.client.get('/api/taskinfo/state?tag=does_not_exist');self.assertNotIn(self.pid,str(response.json))
  with self.assertRaises(RuntimeError):schema.save_tags(self.pid,dict(revision=0,tags=[]),'admin')
  for tags in ([1],['a'*41],['x']*21):
   with self.assertRaises(ValueError):schema.validate_tags(tags)
 def test_api_history_and_no_sql_execution(self):
  result=self.f.client.post('/api/taskinfo/ddl?pid='+self.pid,headers=self.f.headers,json=dict(action='save',revision=0,content='DROP TABLE important;',note='仅记录定义'))
  self.assertEqual(result.status_code,200,result.json)
  self.assertEqual(self.f.client.get('/api/taskinfo/ddl?pid='+self.pid).json['data']['history'][0]['content'],'DROP TABLE important;')
  self.assertEqual(self.f.client.post('/api/taskinfo/ddl?pid='+self.pid,json={}).status_code,403)
  self.assertEqual(self.f.app.test_client().get('/api/taskinfo/ddl?pid='+self.pid).status_code,401)
 def remote(self):return dict(url='https://git.example',project='team/project',token='fixture',ca_bundle='',revision=1,target='main'),'a'*40,'app/jobs/team/task',schema.current(self.pid)['base'],True
 def test_git_preview_conflict_and_stale_head_block_write(self):
  self.save()
  with patch.object(schema,'remote',return_value=self.remote()):preview=schema.preview(self.pid,1)
  changed=list(self.remote());changed[1]='b'*40
  with patch.object(schema,'remote',return_value=tuple(changed)),patch.object(schema.git,'Client') as client:
   with self.assertRaises(RuntimeError):schema.submit(self.pid,preview['token'],'admin')
   client.assert_not_called()
  changed=list(self.remote());changed[3]='remote changed'
  with patch.object(schema,'remote',return_value=tuple(changed)):
   with self.assertRaises(RuntimeError):schema.preview(self.pid,1)
 def test_git_commit_new_branch_and_duplicate_prevention(self):
  self.save();remote=self.remote()
  response=MagicMock();response.__enter__.return_value=response;response.status_code=201;response.json.return_value={'id':'c'*40}
  client=MagicMock();client.session.post.return_value=response;client.project='team%2Fproject'
  with patch.object(schema,'remote',return_value=remote),patch.object(schema.git,'Client',return_value=client):
   preview=schema.preview(self.pid,1);receipt=schema.submit(self.pid,preview['token'],'admin')
   payload=client.session.post.call_args.kwargs['json']
   self.assertTrue(payload['branch'].startswith('wfs/ddl/'));self.assertEqual(payload['start_sha'],'a'*40)
   self.assertEqual(payload['actions'][0]['file_path'],'app/jobs/team/task/ddl/schema.sql')
   self.assertIn('/-/merge_requests/new?',receipt['url'])
   with self.assertRaises(RuntimeError):schema.submit(self.pid,preview['token'],'admin')
   self.assertEqual(client.session.post.call_count,1)
 def test_uncertain_commit_never_automatically_resends(self):
  self.save();client=MagicMock();client.session.post.side_effect=TimeoutError('unknown')
  with patch.object(schema,'remote',return_value=self.remote()),patch.object(schema.git,'Client',return_value=client):
   preview=schema.preview(self.pid,1)
   with self.assertRaises(TimeoutError):schema.submit(self.pid,preview['token'],'admin')
   with self.assertRaises(RuntimeError):schema.submit(self.pid,preview['token'],'admin')
   self.assertEqual(client.session.post.call_count,1)
if __name__=='__main__':unittest.main()
