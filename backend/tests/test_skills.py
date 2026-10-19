"""验证 Skill 的持久化、导入边界、版本并发、绑定原子性与实际 SDK 装配。"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import StreamEvent
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.models.skills import SkillDefinition
from app.services.skill_loads import SkillLoads
from app.services.skill_catalog import CATALOG_MAX_CHARS
from app.tools.skill_tools import ALLOWED_TOOL, SEARCH_TOOL, SERVER_NAME


class SkillsTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name) / "test.db")
        self.services = build_services(self.settings)
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)

    def definition(self, **updates):
        return {"name": "需求拆解", "description": "将需求整理为可验证任务", "content": "# 方法\n保留需求出处；缺少证据时标为待验证。", **updates}

    def create_skill(self, **updates):
        response = self.client.post("/api/skills", json=self.definition(**updates))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def update_skill(self, skill, **updates):
        return self.client.put(f"/api/skills/{skill['id']}", json={**self.definition(), "expected_version": skill["version"], **updates})

    def bind(self, ids, agent_id="policy_qa_assistant", versions=None):
        return self.client.put(f"/api/agents/{agent_id}/skills", json={"skill_ids": ids, "skill_versions": versions or {}})

    def import_preview(self, content, filename="SKILL.md"):
        return self.client.post("/api/skills/import-preview", json={"filename": filename, "content": content})

    def create_agent(self, ids, versions=None):
        return self.client.post("/api/agents", json={
            "name": "项目助理", "description": "处理项目文档", "system_prompt": "按规则整理用户提供的信息。", "skill_ids": ids,
            "skill_versions": versions or {},
        })

    def test_create_edit_restart_and_immutable_versions(self):
        skill = self.create_skill()
        self.assertEqual(skill["version"], 1)
        updated = self.update_skill(skill, content="# 新方法\n逐项说明验收条件。")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["version"], 2)
        versions = self.client.get(f"/api/skills/{skill['id']}/versions").json()
        self.assertEqual([item["version"] for item in versions], [2, 1])
        self.assertEqual(versions[1]["content"], skill["content"])
        fresh = build_services(self.settings)
        self.assertEqual(fresh.skills.get(skill["id"]), updated.json())
        self.assertEqual(fresh.skills.versions(skill["id"]), versions)

    def test_noop_duplicate_names_stale_updates_and_missing_ids(self):
        skill = self.create_skill()
        self.assertEqual(self.update_skill(skill).json()["version"], 1)
        self.assertEqual(len(self.services.skills.versions(skill["id"])), 1)
        self.assertEqual(self.client.post("/api/skills", json=self.definition()).status_code, 409)
        other = self.create_skill(name="其他规则")
        self.assertEqual(self.update_skill(other).status_code, 409)
        self.assertEqual(self.update_skill(skill, content="已更新").status_code, 200)
        self.assertEqual(self.update_skill(skill, content="过期编辑").status_code, 409)
        self.assertEqual(self.services.skills.get(skill["id"])["content"], "已更新")
        self.assertEqual(self.client.put("/api/skills/missing", json={**self.definition(), "expected_version": 1}).status_code, 404)
        self.assertEqual(self.client.get("/api/skills/missing/versions").status_code, 404)

    def test_definition_limits_and_no_arbitrary_fields(self):
        for update in [{"name": " "}, {"description": ""}, {"content": " "}, {"content": "a" * 30001},
                       {"tools": ["Bash"]}, {"id": "policy_qa_assistant"}]:
            self.assertEqual(self.client.post("/api/skills", json=self.definition(**update)).status_code, 422)
        self.assertEqual(self.client.get("/api/skills").json(), [])

    def test_import_frontmatter_unicode_multiline_and_no_automatic_save(self):
        text = '\ufeff---\r\nname: "项目检查"\r\ndescription: >\r\n  检查接口\r\n  并保留证据\r\nallowed-tools: [Bash]\r\n---\r\n\r\n# 规则\r\n```python\r\nprint("示例")\r\n```'
        response = self.import_preview(text)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "项目检查")
        self.assertIn("检查接口 并保留证据", response.json()["description"])
        self.assertEqual(response.json()["ignored_fields"], ["allowed-tools"])
        self.assertIn('print("示例")', response.json()["content"])
        self.assertEqual(self.services.skills.list(), [])

    def test_import_rejects_invalid_metadata_tags_aliases_binary_and_oversize(self):
        invalid = ["正文", "---\nname: x", "---\n- x\n---\n正文", "---\nname: x\n---\n正文",
                   "---\nname: x\ndescription: x\n---\n ",
                   "---\nname: !!python/object/apply:os.system ['echo bad']\ndescription: x\n---\n正文",
                   "---\nname: &x x\ndescription: *x\n---\n正文", "\x00",
                   "---\nname: " + "x" * 8200 + "\n---\n正文", "字" * 40000]
        for text in invalid:
            with self.subTest(text=text[:50]):
                self.assertEqual(self.import_preview(text).status_code, 422)
        self.assertEqual(self.import_preview("text", "skill.zip").status_code, 422)

    def test_skill_only_agent_and_builtin_bindings_persist_without_replacing_builtin_rules(self):
        skill = self.create_skill()
        response = self.create_agent([skill["id"]])
        self.assertEqual(response.status_code, 201, response.text)
        agent_id = response.json()["id"]
        self.assertEqual(self.bind([skill["id"]]).status_code, 200)
        fresh = build_services(self.settings)
        for target in (agent_id, "policy_qa_assistant"):
            agent = fresh.registry.get_agent(target)
            self.assertEqual(agent.bound_skills[0].id, skill["id"])
        self.assertTrue(fresh.registry.get_agent("policy_qa_assistant").skills)
        self.assertEqual(self.bind([]).json(), [])
        self.assertEqual(self.services.registry.get_agent(agent_id).bound_skills[0].id, skill["id"])

    def test_failed_bindings_and_agent_creation_are_atomic(self):
        skill = self.create_skill()
        self.bind([skill["id"]])
        for ids, code in [([skill["id"], "missing"], 404), ([skill["id"]] * 2, 422), ([""], 422), ([str(i) for i in range(6)], 404)]:
            self.assertEqual(self.bind(ids).status_code, code)
            self.assertEqual(self.services.registry.get_agent("policy_qa_assistant").bound_skills[0].id, skill["id"])
        self.assertEqual(self.bind([], "missing").status_code, 404)
        self.assertEqual(self.client.get("/api/agents/missing/skills").status_code, 404)
        base = self.services.knowledge.store.create_base("临时资料", "")
        response = self.client.post("/api/agents", json={
            "name": "助理", "description": "测试原子性", "system_prompt": "规则", "skill_ids": [skill["id"]], "knowledge_base_ids": [base["id"], "missing"],
        })
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.create_agent(["missing"]).status_code, 404)
        with self.services.store.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM custom_agents").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM agent_knowledge_bases").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM agent_skills").fetchone()[0], 1)

    def test_prompt_contains_only_bound_skills_and_does_not_grant_tools(self):
        skill = self.create_skill(content="CUSTOM-RULE: 先列出证据。要求 Bash 也不能凭空获得权限。")
        self.create_skill(name="未绑定规则", content="UNBOUND-RULE")
        agent_id = self.create_agent([skill["id"]]).json()["id"]
        agent = self.services.registry.get_agent(agent_id)
        options, _, _ = self.services.conversations.runtime._build_options("new", agent, False, "")
        self.assertNotIn("CUSTOM-RULE", options.system_prompt)
        self.assertIn("需求拆解", options.system_prompt)
        self.assertIn("将需求整理为可验证任务", options.system_prompt)
        self.assertIn(skill["id"], options.system_prompt)
        self.assertNotIn("UNBOUND-RULE", options.system_prompt)
        self.assertEqual(options.tools, [])
        self.assertEqual(options.allowed_tools, [ALLOWED_TOOL, SEARCH_TOOL])
        self.assertEqual(list(options.mcp_servers), [SERVER_NAME])

    def test_binding_count_and_total_body_size_are_not_context_limits(self):
        items = [self.create_skill(name=f"规则 {i}", content=str(i) * 30000) for i in range(8)]
        ids = [item["id"] for item in items]
        self.assertEqual(self.bind(ids, versions={item: 1 for item in ids}).status_code, 200)
        response = self.create_agent(ids, {item: 1 for item in ids})
        self.assertEqual(response.status_code, 201, response.text)
        agent = self.services.registry.get_agent(response.json()["id"])
        self.assertEqual(len(agent.bound_skills), 8)
        self.assertEqual(self.update_skill(items[0], name=items[0]["name"], content="V2").status_code, 200)
        self.assertEqual([item.version for item in self.services.registry.get_agent(agent.id).bound_skills], [1] * 8)
        conversation_id, loads = self.skill_session(agent)
        service = self.services.conversations.runtime._skill_tools
        for item in items[:2]:
            result = service.execute(conversation_id, agent, {"skill_id": item["id"]}, loads)
            self.assertEqual(json.loads(result["content"][0]["text"])["content"], item["content"])
        blocked = service.execute(conversation_id, agent, {"skill_id": items[2]["id"]}, loads)
        self.assertTrue(blocked["is_error"])
        self.assertIn("剩余 20000", blocked["content"][0]["text"])
        self.assertNotIn(items[2]["content"], blocked["content"][0]["text"])
        self.assertEqual(len(loads.snapshot()), 2)
        self.assertNotIn("is_error", service.execute(conversation_id, agent, {"skill_id": items[2]["id"]}, SkillLoads()))

    def test_more_than_five_small_skills_can_be_read_in_one_turn(self):
        items = [self.create_skill(name=f"小规则 {i}", content=f"步骤 {i}") for i in range(8)]
        agent_id = self.create_agent([item["id"] for item in items]).json()["id"]
        agent = self.services.registry.get_agent(agent_id)
        conversation_id, loads = self.skill_session(agent)
        service = self.services.conversations.runtime._skill_tools
        for item in items:
            self.assertNotIn("is_error", service.execute(conversation_id, agent, {"skill_id": item["id"]}, loads))
        self.assertEqual(len(loads.snapshot()), 8)

    def test_repeated_reads_consume_budget_and_failed_reads_do_not(self):
        first = self.create_skill(content="abc")
        second = self.create_skill(name="第二规则", content="de")
        agent_id = self.create_agent([first["id"], second["id"]]).json()["id"]
        agent = self.services.registry.get_agent(agent_id)
        conversation_id, _ = self.skill_session(agent)
        loads = SkillLoads(8)
        service = self.services.conversations.runtime._skill_tools
        for expected in (3, 6):
            result = service.execute(conversation_id, agent, {"skill_id": first["id"]}, loads)
            self.assertEqual(json.loads(result["content"][0]["text"])["budget"]["used_chars"], expected)
        self.assertTrue(service.execute(conversation_id, agent, {"skill_id": first["id"]}, loads)["is_error"])
        self.assertTrue(service.execute(conversation_id, agent, {"skill_id": "missing"}, loads)["is_error"])
        result = service.execute(conversation_id, agent, {"skill_id": second["id"]}, loads)
        self.assertEqual(json.loads(result["content"][0]["text"])["budget"]["remaining_chars"], 0)
        self.assertEqual(len(loads.snapshot()), 2)

    def test_concurrent_reads_cannot_exceed_shared_turn_budget(self):
        items = [self.create_skill(name=f"并行规则 {i}", content="abcdef") for i in range(2)]
        agent_id = self.create_agent([item["id"] for item in items]).json()["id"]
        agent = self.services.registry.get_agent(agent_id)
        conversation_id, _ = self.skill_session(agent)
        loads = SkillLoads(10)
        service = self.services.conversations.runtime._skill_tools
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda item: service.execute(conversation_id, agent, {"skill_id": item["id"]}, loads), items))
        self.assertEqual(sum("is_error" not in result for result in results), 1)
        self.assertEqual(len(loads.snapshot()), 1)

    def test_configured_budget_reaches_prepared_turn_and_runtime_fallback(self):
        skill = self.create_skill(content="abcdef")
        agent_id = self.create_agent([skill["id"]]).json()["id"]
        configured = build_services(Settings(database_path=self.settings.database_path, skill_read_budget_chars=5))
        conversation_id = configured.store.create(agent_id)
        prepared = configured.conversations.prepare(conversation_id, "读取规则")
        service = configured.conversations.runtime._skill_tools
        self.assertTrue(service.execute(conversation_id, prepared.agent, {"skill_id": skill["id"]}, prepared.skill_loads)["is_error"])
        options, _, _ = configured.conversations.runtime._build_options(conversation_id, prepared.agent, False, "")
        self.assertIn("5 字符", options.system_prompt)
        async def run():
            async with create_connected_server_and_client_session(options.mcp_servers[SERVER_NAME]["instance"]) as session:
                result = await session.call_tool("load_skill", {"skill_id": skill["id"]})
                self.assertTrue(result.isError)
        asyncio.run(run())
        for invalid in (0, -1, True):
            with self.assertRaises(ValueError):
                Settings(skill_read_budget_chars=invalid)
        with patch("app.config.load_dotenv"), patch.dict(os.environ, {"WORKBENCH_SKILL_READ_BUDGET_CHARS": "42"}):
            self.assertEqual(Settings.from_env().skill_read_budget_chars, 42)

    def test_large_catalog_is_searchable_in_bounded_pages_without_bodies_or_schema_enums(self):
        items = [self.create_skill(name=f"目录规则 {i:02}", description="目录关键词 " + "用途" * 480, content=f"PRIVATE-BODY-{i}") for i in range(24)]
        other = self.create_skill(name="未绑定目录", description="PRIVATE-UNBOUND-DESCRIPTION")
        agent_id = self.create_agent([item["id"] for item in items]).json()["id"]
        agent = self.services.registry.get_agent(agent_id)
        options, _, _ = self.services.conversations.runtime._build_options("new", agent, False, "")
        self.assertIn("目录较大", options.system_prompt)
        self.assertLess(len(options.system_prompt), CATALOG_MAX_CHARS)
        self.assertNotIn(items[0]["id"], options.system_prompt)
        self.update_skill(items[-1], name=items[-1]["name"], description="LATEST-UNSELECTED-DESCRIPTION", content="NEW-BODY")
        conversation_id, loads = self.skill_session(agent)
        service = self.services.conversations.runtime._skill_tools
        offset = 0
        found = []
        while offset is not None:
            result = service.search(conversation_id, agent, {"query": "目录关键词", "offset": offset, "limit": 20})
            text = result["content"][0]["text"]
            self.assertLessEqual(len(text), CATALOG_MAX_CHARS)
            self.assertNotIn("PRIVATE-BODY", text)
            self.assertNotIn(other["id"], text)
            self.assertNotIn("LATEST-UNSELECTED", text)
            page = json.loads(text)
            self.assertEqual(page["total_matches"], 24)
            self.assertTrue(page["matches"])
            found.extend(page["matches"])
            offset = page["next_offset"]
        self.assertEqual([item["skill_id"] for item in found], [item["id"] for item in items])
        self.assertTrue(all(item["version"] == 1 for item in found))
        self.assertEqual(loads.snapshot(), [])
        self.assertEqual(json.loads(service.search(conversation_id, agent, {"query": "不存在的关键词"})["content"][0]["text"])["matches"], [])

    def test_catalog_search_respects_revocation_version_switch_and_turn_snapshot(self):
        first = self.create_skill(description="SQL 用途 V1")
        other = self.create_skill(name="新绑定", description="PRIVATE-NEW-DESCRIPTION")
        agent_id = self.create_agent([first["id"]]).json()["id"]
        agent = self.services.registry.get_agent(agent_id)
        conversation_id, _ = self.skill_session(agent)
        service = self.services.conversations.runtime._skill_tools
        result = json.loads(service.search(conversation_id, agent, {"query": "sql"})["content"][0]["text"])
        self.assertEqual(result["matches"][0]["description"], "SQL 用途 V1")
        self.update_skill(first, description="PRIVATE-V2-DESCRIPTION")
        self.bind([first["id"], other["id"]], agent_id, {first["id"]: 2})
        result = json.loads(service.search(conversation_id, agent, {})["content"][0]["text"])
        self.assertEqual(result["matches"], [])
        self.bind([], agent_id)
        self.assertEqual(json.loads(service.search(conversation_id, agent, {})["content"][0]["text"])["matches"], [])
        for invalid in ({"limit": True}, {"offset": -1}, {"query": 42}, {"query": "a" * 201}, {"limit": 21}, {"agent_id": "other"}):
            self.assertTrue(service.search(conversation_id, agent, invalid)["is_error"])

    def test_stream_uses_frozen_skill_version_and_history_keeps_it_after_updates(self):
        skill = self.create_skill(content="VERSION-ONE")
        agent_id = self.create_agent([skill["id"]]).json()["id"]
        conversation_id = self.services.store.create(agent_id)
        captured = []
        loaded_contents = []

        async def query(prompt, options):
            captured.append(options.system_prompt)
            async with create_connected_server_and_client_session(options.mcp_servers[SERVER_NAME]["instance"]) as session:
                result = await session.call_tool("load_skill", {"skill_id": skill["id"]})
                self.assertFalse(result.isError)
                loaded_contents.append(json.loads(result.content[0].text)["content"])
            yield StreamEvent(uuid="event", session_id=conversation_id, event={
                "type": "content_block_delta", "delta": {"type": "text_delta", "text": "按 Skill 整理的结果"},
            })

        async def run_prepared():
            prepared = self.services.conversations.prepare(conversation_id, "请拆解需求")
            self.update_skill(skill, content="VERSION-TWO")
            return [event async for event in self.services.conversations.stream(conversation_id, "请拆解需求", prepared)]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch("app.services.claude_runtime.query", query):
            events = asyncio.run(run_prepared())
            self.assertEqual(events[0]["type"], "skills")
            self.assertEqual(events[0]["skills"], [])
            self.assertEqual([item for event in events if event["type"] == "skills" for item in event["skills"]][-1]["version"], 1)
            self.assertNotIn("VERSION-ONE", captured[0])
            self.assertNotIn("VERSION-TWO", captured[0])
            response = self.client.post(f"/api/conversations/{conversation_id}/messages/stream", json={"content": "再检查一次"})
            self.assertIn('"version": 1', response.text)
            self.bind([skill["id"]], agent_id, {skill["id"]: 2})
            response = self.client.post(f"/api/conversations/{conversation_id}/messages/stream", json={"content": "使用切换后的版本"})
        self.assertIn('"version": 2', response.text)
        self.assertNotIn("VERSION-TWO", captured[1])
        self.assertEqual(loaded_contents, ["VERSION-ONE", "VERSION-ONE", "VERSION-TWO"])
        history = self.client.get(f"/api/conversations/{conversation_id}/messages").json()
        self.assertEqual([message["skills"][0]["version"] for message in history if message["role"] == "assistant"], [1, 1, 2])

    def test_agents_pin_independent_versions_and_switch_both_directions_after_restart(self):
        skill = self.create_skill(content="V1")
        v2 = self.update_skill(skill, name="新名称", description="V2 用途", content="V2").json()
        first = self.create_agent([skill["id"]], {skill["id"]: 1}).json()["id"]
        second = self.create_agent([skill["id"]], {skill["id"]: 2}).json()["id"]
        self.assertEqual(self.update_skill(v2, content="V3").status_code, 200)
        fresh = build_services(self.settings)
        old = fresh.registry.get_agent(first).bound_skills[0]
        self.assertEqual((old.version, old.name, old.description, old.content), (1, skill["name"], skill["description"], "V1"))
        self.assertEqual(fresh.registry.get_agent(second).bound_skills[0].content, "V2")
        for version in (3, 2, 1):
            response = self.bind([skill["id"]], first, {skill["id"]: version})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()[0]["version"], version)
            self.assertEqual(build_services(self.settings).registry.get_agent(first).bound_skills[0].content, f"V{version}")
        self.assertEqual(self.services.registry.get_agent(second).bound_skills[0].version, 2)

    def test_invalid_or_missing_version_does_not_change_saved_binding_or_create_agent(self):
        skill = self.create_skill()
        self.bind([skill["id"]])
        for value in (0, -1, True, 1.5, "1", None):
            with self.subTest(version=value):
                response = self.bind([skill["id"]], versions={skill["id"]: value})
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.bind([skill["id"]], versions={"unselected": 1}).status_code, 422)
        self.assertEqual(self.bind([skill["id"]], versions={skill["id"]: 999}).status_code, 404)
        self.assertEqual(self.create_agent([skill["id"]], {skill["id"]: 999}).status_code, 404)
        self.assertEqual(self.services.registry.get_agent("policy_qa_assistant").bound_skills[0].version, 1)
        with self.services.store.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM custom_agents").fetchone()[0], 0)

    def test_old_database_bindings_pin_once_and_are_not_upgraded_on_subsequent_start(self):
        skill = self.create_skill(content="V1")
        v2 = self.update_skill(skill, content="V2").json()
        with self.services.store.database.connection() as connection:
            connection.execute("DROP TABLE agent_skills")
            connection.execute("CREATE TABLE agent_skills (agent_id TEXT NOT NULL, skill_id TEXT NOT NULL, ordinal INTEGER NOT NULL, PRIMARY KEY (agent_id, skill_id))")
            connection.execute("INSERT INTO agent_skills VALUES (?, ?, 0)", ("policy_qa_assistant", skill["id"]))
        fresh = build_services(self.settings)
        self.assertEqual(fresh.registry.get_agent("policy_qa_assistant").bound_skills[0].version, 2)
        self.update_skill(v2, content="V3")
        restarted = build_services(self.settings)
        self.assertEqual(restarted.registry.get_agent("policy_qa_assistant").bound_skills[0].version, 2)

    def test_switching_binding_mid_turn_rejects_old_snapshot_until_next_turn(self):
        skill = self.create_skill(content="V1")
        self.update_skill(skill, content="V2")
        agent_id = self.create_agent([skill["id"]], {skill["id"]: 1}).json()["id"]
        agent = self.services.registry.get_agent(agent_id)
        conversation_id, loads = self.skill_session(agent)
        service = self.services.conversations.runtime._skill_tools
        self.bind([skill["id"]], agent_id, {skill["id"]: 2})
        self.assertTrue(service.execute(conversation_id, agent, {"skill_id": skill["id"]}, loads)["is_error"])
        self.assertEqual(loads.snapshot(), [])
        fresh = self.services.registry.get_agent(agent_id)
        loaded = service.execute(conversation_id, fresh, {"skill_id": skill["id"]}, loads)
        self.assertEqual(json.loads(loaded["content"][0]["text"])["content"], "V2")
        self.assertEqual(loads.snapshot()[0]["version"], 2)

    def test_failure_and_early_close_keep_skill_record_and_release_conversation(self):
        skill = self.create_skill()
        agent_id = self.create_agent([skill["id"]]).json()["id"]
        conversation_id = self.services.store.create(agent_id)

        async def run():
            prepared = self.services.conversations.prepare(conversation_id, "测试中断")
            stream = self.services.conversations.stream(conversation_id, "测试中断", prepared)
            self.assertEqual((await anext(stream))["type"], "skills")
            await stream.aclose()
        asyncio.run(run())
        self.assertNotIn(conversation_id, self.services.conversations._active)
        last = self.services.store.get_messages(conversation_id)[-1]
        self.assertEqual(last["skills"], [])
        self.assertEqual(last["skill_mode"], "on_demand")
        self.assertEqual(last["status"], "failed")

    def skill_session(self, agent):
        return self.services.store.create(agent.id), SkillLoads()

    def test_protocol_search_returns_metadata_without_loading_and_reader_returns_full_body(self):
        skill = self.create_skill(content="# 完整步骤\n步骤一\n步骤二\nDETAIL-NOT-IN-CATALOG")
        agent_id = self.create_agent([skill["id"]]).json()["id"]
        agent = self.services.registry.get_agent(agent_id)
        conversation_id, loads = self.skill_session(agent)
        service = self.services.conversations.runtime._skill_tools
        server = service.create_server(conversation_id, agent, loads)

        async def run():
            async with create_connected_server_and_client_session(server["instance"]) as session:
                tools = (await session.list_tools()).tools
                self.assertEqual([tool.name for tool in tools], ["load_skill", "search_skills"])
                self.assertNotIn("enum", tools[0].inputSchema["properties"]["skill_id"])
                self.assertNotIn("DETAIL-NOT-IN-CATALOG", tools[0].description)
                found = await session.call_tool("search_skills", {"query": "需求"})
                self.assertFalse(found.isError)
                self.assertEqual(json.loads(found.content[0].text)["matches"][0]["skill_id"], skill["id"])
                self.assertNotIn("DETAIL-NOT-IN-CATALOG", found.content[0].text)
                self.assertEqual(loads.snapshot(), [])
                for _ in range(2):
                    result = await session.call_tool("load_skill", {"skill_id": skill["id"]})
                    self.assertFalse(result.isError)
                    self.assertEqual(json.loads(result.content[0].text)["content"], skill["content"])
        asyncio.run(run())
        self.assertEqual(loads.snapshot(), [{"id": skill["id"], "name": skill["name"], "version": 1}])
        logs = self.services.tool_store.get_audit_logs(conversation_id)
        self.assertEqual(len(logs), 3)
        self.assertTrue(all(log["tool_type"] == "skill" and log["status"] == "success" for log in logs))
        self.assertNotIn("DETAIL-NOT-IN-CATALOG", json.dumps(logs))

    def test_unbound_revoked_and_newly_bound_skills_cannot_leak_into_existing_turn(self):
        skill = self.create_skill()
        other = self.create_skill(name="其他规则", content="PRIVATE-UNBOUND-CONTENT")
        agent_id = self.create_agent([skill["id"]]).json()["id"]
        agent = self.services.registry.get_agent(agent_id)
        conversation_id, loads = self.skill_session(agent)
        service = self.services.conversations.runtime._skill_tools
        for args in [{}, {"skill_id": "../secret"}, {"skill_id": other["id"]},
                     {"skill_id": True}, {"skill_id": skill["id"], "agent_id": "other"}]:
            result = service.execute(conversation_id, agent, args, loads)
            self.assertTrue(result["is_error"])
            self.assertNotIn("PRIVATE-UNBOUND-CONTENT", json.dumps(result))
        self.bind([other["id"]], agent_id)
        for candidate in (skill, other):
            self.assertTrue(service.execute(conversation_id, agent, {"skill_id": candidate["id"]}, loads)["is_error"])
        self.assertEqual(loads.snapshot(), [])
        self.assertTrue(all(log["status"] == "failed" for log in self.services.tool_store.get_audit_logs(conversation_id)))

    def test_no_reader_call_means_no_body_or_loaded_record_even_if_model_claims_usage(self):
        skill = self.create_skill(content="RULE-SECRET")
        agent_id = self.create_agent([skill["id"]]).json()["id"]
        conversation_id = self.services.store.create(agent_id)

        async def query(prompt, options):
            self.assertNotIn("RULE-SECRET", options.system_prompt)
            yield StreamEvent(uuid="event", session_id=conversation_id, event={
                "type": "content_block_delta", "delta": {"type": "text_delta", "text": "你好，我声称用过 Skill。"},
            })
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch("app.services.claude_runtime.query", query):
            response = self.client.post(f"/api/conversations/{conversation_id}/messages/stream", json={"content": "你好"})
        self.assertIn('"type": "done"', response.text)
        history = self.client.get(f"/api/conversations/{conversation_id}/messages").json()
        self.assertEqual(history[-1]["skills"], [])
        self.assertEqual(history[-1]["skill_mode"], "on_demand")
        self.assertEqual(self.services.tool_store.get_audit_logs(conversation_id), [])

    def test_failure_after_read_preserves_only_actually_read_version(self):
        skill = self.create_skill()
        other = self.create_skill(name="不会读取", content="NOT-LOADED")
        agent_id = self.create_agent([skill["id"], other["id"]]).json()["id"]
        conversation_id = self.services.store.create(agent_id)

        async def query(prompt, options):
            async with create_connected_server_and_client_session(options.mcp_servers[SERVER_NAME]["instance"]) as session:
                self.assertFalse((await session.call_tool("load_skill", {"skill_id": skill["id"]})).isError)
            raise RuntimeError("private-provider-details")
            yield
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch("app.services.claude_runtime.query", query), \
                patch("app.services.conversation_service.logger.exception"):
            response = self.client.post(f"/api/conversations/{conversation_id}/messages/stream", json={"content": "请读取规则"})
        self.assertIn('"type": "error"', response.text)
        self.assertNotIn("private-provider-details", response.text)
        last = self.services.store.get_messages(conversation_id)[-1]
        self.assertEqual(last["skills"], [{"id": skill["id"], "name": skill["name"], "version": 1}])
        self.assertEqual(last["skill_mode"], "on_demand")
        self.assertEqual(last["status"], "failed")
        self.assertNotIn(conversation_id, self.services.conversations._active)

    def test_audit_failure_does_not_return_body_or_report_successful_load(self):
        skill = self.create_skill(content="PRIVATE-RULE")
        agent_id = self.create_agent([skill["id"]]).json()["id"]
        agent = self.services.registry.get_agent(agent_id)
        conversation_id, loads = self.skill_session(agent)
        service = self.services.conversations.runtime._skill_tools
        with patch.object(self.services.tool_store, "add_audit_log", side_effect=RuntimeError("private-db-details")), \
                patch("app.tools.skill_tools.logger.exception"):
            result = service.execute(conversation_id, agent, {"skill_id": skill["id"]}, loads)
        self.assertTrue(result["is_error"])
        self.assertNotIn("PRIVATE-RULE", json.dumps(result))
        self.assertNotIn("private-db-details", json.dumps(result))
        self.assertEqual(loads.snapshot(), [])

    def test_disconnect_after_tool_read_preserves_record_and_closes_sdk_stream(self):
        skill = self.create_skill()
        agent_id = self.create_agent([skill["id"]]).json()["id"]
        conversation_id = self.services.store.create(agent_id)
        closed = []

        async def query(prompt, options):
            try:
                async with create_connected_server_and_client_session(options.mcp_servers[SERVER_NAME]["instance"]) as session:
                    self.assertFalse((await session.call_tool("load_skill", {"skill_id": skill["id"]})).isError)
                yield StreamEvent(uuid="event", session_id=conversation_id, event={
                    "type": "content_block_delta", "delta": {"type": "text_delta", "text": "部分回复"},
                })
            finally:
                closed.append(True)

        async def run():
            prepared = self.services.conversations.prepare(conversation_id, "读取后取消")
            stream = self.services.conversations.stream(conversation_id, "读取后取消", prepared)
            self.assertEqual((await anext(stream))["skills"], [])
            self.assertEqual((await anext(stream))["skills"][0]["id"], skill["id"])
            await stream.aclose()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), patch("app.services.claude_runtime.query", query):
            asyncio.run(run())
        self.assertEqual(closed, [True])
        self.assertNotIn(conversation_id, self.services.conversations._active)
        last = self.services.store.get_messages(conversation_id)[-1]
        self.assertEqual(last["skills"][0]["id"], skill["id"])
        self.assertEqual(last["status"], "failed")

    def test_skill_tool_namespace_is_reserved(self):
        skill = self.create_skill()
        response = self.client.post("/api/agents", json={
            "name": "助理", "description": "命名冲突", "system_prompt": "规则", "skill_ids": [skill["id"]],
            "tools": [{"type": "mcp", "name": SERVER_NAME, "url": "http://localhost:8059/mcp", "actions": ["load_skill"]}],
        })
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
