"""Immutable profile versions; drafts from an Agent need a user save before a kit may use them."""
import json
from uuid import uuid4

from app.errors import ServiceError
from app.models.profiles import DateRange, DateValue, ProfileData


class ProfileStore:
    def __init__(self, database):
        self.database = database

    def list(self):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT p.*, (SELECT MAX(version) FROM profile_versions v WHERE v.profile_id=p.id AND v.review_state=\'reviewed\') AS reviewed_version '
                                      'FROM profiles p ORDER BY p.updated_at DESC').fetchall()
            return [dict(row) for row in rows]

    def get(self, profile_id, version=None):
        with self.database.connection() as connection:
            profile = connection.execute('SELECT * FROM profiles WHERE id=?', (profile_id,)).fetchone()
            if profile is None:
                raise ServiceError('资料档案不存在。', 404)
            row = connection.execute('SELECT * FROM profile_versions WHERE profile_id=? AND version=?', (profile_id, version or profile['latest_version'])).fetchone()
            if row is None:
                raise ServiceError('资料版本不存在。', 404)
            versions = connection.execute('SELECT version,review_state,source_file_id,created_at FROM profile_versions WHERE profile_id=? ORDER BY version DESC', (profile_id,)).fetchall()
        return {**dict(profile), 'version': row['version'], 'review_state': row['review_state'], 'source_file_id': row['source_file_id'],
                'data': json.loads(row['data']), 'versions': [dict(v) for v in versions]}

    def save(self, request, profile_id=None, review_state='reviewed'):
        data = request.data.model_dump_json()
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if profile_id is None:
                profile_id, version = 'profile_' + uuid4().hex, 1
                connection.execute('INSERT INTO profiles(id,name,latest_version) VALUES (?,?,1)', (profile_id, request.name))
            else:
                profile = connection.execute('SELECT * FROM profiles WHERE id=?', (profile_id,)).fetchone()
                if profile is None:
                    raise ServiceError('资料档案不存在。', 404)
                if request.expected_version != profile['latest_version']:
                    raise ServiceError('资料已有更新的版本，请重新读取后保存。', 409)
                version = profile['latest_version'] + 1
                connection.execute('UPDATE profiles SET name=?,latest_version=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (request.name, version, profile_id))
            connection.execute('INSERT INTO profile_versions(profile_id,version,data,review_state,source_file_id) VALUES (?,?,?,?,?)',
                               (profile_id, version, data, review_state, request.source_file_id))
        return self.get(profile_id, version)

    def delete(self, profile_id):
        with self.database.connection() as connection:
            connection.execute('DELETE FROM profile_versions WHERE profile_id=?', (profile_id,))
            if not connection.execute('DELETE FROM profiles WHERE id=?', (profile_id,)).rowcount:
                raise ServiceError('资料档案不存在。', 404)
        return {'deleted': True}

    def reviewed(self, profile_id, version):
        """Kits may only read versions the user saved themselves."""
        profile = self.get(profile_id, version)
        if profile['review_state'] != 'reviewed':
            raise ServiceError('该资料版本是 Agent 草稿，需要用户审阅保存后才能使用。', 409)
        return ProfileData.model_validate(profile['data'])


def resolve(data, path, transform=''):
    """Resolve `education.0.period.start` style paths. Returns text; never invents missing parts."""
    node = data
    for part in path.split('.'):
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        elif hasattr(node, part) and not part.startswith('_'):
            node = getattr(node, part)
        else:
            raise ServiceError(f'资料中没有 {path}，请补充资料或询问用户。', 422)
    if isinstance(node, DateRange):
        raise ServiceError(f'{path} 是时间段，请分别使用 .start / .end / .present。', 422)
    if node is None:
        # An open-ended period: the page should use its own “至今” option.
        raise ServiceError(f'{path} 为“至今”，没有结束日期；表单中请选“至今”（{path.rsplit(".", 1)[0]}.present）。', 422)
    if isinstance(node, DateValue):
        parts = transform.split(':') if transform.startswith('date:') else ['date', node.precision]
        value = node.format(parts[1])
        return value.replace('-', parts[2]) if len(parts) > 2 else value
    if isinstance(node, bool):
        return 'true' if node else 'false'
    if isinstance(node, list):
        return '、'.join(str(item) for item in node)
    if not isinstance(node, (str, int, float)):
        raise ServiceError(f'{path} 不是可直接填写的单个值。', 422)
    return str(node)
