"""Only list/read UTF-8 artifacts below one conversation; never follow symlinks."""
from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
import stat
from app.runtime.result_offload import record_artifact_read

from deepagents.backends.protocol import BackendProtocol, FileData, LsResult, ReadResult


class SessionReadOnlyBackend(BackendProtocol):
    def __init__(self, directory):
        self.directory = Path(directory)

    @contextmanager
    def _open(self, path, directory=False):
        parts = PurePosixPath(path).parts
        if '..' in parts or '~' in path or '\\' in path:
            raise ValueError('Invalid path')
        parts = [part for part in parts if part not in ('/', '.', '')]
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(self.directory, flags | os.O_DIRECTORY)
        try:
            for index, part in enumerate(parts):
                last = index == len(parts) - 1
                child = os.open(part, flags | (os.O_DIRECTORY if directory or not last else 0), dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)

    def ls(self, path):
        try:
            with self._open(path, directory=True) as fd:
                entries = []
                for name in sorted(os.listdir(fd)):
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode):
                        is_dir = stat.S_ISDIR(info.st_mode)
                        entries.append({'path': '/' + str(PurePosixPath(path.lstrip('/')) / name) + ('/' if is_dir else ''),
                                        'is_dir': is_dir, 'size': info.st_size})
                return LsResult(entries=entries)
        except (OSError, ValueError):
            return LsResult(error='无法读取当前会话目录；路径必须在会话转存范围内。')

    def read(self, file_path, offset=0, limit=2000):
        try:
            if type(offset) is not int or type(limit) is not int or offset < 0 or limit < 1:
                raise ValueError('Invalid range')
            with self._open(file_path) as fd:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError('Not a regular file')
                lines, size, total, full = [], 0, 0, False
                with os.fdopen(os.dup(fd), 'r', encoding='utf-8') as stream:
                    while line := stream.readline(1_000_001):
                        if len(line) > 1_000_000:
                            return ReadResult(error='单行文本过大，请使用有界的转存文本。')
                        if total >= offset and len(lines) < min(limit, 100) and not full:
                            if size + len(line) > 20000:
                                full = True
                            else:
                                lines.append(line)
                                size += len(line)
                        total += 1
                if not lines:
                    if not total:
                        return ReadResult(file_data=FileData(content='', encoding='utf-8'))
                    return ReadResult(error='当前行超出文件范围或单行过大。')
                end = offset + len(lines)
                content = ''.join(lines)
                record_artifact_read(content)
                return ReadResult(file_data=FileData(content=content, encoding='utf-8'),
                    start_line=offset + 1, end_line=end, total_lines=total, next_offset=end if end < total else None)
        except (OSError, ValueError):
            return ReadResult(error='无法读取当前会话转存文本；文件不存在或路径不在允许范围内。')
