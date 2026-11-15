import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_local_integration
from app import create_app
from app.bootstrap import runtime_snapshot
from app.bootstrap.timebase import business_now
from app.api.task import views


class RuntimeReadModelTests(unittest.TestCase):
    def test_task_options_read_one_consistent_task_snapshot(self):
        specs = [{'pid': 'z', 'task_name': '任务 Z', 'folder_name': 'folder-z'},
                 {'pid': 'a', 'task_name': '', 'folder_name': 'folder-a'}]
        with patch.object(views, 'discover_task_specs', return_value=specs) as discover:
            self.assertEqual(views._task_id_options(), [{'id': 'a', 'name': 'folder-a'}, {'id': 'z', 'name': '任务 Z'}])
            discover.assert_called_once()

    def test_marker_deduplication_keeps_boundaries_and_history_priority(self):
        markers = [
            {'id': 'b', 'start_time': '2030-01-01 10:00:00', 'end_time': '', 'source': 'running'},
            {'id': 'a', 'start_time': '2030-01-01 10:00:02', 'end_time': '2030-01-01 10:00:09', 'source': 'history', 'state': 0, 'name': '历史名称'},
            {'id': 'a', 'start_time': '2030-01-01 10:00:00', 'end_time': '2030-01-01 10:00:08', 'source': 'memory', 'name': '运行名称'},
            {'id': 'a', 'start_time': '2030-01-01 10:00:03', 'end_time': '2030-01-01 10:00:10', 'source': 'history', 'state': 1},
            {'id': 'a', 'start_time': 'invalid', 'source': 'running'},
            {'id': 'a', 'start_time': ''}, {'start_time': '2030-01-01 10:00:00'},
        ]
        result = views._dedupe_task_markers(markers)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0]['start_time'], 'invalid')
        self.assertEqual(result[1], {'id': 'a', 'start_time': '2030-01-01 10:00:00', 'end_time': '2030-01-01 10:00:09', 'source': 'history', 'state': 0, 'name': '历史名称'})
        self.assertEqual(result[2]['start_time'], '2030-01-01 10:00:03')
        self.assertEqual(result[3]['id'], 'b')

    def test_marker_deduplication_does_not_compare_unrelated_old_runs(self):
        began = dt.datetime(2030, 1, 1)
        markers = []
        for index in range(1000):
            stamp = (began + dt.timedelta(seconds=index * 10)).isoformat(' ')
            item = {'id': 'frequent-task', 'start_time': stamp, 'end_time': stamp, 'source': 'history', 'state': index % 2}
            markers.append(item)
            if index % 10 == 0:
                markers.append({**item, 'source': 'memory'})
        with patch.object(views, '_same_task_marker', wraps=views._same_task_marker) as compare:
            result = views._dedupe_task_markers(list(reversed(markers)))
        self.assertEqual(len(result), 1000)
        self.assertEqual(compare.call_count, 100)
        self.assertEqual([item['state'] for item in result], [index % 2 for index in range(1000)])
        self.assertTrue(all(item['source'] == 'history' for item in result))

    def test_shared_snapshot_rejects_missing_stale_and_unready_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'runtime-state.json'
            with patch.object(runtime_snapshot, 'snapshot_path', return_value=path):
                self.assertIsNone(runtime_snapshot.read_snapshot())
                data = {'schema':1, 'published_at':business_now().isoformat(' '), 'service':{'ready':True}, 'tasks':[]}
                path.write_text(json.dumps(data), encoding='utf-8')
                self.assertEqual(runtime_snapshot.read_snapshot(), data)
                data['published_at'] = (business_now()-dt.timedelta(seconds=20)).isoformat(' ')
                path.write_text(json.dumps(data), encoding='utf-8')
                self.assertIsNone(runtime_snapshot.read_snapshot())
                data.update(published_at=business_now().isoformat(' '), service={'ready':False})
                path.write_text(json.dumps(data), encoding='utf-8')
                self.assertIsNone(runtime_snapshot.read_snapshot())

    def test_web_status_queries_use_read_model_and_fall_back_when_missing(self):
        client = create_app().test_client()
        client.post('/api/user/login', json={'username':'admin','password':'test-password'})
        data = {'tasks':[{'id':'testJob__test_job1','state':'true','pending':True,'running_instances':1,'next_run_time':'2030-01-01 10:00:00'}],
                'scheduler':{'enabled':True,'job_count':1}, 'server_time':str(business_now()), 'logs':{}, 'task_starts':[]}
        with patch.object(views, 'WFS_ENABLE_SCHEDULER', False), patch.object(views, 'WFS_SCHEDULER_CONTROL_URL', 'http://control'), \
                patch.object(runtime_snapshot, 'read_snapshot', return_value=data), \
                patch.object(views, '_proxy_scheduler_resource', side_effect=AssertionError('query reached control thread')):
            state = client.get('/api/taskinfo/state').json['data']
            row = next(item for item in state['items'] if item['id'] == 'testJob__test_job1')
            self.assertEqual(row['state'], 'true')
            self.assertEqual(row['running_instances'], 1)
            self.assertEqual(client.get('/api/taskinfo/events').json['data']['tasks'], data['tasks'])
            dashboard = client.get('/api/taskinfo/dashboard').json['data']
            self.assertEqual(dashboard['summary']['pending'], 1)
            self.assertTrue(dashboard['scheduler']['enabled'])
        with patch.object(views, 'WFS_ENABLE_SCHEDULER', False), patch.object(views, 'WFS_SCHEDULER_CONTROL_URL', 'http://control'), \
                patch.object(runtime_snapshot, 'read_snapshot', return_value=None), \
                patch.object(views, '_proxy_scheduler_resource', return_value=({'code':100},503)) as forward:
            self.assertEqual(client.get('/api/taskinfo/state').status_code, 503)
            forward.assert_called_once()

    def test_readiness_reports_component_failure_without_leaking_exception(self):
        from app.bootstrap.global_vars import DATA_DIR
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
        client = create_app().test_client()
        healthy = client.get('/api/user/ready')
        self.assertEqual(healthy.status_code, 200)
        self.assertEqual(healthy.json['data']['components']['database']['status'], 'ready')
        with patch('app.bootstrap.database.GaussDB', side_effect=RuntimeError('private-host-and-secret')):
            response = client.get('/api/user/ready')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json['data']['ready'])
        self.assertEqual(response.json['data']['components']['api']['status'], 'ready')
        self.assertEqual(response.json['data']['components']['database']['status'], 'unavailable')
        self.assertNotIn('private-host-and-secret', response.get_data(as_text=True))
