"""Middleware-only redacted text writes. Model-facing backend remains read-only."""
from contextlib import contextmanager
import json
import os
import re
from threading import RLock
from uuid import uuid4

from deepagents.backends import CompositeBackend
from deepagents.backends.protocol import WriteResult, EditResult, FileDownloadResponse, FileUploadResponse

from app.runtime.read_only_backend import SessionReadOnlyBackend
from app.services.redaction import redact, redact_text


def safe_archive_text(text):
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        value = None
    if isinstance(value, (dict, list)):
        text = json.dumps(redact(value, limit=None), ensure_ascii=False)
    text = redact_text(text, limit=None)
    return re.sub(r'(?i)((?:\b(?:password|token|secret|authorization|cookie)\b|密码)\s*[:=：]\s*)[^\s,;<>]+', r'\1***', text)


def safe_messages(messages):
    def clean_content(content):
        if isinstance(content, str):
            return safe_archive_text(content)
        if isinstance(content, list):
            return [{**block, 'text': safe_archive_text(block['text'])} if isinstance(block, dict) and isinstance(block.get('text'), str)
                    else block for block in content]
        return content
    result = []
    for message in messages:
        updates = {'content': clean_content(message.content)}
        if getattr(message, 'tool_calls', None):
            updates['tool_calls'] = [{**call, 'args': redact(call['args'], limit=None)} for call in message.tool_calls]
        result.append(message.model_copy(update=updates))
    return result


class SummaryArchiveBackend(SessionReadOnlyBackend):
    def __init__(self, session_directory):
        self.session = SessionReadOnlyBackend(session_directory)
        super().__init__(self.session.directory / 'summary-archive')
        self.lock = RLock()
        self.writes = 0

    @contextmanager
    def _parent(self, path):
        matched = re.fullmatch(r'/(conversation_history|large_tool_results)/([A-Za-z0-9_-]{1,160}(?:\.(?:md|txt))?)', path)
        if not matched:
            raise ValueError('Invalid archive path')
        category, filename = matched.groups()
        with self.session._open('/', directory=True) as session_fd:
            try:
                os.mkdir('summary-archive', 0o700, dir_fd=session_fd)
            except FileExistsError:
                pass
            root = os.open('summary-archive', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=session_fd)
            try:
                try:
                    os.mkdir(category, 0o700, dir_fd=root)
                except FileExistsError:
                    pass
                parent = os.open(category, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
                try:
                    yield parent, filename
                finally:
                    os.close(parent)
            finally:
                os.close(root)

    def _read_existing(self, parent, filename):
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        import stat
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError('Not a file')
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            return stream.read()

    def _save(self, path, content, old=None):
        with self.lock, self._parent(path) as (parent, filename):
            if old is None:
                # Existing files, including symlinks, cannot be overwritten by write.
                try:
                    os.stat(filename, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise ValueError('Already exists')
            elif self._read_existing(parent, filename) != old:
                raise ValueError('Archive changed')
            temporary = '.tmp-' + uuid4().hex
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    text = safe_archive_text(content)
                    stream.write('\n'.join(line[i:i + 1000] for line in text.split('\n') for i in range(0, max(1, len(line)), 1000)))
                os.replace(temporary, filename, src_dir_fd=parent, dst_dir_fd=parent)
                self.writes += 1
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def write(self, file_path, content):
        try:
            self._save(file_path, content)
            return WriteResult(path=file_path)
        except (OSError, ValueError):
            return WriteResult(error='无法写入当前会话的摘要归档目录。')

    def edit(self, file_path, old_string, new_string, replace_all=False):
        try:
            # Framework archive append uses full old/new content; general edits denied.
            if replace_all or not new_string.startswith(old_string):
                raise ValueError('Only append is supported')
            self._save(file_path, new_string, old=old_string)
            return EditResult(path=file_path, occurrences=1)
        except (OSError, ValueError):
            return EditResult(error='摘要归档只允许追加现有内容。')

    def download_files(self, paths):
        results = []
        for path in paths:
            try:
                with self.lock, self._parent(path) as (parent, filename):
                    text = self._read_existing(parent, filename)
                results.append(FileDownloadResponse(path=path, content=text.encode()))
            except (OSError, ValueError):
                results.append(FileDownloadResponse(path=path, error='file_not_found'))
        return results

    def upload_files(self, files):
        # Binary/media cannot use text redaction; never silently archive unredacted bytes.
        return [FileUploadResponse(path=path, error='permission_denied') for path, _ in files]


def summary_backend(directory):
    return CompositeBackend(default=SessionReadOnlyBackend(directory),
        routes={'/summary-archive/': SummaryArchiveBackend(directory)}, artifacts_root='/summary-archive')
