"""SQLite execution ledger and leased, restartable status checks."""
import json
import time
from uuid import uuid4
from app.errors import ServiceError


def record_pending(connection, action_id, conversation_id, agent_id, tool_name, action, params):
    title = params.get('title') or params.get('filename') or action
    connection.execute('INSERT OR IGNORE INTO execution_records(id,action_id,conversation_id,agent_id,title,target_url) VALUES (?,?,?,?,?,?)',
                       ('run_' + action_id, action_id, conversation_id, agent_id, title[:500], params.get('url', '')))
    if params.get('work_item_id'):
        from app.storage.work_item_store import WorkItemStore
        WorkItemStore.check_link(connection, params['work_item_id'], conversation_id, params.get('url', ''))
        connection.execute('INSERT INTO work_item_actions(action_id,item_id) VALUES (?,?)', (action_id, params['work_item_id']))


def record_finished(connection, action_id, status, result=None):
    row = connection.execute('SELECT action,tool_name FROM pending_actions WHERE id=?', (action_id,)).fetchone()
    if not row:
        return
    state = ('cancelled' if status == 'cancelled' else 'needs_verification' if row['action'] == 'browser_actions'
             else 'confirmed' if status == 'approved' else 'failed')
    connection.execute('UPDATE execution_records SET state=?,result=?,updated_at=CURRENT_TIMESTAMP WHERE action_id=?',
                       (state, json.dumps(result, ensure_ascii=False) if result else None, action_id))


class TrackingStore:
    def __init__(self, database):
        self.database = database

    def records(self, agent_id=None):
        with self.database.connection() as connection:
            connection.execute("UPDATE execution_records SET state='needs_verification',updated_at=CURRENT_TIMESTAMP WHERE state='executing' AND action_id IN (SELECT id FROM pending_actions WHERE status='executing' AND updated_at<datetime('now','-10 minutes'))")
            rows = connection.execute('SELECT r.*,a.action FROM execution_records r JOIN pending_actions a ON a.id=r.action_id WHERE (? IS NULL OR r.agent_id=?) ORDER BY r.created_at DESC,r.rowid DESC LIMIT 200', (agent_id, agent_id)).fetchall()
        return [{key:value for key,value in dict(row).items() if key != 'result'} for row in rows]

    def record(self, record_id, agent_id=None):
        with self.database.connection() as connection:
            row = connection.execute('SELECT r.*,a.action,a.params FROM execution_records r JOIN pending_actions a ON a.id=r.action_id WHERE r.id=? AND (? IS NULL OR r.agent_id=?)', (record_id, agent_id, agent_id)).fetchone()
        if row is None:
            raise ServiceError('执行记录不存在或不属于当前 Agent。', 404)
        item = dict(row)
        for key in ('result','params'):
            item[key] = json.loads(item[key]) if item[key] else None
        return item

    def tasks(self, agent_id=None):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT * FROM tracking_tasks WHERE (? IS NULL OR agent_id=?) ORDER BY created_at DESC,rowid DESC LIMIT 200', (agent_id, agent_id)).fetchall()
        return [self._decode(row) for row in rows]

    def _decode(self, row):
        item = dict(row)
        item['definition'] = json.loads(item['definition'])
        item.pop('lease_token', None)
        return item

    def get(self, task_id, agent_id=None):
        with self.database.connection() as connection:
            row = connection.execute('SELECT * FROM tracking_tasks WHERE id=? AND (? IS NULL OR agent_id=?)', (task_id, agent_id, agent_id)).fetchone()
            if row is None:
                raise ServiceError('跟踪任务不存在或不属于当前 Agent。', 404)
            item = self._decode(row)
            item['checks'] = [dict(row) | {'evidence': json.loads(row['evidence'])} for row in connection.execute('SELECT * FROM tracking_checks WHERE task_id=? ORDER BY id DESC LIMIT 50', (task_id,))]
        return item

    def create(self, conversation_id, agent_id, definition):
        if definition.record_id:
            record = self.record(definition.record_id, agent_id)
            if record['conversation_id'] != conversation_id:
                raise ServiceError('请在原执行记录的会话内建立跟踪。', 403)
        body = definition.model_dump()
        # Identical proposals are idempotent; enabling always remains a UI action.
        encoded = json.dumps(body, ensure_ascii=False, sort_keys=True)
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT id FROM tracking_tasks WHERE conversation_id=? AND definition=?', (conversation_id, encoded)).fetchone()
            if row:
                task_id = row[0]
            else:
                task_id = 'track_' + uuid4().hex
                connection.execute('INSERT INTO tracking_tasks(id,conversation_id,agent_id,record_id,definition) VALUES (?,?,?,?,?)', (task_id, conversation_id, agent_id, definition.record_id, encoded))
        return self.get(task_id)

    def edit(self, task_id, definition, expected_revision):
        encoded = json.dumps(definition.model_dump(), ensure_ascii=False, sort_keys=True)
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            old = connection.execute('SELECT definition FROM tracking_tasks WHERE id=? AND revision=?', (task_id, expected_revision)).fetchone()
            if old is None:
                raise ServiceError('配置已变化，请刷新后重新编辑。', 409)
            previous = json.loads(old[0])
            changed_target = any(previous.get(key) != definition.model_dump().get(key) for key in ('url','anchor','selector','mode','record_id','rules'))
            if changed_target:
                connection.execute("UPDATE tracking_tasks SET business_status='',last_checked_at=NULL WHERE id=?", (task_id,))
            cursor = connection.execute("UPDATE tracking_tasks SET definition=?,record_id=?,state='paused',revision=revision+1,lease_token=NULL,lease_until=NULL,next_check_at=NULL,last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=?",
                                        (encoded, definition.record_id, task_id, expected_revision))
            if cursor.rowcount != 1:
                raise ServiceError('配置已变化，请刷新后重新编辑。', 409)
        return self.get(task_id)

    def control(self, task_id, request):
        with self.database.connection() as connection:
            if request.action == 'read_notifications':
                cursor = connection.execute('UPDATE tracking_tasks SET unread=0 WHERE id=? AND revision=?', (task_id, request.expected_revision))
            else:
                state = {'resume':'active','pause':'paused','finish':'completed'}[request.action]
                cursor = connection.execute('UPDATE tracking_tasks SET state=?,next_check_at=?,revision=revision+1,lease_token=NULL,lease_until=NULL,last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=?',
                                            (state, time.time() if state == 'active' else None, task_id, request.expected_revision))
            if cursor.rowcount != 1:
                raise ServiceError('任务已变化，请刷新后再操作。', 409)
        return self.get(task_id)

    def claim(self, task_id=None, now=None):
        now = time.time() if now is None else now
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute("SELECT * FROM tracking_tasks WHERE ((? IS NOT NULL AND id=?) OR (? IS NULL AND state='active' AND next_check_at<=?)) AND (lease_until IS NULL OR lease_until<?) ORDER BY next_check_at LIMIT 1", (task_id, task_id, task_id, now, now)).fetchone()
            if row is None:
                if task_id:
                    raise ServiceError('任务正在检查，请稍后查看结果。', 409)
                return None
            token = uuid4().hex
            connection.execute('UPDATE tracking_tasks SET lease_token=?,lease_until=? WHERE id=?', (token, now + 90, row['id']))
            return {**self._decode(row), 'lease_token': token}

    def finish(self, task, status, outcome, evidence, error=None, blocked=False, terminal=False):
        now = time.time()
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM tracking_tasks WHERE id=? AND lease_token=? AND revision=?', (task['id'], task['lease_token'], task['revision'])).fetchone()
            if row is None:
                return False  # A pause, edit or newer lease won. Stale results cannot overwrite it.
            previous = row['business_status']
            current = status if outcome == 'matched' else previous
            changed = (current != previous or (error or '') != (row['last_error'] or ''))
            state = 'blocked' if blocked else 'completed' if terminal else row['state']
            next_at = now + task['definition']['interval_minutes'] * 60 if state == 'active' else None
            connection.execute('INSERT INTO tracking_checks(task_id,previous_status,status,outcome,evidence,error) VALUES (?,?,?,?,?,?)',
                               (task['id'], previous, current, outcome, json.dumps(evidence, ensure_ascii=False), error))
            connection.execute('UPDATE tracking_tasks SET business_status=?,state=?,next_check_at=?,last_checked_at=?,last_error=?,unread=unread+?,lease_token=NULL,lease_until=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                               (current, state, next_at, now, error, int(changed), task['id']))
            # Confirmation needs a real matched observation, never just a completed click.
            if task['record_id'] and outcome == 'matched':
                connection.execute("UPDATE execution_records SET state='confirmed',updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='needs_verification'", (task['record_id'],))
        return True
