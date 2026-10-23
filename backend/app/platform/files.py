import base64
import hashlib
import stat
import json
from pathlib import Path
import subprocess
import sys
import os
import signal
import sysconfig
import time
from app.capabilities.sandbox import macos_profile
from uuid import uuid4

from app.errors import ServiceError

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}
ALLOWED_SUFFIXES = {'.pdf', '.docx', '.txt', '.md', '.csv', '.json'} | IMAGE_SUFFIXES
SCANNED_PDF = '[扫描版 PDF'
MAX_MESSAGE_ATTACHMENTS = 5
MAX_MESSAGE_IMAGES = 20


def file_kind(filename, content):
    """text: read with read_file; image / scanned_pdf: sent to the model as images inside a user message."""
    suffix = Path(filename).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return 'image'
    return 'scanned_pdf' if suffix == '.pdf' and content.startswith(SCANNED_PDF) else 'text'


def parse_document(suffix, data):
    return _run_worker({'suffix': suffix, 'data': base64.b64encode(data).decode()})['text']


def document_images(suffix, data):
    """Model-ready JPEGs (downscaled image, or the first pages of a scanned PDF), decoded in the sandbox."""
    return _run_worker({'suffix': suffix, 'data': base64.b64encode(data).decode(), 'mode': 'images'})['images']


def _run_worker(request):
    payload = json.dumps(request).encode()
    worker = Path(__file__).with_name('file_worker.py').resolve()
    command = [sys.executable, '-I', '-B', str(worker)]
    if sys.platform == 'darwin':
        command = ['/usr/bin/sandbox-exec', '-p', macos_profile(worker, [sysconfig.get_path('purelib')]), *command]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, cwd='/tmp', env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    deadline, first = time.monotonic() + 10, True
    try:
        while True:
            try:
                stdout, _ = process.communicate(payload if first else None, timeout=.15)
                break
            except subprocess.TimeoutExpired:
                first = False
                if time.monotonic() >= deadline:
                    raise
                if sys.platform == 'darwin':
                    rss = subprocess.run(['/bin/ps', '-o', 'rss=', '-p', str(process.pid)], capture_output=True, text=True, timeout=1)
                    if rss.stdout.strip().isdigit() and int(rss.stdout) > 384 * 1024:
                        raise subprocess.TimeoutExpired(command, 10)
        result = json.loads(stdout)
        if process.returncode or result.get('error'):
            raise ServiceError(result.get('error', '文件解析失败。'), 422)
        return result
    except ServiceError:
        raise
    except Exception as error:
        raise ServiceError('文件解析超时或失败，请检查文件后重试。', 422) from error
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()


class FileService:
    def __init__(self, database):
        self.database = database

    def _parse(self, filename, data):
        filename = filename.replace('\\', '/').split('/')[-1][:200]
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES or not data or len(data) > 2_000_000:
            raise ServiceError('支持 PDF、DOCX、TXT、MD、CSV、JSON 和 PNG、JPG、WEBP 图片，单文件需为 1 字节至 2 MB。', 422)
        return filename, parse_document(suffix, data), hashlib.sha256(data).hexdigest()

    def _local(self, path):
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 2_000_000:
                    raise ServiceError('关联对象需为不超过 2 MB 的普通文件。', 422)
                return source.read(2_000_001)
        except FileNotFoundError as error:
            raise ServiceError('关联文件已找不到，你是否移动、重命名或删除了文件？请重新关联或上传。', 404) from error
        except PermissionError as error:
            raise ServiceError('没有权限读取关联文件，请检查权限；不能据此判断文件已修改。', 403) from error
        except OSError as error:
            raise ServiceError('本机文件连接失效，请检查文件或重新关联。', 409) from error

    def upload(self, conversation_id, filename, data, source_path=None):
        filename, text, digest = self._parse(filename, data)
        file_id = f'file_{uuid4().hex}'
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            count = connection.execute('SELECT COUNT(*) FROM conversation_files WHERE conversation_id=?', (conversation_id,)).fetchone()[0]
            self._quota(connection, conversation_id, len(data))
            if count >= 50:
                raise ServiceError('当前会话附件已达 50 份，请使用新的会话。', 422)
            connection.execute('INSERT INTO conversation_files(id,conversation_id,filename,byte_size,content,data,content_hash,source_path) VALUES (?,?,?,?,?,?,?,?)',
                               (file_id, conversation_id, filename, len(data), text, data, digest, source_path))
            self._archive(connection, file_id)
        return self.info(conversation_id, file_id)

    def _quota(self, connection, conversation_id, extra):
        size = connection.execute('SELECT COALESCE(SUM(byte_size),0) FROM conversation_file_versions WHERE conversation_id=?', (conversation_id,)).fetchone()[0]
        if size + extra > 20_000_000:
            raise ServiceError('当前会话附件及历史版本已达 20 MB 上限，请使用新的会话。', 422)

    def _archive(self, connection, file_id):
        connection.execute('INSERT INTO conversation_file_versions(id,version,conversation_id,filename,byte_size,content,data,content_hash) SELECT id,version,conversation_id,filename,byte_size,content,data,content_hash FROM conversation_files WHERE id=?', (file_id,))

    def link_local(self, conversation_id, path, file_id=None, expected_version=None):
        if not Path(path).is_absolute():
            raise ServiceError('请明确填写后端所在电脑上单个文件的完整路径。', 422)
        # User-facing API only. Model tools cannot select or change host paths.
        try:
            resolved = str(Path(path).resolve(strict=True))
        except OSError as error:
            raise ServiceError('指定文件不存在，请核对路径。', 404) from error
        if Path(resolved).suffix.lower() not in ALLOWED_SUFFIXES:
            raise ServiceError('仅支持明确关联 PDF、DOCX、TXT、MD、CSV、JSON 或 PNG、JPG、WEBP 文件。', 422)
        data = self._local(resolved)
        if file_id:
            return self.update(conversation_id, file_id, expected_version, Path(resolved).name, data, resolved)
        return self.upload(conversation_id, Path(resolved).name, data, resolved)

    def info(self, conversation_id, file_id, version=None):
        with self.database.connection() as connection:
            if version is None:
                row = connection.execute('SELECT id,filename,byte_size,length(content) AS text_length,created_at,version,content_hash,source_path IS NOT NULL AS linked_local,substr(content,1,20) AS head FROM conversation_files WHERE conversation_id=? AND id=?', (conversation_id, file_id)).fetchone()
            else:
                row = connection.execute('SELECT id,filename,byte_size,length(content) AS text_length,created_at,version,content_hash,0 AS linked_local,substr(content,1,20) AS head FROM conversation_file_versions WHERE conversation_id=? AND id=? AND version=?', (conversation_id, file_id, version)).fetchone()
        if row is None:
            raise ServiceError('当前会话中找不到该附件或版本。请询问用户是否更换文件，并在文件管理中重新上传或关联。', 404)
        info = dict(row)
        info['kind'] = file_kind(info['filename'], info.pop('head'))
        return info

    def model_images(self, conversation_id, file_ids):
        """Images to attach to a user message, from this conversation's image and scanned-PDF attachments."""
        if len(file_ids) > MAX_MESSAGE_ATTACHMENTS or len(set(file_ids)) != len(file_ids):
            raise ServiceError(f'一条消息最多附带 {MAX_MESSAGE_ATTACHMENTS} 个不重复的图片附件。', 422)
        images = []
        for file_id in file_ids:
            info = self.info(conversation_id, file_id)
            if info['kind'] == 'text':
                raise ServiceError(f'{info["filename"]} 是文字附件，请让 Agent 用 read_file 读取，不能作为图片发送。', 422)
            with self.database.connection() as connection:
                data = connection.execute('SELECT data FROM conversation_files WHERE id=? AND conversation_id=?', (file_id, conversation_id)).fetchone()[0]
            for image in document_images(Path(info['filename']).suffix.lower(), data):
                images.append({**image, 'file_id': file_id, 'filename': info['filename']})
        if len(images) > MAX_MESSAGE_IMAGES:
            raise ServiceError(f'一条消息最多附带 {MAX_MESSAGE_IMAGES} 张图片（扫描版 PDF 每页算一张）。', 422)
        return images

    def list(self, conversation_id):
        with self.database.connection() as connection:
            ids = [row[0] for row in connection.execute('SELECT id FROM conversation_files WHERE conversation_id=? ORDER BY rowid', (conversation_id,))]
        return [self.info(conversation_id, file_id) for file_id in ids]

    def versions(self, conversation_id, file_id):
        self.info(conversation_id, file_id)
        with self.database.connection() as connection:
            versions = [row[0] for row in connection.execute('SELECT version FROM conversation_file_versions WHERE conversation_id=? AND id=? ORDER BY version DESC', (conversation_id, file_id))]
        return [self.info(conversation_id, file_id, version) for version in versions]

    def check(self, conversation_id, file_id):
        info = self.info(conversation_id, file_id)
        with self.database.connection() as connection:
            path = connection.execute('SELECT source_path FROM conversation_files WHERE conversation_id=? AND id=?', (conversation_id, file_id)).fetchone()[0]
        if not path:
            return {**info, 'resource_state': 'available', 'message': '使用已保存的上传副本。'}
        try:
            data = self._local(path)
            changed = hashlib.sha256(data).hexdigest() != info['content_hash']
            return {**info, 'resource_state': 'changed' if changed else 'available',
                    'message': '关联文件内容已变化，是否使用新版本？请确认更新，或在文件管理中更换关联。' if changed else '关联文件可读且与已保存版本一致。'}
        except ServiceError as error:
            return {**info, 'resource_state': {404:'missing',403:'permission_denied'}.get(error.status_code, 'unavailable'), 'message': str(error)}

    def validate_reference(self, conversation_id, file_id, version=None, content_hash=None):
        current = self.check(conversation_id, file_id)
        if current['resource_state'] != 'available':
            raise ServiceError(current['message'], 409)
        if (version is not None and current['version'] != version) or (content_hash is not None and current['content_hash'] != content_hash):
            raise ServiceError('附件版本已变化，请重新读取并生成操作清单。', 409)
        return current

    def read(self, conversation_id, file_id, offset=0, limit=12000, version=None):
        info = self.info(conversation_id, file_id, version)
        if version is None:
            self.validate_reference(conversation_id, file_id)
        if offset < 0 or not 1 <= limit <= 20000:
            raise ServiceError('附件分页参数不正确。', 422)
        with self.database.connection() as connection:
            row = connection.execute('SELECT substr(content,?,?) AS text FROM conversation_file_versions WHERE id=? AND conversation_id=? AND version=?', (offset + 1, limit, file_id, conversation_id, info['version'])).fetchone()
        return {**info, 'text': row['text'], 'offset': offset, 'next_offset': offset + limit if offset + limit < info['text_length'] else None}

    def raw(self, conversation_id, file_id, version=None):
        info = self.info(conversation_id, file_id, version)
        if version is None:
            self.validate_reference(conversation_id, file_id)
        with self.database.connection() as connection:
            row = connection.execute('SELECT data FROM conversation_file_versions WHERE id=? AND conversation_id=? AND version=?', (file_id, conversation_id, info['version'])).fetchone()
        return info, row['data']

    def update(self, conversation_id, file_id, expected_version, filename, data, source_path=None):
        filename, text, digest = self._parse(filename, data)
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM conversation_files WHERE id=? AND conversation_id=?', (file_id, conversation_id)).fetchone()
            if row is None:
                raise ServiceError('当前会话附件不存在，请重新上传。', 404)
            if row['version'] != expected_version:
                raise ServiceError('文件版本已变化，请刷新后重新确认。', 409)
            if row['content_hash'] == digest and row['filename'] == filename and row['source_path'] == source_path:
                return self.info(conversation_id, file_id)
            self._quota(connection, conversation_id, len(data))
            connection.execute('UPDATE conversation_files SET filename=?,content=?,data=?,byte_size=?,content_hash=?,source_path=?,version=version+1 WHERE id=?',
                               (filename, text, data, len(data), digest, source_path, file_id))
            self._archive(connection, file_id)
        return self.info(conversation_id, file_id)

    def prepare_update(self, conversation_id, file_id, expected_version, replacement_file_id=None):
        current = self.info(conversation_id, file_id)
        if current['version'] != expected_version:
            raise ServiceError('文件版本已变化，请重新读取。', 409)
        if replacement_file_id:
            target = self.validate_reference(conversation_id, replacement_file_id)
        else:
            with self.database.connection() as connection:
                path = connection.execute('SELECT source_path FROM conversation_files WHERE id=? AND conversation_id=?', (file_id, conversation_id)).fetchone()[0]
            if not path:
                raise ServiceError('请用户先上传替换文件，再提供 replacement_file_id；模型不能填写本机路径。', 422)
            data = self._local(path)
            target = {'filename': Path(path).name, 'content_hash': hashlib.sha256(data).hexdigest(), 'version': None}
        return {'file_id': file_id, 'expected_version': expected_version, 'replacement_file_id': replacement_file_id,
                'replacement_version': target['version'], 'replacement_hash': target['content_hash'], 'filename': target['filename']}

    def execute_update(self, conversation_id, plan):
        replacement = plan.get('replacement_file_id')
        if replacement:
            self.validate_reference(conversation_id, replacement, plan['replacement_version'], plan['replacement_hash'])
            info, data = self.raw(conversation_id, replacement, plan['replacement_version'])
            path = None
        else:
            with self.database.connection() as connection:
                row = connection.execute('SELECT source_path FROM conversation_files WHERE id=? AND conversation_id=?', (plan['file_id'], conversation_id)).fetchone()
            if row is None or not row[0]:
                raise ServiceError('文件关联已变化，请重新确认。', 409)
            path, info = row[0], {'filename': plan['filename']}
            data = self._local(path)
        if hashlib.sha256(data).hexdigest() != plan['replacement_hash']:
            raise ServiceError('待更新文件又发生变化，请重新生成确认清单。', 409)
        updated = self.update(conversation_id, plan['file_id'], plan['expected_version'], info['filename'], data, path)
        return {'file': updated, 'message': f"文件已更新为 v{updated['version']}，历史版本保留。后续操作需重新生成清单。"}
