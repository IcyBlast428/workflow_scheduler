"""Bounded static Python flow overview; task code is never imported or run."""
import ast
from collections import OrderedDict
import copy
import hashlib
from pathlib import PurePosixPath
import threading
from app.bootstrap.task_source import SourceError, read_source

MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 20, 128 * 1024, 1024 * 1024
MAX_AST_NODES, MAX_GRAPHS, MAX_GRAPH_NODES = 12000, 40, 120
_cache, _lock = OrderedDict(), threading.Lock()


class SafeConstants(ast.NodeTransformer):
    def visit_Constant(self, node):
        return ast.copy_location(ast.Constant(value='文本'), node) if isinstance(node.value, (str, bytes)) else node


def expression(node):
    if node is None:
        return ''
    try:
        text = ast.unparse(SafeConstants().visit(copy.deepcopy(node)))
        return text[:160] + ('…' if len(text) > 160 else '')
    except (ValueError, RecursionError):
        return '复杂表达式（请查看源码）'


def call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return (call_name(node.value) or '?') + '.' + node.attr
    return ''


def operation(name):
    last = name.lower().split('.')[-1]
    for names, label, kind in [
        (('print','debug','info','warning','error','exception','log'), '输出日志', 'log'),
        (('read','read_text','read_bytes','read_csv','read_excel','load','open'), '读取或打开数据', 'read'),
        (('write','write_text','write_bytes','to_csv','to_excel','dump','save'), '写入数据', 'write'),
        (('execute','executemany','execute_sql','execute_query_sql','query','fetchall','fetchone','commit'), '数据库操作', 'database'),
        (('send','sendmail','send_message','send_sms','send_email'), '发送消息', 'notify'),
        (('sleep',), '等待', 'wait')]:
        if last in names:
            return label, kind
    if name.startswith(('subprocess.', 'os.system', 'os.popen')) or last in ('eval','exec','__import__'):
        return '外部或动态执行', 'external'
    if name.startswith(('requests.', 'httpx.', 'urllib.')):
        return '调用外部接口', 'external'
    return ('调用方法 ' + last if name.startswith('?.') else '调用 ' + (name or '动态函数')), 'call'


class Analysis:
    def __init__(self, spec):
        self.spec, self.files, self.aliases, self.definitions = spec, {}, {}, {}
        self.graphs, self.warnings, self.total_bytes = [], [], 0
        self.missing, self.read_attempts = set(), 0

    def warn(self, message):
        if message not in self.warnings and len(self.warnings) < 30:
            self.warnings.append(message)

    def read(self, filename, required=False):
        if filename in self.files:
            return filename
        if filename in self.missing:
            return None
        self.read_attempts += 1
        if self.read_attempts > 200 and not required:
            self.warn('模块查找达到 200 次上限，其余调用未展开。')
            return None
        if len(self.files) >= MAX_FILES:
            self.warn('关联文件超过 20 个，其余模块未展开。')
            return None
        try:
            source = read_source(self.spec, filename)
        except SourceError:
            if required:
                raise
            self.missing.add(filename)
            return None
        if source['kind'] != 'text' or source['size'] > MAX_FILE_BYTES:
            if required:
                raise SourceError('入口文件超过 128 KiB 或不是可分析的文本，请查看源码。', 422)
            self.warn(filename + ' 超过分析大小上限或不是文本，未展开。')
            return None
        if self.total_bytes + source['size'] > MAX_TOTAL_BYTES:
            self.warn('关联代码超过 1 MiB，其余模块未展开。')
            return None
        try:
            tree = ast.parse(source['content'], filename=filename)
            if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
                raise ValueError('代码结构过大')
        except (SyntaxError, ValueError, RecursionError) as exc:
            if required:
                raise SourceError('入口代码无法解析，请检查 Python 语法或代码大小。', 422) from exc
            self.warn(filename + ' 无法解析，未展开。')
            return None
        self.total_bytes += source['size']
        self.files[filename], self.aliases[filename] = (source, tree), {}
        return filename

    def module(self, file, name, level=0):
        parts = name.split('.') if name else []
        if not all(part.isidentifier() for part in parts):
            return None
        parent = PurePosixPath(file).parent
        bases = [parent, PurePosixPath(self.spec['main_file']).parent, PurePosixPath('.')]
        if level:
            for _ in range(level - 1):
                if parent == PurePosixPath('.'):
                    return None
                parent = parent.parent
            bases = [parent]
        for base in dict.fromkeys(bases):
            path = base.joinpath(*parts)
            for candidate in (str(path) + '.py', str(path / '__init__.py')):
                if self.read(candidate):
                    return candidate
        return None

    def discover(self):
        self.read(self.spec['main_file'], required=True)
        index = 0
        while index < len(self.files):
            file = list(self.files)[index]
            for node in ast.walk(self.files[file][1]):
                if isinstance(node, ast.Import):
                    for item in node.names:
                        target = self.module(file, item.name)
                        if target:
                            self.aliases[file][item.asname or item.name] = (target, '')
                elif isinstance(node, ast.ImportFrom):
                    target = self.module(file, node.module or '', node.level)
                    for item in node.names:
                        if item.name == '*':
                            self.warn(file + ' 使用星号导入，相关调用不能精确定位。')
                        elif target:
                            self.aliases[file][item.asname or item.name] = (target, item.name)
                        else:
                            child = self.module(file, '.'.join(filter(None, (node.module, item.name))), node.level)
                            if child:
                                self.aliases[file][item.asname or item.name] = (child, '')
            for node in self.files[file][1].body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.definitions[file + '::' + node.name] = node
                elif isinstance(node, ast.ClassDef):
                    for method in node.body:
                        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self.definitions[file + '::' + node.name + '.' + method.name] = method
            index += 1

    def resolve(self, file, name):
        if file + '::' + name in self.definitions:
            return file + '::' + name
        for alias, (target, symbol) in self.aliases[file].items():
            if name == alias or name.startswith(alias + '.'):
                key = target + '::' + '.'.join(filter(None, (symbol, name[len(alias):].lstrip('.'))))
                if key in self.definitions:
                    return key
        return None


class Graph:
    def __init__(self, analysis, file, key, title, body, line=1, summary=''):
        self.analysis, self.file = analysis, file
        self.data = dict(id=key, title=title, file=file, line=line, summary=summary, nodes=[], edges=[])
        self.end = self.add('end', '结束 / 返回', line=line)
        start = self.add('start', '开始', line=line)
        self.link(self.block(body, [(start, '')]), self.end)

    def add(self, kind, label, statement=None, line=None, calls=None):
        if len(self.data['nodes']) >= MAX_GRAPH_NODES:
            raise OverflowError()
        identifier = 'n' + str(len(self.data['nodes']))
        self.data['nodes'].append(dict(id=identifier, kind=kind, label=label, file=self.file,
            line=line or getattr(statement, 'lineno', 1), end_line=getattr(statement, 'end_lineno', line or 1), calls=calls or []))
        return identifier

    def link(self, incoming, target, kind='normal'):
        for source, label in incoming:
            self.data['edges'].append(dict(from_=source, to=target, label=label, kind=kind))

    def calls(self, statement):
        result = []
        for node in ast.walk(statement):
            if isinstance(node, ast.Call):
                name = call_name(node.func)
                if len(result) < 12:
                    result.append(dict(name=name or '动态函数', target=self.analysis.resolve(self.file, name), line=node.lineno))
                if not name or name in ('eval','exec','__import__') or name.startswith('subprocess.'):
                    self.analysis.warn('存在动态调用或外部程序，其内部执行过程未展开。')
        return result

    def finish(self, node, target, loop, finalizers, handlers, depth, label='', unwind_all=False):
        paths = [(node,label)]
        for index in range(len(finalizers)-1,-1,-1):
            if not paths:
                break
            finalizer = finalizers[index]
            if not unwind_all and target != self.end and finalizer['loop'] != loop:
                continue
            cleanup = self.add(finalizer['kind'],finalizer['label'],finalizer['statement'])
            self.link(paths,cleanup)
            outer_handlers=tuple(handler for handler in handlers if handler[2]<=index)
            paths = self.block(finalizer['body'],[(cleanup,'')],loop,False,depth+1,finalizers[:index],outer_handlers)
        self.link(paths,target,'exception' if unwind_all else 'loop' if target != self.end else 'normal')

    def block(self, body, incoming, loop=None, finally_region=False, depth=0, finalizers=(), handlers=()):
        if depth > 24:
            raise OverflowError()
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Pass)):
                continue
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                continue
            if not incoming:
                break
            if isinstance(stmt, ast.If):
                if self.file == self.analysis.spec['main_file'] and isinstance(stmt.test, ast.Compare) and isinstance(stmt.test.left, ast.Name) and stmt.test.left.id == '__name__' and len(stmt.test.ops) == 1 and isinstance(stmt.test.ops[0], ast.Eq) and isinstance(stmt.test.comparators[0], ast.Constant) and stmt.test.comparators[0].value == '__main__':
                    incoming = self.block(stmt.body, incoming, loop, finally_region, depth+1,finalizers,handlers)
                    continue
                node = self.add('decision', '判断：' + expression(stmt.test), stmt, calls=self.calls(stmt.test))
                self.link(incoming, node)
                incoming = self.block(stmt.body, [(node,'是')], loop, finally_region, depth+1,finalizers,handlers) + self.block(stmt.orelse, [(node,'否')], loop, finally_region, depth+1,finalizers,handlers)
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                test = stmt.test if isinstance(stmt, ast.While) else stmt.iter
                node = self.add('loop', ('判断循环：' if isinstance(stmt, ast.While) else '遍历：') + expression(test), stmt, calls=self.calls(test))
                done = self.add('merge', '循环结束', stmt)
                self.link(incoming, node)
                self.link(self.block(stmt.body, [(node,'继续')], (node,done), finally_region, depth+1,finalizers,handlers), node, 'loop')
                self.link(self.block(stmt.orelse, [(node,'完成')], loop, finally_region, depth+1,finalizers,handlers), done)
                incoming = [(done,'')]
            elif isinstance(stmt, (ast.Try, getattr(ast, 'TryStar', ast.Try))):
                node = self.add('try', '尝试执行 / 异常处理', stmt)
                self.link(incoming, node)
                scoped_finalizers=finalizers+({'kind':'finally','label':'最终清理（finally）','statement':stmt,'body':stmt.finalbody,'loop':loop},) if stmt.finalbody else finalizers
                caught_handlers=[]
                for handler in stmt.handlers:
                    caught = self.add('exception', '处理异常：' + (expression(handler.type) or '所有异常'), handler)
                    self.link([(node,'可能异常')], caught, 'exception')
                    caught_handlers.append((handler,caught))
                local_handlers=tuple((expression(handler.type),caught,len(scoped_finalizers)) for handler,caught in caught_handlers)+handlers
                paths = self.block(stmt.body, [(node,'正常')], loop, bool(stmt.finalbody) or finally_region, depth+1,scoped_finalizers,local_handlers)
                paths = self.block(stmt.orelse, paths, loop, finally_region, depth+1,scoped_finalizers,handlers)
                for handler,caught in caught_handlers:
                    paths += self.block(handler.body, [(caught,'')], loop, bool(stmt.finalbody) or finally_region, depth+1,scoped_finalizers,handlers)
                if stmt.finalbody and paths:
                    final = self.add('finally', '最终清理（finally）', stmt)
                    self.link(paths, final)
                    paths = self.block(stmt.finalbody, [(final,'')], loop, finally_region, depth+1,finalizers,handlers) if paths else []
                self.analysis.warn('异常边表示可能路径；外部调用抛出何种异常及异常类型继承需结合源码查看。')
                incoming = paths
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                node = self.add('context', '打开资源 / 进入上下文', stmt, calls=self.calls(stmt.items[0].context_expr) if stmt.items else [])
                self.link(incoming, node)
                scoped_finalizers=finalizers+({'kind':'context','label':'退出上下文 / 释放资源','statement':stmt,'body':[],'loop':loop},)
                incoming = self.block(stmt.body, [(node,'')], loop, finally_region, depth+1,scoped_finalizers,handlers)
                if incoming:
                    close = self.add('context', '退出上下文 / 释放资源', stmt)
                    self.link(incoming, close)
                    incoming = [(close,'')]
            else:
                calls = self.calls(stmt)
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    label, kind = '加载模块：' + ', '.join(item.name for item in stmt.names)[:120], 'import'
                elif isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                    label, kind = {ast.Return:('返回结果','return'), ast.Raise:('抛出异常','raise'), ast.Break:('跳出循环','break'), ast.Continue:('下一轮循环','continue')}[type(stmt)]
                elif calls:
                    label, kind = operation(calls[0]['name'])
                elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                    label, kind = '设置：' + ', '.join(expression(target) for target in targets), 'process'
                else:
                    label, kind = '执行：' + expression(stmt), 'process'
                if finally_region and kind in ('return','raise','break','continue'):
                    label += '（先清理再结束）'
                node = self.add(kind, label, stmt, calls=calls)
                self.link(incoming, node)
                if kind == 'raise' and handlers:
                    exception_name=call_name(stmt.exc.func) if isinstance(stmt.exc,ast.Call) else call_name(stmt.exc)
                    handler=next((item for item in handlers if not item[0] or item[0] in ('Exception','BaseException',exception_name)),None)
                    if handler:
                        # Only inner resources are unwound before entering this handler.
                        self.finish(node,handler[1],loop,finalizers[handler[2]:],(),depth,'捕获异常',True)
                    else:
                        self.finish(node,self.end,loop,finalizers,handlers,depth,'异常传播')
                    incoming=[]
                elif kind in ('return','raise'):
                    self.finish(node,self.end,loop,finalizers,handlers,depth,'终止当前路径')
                    incoming = []
                elif kind in ('break','continue') and loop:
                    self.finish(node,loop[1] if kind == 'break' else loop[0],loop,finalizers,handlers,depth)
                    incoming = []
                else:
                    incoming = [(node,'')]
        return incoming


def analyze(spec):
    analysis = Analysis(spec)
    analysis.discover()
    fingerprint = hashlib.sha256(('task-flow-1\0' + spec['main_file'] + '\0' + '\0'.join(file+':'+source['sha256'] for file,(source,_) in analysis.files.items())).encode()).hexdigest()
    cache_key = (spec['pid'], spec.get('task_release',''), fingerprint)
    with _lock:
        if cache_key in _cache:
            _cache.move_to_end(cache_key)
            return copy.deepcopy(_cache[cache_key])
    plans = [(file, file+'::<module>', '入口流程' if file == spec['main_file'] else '模块初始化 · '+file, tree.body, 1, '') for file,(_,tree) in analysis.files.items()]
    plans += [(key.split('::')[0],key,key.split('::')[1],node.body,node.lineno,(ast.get_docstring(node) or '').split('\n')[0][:180]) for key,node in analysis.definitions.items()]
    for file,key,title,body,line,summary in plans[:MAX_GRAPHS]:
        try:
            graph = Graph(analysis,file,key,title,body,line,summary).data
            for edge in graph['edges']:
                edge['from'] = edge.pop('from_')
            analysis.graphs.append(graph)
        except (OverflowError, RecursionError):
            analysis.warn(title+' 的结构超过分析上限，请查看源码。')
    if len(plans) > MAX_GRAPHS:
        analysis.warn('函数与模块超过 40 个，其余未展开。')
    if not analysis.graphs or analysis.graphs[0]['id'] != spec['main_file']+'::<module>':
        raise SourceError('入口流程超过分析上限，请查看源码。',422)
    ids = {graph['id'] for graph in analysis.graphs}
    for graph in analysis.graphs:
        for node in graph['nodes']:
            for call in node['calls']:
                if call['target'] not in ids:
                    call['target'] = None
    result = dict(schema='task-flow-1',pid=spec['pid'],entry=spec['main_file'],code_version=spec.get('task_release',''),fingerprint=fingerprint,
        files=[dict(path=file,sha256=source['sha256']) for file,(source,_) in analysis.files.items()],graphs=analysis.graphs,warnings=analysis.warnings,
        description_source='static',business_summary='',limitations=['静态逻辑概览，不代表某一次运行实际走过的路径。','外部库、动态调用、对象实例方法和并发任务的内部顺序可能无法展开。','类定义体、装饰器、默认参数和局部嵌套函数未展开；调用分类来自名称规则。'])
    with _lock:
        _cache[cache_key] = copy.deepcopy(result)
        _cache.move_to_end(cache_key)
        while len(_cache) > 8:
            _cache.popitem(last=False)
    return result
