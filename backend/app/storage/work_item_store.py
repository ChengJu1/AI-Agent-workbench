"""Persist intentions independently of approval/execution; never infer external success."""
import json
from uuid import uuid4
from app.errors import ServiceError


class WorkItemStore:
    def __init__(self, database):
        self.database = database

    def list(self, agent_id=None):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT * FROM work_items WHERE (? IS NULL OR agent_id=?) ORDER BY updated_at DESC,rowid DESC LIMIT 200', (agent_id, agent_id)).fetchall()
            return [self._decode(connection, row) for row in rows]

    def _decode(self, connection, row):
        item = dict(row)
        item['key'] = item.pop('item_key')
        item['executions'] = [dict(r) for r in connection.execute('SELECT r.id,r.state,r.action_id,r.updated_at FROM execution_records r JOIN work_item_actions l ON l.action_id=r.action_id WHERE l.item_id=? ORDER BY r.created_at DESC,r.rowid DESC', (item['id'],))]
        item['tracking'] = [dict(r) for r in connection.execute('SELECT t.id,t.state,t.business_status,t.last_error FROM tracking_tasks t JOIN execution_records r ON r.id=t.record_id JOIN work_item_actions l ON l.action_id=r.action_id WHERE l.item_id=? ORDER BY t.created_at DESC,t.rowid DESC', (item['id'],))]
        attempt = connection.execute('SELECT * FROM work_item_attempts WHERE item_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (item['id'],)).fetchone()
        item['last_attempt'] = dict(attempt) if attempt else None
        return item

    def get(self, item_id, agent_id=None):
        with self.database.connection() as connection:
            row = connection.execute('SELECT * FROM work_items WHERE id=? AND (? IS NULL OR agent_id=?)', (item_id, agent_id, agent_id)).fetchone()
            if row is None:
                raise ServiceError('事项不存在或不属于当前 Agent。', 404)
            item = self._decode(connection, row)
            item['events'] = [dict(r) | {'body': json.loads(r['body'])} for r in connection.execute('SELECT * FROM work_item_events WHERE item_id=? ORDER BY id DESC LIMIT 50', (item_id,))]
            item['attempts'] = [dict(r) for r in connection.execute('SELECT * FROM work_item_attempts WHERE item_id=? ORDER BY created_at DESC,rowid DESC LIMIT 20', (item_id,))]
        return item

    def save(self, conversation_id, agent_id, request):
        body = request.model_dump(exclude={'item_id', 'expected_revision'})
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if request.item_id:
                old = connection.execute('SELECT * FROM work_items WHERE id=? AND conversation_id=? AND agent_id=?', (request.item_id, conversation_id, agent_id)).fetchone()
                if old is None:
                    raise ServiceError('请在事项原会话内更新。', 404)
                if old['revision'] != request.expected_revision:
                    raise ServiceError('事项已变化，请重新读取后更新。', 409)
                if old['item_key'] != request.key:
                    raise ServiceError('事项标识不可修改，请创建新事项。', 422)
                # A linked action retains the exact target it was reviewed for.
                if old['target_url'] != request.target_url and connection.execute('SELECT 1 FROM work_item_actions WHERE item_id=?', (old['id'],)).fetchone():
                    raise ServiceError('已有执行操作的事项不能更换目标，请为新目标建立事项。', 409)
                item_id, revision = old['id'], old['revision'] + 1
                connection.execute('UPDATE work_items SET title=?,target_url=?,state=?,note=?,next_step=?,revision=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (request.title, request.target_url, request.state, request.note, request.next_step, revision, item_id))
            else:
                old = connection.execute('SELECT * FROM work_items WHERE conversation_id=? AND item_key=?', (conversation_id, request.key)).fetchone()
                if old:
                    same = all(old['item_key' if key == 'key' else key] == value for key, value in body.items())
                    if not same:
                        raise ServiceError('同一标识的事项已存在，请读取其 ID 和版本后更新。', 409)
                    return self.get(old['id'], agent_id)
                item_id, revision = 'work_' + uuid4().hex, 1
                connection.execute('INSERT INTO work_items(id,conversation_id,agent_id,item_key,title,target_url,state,note,next_step) VALUES (?,?,?,?,?,?,?,?,?)', (item_id, conversation_id, agent_id, request.key, request.title, request.target_url, request.state, request.note, request.next_step))
            connection.execute('INSERT INTO work_item_events(item_id,revision,body) VALUES (?,?,?)', (item_id, revision, json.dumps(body, ensure_ascii=False)))
        return self.get(item_id, agent_id)

    def begin_attempt(self, conversation_id, agent_id, target_url):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute("SELECT id FROM work_items WHERE conversation_id=? AND agent_id=? AND target_url=? AND state!='cancelled'", (conversation_id, agent_id, target_url)).fetchall()
            if len(rows) != 1:
                return None  # Never guess which object a shared page represents.
            attempt = {'id':'attempt_' + uuid4().hex, 'item_id':rows[0]['id']}
            connection.execute('INSERT INTO work_item_attempts(id,item_id,target_url) VALUES (?,?,?)', (attempt['id'], attempt['item_id'], target_url))
        return attempt

    def finish_attempt(self, attempt, result=None, error=''):
        if not attempt:
            return
        result = result or {}
        code = result.get('http_status')
        status = ('failed' if error else 'http_error' if code and code >= 400 else 'partial' if result.get('warning')
                  else 'readable' if result.get('text', '').strip() or result.get('elements') else 'empty')
        with self.database.connection() as connection:
            connection.execute("UPDATE work_item_attempts SET status=?,http_status=?,error=?,notice=?,finished_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'",
                               (status, code, error[:1000], str(result.get('warning', ''))[:1000], attempt['id']))

    def context(self, conversation_id, agent_id):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT id,title,state,revision,note,next_step FROM work_items WHERE conversation_id=? AND agent_id=? ORDER BY updated_at DESC,rowid DESC LIMIT 6', (conversation_id, agent_id)).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item['note'], item['next_step'] = item['note'][:300], item['next_step'][:200]
                attempt = connection.execute('SELECT status,error,finished_at FROM work_item_attempts WHERE item_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (item['id'],)).fetchone()
                item['last_attempt'] = dict(attempt) if attempt else None
                if item['last_attempt']:
                    item['last_attempt']['error'] = item['last_attempt']['error'][:200]
                items.append(item)
        return json.dumps(items, ensure_ascii=False) if items else ''

    def validate_link(self, item_id, conversation_id, target_url):
        with self.database.connection() as connection:
            self.check_link(connection, item_id, conversation_id, target_url)

    @staticmethod
    def check_link(connection, item_id, conversation_id, target_url):
        row = connection.execute('SELECT * FROM work_items WHERE id=? AND conversation_id=?', (item_id, conversation_id)).fetchone()
        if row is None:
            raise ServiceError('关联事项不属于当前会话。', 404)
        if row['state'] == 'cancelled':
            raise ServiceError('事项已取消，请先更新计划。', 409)
        if not row['target_url'] or row['target_url'] != target_url:
            raise ServiceError('事项目标与操作页面不同，请核对并更新事项链接。', 409)
