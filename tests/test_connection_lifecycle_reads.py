"""Connection references stay fresh while reads are independent of list size."""
import json
import unittest
from unittest.mock import patch

import test_local_integration
from app.bootstrap import admission, connection_lifecycle as lifecycle, task_packages


class ConnectionLifecycleReadTests(unittest.TestCase):
    def test_summary_batches_policies_and_tests_and_keeps_all_reference_sources(self):
        policies = {
            'connections:task-a': {'mode': 'restricted', 'connections': ['reports', 'shared']},
            'task:task-a': {'declared_connections': ['reports'], 'test_connections': {'reports': 'reports-test'}},
            'task:unpublished': {'declared_connections': ['shared']},
            'task:deleted': {'declared_connections': ['reports']},
            'connection-test:reports': {'ready': False, 'revision': 2},
        }
        with admission.store() as db:
            for key, value in policies.items():
                db.replace('settings', ('key', 'payload'), (key, json.dumps(value)))
            # Unrelated retired policies were never read by the per-task implementation.
            db.replace('settings', ('key', 'payload'), ('task:orphan', 'invalid retired policy'))
        specs = [{'pid': 'task-a', 'task_name': '报表任务'}] + [
            {'pid': 'empty-' + str(i), 'task_name': ''} for i in range(40)
        ]
        registry = {'task-a': {'task_name': '旧名称'}, 'unpublished': {'task_name': '未发布任务'},
                    'deleted': {'task_name': '已删除', 'deleted_at': '2026-11-15'}}
        profiles = {'platform': {}, 'reports': {}, 'reports-test': {}, 'shared': {}}
        with patch.object(lifecycle, 'discover_task_specs', return_value=specs) as discover, \
                patch.object(task_packages, 'registry', return_value=registry), \
                patch.object(lifecycle.settings, 'profiles', return_value=profiles), \
                patch.object(admission, 'store', wraps=admission.store) as reads:
            summary = {item['id']: item for item in lifecycle.summary()}
            self.assertEqual(reads.call_count, 2)
            discover.assert_called_once()
            self.assertNotIn('platform', summary)
            self.assertEqual(summary['reports']['usage'], [{'pid': 'task-a', 'name': '报表任务', 'mode': 'restricted'}])
            self.assertEqual(summary['reports-test']['usage'], summary['reports']['usage'])
            self.assertEqual([item['pid'] for item in summary['shared']['usage']], ['task-a', 'unpublished'])
            self.assertEqual(summary['reports']['last_test'], {'ready': False, 'revision': 2})
            self.assertEqual(summary['reports-test']['last_test'], {})
            profiles.update({f'unused-{i}': {} for i in range(40)})
            reads.reset_mock()
            self.assertEqual(len(lifecycle.summary()), 43)
            self.assertEqual(reads.call_count, 2)

        # Deletion guards must see changes immediately, never reuse a summary index.
        with admission.store() as db:
            db.replace('settings', ('key', 'payload'), ('connections:task-a', json.dumps({'mode': 'restricted', 'connections': []})))
            db.replace('settings', ('key', 'payload'), ('task:task-a', '{}'))
        with patch.object(lifecycle, 'discover_task_specs', return_value=specs), \
                patch.object(task_packages, 'registry', return_value=registry):
            self.assertEqual(lifecycle.usage('reports'), [])
            self.assertEqual([item['pid'] for item in lifecycle.usage('shared')], ['unpublished'])

    def test_no_business_connections_skip_task_and_policy_reads(self):
        with patch.object(lifecycle.settings, 'profiles', return_value={'platform': {}}), \
                patch.object(lifecycle, 'discover_task_specs') as discover, \
                patch.object(admission, 'store') as reads:
            self.assertEqual(lifecycle.summary(), [])
            discover.assert_not_called()
            reads.assert_not_called()
