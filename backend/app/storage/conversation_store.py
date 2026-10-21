"""查询和保存会话、消息；连接和事务统一由 Database 管理。"""
from uuid import uuid4
import json

from app.errors import ServiceError


class ConversationStore:
    def __init__(self, database):
        self.database = database

    def create(self, agent_id, runtime="claude_sdk"):
        conversation_id = str(uuid4())
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO conversations(id, agent_id, runtime) VALUES (?, ?, ?)",
                (conversation_id, agent_id, runtime),
            )
        return conversation_id

    def get_runtime(self, conversation_id):
        with self.database.connection() as connection:
            row = connection.execute('SELECT runtime FROM conversations WHERE id=?', (conversation_id,)).fetchone()
        if row is None:
            raise KeyError('没有这个对话记录')
        return row['runtime']

    def delete(self, conversation_id):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute("SELECT 1 FROM pending_actions WHERE conversation_id=? AND status='executing' LIMIT 1", (conversation_id,)).fetchone():
                raise ServiceError('当前会话有正在执行的确认操作，请完成后再删除。', 409)
            # Older tracking tables have restrictive foreign keys rather than cascades.
            for table in ('work_item_actions', 'work_item_events', 'work_item_attempts'):
                connection.execute(f'DELETE FROM {table} WHERE item_id IN (SELECT id FROM work_items WHERE conversation_id=?)',
                                   (conversation_id,))
            connection.execute('DELETE FROM work_item_actions WHERE action_id IN (SELECT id FROM pending_actions WHERE conversation_id=?)', (conversation_id,))
            connection.execute('DELETE FROM work_items WHERE conversation_id=?', (conversation_id,))
            connection.execute('DELETE FROM tracking_checks WHERE task_id IN (SELECT id FROM tracking_tasks WHERE conversation_id=?)', (conversation_id,))
            connection.execute('DELETE FROM tracking_tasks WHERE conversation_id=?', (conversation_id,))
            connection.execute('DELETE FROM execution_records WHERE conversation_id=?', (conversation_id,))
            connection.execute('DELETE FROM conversations WHERE id=?', (conversation_id,))

    def exists(self, conversation_id):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return row is not None

    def get_agent_id(self, conversation_id):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT agent_id FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        if row is None:
            raise KeyError("没有这个对话记录")
        return row["agent_id"]

    def has_assistant_messages(self, conversation_id):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM messages WHERE conversation_id = ? "
                "AND role = 'assistant' LIMIT 1",
                (conversation_id,),
            ).fetchone()
        return row is not None

    def add_message(self, conversation_id, role, content, knowledge=None, status=None, skills=None, skill_mode=None,
                    usage=None, tool_activity=None):
        metadata = {}
        if usage is not None:
            metadata['usage'] = usage
        if tool_activity is not None:
            metadata['tool_activity'] = tool_activity
        if knowledge is not None:
            metadata["knowledge"] = knowledge
        if status is not None:
            metadata["status"] = status
        if skills is not None:
            metadata["skills"] = skills
        if skill_mode is not None:
            metadata["skill_mode"] = skill_mode
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO messages(conversation_id, role, content, metadata) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, json.dumps(metadata, ensure_ascii=False)),
            )

    def get_messages(self, conversation_id):
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT role, content, metadata FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        messages = []
        for row in rows:
            message = {"role": row["role"], "content": row["content"]}
            metadata = json.loads(row["metadata"])
            for key in ("knowledge", "status", "skills", "skill_mode", "usage", "tool_activity"):
                if key in metadata:
                    message[key] = metadata[key]
            messages.append(message)
        return messages

    def list_conversations(self, agent_id):
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT conversations.id, conversations.agent_id, conversations.created_at, conversations.runtime,
                    (SELECT content FROM messages
                     WHERE conversation_id = conversations.id AND role = 'user'
                     ORDER BY id LIMIT 1) AS title
                FROM conversations
                WHERE agent_id = ?
                ORDER BY created_at DESC, conversations.rowid DESC
                """,
                (agent_id,),
            ).fetchall()
        conversations = []
        for row in rows:
            conversations.append(dict(row))
        return conversations
