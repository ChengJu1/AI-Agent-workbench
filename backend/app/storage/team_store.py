"""保存委派产生的子会话、负责人按需创建的临时 Agent，以及会话里已批准的团队计划。"""
import json
from uuid import uuid4


class TeamStore:
    def __init__(self, database):
        self.database = database

    def child_conversation(self, parent_id, member_id):
        with self.database.connection() as connection:
            row = connection.execute('SELECT child_conversation_id FROM conversation_delegations '
                                     'WHERE parent_conversation_id = ? AND member_agent_id = ?', (parent_id, member_id)).fetchone()
        return row['child_conversation_id'] if row else None

    def add_delegation(self, parent_id, member_id, child_id):
        with self.database.connection() as connection:
            connection.execute('INSERT INTO conversation_delegations(parent_conversation_id, member_agent_id, child_conversation_id) '
                               'VALUES (?, ?, ?)', (parent_id, member_id, child_id))

    def delegations(self, parent_id):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT member_agent_id, child_conversation_id, created_at FROM conversation_delegations '
                                      'WHERE parent_conversation_id = ? ORDER BY created_at, rowid', (parent_id,)).fetchall()
        return [dict(row) for row in rows]

    def parent(self, child_id):
        """子会话所属的主会话和负责人；不是子会话时返回 None。"""
        with self.database.connection() as connection:
            row = connection.execute(
                'SELECT delegations.parent_conversation_id, conversations.agent_id AS lead_agent_id '
                'FROM conversation_delegations AS delegations '
                'JOIN conversations ON conversations.id = delegations.parent_conversation_id '
                'WHERE delegations.child_conversation_id = ?', (child_id,)).fetchone()
        return dict(row) if row else None

    def create_temporary(self, parent_id, lead_id, name, instructions, capabilities):
        agent_id = f'temp_{uuid4().hex}'
        with self.database.connection() as connection:
            connection.execute('INSERT INTO temporary_agents(id, parent_conversation_id, lead_agent_id, name, instructions, capabilities) '
                               'VALUES (?, ?, ?, ?, ?, ?)', (agent_id, parent_id, lead_id, name, instructions, json.dumps(capabilities)))
        return agent_id

    def temporary(self, agent_id):
        with self.database.connection() as connection:
            row = connection.execute('SELECT * FROM temporary_agents WHERE id = ?', (agent_id,)).fetchone()
        return {**dict(row), 'capabilities': json.loads(row['capabilities'])} if row else None

    def plans(self, conversation_id):
        """会话里的团队计划，最早的在前。"""
        with self.database.connection() as connection:
            rows = connection.execute("SELECT status, result FROM pending_actions WHERE conversation_id = ? "
                                      "AND tool_name = 'workbench_team' ORDER BY created_at, rowid", (conversation_id,)).fetchall()
        return [{'status': row['status'], 'result': json.loads(row['result']) if row['result'] else None} for row in rows]
