"""持久化工具操作与审计；最终状态、审计和反馈消息在同一事务内保存。"""
import json
from uuid import uuid4


def decode_action(row):
    if row is None:
        return None
    action = dict(row)
    action["params"] = json.loads(action["params"])
    if action["result"] is not None:
        action["result"] = json.loads(action["result"])
    return action


class ToolStore:
    def __init__(self, database):
        self.database = database

    def create_pending_action(self, conversation_id, agent_id, tool_name, action, params):
        action_id = str(uuid4())
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO pending_actions "
                "(id, conversation_id, agent_id, tool_name, action, params) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (action_id, conversation_id, agent_id, tool_name, action,
                 json.dumps(params, ensure_ascii=False)),
            )
            self._insert_audit(
                connection, conversation_id, agent_id, tool_name, action, params,
                "pending", {"pending_action_id": action_id}, None, "cli",
            )
        return action_id

    def get_pending_action(self, action_id):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE id = ?", (action_id,)
            ).fetchone()
        return decode_action(row)

    def get_pending_actions(self, conversation_id):
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM pending_actions WHERE conversation_id = ? "
                "AND status = 'pending' ORDER BY created_at, rowid",
                (conversation_id,),
            ).fetchall()
        actions = []
        for row in rows:
            actions.append(decode_action(row))
        return actions

    def get_last_resolved_action(self, conversation_id):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE conversation_id = ? "
                "AND action = 'submit_timesheet' "
                "AND status IN ('approved', 'cancelled', 'failed') "
                "ORDER BY updated_at DESC, rowid DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
        return decode_action(row)

    def update_pending_action(self, action_id, status, result=None, expected_status="pending"):
        result_json = None
        if result is not None:
            result_json = json.dumps(result, ensure_ascii=False)
        with self.database.connection() as connection:
            cursor = connection.execute(
                "UPDATE pending_actions SET status = ?, result = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = ?",
                (status, result_json, action_id, expected_status),
            )
            return cursor.rowcount == 1

    def finish_action(self, action, status, message, result=None, error=None,
                      expected_status="executing"):
        result_json = None
        if result is not None:
            result_json = json.dumps(result, ensure_ascii=False)
        with self.database.connection() as connection:
            cursor = connection.execute(
                "UPDATE pending_actions SET status = ?, result = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = ?",
                (status, result_json, action["id"], expected_status),
            )
            if cursor.rowcount != 1:
                return False
            self._insert_audit(
                connection, action["conversation_id"], action["agent_id"],
                action["tool_name"], action["action"], action["params"],
                status, result, error, "cli",
            )
            connection.execute(
                "INSERT INTO messages(conversation_id, role, content) VALUES (?, ?, ?)",
                (action["conversation_id"], "assistant", message),
            )
        return True

    def _insert_audit(self, connection, conversation_id, agent_id, tool_name, action,
                      params, status, result, error, tool_type):
        result_json = None
        if result is not None:
            result_json = json.dumps(result, ensure_ascii=False)
        connection.execute(
            "INSERT INTO tool_audit_logs (conversation_id, agent_id, tool_type, "
            "tool_name, action, params, status, result, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (conversation_id, agent_id, tool_type, tool_name, action,
             json.dumps(params, ensure_ascii=False), status, result_json, error),
        )

    def add_audit_log(self, conversation_id, agent_id, tool_name, action, params,
                      status, result=None, error=None, tool_type="cli"):
        with self.database.connection() as connection:
            self._insert_audit(
                connection, conversation_id, agent_id, tool_name, action,
                params, status, result, error, tool_type,
            )

    def get_audit_logs(self, conversation_id):
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tool_audit_logs WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        logs = []
        for row in rows:
            log = dict(row)
            log["params"] = json.loads(log["params"])
            if log["result"] is not None:
                log["result"] = json.loads(log["result"])
            logs.append(log)
        return logs
