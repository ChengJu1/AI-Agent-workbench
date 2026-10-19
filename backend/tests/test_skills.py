"""验证 Skill 的持久化、导入边界、版本并发、绑定原子性与实际 SDK 装配。"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import StreamEvent
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.models.skills import SkillDefinition


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

    def bind(self, ids, agent_id="policy_qa_assistant"):
        return self.client.put(f"/api/agents/{agent_id}/skills", json={"skill_ids": ids})

    def import_preview(self, content, filename="SKILL.md"):
        return self.client.post("/api/skills/import-preview", json={"filename": filename, "content": content})

    def create_agent(self, ids):
        return self.client.post("/api/agents", json={
            "name": "项目助理", "description": "处理项目文档", "system_prompt": "按规则整理用户提供的信息。", "skill_ids": ids,
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
        for ids, code in [([skill["id"], "missing"], 404), ([skill["id"]] * 2, 422), ([""], 422), ([str(i) for i in range(6)], 422)]:
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
        self.assertIn("CUSTOM-RULE", options.system_prompt)
        self.assertIn("需求拆解（v1）", options.system_prompt)
        self.assertNotIn("UNBOUND-RULE", options.system_prompt)
        self.assertEqual(options.tools, [])
        self.assertEqual(options.allowed_tools, [])
        self.assertEqual(options.mcp_servers, {})

    def test_oversize_binding_is_rejected_and_update_can_be_recovered_by_rebinding(self):
        items = [self.create_skill(name=f"规则 {i}", content="a" * 30000) for i in range(3)]
        self.assertEqual(self.bind([item["id"] for item in items]).status_code, 422)
        self.assertEqual(self.bind([item["id"] for item in items[:2]]).status_code, 200)
        self.assertEqual(self.bind([]).status_code, 200)
        items = [self.create_skill(name=f"短规则 {i}", content="a" * 26000) for i in range(3)]
        self.assertEqual(self.bind([item["id"] for item in items]).status_code, 200)
        self.assertEqual(self.update_skill(items[0], name=items[0]["name"], content="a" * 30000).status_code, 422)
        self.assertEqual(self.services.skills.get(items[0]["id"])["version"], 1)
        self.assertEqual(self.bind([items[0]["id"]]).status_code, 200)
        self.assertEqual(self.update_skill(items[0], name=items[0]["name"], content="a" * 30000).status_code, 200)

    def test_stream_uses_frozen_skill_version_and_history_keeps_it_after_updates(self):
        skill = self.create_skill(content="VERSION-ONE")
        agent_id = self.create_agent([skill["id"]]).json()["id"]
        conversation_id = self.services.store.create(agent_id)
        captured = []

        async def query(prompt, options):
            captured.append(options.system_prompt)
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
            self.assertEqual(events[0]["skills"][0]["version"], 1)
            self.assertIn("VERSION-ONE", captured[0])
            self.assertNotIn("VERSION-TWO", captured[0])
            response = self.client.post(f"/api/conversations/{conversation_id}/messages/stream", json={"content": "再检查一次"})
        self.assertIn('"version": 2', response.text)
        self.assertIn("VERSION-TWO", captured[1])
        history = self.client.get(f"/api/conversations/{conversation_id}/messages").json()
        self.assertEqual([message["skills"][0]["version"] for message in history if message["role"] == "assistant"], [1, 2])

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
        self.assertEqual(last["skills"][0]["version"], 1)
        self.assertEqual(last["status"], "failed")


if __name__ == "__main__":
    unittest.main()
