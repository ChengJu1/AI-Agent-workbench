"""保存前端创建的 Agent 配置，和会话使用同一个数据库。"""
from app.models.agents import LoadedAgent


class AgentStore:
    def __init__(self, database):
        self.database = database

    def create(self, agent):
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO custom_agents(id, definition) VALUES (?, ?)",
                (agent.id, agent.model_dump_json()),
            )

    def get(self, agent_id):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT definition FROM custom_agents WHERE id = ?", (agent_id,)
            ).fetchone()
        return LoadedAgent.model_validate_json(row["definition"]) if row else None

    def list_agents(self):
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT definition FROM custom_agents ORDER BY created_at, rowid"
            ).fetchall()
        return [LoadedAgent.model_validate_json(row["definition"]) for row in rows]
