"""Application ledger storage. Every change bumps `revision`; stage changes and kit generations are kept as events."""
import json
from datetime import datetime
from uuid import uuid4

from app.errors import ServiceError
from app.services.redaction import redact

FIELDS = ('company', 'position', 'url', 'deadline', 'next_event_at', 'next_event', 'note')
STAGE_LABELS = {'saved': '待投递', 'preparing': '准备中', 'applied': '已投递', 'test': '笔试/测评', 'interview': '面试',
                'offer': 'offer', 'rejected': '未通过', 'withdrawn': '放弃'}


class ApplicationStore:
    def __init__(self, database):
        self.database = database

    def list(self):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT * FROM applications ORDER BY updated_at DESC').fetchall()
        # The list stays light: kits are read per application.
        return [{**self._decode(row), 'kit': None, 'has_kit': row['kit'] != '{}'} for row in rows]

    def get(self, application_id):
        with self.database.connection() as connection:
            row = self._require(connection, application_id)
            events = connection.execute('SELECT * FROM application_events WHERE application_id=? ORDER BY id', (application_id,)).fetchall()
        return {**self._decode(row), 'events': [{**dict(e), 'body': json.loads(e['body'])} for e in events]}

    def save(self, request, application_id=None, actor='user', stage=None):
        values = {field: getattr(request, field) for field in FIELDS}
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if application_id is None:
                application_id = 'app_' + uuid4().hex
                if request.url and (dup := connection.execute('SELECT id FROM applications WHERE url=?', (request.url,)).fetchone()):
                    raise ServiceError(f'台账里已有这个岗位链接（{dup["id"]}），请直接修改。', 409)
                connection.execute(f'INSERT INTO applications(id,{",".join(FIELDS)},stage) VALUES (?,{",".join("?" * len(FIELDS))},?)',
                                   (application_id, *values.values(), stage or 'saved'))
                self._event(connection, application_id, actor, {'action': 'created', 'stage': stage or 'saved'})
            else:
                row = self._require(connection, application_id, getattr(request, 'expected_revision', None))
                connection.execute(f'UPDATE applications SET {",".join(f"{f}=?" for f in FIELDS)},revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                                   (*values.values(), application_id))
                changed = [f for f in FIELDS if row[f] != values[f]]
                self._event(connection, application_id, actor, {'action': 'edited', 'fields': changed})
                if stage and stage != row['stage']:
                    self._stage(connection, row, stage, actor, '')
        return self.get(application_id)

    def change_stage(self, application_id, request, actor='user'):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = self._require(connection, application_id, request.expected_revision)
            if row['stage'] != request.stage:
                self._stage(connection, row, request.stage, actor, request.note)
        return self.get(application_id)

    def save_kit(self, application_id, kit, actor='agent'):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = self._require(connection, application_id)
            connection.execute("UPDATE applications SET kit=?,stage=CASE WHEN stage='saved' THEN 'preparing' ELSE stage END,"
                               'revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?', (json.dumps(kit, ensure_ascii=False), application_id))
            # Values stay out of the event log; only what was generated.
            self._event(connection, application_id, actor, {'action': 'kit', 'items': len(kit['items']), 'profile_version': kit.get('profile_version')})
            if row['stage'] == 'saved':
                self._event(connection, application_id, actor, {'action': 'stage', 'from': 'saved', 'to': 'preparing'})
        return self.get(application_id)

    def edit_kit(self, application_id, request, actor='user'):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = self._require(connection, application_id, request.expected_revision)
            kit = json.loads(row['kit'])
            items = kit.get('items', [])
            if request.index >= len(items):
                raise ServiceError('资料包条目不存在。', 404)
            items[request.index].update(value=request.value, edited=True)
            connection.execute('UPDATE applications SET kit=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                               (json.dumps(kit, ensure_ascii=False), application_id))
            self._event(connection, application_id, actor, {'action': 'kit_edited', 'label': items[request.index]['label']})
        return self.get(application_id)

    def delete(self, application_id):
        with self.database.connection() as connection:
            connection.execute('DELETE FROM application_events WHERE application_id=?', (application_id,))
            if not connection.execute('DELETE FROM applications WHERE id=?', (application_id,)).rowcount:
                raise ServiceError('台账记录不存在。', 404)
        return {'deleted': True}

    # ---------- helpers ----------
    def _stage(self, connection, row, stage, actor, note):
        applied = datetime.now().strftime('%Y-%m-%d %H:%M') if stage == 'applied' and not row['applied_at'] else row['applied_at']
        connection.execute('UPDATE applications SET stage=?,applied_at=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                           (stage, applied, row['id']))
        self._event(connection, row['id'], actor, {'action': 'stage', 'from': row['stage'], 'to': stage, **({'note': note} if note else {})})

    @staticmethod
    def _require(connection, application_id, expected_revision=None):
        row = connection.execute('SELECT * FROM applications WHERE id=?', (application_id,)).fetchone()
        if row is None:
            raise ServiceError('台账记录不存在。', 404)
        if expected_revision is not None and row['revision'] != expected_revision:
            raise ServiceError('台账记录已被修改，请刷新后再操作。', 409)
        return row

    @staticmethod
    def _decode(row):
        item = dict(row)
        item['kit'] = json.loads(item['kit']) or None
        item['stage_label'] = STAGE_LABELS.get(item['stage'], item['stage'])
        return item

    @staticmethod
    def _event(connection, application_id, actor, body):
        connection.execute('INSERT INTO application_events(application_id,actor,body) VALUES (?,?,?)',
                           (application_id, actor, json.dumps(redact(body), ensure_ascii=False)))
