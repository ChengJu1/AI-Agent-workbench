"""原子保存 Skill 版本，绑定顺序固定；旧版本供历史回答追溯。"""
import sqlite3
from uuid import uuid4

from app.errors import ServiceError


def replace_skill_bindings(connection, agent_id, skill_ids):
    total = 0
    for skill_id in skill_ids:
        row = connection.execute("SELECT length(content) FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if row is None:
            raise ServiceError("所选 Skill 不存在，请刷新后重新选择。", 404)
        total += row[0]
    if total > 80000:
        raise ServiceError("绑定的 Skill 正文合计不能超过 80000 字符，请减少选择。", 422)
    connection.execute("DELETE FROM agent_skills WHERE agent_id = ?", (agent_id,))
    connection.executemany(
        "INSERT INTO agent_skills(agent_id, skill_id, ordinal) VALUES (?, ?, ?)",
        [(agent_id, skill_id, index) for index, skill_id in enumerate(skill_ids)],
    )


class SkillStore:
    def __init__(self, database):
        self.database = database

    def list(self):
        with self.database.connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM skills ORDER BY created_at DESC, rowid DESC")]

    def get(self, skill_id):
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if row is None:
            raise ServiceError("Skill 不存在。", 404)
        return dict(row)

    def versions(self, skill_id):
        self.get(skill_id)
        with self.database.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM skill_versions WHERE id = ? ORDER BY version DESC", (skill_id,)
            )]

    def get_for_agent(self, agent_id):
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT s.* FROM skills s JOIN agent_skills a ON a.skill_id = s.id "
                "WHERE a.agent_id = ? ORDER BY a.ordinal", (agent_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def is_bound(self, agent_id, skill_id):
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT 1 FROM agent_skills WHERE agent_id = ? AND skill_id = ?", (agent_id, skill_id),
            ).fetchone() is not None

    def bind(self, agent_id, skill_ids):
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replace_skill_bindings(connection, agent_id, skill_ids)

    def save(self, definition, skill_id=None, expected_version=None):
        values = (definition.name, definition.description, definition.content)
        try:
            with self.database.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if skill_id is None:
                    skill_id = f"skill_{uuid4().hex}"
                    connection.execute(
                        "INSERT INTO skills(id, name, description, content) VALUES (?, ?, ?, ?)", (skill_id, *values),
                    )
                else:
                    row = connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
                    if row is None:
                        raise ServiceError("Skill 不存在。", 404)
                    if row["version"] != expected_version:
                        raise ServiceError("Skill 已被更新，请重新打开最新版本后再编辑。", 409)
                    if values != (row["name"], row["description"], row["content"]):
                        connection.execute(
                            "UPDATE skills SET name = ?, description = ?, content = ?, version = version + 1, "
                            "updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?", (*values, skill_id),
                        )
                        too_large = connection.execute(
                            "SELECT a.agent_id FROM agent_skills a JOIN skills s ON s.id = a.skill_id "
                            "GROUP BY a.agent_id HAVING SUM(length(s.content)) > 80000 LIMIT 1"
                        ).fetchone()
                        if too_large:
                            raise ServiceError("此修改会使已绑定 Agent 的 Skill 总长超过 80000 字符，请先减少绑定。", 422)
                connection.execute(
                    "INSERT OR IGNORE INTO skill_versions SELECT * FROM skills WHERE id = ?", (skill_id,),
                )
                saved = dict(connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone())
        except sqlite3.IntegrityError as error:
            if "skills.name" in str(error):
                raise ServiceError("已存在同名 Skill，请使用其他名称或编辑已有 Skill。", 409) from error
            raise
        return saved
