"""Static discovery never executes task code or mistakes local modules for pip packages."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.bootstrap.task_dependencies import inspect, parse_requirements, download_error


class DependencyDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def scan(self, files):
        for name, source in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding='utf-8')
        return inspect(self.root, 'main.py')

    def test_mail_task_includes_public_helpers_without_platform_or_database_drivers(self):
        result = self.scan({'main.py': 'import requests\nfrom time import sleep\nfrom app.common.mail import send_mail\nimport pandas as pd\nraise RuntimeError("never execute")'})
        self.assertEqual(result['requirements'], ['pandas', 'requests', 'SQLAlchemy', 'urllib3'])
        sqlalchemy = next(item for item in result['modules'] if item['module'] == 'sqlalchemy')
        self.assertTrue(all(source.startswith('公共模块/') for source in sqlalchemy['sources']))

    def test_local_packages_namespaces_src_relative_imports_and_stdlib_are_not_downloaded(self):
        result = self.scan({'main.py': 'import os, json, helper\nfrom tools import report\nfrom my_pkg import job\n',
                            'helper.py': 'import requests', 'tools/report.py': 'from . import child',
                            'src/my_pkg/job.py': 'import pandas'})
        self.assertEqual(result['requirements'], ['pandas', 'requests'])

    def test_aliases_dynamic_imports_and_optional_modules(self):
        result = self.scan({'main.py': 'import importlib\nfrom typing import TYPE_CHECKING\nfrom PIL import Image\nimport yaml\nimportlib.import_module("openpyxl")\nimportlib.import_module(plugin_name)\nif TYPE_CHECKING:\n import type_only\ntry:\n import optional_package\nexcept ImportError:\n pass\n'})
        self.assertEqual(result['requirements'], ['openpyxl', 'Pillow', 'PyYAML'])
        self.assertTrue(any('动态导入' in warning for warning in result['warnings']))
        self.assertTrue(any('可选导入' in warning for warning in result['warnings']))

    def test_unknown_names_are_explained_and_private_sdk_snapshot_is_followed(self):
        sdk = self.root / 'sdk'
        module = sdk / 'app/common/helper.py'
        module.parent.mkdir(parents=True)
        module.write_text('import corporate_client\ndef optional():\n import unused_driver\n', encoding='utf-8')
        code = self.root / 'code'
        code.mkdir()
        (code / 'main.py').write_text('from app.common.helper import helper')
        result = inspect(code, 'main.py', sdk=sdk)
        self.assertEqual(result['requirements'], ['corporate-client'])
        self.assertEqual(result['modules'][0]['mapping'], 'same_name')
        self.assertTrue(result['warnings'])

    def test_platform_guards_do_not_install_packages_for_another_operating_system(self):
        files = {'main.py': 'import sys, os\nif sys.platform == "win32":\n import win32api\nelse:\n import linux_helper\nif os.name not in ("nt",):\n import posix_helper\nif False:\n import unreachable\n'}
        with patch('app.bootstrap.task_dependencies.sys.platform', 'linux'), patch('app.bootstrap.task_dependencies.os.name', 'posix'):
            from app.bootstrap.task_dependencies import Imports
            import ast
            visitor = Imports()
            visitor.visit(ast.parse(files['main.py']))
        modules = {module for module, _, _ in visitor.imports}
        self.assertIn('linux_helper', modules)
        self.assertIn('posix_helper', modules)
        self.assertNotIn('win32api', modules)
        self.assertNotIn('unreachable', modules)

    def test_effective_requirements_reject_options_urls_paths_and_oversized_lists(self):
        self.assertEqual(parse_requirements('requests>=2\npandas==2.2.3 # tested'), ['requests>=2', 'pandas==2.2.3'])
        for value in ('--extra-index-url https://example.org', 'pkg @ https://example.org/a.whl', '../local',
                      '-e .', ['requests\n--index-url evil'], {'requirements': 'requests'}, 'x' * 65537):
            with self.subTest(value=str(value)[:60]), self.assertRaises(ValueError):
                parse_requirements(value)

    def test_failures_distinguish_missing_wheel_permissions_network_and_conflicts(self):
        cases = [
            ('ERROR: No matching distribution found for custom-module>=2', 'Nexus 中未找到可用依赖：custom-module>=2'),
            ('401 Error, Credentials not correct; No matching distribution found for foo', '账号和读取权限'),
            ('WARNING: Retrying after connection broken\nNo matching distribution found for foo', '连接失败'),
            ('ResolutionImpossible: conflicting dependencies', '版本冲突'),
        ]
        for output, expected in cases:
            self.assertIn(expected, download_error(output, 'nexus'))
        self.assertNotIn('secret', download_error('Error https://user:secret@private/path', 'nexus'))


if __name__ == '__main__':
    unittest.main()
