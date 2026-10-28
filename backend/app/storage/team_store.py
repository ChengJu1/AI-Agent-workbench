"""保存负责人和成员的团队关系，以及委派产生的子会话。"""


class TeamStore:
    def __init__(self, database):
        self.database = database

    def members(self, lead_id):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT member_agent_id FROM agent_team_members WHERE lead_agent_id = ? ORDER BY position',
                                      (lead_id,)).fetchall()
        return [row['member_agent_id'] for row in rows]

    def set_members(self, lead_id, member_ids):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DELETE FROM agent_team_members WHERE lead_agent_id = ?', (lead_id,))
            connection.executemany('INSERT INTO agent_team_members(lead_agent_id, member_agent_id, position) VALUES (?, ?, ?)',
                                   [(lead_id, member_id, position) for position, member_id in enumerate(member_ids)])

    def mode(self, lead_id):
        with self.database.connection() as connection:
            row = connection.execute('SELECT mode FROM agent_team_settings WHERE lead_agent_id = ?', (lead_id,)).fetchone()
        return row['mode'] if row else 'delegate'

    def set_mode(self, lead_id, mode):
        with self.database.connection() as connection:
            connection.execute('INSERT INTO agent_team_settings(lead_agent_id, mode) VALUES (?, ?) '
                               'ON CONFLICT(lead_agent_id) DO UPDATE SET mode = excluded.mode', (lead_id, mode))

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
