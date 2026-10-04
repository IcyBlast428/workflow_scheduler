"""Static flow: no execution, branches, calls, bounds, and version isolation."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_local_integration as shared
from app import create_app
from app.api import operations as views
from app.bootstrap import task_source
from app.bootstrap.task_flow import analyze, MAX_FILE_BYTES
from app.bootstrap.task_source import SourceError


class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=create_app();cls.app.testing=True

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.task=self.root/'group/task';self.task.mkdir(parents=True)
        self.spec=dict(pid='flow-fixture',main_file='main.py',task_dir=self.task)
        self.root_patch=patch.object(task_source,'TASK_DIR',self.root)
        self.root_patch.start();self.addCleanup(self.root_patch.stop);self.addCleanup(self.temporary.cleanup)

    def write(self,main,helper=None):
        (self.task/'main.py').write_text(main,encoding='utf-8')
        if helper is not None:(self.task/'helpers.py').write_text(helper,encoding='utf-8')

    def test_branch_loop_multifile_and_source_locations_without_execution(self):
        self.write('from helpers import process as work\nraise RuntimeError("MUST NOT EXECUTE")\ndef main(rows):\n    for row in rows:\n        if row:\n            work(row)\n        else:\n            continue\n    return True\nif __name__ == "__main__":\n    main([1])\n',
                   'def process(row):\n    """处理一条记录"""\n    print(row)\n    return row\n')
        result=analyze(self.spec)
        graphs={graph['id']:graph for graph in result['graphs']}
        main=graphs['main.py::main']
        self.assertTrue(any(node['kind']=='decision' for node in main['nodes']))
        self.assertTrue(any(edge['kind']=='loop' for edge in main['edges']))
        call=next(node for node in main['nodes'] if any(call['name']=='work' for call in node['calls']))
        self.assertEqual(call['line'],6)
        self.assertEqual(call['calls'][0]['target'],'helpers.py::process')
        self.assertEqual(graphs['helpers.py::process']['summary'],'处理一条记录')
        self.assertNotIn('MUST NOT EXECUTE',json.dumps(result))

    def test_early_return_has_no_successor_step(self):
        self.write('def main(value):\n    if value:\n        return True\n    print(value)\nmain(1)\n')
        graph=next(graph for graph in analyze(self.spec)['graphs'] if graph['title']=='main')
        returned=next(node for node in graph['nodes'] if node['kind']=='return')
        end=next(node for node in graph['nodes'] if node['kind']=='end')
        outgoing=[edge['to'] for edge in graph['edges'] if edge['from']==returned['id']]
        self.assertEqual(outgoing,[end['id']])

    def test_nested_relative_imports_and_entry_guard(self):
        self.spec['main_file']='src/main.py';(self.task/'src').mkdir();(self.task/'src/pkg').mkdir()
        (self.task/'src/main.py').write_text('from pkg.worker import run\nif __name__ == "__main__":\n    run()\n')
        (self.task/'src/pkg/worker.py').write_text('from .helper import done\ndef run():\n    done()\n')
        (self.task/'src/pkg/helper.py').write_text('def done():\n    print("done")\n')
        result=analyze(self.spec)
        self.assertFalse(any(node['kind']=='decision' for node in result['graphs'][0]['nodes']))
        graph=next(graph for graph in result['graphs'] if graph['id']=='src/pkg/worker.py::run')
        self.assertEqual(next(node for node in graph['nodes'] if node['calls'])['calls'][0]['target'],'src/pkg/helper.py::done')

    def test_fingerprint_refresh_and_cached_results_are_independent(self):
        self.write('import helpers\nhelpers.work()\n','def work():\n    print(1)\n')
        first=analyze(self.spec);first['graphs'].clear()
        second=analyze(self.spec);self.assertTrue(second['graphs'])
        (self.task/'helpers.py').write_text('def work():\n    print(2)\n')
        self.assertNotEqual(first['fingerprint'],analyze(self.spec)['fingerprint'])
        self.spec['task_release']='version-2';self.assertEqual(analyze(self.spec)['code_version'],'version-2')

    def test_syntax_size_symlink_and_dynamic_limits(self):
        self.write('if broken\n');self.assertRaises(SourceError,analyze,self.spec)
        self.write('#'+('x'*MAX_FILE_BYTES));self.assertRaises(SourceError,analyze,self.spec)
        self.write('import subprocess\nsubprocess.run(["secret-command"])\n')
        result=analyze(self.spec);self.assertTrue(result['warnings']);self.assertNotIn('secret-command',json.dumps(result))
        if os.name!='nt':
            outside=self.root/'outside.py';outside.write_text('print(1)')
            (self.task/'helpers.py').symlink_to(outside)
            self.write('import helpers\nhelpers.work()\n')
            self.assertEqual(len(analyze(self.spec)['files']),1)

    def test_try_finally_and_api_authentication(self):
        self.write('try:\n    print(1)\nexcept ValueError:\n    print(2)\nfinally:\n    print(3)\n')
        self.assertTrue(any(node['kind']=='finally' for node in analyze(self.spec)['graphs'][0]['nodes']))
        endpoint='/api/taskinfo/flow'
        with patch.object(views,'discover_task_specs',return_value=[self.spec]):
            client=self.app.test_client()
            self.assertEqual(client.get(endpoint,query_string={'pid':self.spec['pid']}).status_code,401)
            self.assertEqual(client.post('/api/user/login',json={'username':'admin','password':'test-password'}).status_code,200)
            self.assertEqual(client.get(endpoint,query_string={'pid':self.spec['pid']}).status_code,200)
            self.assertEqual(client.get(endpoint,query_string={'pid':'missing'}).status_code,404)

    def test_return_unwinds_finally_and_resources_before_end(self):
        self.write('def work():\n    try:\n        with open("file") as handle:\n            return 1\n    finally:\n        print("cleanup")\nwork()\n')
        graph=next(graph for graph in analyze(self.spec)['graphs'] if graph['title']=='work')
        nodes={node['id']:node for node in graph['nodes']}
        current=next(node['id'] for node in graph['nodes'] if node['kind']=='return')
        kinds=[]
        while nodes[current]['kind']!='end':
            kinds.append(nodes[current]['kind'])
            outgoing=[edge['to'] for edge in graph['edges'] if edge['from']==current]
            self.assertEqual(len(outgoing),1)
            current=outgoing[0]
        self.assertEqual(kinds,['return','context','finally','log'])

    def test_explicit_raise_enters_matching_handler(self):
        self.write('try:\n    raise ValueError()\nexcept ValueError:\n    print(1)\nfinally:\n    print(2)\n')
        graph=analyze(self.spec)['graphs'][0]
        raised=next(node for node in graph['nodes'] if node['kind']=='raise')
        target=next(edge['to'] for edge in graph['edges'] if edge['from']==raised['id'])
        self.assertEqual(next(node for node in graph['nodes'] if node['id']==target)['kind'],'exception')

    def test_finally_exception_is_not_caught_by_its_own_try(self):
        self.write('def work():\n    try:\n        return 1\n    except ValueError:\n        print(1)\n    finally:\n        raise ValueError()\nwork()\n')
        graph=next(graph for graph in analyze(self.spec)['graphs'] if graph['title']=='work')
        raised=[node for node in graph['nodes'] if node['kind']=='raise']
        end=next(node for node in graph['nodes'] if node['kind']=='end')
        for node in raised:
            self.assertEqual([edge['to'] for edge in graph['edges'] if edge['from']==node['id']],[end['id']])

    def test_unknown_instance_method_is_not_linked_to_same_named_function(self):
        self.write('def work():\n    return 1\nfactory().work()\n')
        calls=[call for node in analyze(self.spec)['graphs'][0]['nodes'] for call in node['calls']]
        self.assertIsNone(next(call for call in calls if call['name']=='?.work')['target'])
