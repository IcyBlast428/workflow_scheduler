"""Bounded, read-only file browsing under a discovered task directory."""
import base64
import datetime as dt
import hashlib
import io
import mimetypes
import os
from pathlib import Path, PurePosixPath
import stat
import tokenize

from app.bootstrap.global_vars import TASK_DIR

MAX_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_LINES = 10000
PAGE_SIZE = 200
MAX_ENTRIES = 20000
MAX_DEPTH = 32
IMAGE_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
               '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp'}


class SourceError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _parts(filename, directory=False):
    if directory and filename == '':
        return ()
    if not isinstance(filename, str) or not filename or len(filename) > 512 or any(c in filename for c in ('\\', ':', '\0')):
        raise SourceError('文件路径无效。')
    parts = filename.split('/')
    if PurePosixPath(filename).is_absolute() or len(parts) > MAX_DEPTH or any(part in ('', '.', '..') for part in parts):
        raise SourceError('只能查看此任务目录内的文件。')
    return tuple(parts)


def _root(spec):
    root = Path(TASK_DIR).resolve()
    if spec.get('managed'):
        from app.bootstrap.task_packages import storage_root
        root = storage_root()
    task = Path(spec['task_dir']).absolute()
    try:
        relative = task.relative_to(root)
        task.resolve(strict=True).relative_to(root)
    except (ValueError, OSError):
        raise SourceError('任务目录不在可访问范围内。', 403)
    if not relative.parts or any(part in ('.', '..') for part in relative.parts):
        raise SourceError('任务目录无效。', 403)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise SourceError('不开放符号链接目录。', 403)
    if not task.is_dir():
        raise SourceError('任务目录不存在。', 404)
    return root, relative, task


def _open_relative(root, relative, task, parts, directory=False):
    # Walk every directory with no-follow descriptors on Linux. A swapped
    # directory cannot redirect an already-open parent into another task.
    if os.open in os.supports_dir_fd and hasattr(os, 'O_NOFOLLOW'):
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            all_parts = (*relative.parts, *parts)
            for part in (all_parts if directory else all_parts[:-1]):
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            if directory:
                result, descriptor = descriptor, None
                return result
            source = os.open(all_parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            return os.fdopen(source, 'rb')
        finally:
            if descriptor is not None:
                os.close(descriptor)
    current = task
    for part in parts:
        current /= part
        if current.is_symlink():
            raise SourceError('不开放符号链接文件或目录。', 403)
    try:
        current.resolve(strict=True).relative_to(task)
    except (ValueError, OSError):
        raise SourceError('文件不存在或不在任务目录内。', 404)
    return current if directory else current.open('rb')


def list_source(spec, directory='', offset=0):
    parts = _parts(directory, directory=True)
    try:
        offset = int(offset)
        if not 0 <= offset < MAX_ENTRIES:
            raise ValueError()
    except (TypeError, ValueError):
        raise SourceError('文件列表位置无效。')
    root, relative, task = _root(spec)
    handle = None
    entries, truncated = [], False
    try:
        handle = _open_relative(root, relative, task, parts, directory=True)
        with os.scandir(handle) as iterator:
            for index, entry in enumerate(iterator):
                if index >= MAX_ENTRIES:
                    truncated = True
                    break
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                kind = 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'unavailable'
                filename = '/'.join((*parts, entry.name))
                entries.append({'name': entry.name, 'path': filename, 'type': kind,
                                'size': info.st_size, 'is_entry': filename == spec.get('main_file')})
    except OSError:
        raise SourceError('目录不存在、无读取权限或属于符号链接。', 404)
    finally:
        if isinstance(handle, int):
            os.close(handle)
    entries.sort(key=lambda item: (item['type'] != 'directory', not item['is_entry'], item['name']))
    return {'entries': entries[offset:offset+PAGE_SIZE], 'directory': directory,
            'has_more': len(entries) > offset+PAGE_SIZE, 'next_offset': offset+PAGE_SIZE,
            'truncated': truncated, 'main_file': spec.get('main_file', ''), 'readonly': True}


def read_source(spec, filename):
    parts = _parts(filename)
    root, relative, task = _root(spec)
    suffix = Path(filename).suffix.lower()
    image_type = IMAGE_TYPES.get(suffix)
    limit = MAX_IMAGE_BYTES if image_type else MAX_BYTES
    try:
        with _open_relative(root, relative, task, parts) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise SourceError('只能查看普通文件。', 403)
            result = {'path': filename, 'size': info.st_size,
                      'modified_at': dt.datetime.fromtimestamp(info.st_mtime).isoformat(' ', timespec='seconds'),
                      'mime_type': mimetypes.guess_type(filename)[0] or 'application/octet-stream',
                      'readonly': True}
            if info.st_size > limit:
                return dict(result, kind='unavailable', reason=f'文件超过 {limit // (1024*1024)} MiB 预览上限，请在服务器查看。')
            raw = stream.read(limit+1)
    except SourceError:
        raise
    except OSError:
        raise SourceError('文件不存在、无读取权限或属于符号链接。', 404)
    if len(raw) > limit:
        return dict(result, kind='unavailable', reason='文件读取时超过预览上限，请刷新后重试。')
    result.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    if image_type:
        return dict(result, kind='image', data_url=f'data:{image_type};base64,'+base64.b64encode(raw).decode('ascii'))
    controls = sum(byte < 32 and byte not in (9, 10, 12, 13) for byte in raw)
    if b'\0' in raw or controls > max(0, len(raw)*0.01):
        return dict(result, kind='binary', reason='此二进制文件仅显示文件信息，暂不支持在线预览。')
    try:
        if suffix == '.py':
            encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
            content = raw.decode(encoding)
        else:
            encoding = 'utf-8-sig'
            try:
                content = raw.decode(encoding)
            except UnicodeDecodeError:
                encoding = 'gb18030'
                content = raw.decode(encoding)
    except (UnicodeError, LookupError, SyntaxError):
        return dict(result, kind='unavailable', reason='无法识别文本编码，请在服务器查看。')
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    if content.count('\n')+1 > MAX_LINES:
        return dict(result, kind='unavailable', reason='文件超过 10000 行预览上限，请在服务器查看。')
    return dict(result, kind='text', content=content, encoding=encoding)
