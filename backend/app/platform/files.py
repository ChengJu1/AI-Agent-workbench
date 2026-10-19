import base64
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

ALLOWED_SUFFIXES = {'.pdf', '.docx', '.txt', '.md', '.csv', '.json'}


def parse_document(suffix, data):
    payload = json.dumps({'suffix': suffix, 'data': base64.b64encode(data).decode()}).encode()
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
        return result['text']
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

    def upload(self, conversation_id, filename, data):
        filename = filename.replace('\\', '/').split('/')[-1][:200]
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES or not data or len(data) > 2_000_000:
            raise ServiceError('支持 PDF、DOCX、TXT、MD、CSV、JSON，单文件需为 1 字节至 2 MB。', 422)
        text = parse_document(suffix, data)
        file_id = f'file_{uuid4().hex}'
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            size = connection.execute('SELECT COALESCE(SUM(byte_size),0) FROM conversation_files WHERE conversation_id=?', (conversation_id,)).fetchone()[0]
            if len(self.list(conversation_id)) >= 50 or size + len(data) > 20_000_000:
                raise ServiceError('当前会话附件已达 50 份或 20 MB 上限，请使用新的会话。', 422)
            connection.execute('INSERT INTO conversation_files(id,conversation_id,filename,byte_size,content,data) VALUES (?,?,?,?,?,?)',
                               (file_id, conversation_id, filename, len(data), text, data))
        return self.info(conversation_id, file_id)

    def info(self, conversation_id, file_id):
        with self.database.connection() as connection:
            row = connection.execute('SELECT id,filename,byte_size,length(content) AS text_length,created_at FROM conversation_files WHERE conversation_id=? AND id=?', (conversation_id, file_id)).fetchone()
        if row is None:
            raise ServiceError('当前会话中找不到该附件。', 404)
        return dict(row)

    def list(self, conversation_id):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT id,filename,byte_size,length(content) AS text_length,created_at FROM conversation_files WHERE conversation_id=? ORDER BY rowid', (conversation_id,)).fetchall()
        return [dict(row) for row in rows]

    def read(self, conversation_id, file_id, offset=0, limit=12000):
        info = self.info(conversation_id, file_id)
        if offset < 0 or not 1 <= limit <= 20000:
            raise ServiceError('附件分页参数不正确。', 422)
        with self.database.connection() as connection:
            row = connection.execute('SELECT substr(content,?,?) AS text FROM conversation_files WHERE id=? AND conversation_id=?', (offset + 1, limit, file_id, conversation_id)).fetchone()
        return {**info, 'text': row['text'], 'offset': offset, 'next_offset': offset + limit if offset + limit < info['text_length'] else None}

    def raw(self, conversation_id, file_id):
        info = self.info(conversation_id, file_id)
        with self.database.connection() as connection:
            row = connection.execute('SELECT data FROM conversation_files WHERE id=? AND conversation_id=?', (file_id, conversation_id)).fetchone()
        return info, row['data']
