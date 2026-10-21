"""显式初始化 SQLite，并统一处理连接、事务和旧数据库的兼容升级。"""
import sqlite3
import hashlib
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
            skill_columns = {column[1] for column in connection.execute("PRAGMA table_info(agent_skills)")}
            if "skill_version" not in skill_columns:
                connection.execute("ALTER TABLE agent_skills ADD COLUMN skill_version INTEGER")
                # 升级时固定旧绑定正在使用的版本；之后保存新正文不改变绑定。
                connection.execute(
                    "UPDATE agent_skills SET skill_version = "
                    "(SELECT version FROM skills WHERE skills.id = agent_skills.skill_id)"
                )
            file_columns = {column[1] for column in connection.execute("PRAGMA table_info(conversation_files)")}
            for field, declaration in [('version', 'INTEGER NOT NULL DEFAULT 1'), ('source_path', 'TEXT'), ('content_hash', "TEXT NOT NULL DEFAULT ''")]:
                if field not in file_columns:
                    connection.execute(f'ALTER TABLE conversation_files ADD COLUMN {field} {declaration}')
            for row in connection.execute("SELECT id,version,data FROM conversation_files WHERE content_hash='' ").fetchall():
                connection.execute('UPDATE conversation_files SET content_hash=? WHERE id=?', (hashlib.sha256(row[2]).hexdigest(), row[0]))
            # The task-execution capability was replaced by the read-only application ledger.
            connection.execute('''UPDATE agent_platform_capabilities SET capabilities=REPLACE(capabilities,'"tasks"','"applications"') WHERE capabilities LIKE '%"tasks"%' ''')
            connection.execute('INSERT OR IGNORE INTO conversation_file_versions(id,version,conversation_id,filename,byte_size,content,data,content_hash) SELECT id,version,conversation_id,filename,byte_size,content,data,content_hash FROM conversation_files')
            connection.execute(
                "INSERT OR IGNORE INTO knowledge_document_versions "
                "(document_id, version, knowledge_base_id, knowledge_base_name, filename, content) "
                "SELECT d.id, d.version, d.knowledge_base_id, b.name, d.filename, d.content "
                "FROM knowledge_documents d JOIN knowledge_bases b ON b.id = d.knowledge_base_id"
            )
            connection.execute("INSERT OR IGNORE INTO execution_records(id,action_id,conversation_id,agent_id,title,target_url,state,result,created_at,updated_at) SELECT 'run_'||id,id,conversation_id,agent_id,action,'',CASE WHEN status='pending' THEN 'pending' WHEN status='cancelled' THEN 'cancelled' WHEN action='browser_actions' OR status='executing' THEN 'needs_verification' WHEN status='approved' THEN 'confirmed' ELSE 'failed' END,result,created_at,updated_at FROM pending_actions")
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
