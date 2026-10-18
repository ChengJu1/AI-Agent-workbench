"""验证真实 MCP 协议、Notes 读取范围、只读连接及原文分页。"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.memory import create_connected_server_and_client_session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.knowledge_service import KnowledgeService
from app.services.notes_reader import NotesReader
from app.storage.database import Database
from app.storage.knowledge_store import KnowledgeStore
from mcp_servers.notes_server import create_notes_server


class NotesMcpTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "notes.db"
        database = Database(self.path)
        database.initialize()
        store = KnowledgeStore(database)
        self.knowledge = KnowledgeService(store)
        self.base = store.create_base("笔记 · Python 基础", "学习笔记")
        self.hidden = store.create_base("演示知识库", "不开放")
        self.text = "# Python\n\n装饰器 decorator 使用闭包。\n第二行内容。"
        self.note = self.knowledge.ingest(self.base["id"], "python.md", self.text.encode())["document"]
        self.hidden_note = self.knowledge.ingest(self.hidden["id"], "private.md", b"hidden decorator")["document"]
        self.reader = NotesReader(self.path)
        self.server = create_notes_server(self.path)

    @staticmethod
    def value(result):
        return json.loads(result.content[0].text)

    async def test_protocol_lists_readonly_tools_and_reads_sources(self):
        async with create_connected_server_and_client_session(self.server._mcp_server) as session:
            tools = (await session.list_tools()).tools
            self.assertEqual({tool.name for tool in tools}, {
                "list_note_collections", "list_notes", "search_notes", "read_note",
            })
            self.assertTrue(all(tool.annotations.readOnlyHint for tool in tools))
            collections = self.value(await session.call_tool("list_note_collections", {}))["collections"]
            self.assertEqual([base["id"] for base in collections], [self.base["id"]])
            notes = self.value(await session.call_tool("list_notes", {"collection_id": self.base["id"]}))
            self.assertEqual(notes["items"][0]["id"], self.note["id"])
            found = self.value(await session.call_tool("search_notes", {"query": "decorator"}))
            match = found["collections"][0]["matches"][0]
            self.assertEqual(match["document_id"], self.note["id"])
            self.assertEqual(match["document_version"], 1)
            self.assertEqual(match["content"], self.text)
            self.assertEqual(match["start_line"], 1)
            read = self.value(await session.call_tool("read_note", {
                "collection_id": self.base["id"], "note_id": match["document_id"],
            }))
            self.assertEqual(read["content"], self.text)

    async def test_hidden_collections_and_cross_collection_reads_are_rejected(self):
        async with create_connected_server_and_client_session(self.server._mcp_server) as session:
            for name, arguments in [
                ("list_notes", {"collection_id": self.hidden["id"]}),
                ("search_notes", {"query": "decorator", "collection_id": self.hidden["id"]}),
                ("read_note", {"collection_id": self.base["id"], "note_id": self.hidden_note["id"]}),
                ("read_note", {"collection_id": self.hidden["id"], "note_id": self.hidden_note["id"]}),
            ]:
                self.assertTrue((await session.call_tool(name, arguments)).isError)

    def test_pagination_preserves_all_unicode_and_line_positions(self):
        parts = []
        offset = 0
        while True:
            page = self.reader.read_note(self.base["id"], self.note["id"], offset, 7)
            self.assertEqual(page["start_line"], self.text[:offset].count("\n") + 1)
            parts.append(page["content"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        self.assertEqual("".join(parts), self.text)
        self.assertEqual(self.reader.list_notes(self.base["id"], offset=1)["items"], [])

    def test_live_updates_deletes_and_explicit_scope(self):
        self.knowledge.ingest(self.base["id"], "python.md", b"replacementonly new note")
        self.assertEqual(self.reader.search_notes("decorator")["collections"][0]["matches"], [])
        matches = self.reader.search_notes("replacementonly")["collections"][0]["matches"]
        self.assertEqual(matches[0]["document_version"], 2)
        self.assertEqual(self.reader.read_note(self.base["id"], self.note["id"])["document_version"], 2)
        self.knowledge.delete_document(self.base["id"], self.note["id"])
        self.assertEqual(self.reader.search_notes("replacementonly")["collections"][0]["matches"], [])
        self.assertEqual(NotesReader(self.path, []).list_collections(), [])
        self.assertEqual(NotesReader(self.path, [self.hidden["id"]]).list_collections()[0]["id"], self.hidden["id"])

    def test_readonly_database_cannot_mutate_or_create_database(self):
        with self.reader.database.connection() as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM knowledge_documents")
        missing = self.path.with_name("missing.db")
        with self.assertRaises(sqlite3.OperationalError):
            NotesReader(missing).list_collections()
        self.assertFalse(missing.exists())

    async def test_invalid_parameters_and_database_errors_are_clear(self):
        async with create_connected_server_and_client_session(self.server._mcp_server) as session:
            for arguments in ({"query": " "}, {"query": "x", "limit": 11}, {"query": "x" * 201}):
                self.assertTrue((await session.call_tool("search_notes", arguments)).isError)
            self.assertTrue((await session.call_tool("read_note", {
                "collection_id": self.base["id"], "note_id": self.note["id"], "offset": -1,
            })).isError)
        server = create_notes_server(self.path.with_name("missing.db"))
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            result = await session.call_tool("list_note_collections", {})
            self.assertTrue(result.isError)
            self.assertIn("NOTES_DATABASE_PATH", result.content[0].text)
            self.assertNotIn(str(self.path.parent), result.content[0].text)

    async def test_streamable_http_initializes_and_calls_tool(self):
        with patch.dict(os.environ, {"NOTES_MCP_TOKEN": "test-notes-token-" + "x" * 32}):
            app = self.server.streamable_http_app()
        async with self.server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers={"Authorization": "Bearer test-notes-token-" + "x" * 32}) as client:
                async with streamable_http_client("http://localhost:8059/mcp", http_client=client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        result = await session.call_tool("search_notes", {"query": "装饰器"})
                        self.assertFalse(result.isError)
                        self.assertTrue(self.value(result)["collections"][0]["matches"])

    async def test_http_rejects_missing_wrong_and_duplicate_tokens(self):
        with patch.dict(os.environ, {"NOTES_MCP_TOKEN": "test-notes-token-" + "x" * 32}):
            app = self.server.streamable_http_app()
        async with self.server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                for method in ("GET", "POST", "DELETE"):
                    for headers in ({}, {"Authorization": "Bearer wrong"}, [("Authorization", "Bearer wrong"), ("Authorization", "Bearer test-notes-token-" + "x" * 32)]):
                        response = await client.request(method, "http://localhost:8059/mcp", headers=headers)
                        self.assertEqual(response.status_code, 401)
                        self.assertIn("Bearer", response.headers["www-authenticate"])
                        self.assertNotIn("test-notes-token", response.text)

    def test_http_fails_closed_without_configured_token(self):
        with patch.dict(os.environ, {"NOTES_MCP_TOKEN": ""}):
            with self.assertRaisesRegex(ValueError, "NOTES_MCP_TOKEN"):
                self.server.streamable_http_app()


if __name__ == "__main__":
    unittest.main()
