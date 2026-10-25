"""Read-only access to local code projects the user bound to an Agent. The model never picks a path on disk:
it names a bound project and a path inside it, and everything is checked against that project's root."""
import ast
import fnmatch
import os
import re
import subprocess
import time
from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.errors import ServiceError
from app.services.redaction import redact_text

MAX_PROJECTS = 3
MAX_FILES = 20000
MAX_FILE_BYTES = 1_000_000
MAX_READ_LINES = 400
DEFAULT_READ_LINES = 200
MAX_ENTRIES = 500
MAX_SEARCH_RESULTS = 50
SEARCH_SECONDS = 5
MAX_LINE_CHARS = 2000
SKIP_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build', '.next', '.nuxt', '.mypy_cache',
             '.pytest_cache', '.ruff_cache', '.tox', '.idea', '.vscode', 'coverage', '.cache', 'target', '.gradle'}
# Files that tend to hold credentials or private keys: never listed, searched or read.
SENSITIVE = ('.env', '.env.*', '*.pem', '*.key', '*.p12', '*.pfx', '*.keystore', '*.jks', 'id_rsa*', 'id_ed25519*', 'id_ecdsa*',
             'id_dsa*', '.netrc', '.npmrc', '.pypirc', '.git-credentials', 'credentials*.json', 'secrets.json', 'secrets.yaml',
             'secrets.yml', 'secrets.toml', '*.sqlite', '*.sqlite3', '*.db')
SAFE_TEMPLATES = {'.env.example', '.env.sample', '.env.template'}
# Secret-looking string literals and well-known token shapes inside code.
SECRET_LITERAL = re.compile(r'(?i)((?:api[_-]?key|secret|token|password|passwd|credential|access[_-]?key)\w*["\']?\s*[:=]\s*)(["\'])([^"\'\n]{8,})\2')
SECRET_TOKEN = re.compile(r'\b(sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})')
TS_SYMBOL = re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:(function)\s+(\w+)|(class)\s+(\w+)|(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>|(interface|type)\s+(\w+))')
OUTLINE_SUFFIXES = {'.py', '.ts', '.tsx', '.js', '.jsx', '.mjs'}


def sensitive(relative):
    name = PurePosixPath(relative).name
    return name not in SAFE_TEMPLATES and any(fnmatch.fnmatch(name.lower(), pattern) for pattern in SENSITIVE)


def inside(resolved_root, path):
    """True when the path, after following symlinks, is still within the project."""
    target = Path(path).resolve()
    return target == resolved_root or resolved_root in target.parents


def scrub(text):
    """Code is shown to the model; secret values and personal identifiers are masked first."""
    text = SECRET_LITERAL.sub(lambda match: f'{match.group(1)}{match.group(2)}***{match.group(2)}', text)
    return redact_text(SECRET_TOKEN.sub('***', text), limit=None)


class CodeProjects:
    def __init__(self, database):
        self.database = database

    # ---- bindings (user-facing API only) ----

    def list(self, agent_id):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT id,name,root,created_at FROM agent_code_projects WHERE agent_id=? ORDER BY rowid', (agent_id,)).fetchall()
        return [{**dict(row), 'git': (Path(row['root']) / '.git').exists(), 'available': Path(row['root']).is_dir()} for row in rows]

    def add(self, agent_id, path, name=None):
        if not path or not Path(path).expanduser().is_absolute():
            raise ServiceError('请填写后端所在电脑上项目目录的完整路径。', 422)
        try:
            root = Path(path).expanduser().resolve(strict=True)
        except OSError as error:
            raise ServiceError('项目目录不存在，请核对路径。', 404) from error
        if not root.is_dir():
            raise ServiceError('请选择一个目录，而不是单个文件。', 422)
        if root == Path(root.anchor) or root == Path.home().resolve():
            raise ServiceError('不能绑定根目录或整个用户目录，请选择具体的项目目录。', 422)
        files, truncated = self._files(root)
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            count = connection.execute('SELECT COUNT(*) FROM agent_code_projects WHERE agent_id=?', (agent_id,)).fetchone()[0]
            if connection.execute('SELECT 1 FROM agent_code_projects WHERE agent_id=? AND root=?', (agent_id, str(root))).fetchone():
                raise ServiceError('这个项目已经绑定过了。', 409)
            if count >= MAX_PROJECTS:
                raise ServiceError(f'每个 Agent 最多绑定 {MAX_PROJECTS} 个项目，请先移除一个。', 422)
            project_id = f'code_{uuid4().hex}'
            connection.execute('INSERT INTO agent_code_projects(id,agent_id,name,root) VALUES (?,?,?,?)',
                               (project_id, agent_id, (name or root.name)[:100], str(root)))
        return {'id': project_id, 'name': (name or root.name)[:100], 'root': str(root), 'git': (root / '.git').exists(),
                'file_count': len(files), 'files_truncated': truncated}

    def remove(self, agent_id, project_id):
        with self.database.connection() as connection:
            if connection.execute('DELETE FROM agent_code_projects WHERE id=? AND agent_id=?', (project_id, agent_id)).rowcount != 1:
                raise ServiceError('这个 Agent 没有绑定该项目。', 404)
        return {'removed': True}

    # ---- safe access ----

    def _root(self, agent_id, project_id):
        with self.database.connection() as connection:
            row = connection.execute('SELECT root FROM agent_code_projects WHERE id=? AND agent_id=?', (project_id, agent_id)).fetchone()
        if row is None:
            raise ServiceError('当前 Agent 没有绑定这个项目。先用 code_projects 查看可用的项目 ID。', 404)
        root = Path(row['root'])
        if not root.is_dir():
            raise ServiceError('项目目录已不存在或无法访问，请让用户在基础能力设置中重新绑定。', 409)
        return root

    def _files(self, root):
        """Project files as relative POSIX paths: git's view when it is a repository (respects .gitignore)."""
        files = None
        if (root / '.git').exists():
            try:
                done = subprocess.run(['git', '-C', str(root), 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                                      capture_output=True, timeout=5, check=True)
                files = [item for item in done.stdout.decode('utf-8', 'replace').split('\0') if item]
            except (OSError, subprocess.SubprocessError):
                files = None
        if files is None:
            files = []
            for current, directories, names in os.walk(root, followlinks=False):
                directories[:] = sorted(d for d in directories if d not in SKIP_DIRS and not d.startswith('.'))
                base = Path(current).relative_to(root)
                files.extend((base / name).as_posix() for name in sorted(names))
                if len(files) > MAX_FILES:
                    break
        resolved = root.resolve()
        files = [item for item in files if not sensitive(item) and not set(PurePosixPath(item).parts[:-1]) & SKIP_DIRS
                 and inside(resolved, root / item)]
        return files[:MAX_FILES], len(files) > MAX_FILES

    def _path(self, root, relative):
        relative = (relative or '').strip().replace('\\', '/')
        parts = PurePosixPath(relative).parts
        if relative.startswith(('/', '~')) or '..' in parts:
            raise ServiceError('路径只能是项目内的相对路径，不能包含 .. 或绝对路径。', 422)
        relative = PurePosixPath(relative).as_posix() if relative else ''
        target = (root / relative).resolve()
        if not inside(root.resolve(), target):
            raise ServiceError('路径超出了项目目录（可能是指向外部的符号链接）。', 403)
        if relative and (sensitive(relative) or set(parts) & SKIP_DIRS):
            raise ServiceError('这个文件可能包含密钥或属于被忽略的目录，不能读取。', 403)
        return relative, target

    def _source(self, target):
        if not target.is_file():
            raise ServiceError('文件不存在。先用 code_list 或 code_search 找到实际路径。', 404)
        size = target.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ServiceError(f'文件超过 {MAX_FILE_BYTES // 1_000_000} MB，不能读取；可以先用 code_search 定位需要的部分。', 422)
        data = target.read_bytes()
        if b'\0' in data[:8192]:
            raise ServiceError('这是二进制文件，不能按文本读取。', 422)
        return data.decode('utf-8', 'replace')

    # ---- tools ----

    def projects(self, agent_id):
        return {'projects': [{key: item[key] for key in ('id', 'name', 'git', 'available')} for item in self.list(agent_id)]}

    def list_dir(self, agent_id, project_id, path='', depth=1):
        root = self._root(agent_id, project_id)
        prefix, target = self._path(root, path)
        if prefix and not target.is_dir():
            raise ServiceError('这不是目录。读取文件请用 code_read。', 422)
        files, truncated = self._files(root)
        entries = {}
        for item in files:
            if prefix and not item.startswith(prefix + '/'):
                continue
            parts = PurePosixPath(item[len(prefix) + 1:] if prefix else item).parts
            for level in range(1, min(len(parts), depth) + 1):
                key = '/'.join(parts[:level])
                is_file = level == len(parts)
                entries.setdefault(key, {'path': f'{prefix}/{key}' if prefix else key, 'type': 'file' if is_file else 'dir'})
        ordered = sorted(entries.values(), key=lambda entry: (entry['path'].count('/'), entry['type'] != 'dir', entry['path']))
        for entry in ordered[:MAX_ENTRIES]:
            if entry['type'] == 'file':
                entry['bytes'] = (root / entry['path']).stat().st_size if (root / entry['path']).is_file() else None
        return {'path': prefix or '.', 'entries': ordered[:MAX_ENTRIES], 'truncated': truncated or len(ordered) > MAX_ENTRIES}

    def search(self, agent_id, project_id, pattern, regex=False, case_sensitive=False, glob=None, path=''):
        root = self._root(agent_id, project_id)
        prefix, _ = self._path(root, path)
        try:
            matcher = re.compile(pattern if regex else re.escape(pattern), 0 if case_sensitive else re.IGNORECASE)
        except re.error as error:
            raise ServiceError(f'正则表达式无效：{error}', 422) from error
        files, _ = self._files(root)
        deadline, matches, scanned, timed_out = time.monotonic() + SEARCH_SECONDS, [], 0, False
        for item in files:
            if prefix and not item.startswith(prefix + '/'):
                continue
            if glob and not (fnmatch.fnmatch(item, glob) or fnmatch.fnmatch(PurePosixPath(item).name, glob)):
                continue
            if time.monotonic() > deadline:
                timed_out = True
                break
            target = root / item
            try:
                if not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = target.read_bytes()
            except OSError:
                continue
            if b'\0' in data[:8192]:
                continue
            scanned += 1
            for number, line in enumerate(data.decode('utf-8', 'replace').splitlines(), 1):
                if len(line) <= MAX_LINE_CHARS and matcher.search(line):
                    matches.append({'path': item, 'line': number, 'text': scrub(line.strip())[:300]})
                    if len(matches) >= MAX_SEARCH_RESULTS:
                        return {'matches': matches, 'files_scanned': scanned, 'truncated': True,
                                'notice': f'结果已达 {MAX_SEARCH_RESULTS} 条上限，请用 glob 或 path 缩小范围。'}
        return {'matches': matches, 'files_scanned': scanned, 'truncated': timed_out,
                **({'notice': f'搜索超过 {SEARCH_SECONDS} 秒已停止，请用 glob 或 path 缩小范围。'} if timed_out else {})}

    def read(self, agent_id, project_id, path, start_line=1, end_line=None):
        root = self._root(agent_id, project_id)
        relative, target = self._path(root, path)
        lines = scrub(self._source(target)).splitlines()
        if start_line > max(len(lines), 1):
            raise ServiceError(f'起始行超出文件长度（共 {len(lines)} 行）。', 422)
        end = min(end_line or start_line + DEFAULT_READ_LINES - 1, start_line + MAX_READ_LINES - 1, len(lines))
        width = len(str(end))
        content = '\n'.join(f'{number:>{width}}| {lines[number - 1]}' for number in range(start_line, end + 1))
        return {'path': relative, 'start_line': start_line, 'end_line': end, 'total_lines': len(lines), 'content': content,
                'next_start_line': end + 1 if end < len(lines) else None}

    def outline(self, agent_id, project_id, path):
        root = self._root(agent_id, project_id)
        relative, target = self._path(root, path)
        text = self._source(target)  # parsed unmasked so masking cannot break syntax; only names and lines are returned
        suffix = PurePosixPath(relative).suffix.lower()
        if suffix not in OUTLINE_SUFFIXES:
            raise ServiceError('目前只能列出 Python 和 TypeScript/JavaScript 文件的结构，其他文件请用 code_read。', 422)
        symbols = python_symbols(text) if suffix == '.py' else script_symbols(text)
        return {'path': relative, 'symbols': symbols[:MAX_ENTRIES], 'total_lines': len(text.splitlines())}


def browse_directories(path=None):
    """Subdirectories of a folder on the backend machine, for the user's project picker; the model never calls this."""
    try:
        folder = Path(path).expanduser().resolve(strict=True) if path else Path.home().resolve()
    except OSError as error:
        raise ServiceError('目录不存在。', 404) from error
    if not folder.is_absolute() or not folder.is_dir():
        raise ServiceError('请选择一个目录。', 422)
    try:
        children = sorted((child for child in folder.iterdir()
                           if not child.name.startswith('.') and child.name not in SKIP_DIRS and child.suffix != '.app' and child.is_dir()),
                          key=lambda child: child.name.lower())
    except PermissionError as error:
        raise ServiceError('没有权限读取这个目录。', 403) from error
    return {'path': str(folder), 'parent': str(folder.parent) if folder.parent != folder else None,
            'git': (folder / '.git').exists(), 'truncated': len(children) > MAX_ENTRIES,
            'directories': [{'name': child.name, 'path': str(child), 'git': (child / '.git').exists()} for child in children[:MAX_ENTRIES]]}


def python_symbols(text):
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        raise ServiceError(f'Python 语法解析失败（第 {error.lineno} 行），请改用 code_read。', 422) from error
    symbols = []

    def visit(node, owner=''):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f'{owner}.{child.name}' if owner else child.name
                kind = 'class' if isinstance(child, ast.ClassDef) else 'method' if owner else 'function'
                symbols.append({'name': name, 'kind': kind, 'line': child.lineno, 'end_line': child.end_lineno})
                if isinstance(child, ast.ClassDef):
                    visit(child, name)
    visit(tree)
    return symbols


def script_symbols(text):
    symbols = []
    for number, line in enumerate(text.splitlines(), 1):
        match = TS_SYMBOL.match(line)
        if match:
            kind, name = next((kind, name) for kind, name in [('function', match.group(2)), ('class', match.group(4)),
                              ('function', match.group(5)), (match.group(6), match.group(7))] if name)
            symbols.append({'name': name, 'kind': kind, 'line': number})
    return symbols
