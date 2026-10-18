import assert from "node:assert/strict";
import test from "node:test";
import { agentDefinition, newMcpServer } from "../src/lib/agentDefinitions.ts";

function server() {
  return { ...newMcpServer(), name: "team", url: "http://localhost:8059/mcp", actions: ["search_policy"] };
}

test("未选工具、未配置服务或缺少提示词时不提交 Agent", () => {
  assert.throws(() => agentDefinition("我的助理", "查询制度", "使用工具", []), /至少选择/);
  assert.throws(() => agentDefinition("我的助理", "查询制度", "使用工具", [{ ...server(), actions: [] }]), /至少选择/);
  assert.throws(() => agentDefinition("我的助理", "查询制度", "  ", [server()]), /提示词/);
});

test("同名 MCP 服务不能覆盖彼此的配置", () => {
  assert.throws(() => agentDefinition("助理", "查询", "使用工具", [server(), { ...server(), name: " team " }]), /不同的名称/);
});

test("创建请求只开放所选工具，并按 MCP 请求头传递认证", () => {
  const draft = { ...server(), token: " test-token " };
  const definition = agentDefinition(" 我的助理 ", "查询", "使用工具", [draft]);
  assert.deepEqual(definition.tools, [{
    type: "mcp", name: "team", transport: "http", url: "http://localhost:8059/mcp",
    actions: ["search_policy"], headers: { Authorization: "Bearer test-token" },
  }]);
  assert.equal(definition.name, "我的助理");
  assert.equal(JSON.stringify(definition).includes(draft.id), false);
  definition.tools[0].actions.push("other_tool");
  assert.deepEqual(draft.actions, ["search_policy"]);
});

test("只选知识库也能创建 Agent，绑定列表独立保存", () => {
  const ids = ["base-a", "base-b"];
  const definition = agentDefinition("知识库助理", "查询资料", "先检索资料", [], ids);
  assert.deepEqual(definition.tools, []);
  assert.deepEqual(definition.knowledge_base_ids, ids);
  definition.knowledge_base_ids.pop();
  assert.deepEqual(ids, ["base-a", "base-b"]);
});

test("绑定知识库不能绕过未选工具的连接校验", () => {
  assert.throws(() => agentDefinition("助理", "查询", "检索", [{ ...server(), actions: [] }], ["base-a"]), /至少选择/);
  assert.throws(() => agentDefinition("助理", "查询", "检索", [], ["a", "a"]), /不能重复/);
  assert.throws(() => agentDefinition("助理", "查询", "检索", [], Array.from({ length: 11 }, (_, i) => String(i))), /最多/);
  assert.throws(() => agentDefinition("助理", "查询", "检索", [{ ...server(), name: "workbench_knowledge" }]), /保留/);
});
