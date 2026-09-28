# 使用 SQLite 保存等待确认的工具操作和完整审计日志。
# 它记录工具参数、审批状态、执行结果和错误信息。
import json
import sqlite3
from pathlib import Path
from sqlite3 import connect
from uuid import uuid4


class ToolStore:
    def __init__(self):
        self._database_path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "workbench.db"
        )

        self._initialize_database()

    def _connect(self):
        connection = sqlite3.connect(
            self._database_path
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        return connection

    def _initialize_database(self):
        connection = self._connect()

        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_actions (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    params TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result TEXT,
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tool_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    tool_type TEXT NOT NULL DEFAULT 'cli',
                    tool_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    params TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
                );
                """
            )

            tool_audit_table = connection.execute("PRAGMA table_info(tool_audit_logs)")
            fetched_tool_audit_table = tool_audit_table.fetchall()

            found_tool_type = False

            for i in fetched_tool_audit_table:
                if i[1] == "tool_type":
                    found_tool_type = True
                    break
            if not found_tool_type:
                connection.executescript(
                    """
                    ALTER TABLE tool_audit_logs
                    ADD COLUMN tool_type TEXT NOT NULL DEFAULT 'cli'
                    """
                )

            connection.commit()
        finally:
            connection.close()

    def create_pending_action(
        self,
        conversation_id,
        agent_id,
        tool_name,
        action,
        params,
    ):
        pending_action_id = str(uuid4())

        params_json = json.dumps(
            params,
            ensure_ascii=False,
        )

        connection = self._connect()

        try:
            connection.execute(
                """
                INSERT INTO pending_actions (
                    id,
                    conversation_id,
                    agent_id,
                    tool_name,
                    action,
                    params
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    pending_action_id,
                    conversation_id,
                    agent_id,
                    tool_name,
                    action,
                    params_json,
                ),
            )

            connection.commit()
        finally:
            connection.close()

        return pending_action_id

    def get_pending_action(
        self,
        pending_action_id,
    ):
        connection = self._connect()

        try:
            row = connection.execute(
                """
                SELECT
                    id,
                    conversation_id,
                    agent_id,
                    tool_name,
                    action,
                    params,
                    status,
                    result,
                    created_at,
                    updated_at
                FROM pending_actions
                WHERE id = ?
                """,
                (pending_action_id,),
            ).fetchone()
        finally:
            connection.close()

        if row is None:
            return None

        pending_action = {
            "id": row["id"],
            "conversation_id": row[
                "conversation_id"
            ],
            "agent_id": row["agent_id"],
            "tool_name": row["tool_name"],
            "action": row["action"],
            "params": json.loads(row["params"]),
            "status": row["status"],
            "result": None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

        if row["result"] is not None:
            pending_action["result"] = json.loads(
                row["result"]
            )

        return pending_action

    def get_last_resolved_action(self, conversation_id):
        connection = self._connect()
        try:
            last_pending_action = connection.execute(
                """
            SELECT
                id,
                conversation_id,
                agent_id,
                tool_name,
                action,
                status,
                result,
                updated_at
            FROM pending_actions
            WHERE conversation_id = ?
              AND status IN ('approved', 'cancelled', 'failed')
            ORDER BY updated_at DESC, rowid DESC
            LIMIT 1
                """,(conversation_id,)

            ).fetchone()
        finally:
            connection.close()
        if not last_pending_action:
            return None
        last_action = {
            "id": last_pending_action["id"],
            "conversation_id": last_pending_action[
                "conversation_id"
            ],
            "agent_id": last_pending_action["agent_id"],
            "tool_name": last_pending_action["tool_name"],
            "action": last_pending_action["action"],
            "status": last_pending_action["status"],
            "result": None,
            "updated_at": last_pending_action["updated_at"],
        }

        if last_pending_action["result"] is not None:
            last_action["result"] = json.loads(
                last_pending_action["result"]
            )

        return last_action

    def update_pending_action(
        self,
        pending_action_id,
        status,
        result=None,
        expected_status="pending",
    ):
        result_json = None

        if result is not None:
            result_json = json.dumps(
                result,
                ensure_ascii=False,
            )

        connection = self._connect()

        try:
            cursor = connection.execute(
                """
                UPDATE pending_actions
                SET
                    status = ?,
                    result = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND status = ?
                """,
                (
                    status,
                    result_json,
                    pending_action_id,
                    expected_status,
                ),
            )

            connection.commit()
        finally:
            connection.close()

        return cursor.rowcount == 1

    def get_pending_actions(self, conversation_id):
        connection = self._connect()

        try:
            rows = connection.execute(
                """
                SELECT
                    id,
                    conversation_id,
                    agent_id,
                    tool_name,
                    action,
                    params,
                    status,
                    result,
                    created_at,
                    updated_at
                FROM pending_actions
                WHERE conversation_id = ?
                  AND status = 'pending'
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            ).fetchall()
        finally:
            connection.close()

        pending_actions = []

        for row in rows:
            pending_action = {
                "id": row["id"],
                "conversation_id": row[
                    "conversation_id"
                ],
                "agent_id": row["agent_id"],
                "tool_name": row["tool_name"],
                "action": row["action"],
                "params": json.loads(row["params"]),
                "status": row["status"],
                "result": None,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

            if row["result"] is not None:
                pending_action["result"] = json.loads(
                    row["result"]
                )

            pending_actions.append(pending_action)

        return pending_actions

    def add_audit_log(
        self,
        conversation_id,
        agent_id,
        tool_name,
        action,
        params,
        status,
        result=None,
        error=None,
        tool_type='cli',
    ):
        params_json = json.dumps(
            params,
            ensure_ascii=False,
        )

        result_json = None

        if result is not None:
            result_json = json.dumps(
                result,
                ensure_ascii=False,
            )

        connection = self._connect()

        try:
            connection.execute(
                """
                INSERT INTO tool_audit_logs (
                    conversation_id,
                    agent_id,
                    tool_type,
                    tool_name,
                    action,
                    params,
                    status,
                    result,
                    error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    agent_id,
                    tool_type,
                    tool_name,
                    action,
                    params_json,
                    status,
                    result_json,
                    error,
                ),
            )

            connection.commit()
        finally:
            connection.close()

    def get_audit_logs(self, conversation_id):
        connection = self._connect()

        try:
            rows = connection.execute(
                """
                SELECT
                    id,
                    conversation_id,
                    agent_id,
                    tool_type,
                    tool_name,
                    action,
                    params,
                    status,
                    result,
                    error,
                    created_at
                FROM tool_audit_logs
                WHERE conversation_id = ?
                ORDER BY id ASC
                """,
                (conversation_id,),
            ).fetchall()
        finally:
            connection.close()

        audit_logs = []

        for row in rows:
            audit_log = {
                "id": row["id"],
                "conversation_id": row[
                    "conversation_id"
                ],
                "agent_id": row["agent_id"],
                "tool_type": row["tool_type"],
                "tool_name": row["tool_name"],
                "action": row["action"],
                "params": json.loads(row["params"]),
                "status": row["status"],
                "result": None,
                "error": row["error"],
                "created_at": row["created_at"],
            }

            if row["result"] is not None:
                audit_log["result"] = json.loads(
                    row["result"]
                )

            audit_logs.append(audit_log)

        return audit_logs
