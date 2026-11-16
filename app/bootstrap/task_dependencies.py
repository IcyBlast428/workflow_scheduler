"""Inspect imports without importing or executing task code.

Import names are not necessarily distribution names. Known aliases are mapped;
other names are proposed explicitly and can be corrected in the release form.
The resolver still uses only the administrator's configured package repository.
"""
import ast
import os
from pathlib import Path
import re
import sys


PACKAGES = {
    'requests': 'requests', 'pandas': 'pandas', 'numpy': 'numpy',
    'sqlalchemy': 'SQLAlchemy', 'urllib3': 'urllib3', 'configobj': 'configobj',
    'cryptography': 'cryptography', 'openpyxl': 'openpyxl', 'xlsxwriter': 'XlsxWriter',
    'PIL': 'Pillow', 'yaml': 'PyYAML', 'sklearn': 'scikit-learn',
    'cv2': 'opencv-python', 'bs4': 'beautifulsoup4', 'Crypto': 'pycryptodome',
    'Cryptodome': 'pycryptodomex', 'dateutil': 'python-dateutil', 'dotenv': 'python-dotenv',
    'jwt': 'PyJWT', 'docx': 'python-docx', 'pptx': 'python-pptx',
    'fitz': 'PyMuPDF', 'psutil': 'psutil', 'paramiko': 'paramiko',
    'lxml': 'lxml', 'httpx': 'httpx', 'aiohttp': 'aiohttp', 'tenacity': 'tenacity',
    'pymysql': 'PyMySQL', 'pyodbc': 'pyodbc', 'psycopg2': 'psycopg2-binary',
    'win32api': 'pywin32', 'win32com': 'pywin32', 'win32con': 'pywin32',
}


def _condition(node):
    """Resolve common platform guards with literals only, never eval user code."""
    unknown = object()

    def value(item):
        if isinstance(item, ast.Constant) and isinstance(item.value, (str, bool, int, type(None))):
            return item.value
        if isinstance(item, (ast.Tuple, ast.List)):
            values = [value(child) for child in item.elts]
            return unknown if any(child is unknown for child in values) else values
        if isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name):
            return {('sys', 'platform'): sys.platform, ('os', 'name'): os.name}.get((item.value.id, item.attr), unknown)
        return unknown

    if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int, type(None))):
        return bool(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        result = _condition(node.operand)
        return None if result is None else not result
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left, right = value(node.left), value(node.comparators[0])
        if left is not unknown and right is not unknown:
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
            if isinstance(right, (str, list)) and isinstance(left, str):
                if isinstance(node.ops[0], ast.In):
                    return left in right
                if isinstance(node.ops[0], ast.NotIn):
                    return left not in right
    return None


def parse_requirements(value):
    from packaging.requirements import Requirement, InvalidRequirement
    if isinstance(value, list) and all(isinstance(line, str) and '\n' not in line and '\r' not in line for line in value):
        value = '\n'.join(value)
    if not isinstance(value, str) or len(value.encode('utf-8')) > 65536:
        raise ValueError('依赖清单须为文本或逐行列表，最多 64 KiB。')
    result = []
    for line in value.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            raise ValueError('依赖应逐行填写包名和版本；不接受安装参数、脚本或文件路径。') from None
        if requirement.url or len(line) > 1000:
            raise ValueError('依赖不接受直接下载地址；请使用管理员配置的仓库。')
        if line not in result:
            result.append(line)
        if len(result) > 500:
            raise ValueError('最多声明 500 项直接依赖。')
    return result


class Imports(ast.NodeVisitor):
    def __init__(self, *, module_scope=False):
        self.module_scope = module_scope
        self.imports = []
        self.warnings = []

    def visit_Import(self, node):
        self.imports.extend((alias.name, 0, node.lineno) for alias in node.names)

    def visit_ImportFrom(self, node):
        module = node.module or ''
        self.imports.append((module, node.level, node.lineno))
        self.imports.extend((module + ('.' if module else '') + alias.name, node.level, node.lineno)
                            for alias in node.names if alias.name != '*')

    def visit_FunctionDef(self, node):
        if not self.module_scope:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node):
        if (isinstance(node.test, ast.Name) and node.test.id == 'TYPE_CHECKING') or (
                isinstance(node.test, ast.Attribute) and node.test.attr == 'TYPE_CHECKING'):
            for child in node.orelse:
                self.visit(child)
            return
        condition = _condition(node.test)
        if condition is not None:
            for child in node.body if condition else node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Try(self, node):
        optional = any(any(isinstance(item, ast.Name) and item.id in ('ImportError', 'ModuleNotFoundError')
                           for item in ast.walk(handler.type)) for handler in node.handlers if handler.type)
        if optional:
            self.warnings.append(f'第 {node.lineno} 行含可选导入，请按使用的功能补充依赖。')
            for child in [*node.orelse, *node.finalbody]:
                self.visit(child)
        else:
            self.generic_visit(node)

    visit_TryStar = visit_Try

    def visit_Call(self, node):
        function = node.func
        dynamic = (isinstance(function, ast.Name) and function.id == '__import__') or (
            isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name)
            and function.value.id == 'importlib' and function.attr == 'import_module')
        if dynamic:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and not node.args[0].value.startswith('.'):
                self.imports.append((node.args[0].value, 0, node.lineno))
            else:
                self.warnings.append(f'第 {node.lineno} 行使用动态导入，无法自动确定包名。')
        self.generic_visit(node)


def inspect(code, entry='', *, sdk=None):
    """Scan task Python files, then only import-time dependencies of referenced SDK modules."""
    code = Path(code)
    sdk = Path(sdk) if sdk else Path(__file__).resolve().parents[2]
    roots = [code, code / 'src']
    if entry:
        roots.append((code / entry).parent)
    standard = sys.stdlib_module_names | {'__future__'}
    found, warnings, visited = {}, set(), set()
    sdk_queue = []

    def module_path(root, module):
        base = root.joinpath(*module.split('.'))
        for path in (base.with_suffix('.py'), base / '__init__.py'):
            if path.is_file() and not path.is_symlink():
                return path
        return None

    def add_module(module, source, line, *, shared=False):
        if not module:
            return
        top = module.split('.')[0]
        if top in standard:
            return
        if not shared and any(module_path(root, top) or (root / top).is_dir() for root in roots):
            return
        if top == 'app':
            parts = module.split('.')
            for count in range(1, len(parts) + 1):
                name = '.'.join(parts[:count])
                path = module_path(sdk, name)
                if path and path not in visited:
                    sdk_queue.append((name, path))
            return
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', top):
            warnings.add(f'{source}:{line} 的导入名无法识别，请手动补充依赖。')
            return
        item = found.setdefault(top, dict(module=top, package=PACKAGES.get(top, top.replace('_', '-')),
                                         mapping='known' if top in PACKAGES else 'same_name', sources=[]))
        location = f'{source}:{line}'
        if location not in item['sources'] and len(item['sources']) < 8:
            item['sources'].append(location)

    def scan(path, name='', *, shared=False):
        if path in visited:
            return
        visited.add(path)
        source = ('公共模块/' + path.relative_to(sdk).as_posix()) if shared else path.relative_to(code).as_posix()
        try:
            tree = ast.parse(path.read_bytes(), filename=source)
        except (SyntaxError, UnicodeError, ValueError) as exc:
            raise ValueError(f'依赖识别无法读取 Python 文件：{source}') from exc
        visitor = Imports(module_scope=shared)
        visitor.visit(tree)
        warnings.update(f'{source}：{message}' for message in visitor.warnings)
        for module, level, line in visitor.imports:
            if level:
                if not shared:
                    continue  # Local files are scanned separately, never fetched from the repository.
                package = name.split('.') if path.name == '__init__.py' else name.split('.')[:-1]
                module = '.'.join(package[:len(package) - level + 1] + ([module] if module else []))
            add_module(module, source, line, shared=shared)

    for path in sorted(code.rglob('*.py')):
        if path.is_symlink() or any(part in ('wheels', '__pycache__', '.venv') for part in path.relative_to(code).parts):
            continue
        scan(path)
    while sdk_queue:
        name, path = sdk_queue.pop()
        scan(path, name, shared=True)
    modules = sorted(found.values(), key=lambda value: value['module'].casefold())
    requirements = sorted({item['package'] for item in modules}, key=str.casefold)
    if any(item['mapping'] == 'same_name' for item in modules):
        warnings.add('部分导入名按同名包匹配；若仓库中包名不同，可在下方调整依赖清单。')
    return dict(requirements=requirements, modules=modules, warnings=sorted(warnings))


def download_error(output, mode):
    """Only return controlled text; pip output may contain credentials or private URLs."""
    lower = output.lower()
    if re.search(r'\b(?:401|403)\s+(?:client\s+)?error', lower) or any(text in lower for text in ('credentials not correct', 'unauthorized', 'forbidden')):
        return '依赖仓库拒绝访问，请管理员检查 Nexus 账号和读取权限。'
    if any(text in lower for text in ('connectionerror', 'connection refused', 'connection broken', 'failed to establish', 'nameresolutionerror', 'timed out', 'sslerror', 'certificate verify failed', 'proxyerror', 'retrying', '502 server error', '503 server error')):
        return '依赖仓库连接失败或证书校验失败，请管理员检查 Nexus 地址、网络和证书。'
    if 'resolutionimpossible' in lower or 'conflicting dependencies' in lower:
        return '依赖版本冲突。请在依赖清单中调整版本范围后重新准备。'
    match = re.search(r'(?:No matching distribution found for|Could not find a version that satisfies the requirement)\s+([A-Za-z0-9][A-Za-z0-9_.\-\[\],<>=!~+; ]{0,180})', output)
    if match:
        package = match.group(1).strip()
        source = 'Nexus' if mode == 'nexus' else '离线 wheel 目录'
        return f'{source} 中未找到可用依赖：{package}。请核对包名、版本及当前 Python/系统对应的 wheel；由管理员补齐后重试。'
    return '依赖准备失败，请核对包名和版本；管理员可查看该版本 prepare.log。'
