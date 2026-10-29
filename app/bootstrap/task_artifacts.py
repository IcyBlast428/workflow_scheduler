"""Read-only execution outputs, isolated from task code and persistent state."""
import csv
import codecs
import io
import os
from pathlib import Path
import re
import stat

from app.bootstrap.global_vars import DATA_DIR
from app.bootstrap.operations import read_run
from app.bootstrap.task_source import SourceError, _parts, _open_relative

PREVIEW_BYTES = 256 * 1024
PAGE_SIZE = 200
SCAN_LIMIT = 10000
TEXT_TYPES = {'.csv', '.tsv', '.json', '.jsonl', '.ndjson', '.txt', '.log', '.out',
              '.err', '.md', '.xml', '.html', '.sql', '.yaml', '.yml', '.ini', '.cfg'}


def _linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def output_directory(pid, run_id, create=False, trial=False):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}', str(pid)) or not re.fullmatch(r'[a-f0-9]{32}', str(run_id)):
        raise SourceError('任务或执行编号无效。')
    base = Path(DATA_DIR).resolve()
    relative = Path('trial-data' if trial else 'task-data') / pid / 'runs' / run_id
    current = base
    for part in relative.parts:
        current /= part
        if _linked(current):
            raise SourceError('输出目录不能使用链接。', 403)
    if create:
        current.mkdir(parents=True, exist_ok=True)
    current.resolve().relative_to(base)
    return base, relative, current


def _location(run_id, filename='', directory=False):
    if isinstance(filename, str) and any(ord(char) < 32 for char in filename):
        raise SourceError('文件路径包含无效字符。')
    try:
        record = read_run(run_id)
    except (ValueError, OSError):
        raise SourceError('执行记录不存在。', 404)
    if record.get('output_layout') != 'per-run-v1':
        raise SourceError('此历史执行尚未使用独立输出目录。', 404)
    root, relative, task = output_directory(record['pid'], run_id, trial=record.get('source')=='trial')
    parts = _parts(filename, directory=directory)
    current = task
    for part in parts:
        current /= part
        if _linked(current):
            raise SourceError('不开放链接文件或目录。', 403)
    return record, root, relative, task, parts


def list_outputs(run_id, directory='', offset=0):
    try:
        offset = int(offset)
        if not 0 <= offset < SCAN_LIMIT:
            raise ValueError()
    except (TypeError, ValueError):
        raise SourceError('文件列表位置无效。')
    record, root, relative, task, parts = _location(run_id, directory, directory=True)
    handle = None
    entries, truncated = [], False
    try:
        handle = _open_relative(root, relative, task, parts, directory=True)
        with os.scandir(handle) as iterator:
            for index, entry in enumerate(iterator):
                if index >= SCAN_LIMIT:
                    truncated = True
                    break
                try:
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) and not info.st_nlink:
                        # Windows DirEntry.stat() omits link counts; inspect the real file.
                        info = os.stat(entry.path, follow_symlinks=False)
                    if entry.is_symlink() or (getattr(info, 'st_file_attributes', 0) & 0x400):
                        continue
                    kind = 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 else ''
                    if kind:
                        entries.append({'name': entry.name, 'path': '/'.join((*parts, entry.name)),
                                        'type': kind, 'size': info.st_size})
                except OSError:
                    continue
    except OSError:
        raise SourceError('输出目录尚未生成、已清理或无法读取。', 404)
    finally:
        if isinstance(handle, int):
            os.close(handle)
    entries.sort(key=lambda item: (item['type'] != 'directory', item['name']))
    return {'directory': directory, 'entries': entries[offset:offset+PAGE_SIZE],
            'has_more': len(entries) > offset+PAGE_SIZE, 'next_offset': offset+PAGE_SIZE,
            'truncated': truncated, 'final': record['status'] not in ('queued', 'running')}


def open_output(run_id, filename):
    record, root, relative, task, parts = _location(run_id, filename)
    try:
        stream = _open_relative(root, relative, task, parts)
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            stream.close()
            raise SourceError('只开放普通输出文件。', 403)
        return record, stream, info
    except OSError:
        raise SourceError('输出文件不存在、已清理或无法读取。', 404)


def preview_output(run_id, filename):
    _, stream, info = open_output(run_id, filename)
    with stream:
        raw = stream.read(PREVIEW_BYTES+1)
    clipped = len(raw) > PREVIEW_BYTES
    raw = raw[:PREVIEW_BYTES]
    result = {'path': filename, 'size': info.st_size, 'truncated': clipped, 'content': ''}
    if Path(filename).suffix.lower() not in TEXT_TYPES or b'\0' in raw:
        return dict(result, kind='binary', reason='此文件提供下载，暂不支持在线预览。')
    content = None
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            content = codecs.getincrementaldecoder(encoding)().decode(raw, final=not clipped)
            break
        except UnicodeError:
            continue
    if content is None:
        return dict(result, kind='binary', reason='无法识别文本编码，请下载后查看。')
    suffix = Path(filename).suffix.lower()
    if suffix in {'.csv', '.tsv'}:
        rows = []
        try:
            for index, row in enumerate(csv.reader(io.StringIO(content), delimiter='\t' if suffix == '.tsv' else ',')):
                if index >= 200:
                    clipped = True
                    break
                clipped |= len(row) > 50
                rows.append(row[:50])
            return dict(result, kind='csv', rows=rows, truncated=clipped)
        except csv.Error:
            pass
    lines = content.splitlines(keepends=True)
    return dict(result, kind='text', content=''.join(lines[:2000]),
                truncated=clipped or len(lines) > 2000, language='json' if suffix == '.json' else 'plaintext')
