"""密钥初始化幂等、文件权限与已有 Agent 凭据同步范围。"""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from scripts.configure_notes_token import configure


class NotesTokenSetupTestCase(unittest.TestCase):
    def test_setup_preserves_secrets_and_only_updates_local_notes_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_path, database, token_path = root / ".env", root / "test.db", root / "token.txt"
            env_path.write_text("ANTHROPIC_API_KEY=existing-key\n", encoding="utf-8")
            tools = [{"type": "mcp", "transport": "http", "url": url, "actions": ["search_notes"], "headers": {"X-Keep": "yes"}}
                     for url in ("http://127.0.0.1:8059/mcp", "https://remote.example/mcp", "http://127.0.0.1:9999/mcp")]
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE custom_agents(id TEXT, definition TEXT)")
                connection.execute("INSERT INTO custom_agents VALUES (?, ?)", ("agent", json.dumps({"tools": tools})))
            self.assertEqual(configure(env_path, database, token_path, True), 1)
            token = token_path.read_text().strip()
            self.assertGreaterEqual(len(token), 32)
            self.assertEqual(dotenv_values(env_path)["ANTHROPIC_API_KEY"], "existing-key")
            self.assertEqual(os.stat(token_path).st_mode & 0o777, 0o600)
            configure(env_path, database, token_path, True)
            self.assertEqual(token_path.read_text().strip(), token)
            with sqlite3.connect(database) as connection:
                saved = json.loads(connection.execute("SELECT definition FROM custom_agents").fetchone()[0])["tools"]
            self.assertEqual(saved[0]["headers"], {"X-Keep": "yes", "Authorization": f"Bearer {token}"})
            self.assertEqual(saved[1:], tools[1:])
