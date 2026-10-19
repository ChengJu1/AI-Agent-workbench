"""Server-side build drafts and immutable published capability versions."""
import hashlib
import json
import time
from uuid import uuid4

from app.errors import ServiceError
from app.models.agents import GeneratedBinding, LoadedAgent, PermissionsManifest
from app.storage.agent_store import AgentStore


def plan_hash(plan):
    return hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


class BuildStore:
    def __init__(self, database):
        self.database = database

    def _load(self, connection, build_id):
        row = connection.execute('SELECT definition FROM agent_builds WHERE id=?', (build_id,)).fetchone()
        if row is None:
            raise ServiceError('构建记录不存在。', 404)
        return json.loads(row['definition'])

    def _save(self, connection, build):
        connection.execute('UPDATE agent_builds SET definition=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                           (json.dumps(build, ensure_ascii=False), build['id']))

    def get(self, build_id):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            build = self._load(connection, build_id)
            if build['status'] in ('generating', 'testing') and time.time() - build['started_at'] > 360:
                build.update(status='failed', error='上次构建已中断或超时，可以补充要求重新生成。', revision=build['revision'] + 1)
                self._save(connection, build)
            return build

    def list_builds(self):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT id FROM agent_builds ORDER BY updated_at DESC,rowid DESC LIMIT 30').fetchall()
        builds = [self.get(row['id']) for row in rows]
        return [{'id': build['id'], 'status': build['status'], 'name': (build['plan'] or {}).get('name') or build['history'][0]['content'][:30]} for build in builds]

    def package(self, package_id, version=None):
        with self.database.connection() as connection:
            row = connection.execute('SELECT definition FROM capability_packages WHERE id=? AND (? IS NULL OR version=?) ORDER BY version DESC LIMIT 1',
                                     (package_id, version, version)).fetchone()
        if row is None:
            raise ServiceError('能力包版本不存在。', 404)
        package = json.loads(row['definition'])
        if package['hash'] != plan_hash(package['plan']):
            raise ServiceError('能力包校验失败。', 409)
        return package

    def packages(self):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT id,MAX(version) AS version FROM capability_packages GROUP BY id ORDER BY rowid DESC').fetchall()
        return [{'id': row['id'], 'version': row['version'], 'name': self.package(row['id'], row['version'])['plan']['name']} for row in rows]

    def start(self, request):
        build_id = str(request.request_id)
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            exists = connection.execute('SELECT definition FROM agent_builds WHERE id=?', (build_id,)).fetchone()
            if exists:
                build = json.loads(exists['definition'])
                if build['history'][0]['content'] != request.message or build['base_package_id'] != request.base_package_id:
                    raise ServiceError('请求编号已被其他构建占用。', 409)
                return build, False
            base = self.package(request.base_package_id) if request.base_package_id else None
            build = {'id': build_id, 'package_id': request.base_package_id or f'pkg_{uuid4().hex}',
                     'base_package_id': request.base_package_id, 'base_version': base['version'] if base else 0,
                     'status': 'generating', 'revision': 1, 'started_at': time.time(),
                     'history': [{'role': 'user', 'content': request.message}],
                     'plan': base['plan'] if base else None, 'tests': [], 'tested_hash': None,
                     'error': None, 'published_agent': None}
            connection.execute('INSERT INTO agent_builds(id,definition) VALUES (?,?)', (build_id, json.dumps(build, ensure_ascii=False)))
            return build, True

    def revise(self, build_id, request):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            build = self._load(connection, build_id)
            if build['revision'] != request.expected_revision or build['status'] in ('generating', 'testing', 'published'):
                raise ServiceError('构建状态已变化，请刷新后再操作；已发布版本请新建版本。', 409)
            if sum(len(item['content']) for item in build['history']) + len(request.message) > 48000:
                raise ServiceError('当前讨论较长，请新建构建并概括最终要求。', 422)
            build['history'].append({'role': 'user', 'content': request.message})
            build.update(status='generating', revision=build['revision'] + 1, started_at=time.time(), error=None, tests=[], tested_hash=None)
            self._save(connection, build)
            return build

    def update(self, build_id, revision, **changes):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            build = self._load(connection, build_id)
            if build['revision'] != revision or build['status'] not in ('generating', 'testing'):
                return None
            build.update(changes)
            self._save(connection, build)
            return build

    def publish(self, build_id, revision):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            build = self._load(connection, build_id)
            if build['status'] == 'published':
                return build['published_agent']
            if build['revision'] != revision or build['status'] != 'ready' or build['tested_hash'] != plan_hash(build['plan']):
                raise ServiceError('当前方案尚未通过测试或已变化，不能发布。', 409)
            row = connection.execute('SELECT MAX(version) AS latest FROM capability_packages WHERE id=?', (build['package_id'],)).fetchone()
            version = (row['latest'] or 0) + 1
            if version - 1 != build['base_version']:
                raise ServiceError('能力包已有新版本，请基于最新版本重新构建。', 409)
            package = {'id': build['package_id'], 'version': version, 'plan': build['plan'],
                       'hash': build['tested_hash'], 'tests': build['tests']}
            connection.execute('INSERT INTO capability_packages(id,version,definition) VALUES (?,?,?)',
                               (package['id'], version, json.dumps(package, ensure_ascii=False)))
            plan = build['plan']
            agent = LoadedAgent(id=f'custom_{uuid4().hex}', name=f"{plan['name']} · v{version}",
                                description=plan['description'], system_prompt=plan['system_prompt'], skills=[], tools=[],
                                permissions=PermissionsManifest(dry_run_by_default=True),
                                generated_tools=[GeneratedBinding(package_id=package['id'], version=version)])
            AgentStore(self.database).create_in_connection(connection, agent)
            info = {'id': agent.id, 'name': agent.name, 'description': agent.description}
            build.update(status='published', published_agent=info)
            self._save(connection, build)
            return info
