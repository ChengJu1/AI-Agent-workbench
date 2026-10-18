"""显式初始化 SQLite，并统一处理连接、事务和旧数据库的兼容升级。"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            connection.executescript("BEGIN IMMEDIATE;\n" + schema)
            columns = connection.execute("PRAGMA table_info(tool_audit_logs)").fetchall()
            has_tool_type = False
            for column in columns:
                if column[1] == "tool_type":
                    has_tool_type = True
                    break
            if not has_tool_type:
                connection.execute(
                    "ALTER TABLE tool_audit_logs "
                    "ADD COLUMN tool_type TEXT NOT NULL DEFAULT 'cli'"
                )
            message_columns = connection.execute("PRAGMA table_info(messages)").fetchall()
            if not any(column[1] == "metadata" for column in message_columns):
                connection.execute("ALTER TABLE messages ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
            document_columns = {column[1] for column in connection.execute("PRAGMA table_info(knowledge_documents)")}
            if "indexing_version" not in document_columns:
                connection.execute("ALTER TABLE knowledge_documents ADD COLUMN indexing_version TEXT NOT NULL DEFAULT ''")
            if "chunking_strategy" not in document_columns:
                connection.execute("ALTER TABLE knowledge_documents ADD COLUMN chunking_strategy TEXT NOT NULL DEFAULT 'characters'")
            connection.execute(
                "INSERT OR IGNORE INTO knowledge_document_versions "
                "(document_id, version, knowledge_base_id, knowledge_base_name, filename, content) "
                "SELECT d.id, d.version, d.knowledge_base_id, b.name, d.filename, d.content "
                "FROM knowledge_documents d JOIN knowledge_bases b ON b.id = d.knowledge_base_id"
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def connection(self):
        # mode=rw 防止拼错路径时静默创建另一个空数据库。
        connection = sqlite3.connect(
            self.path.as_uri() + "?mode=rw", uri=True, timeout=10
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
