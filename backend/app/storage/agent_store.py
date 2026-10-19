"""保存前端创建的 Agent 配置，和会话使用同一个数据库。"""
from app.models.agents import LoadedAgent
from app.errors import ServiceError
from app.storage.skill_store import replace_skill_bindings


class AgentStore:
    def __init__(self, database):
        self.database = database

    def create(self, agent):
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._replace_bindings(connection, agent.id, agent.knowledge_base_ids)
            replace_skill_bindings(connection, agent.id, [skill.id for skill in agent.bound_skills])
            connection.execute(
                "INSERT INTO custom_agents(id, definition) VALUES (?, ?)",
                (agent.id, agent.model_dump_json(exclude={"knowledge_base_ids", "bound_skills"})),
            )

    def get_knowledge_base_ids(self, agent_id):
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT knowledge_base_id FROM agent_knowledge_bases WHERE agent_id = ? ORDER BY rowid",
                (agent_id,),
            ).fetchall()
        return [row["knowledge_base_id"] for row in rows]

    def _replace_bindings(self, connection, agent_id, base_ids):
        for base_id in base_ids:
            if connection.execute("SELECT 1 FROM knowledge_bases WHERE id = ?", (base_id,)).fetchone() is None:
                raise ServiceError("所选知识库不存在，请刷新后重新选择。", 404)
        connection.execute("DELETE FROM agent_knowledge_bases WHERE agent_id = ?", (agent_id,))
        connection.executemany(
            "INSERT INTO agent_knowledge_bases(agent_id, knowledge_base_id) VALUES (?, ?)",
            [(agent_id, base_id) for base_id in base_ids],
        )

    def set_knowledge_base_ids(self, agent_id, base_ids):
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._replace_bindings(connection, agent_id, base_ids)

    def get(self, agent_id):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT definition FROM custom_agents WHERE id = ?", (agent_id,)
            ).fetchone()
        if row is None:
            return None
        agent = LoadedAgent.model_validate_json(row["definition"])
        return agent.model_copy(update={"knowledge_base_ids": self.get_knowledge_base_ids(agent_id)})

    def list_agents(self):
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT definition FROM custom_agents ORDER BY created_at, rowid"
            ).fetchall()
        agents = [LoadedAgent.model_validate_json(row["definition"]) for row in rows]
        return [agent.model_copy(update={"knowledge_base_ids": self.get_knowledge_base_ids(agent.id)})
                for agent in agents]
