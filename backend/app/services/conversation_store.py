import sqlite3
from pathlib import Path
from uuid import uuid4


class ConversationStore:
    def __init__(self):
        self._database_path = (
            Path(__file__)
            .resolve().parents[2]
            / "data"
            / "workbench.db"
        )
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _connect(self):
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_database(self):
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations(
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
                    );
                """
            )
            connection.commit()
        finally:
            connection.close()

    def create(self, agent_id):
        conversation_id = str(uuid4())
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO conversations(id, agent_id)
                VALUES(?, ?)
                """,
                (conversation_id, agent_id),
            )
            connection.commit()
        finally:
            connection.close()
        return conversation_id

    def exists(self, conversation_id):
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT 1 FROM conversations WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        finally:
            connection.close()
        return row is not None

    def get_agent_id(self, conversation_id):
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT agent_id
                FROM conversations
                WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError("没有这个对话记录")
        return row["agent_id"]

    def add_message(self, conversation_id, role, content):
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO messages(conversation_id, role, content)
                VALUES(?, ?, ?)
                """,
                (conversation_id, role, content),
            )
            connection.commit()
        finally:
            connection.close()

    def get_messages(self, conversation_id):
        connection = self._connect()
        try:
            messages = connection.execute(
                """
                SELECT role, content
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id ASC
                """,
                (conversation_id,),
            ).fetchall()
        finally:
            connection.close()
        return [
            {
                "role": row["role"],
                "content": row["content"],
            }
            for row in messages
        ]
