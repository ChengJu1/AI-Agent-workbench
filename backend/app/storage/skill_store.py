"""原子保存 Skill 版本与固定版本绑定；旧正文既可读取也可追溯。"""
import sqlite3
from uuid import uuid4

from app.errors import ServiceError


def replace_skill_bindings(connection, agent_id, skill_ids, skill_versions=None):
    versions = skill_versions or {}
    bindings = []
    for skill_id in skill_ids:
        version = versions.get(skill_id)
        # 旧调用方未传版本时，在保存绑定的事务内固定当时的最新版。
        row = connection.execute(
            "SELECT version FROM skill_versions WHERE id = ? AND version = "
            "COALESCE(?, (SELECT version FROM skills WHERE id = ?))", (skill_id, version, skill_id),
        ).fetchone()
        if row is None:
            raise ServiceError("所选 Skill 或版本不存在，请刷新后重新选择。", 404)
        bindings.append((agent_id, skill_id, len(bindings), row["version"]))
    connection.execute("DELETE FROM agent_skills WHERE agent_id = ?", (agent_id,))
    connection.executemany(
        "INSERT INTO agent_skills(agent_id, skill_id, ordinal, skill_version) VALUES (?, ?, ?, ?)", bindings,
    )


class SkillStore:
    def __init__(self, database):
        self.database = database

    def list(self):
        with self.database.connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM skills ORDER BY created_at DESC, rowid DESC")]

    def get(self, skill_id, version=None):
        with self.database.connection() as connection:
            if version is None:
                row = connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
            else:
                row = connection.execute("SELECT * FROM skill_versions WHERE id = ? AND version = ?", (skill_id, version)).fetchone()
        if row is None:
            raise ServiceError("Skill 或版本不存在。", 404)
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
                "SELECT s.* FROM skill_versions s JOIN agent_skills a "
                "ON a.skill_id = s.id AND a.skill_version = s.version "
                "WHERE a.agent_id = ? ORDER BY a.ordinal", (agent_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def is_bound(self, agent_id, skill_id, version=None):
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT 1 FROM agent_skills WHERE agent_id = ? AND skill_id = ? "
                "AND (? IS NULL OR skill_version = ?)", (agent_id, skill_id, version, version),
            ).fetchone() is not None

    def binding_versions(self, agent_id):
        with self.database.connection() as connection:
            return dict(connection.execute(
                "SELECT skill_id, skill_version FROM agent_skills WHERE agent_id = ?", (agent_id,),
            ).fetchall())

    def bind(self, agent_id, skill_ids, skill_versions=None):
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replace_skill_bindings(connection, agent_id, skill_ids, skill_versions)

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
                connection.execute(
                    "INSERT OR IGNORE INTO skill_versions SELECT * FROM skills WHERE id = ?", (skill_id,),
                )
                saved = dict(connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone())
        except sqlite3.IntegrityError as error:
            if "skills.name" in str(error):
                raise ServiceError("已存在同名 Skill，请使用其他名称或编辑已有 Skill。", 409) from error
            raise
        return saved
