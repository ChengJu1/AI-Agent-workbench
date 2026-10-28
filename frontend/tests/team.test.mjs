import assert from "node:assert/strict";
import test from "node:test";
import { applyDelegation, moveMember, teamUsage, toggleMember } from "../src/lib/team.ts";
import { restoreMessages } from "../src/lib/messages.ts";
import { consumeEventStream } from "../src/api/sse.ts";

const usage = (input, output) => ({ input_tokens: input, output_tokens: output, cache_read_input_tokens: null, model_calls: 1, tool_calls: 0 });

test("委派开始新增卡片，结束时更新同一子会话最近的进行中卡片并保留任务摘要", () => {
  let list = applyDelegation([], { member_id: "m", member_name: "研究员", child_conversation_id: "c", status: "running", task: "第一项" });
  list = applyDelegation(list, { member_id: "m", member_name: "研究员", child_conversation_id: "c", status: "complete", usage: usage(5, 1) });
  list = applyDelegation(list, { member_id: "m", member_name: "研究员", child_conversation_id: "c", status: "running", task: "第二项" });
  list = applyDelegation(list, { member_id: "m", member_name: "研究员", child_conversation_id: "c", status: "needs_approval", usage: usage(7, 2) });
  assert.deepEqual(list.map(item => [item.task, item.status]), [["第一项", "complete"], ["第二项", "needs_approval"]]);
  // 刷新后只有保存下来的结束记录，没有开始事件。
  const restored = applyDelegation([], { member_id: "m", member_name: "研究员", child_conversation_id: "c", status: "failed" });
  assert.equal(restored[0].status, "failed");
});

test("全队用量 = 负责人 + 各成员；任何一方未提供时不按 0 计算", () => {
  const lead = { runtime: "deep_agents", input_tokens: 100, output_tokens: 10, cache_read_input_tokens: null, cache_creation_input_tokens: null,
    model_calls: 2, tool_calls: 1, first_token_ms: null, duration_ms: 1, status: "complete" };
  const message = { role: "assistant", content: "", usage: lead,
    delegations: [{ member_id: "m", member_name: "", child_conversation_id: "c", status: "complete", usage: usage(5, null) }] };
  const total = teamUsage(message);
  assert.equal(total.input_tokens, 105);
  assert.equal(total.output_tokens, null);
  assert.equal(total.model_calls, 3);
  assert.equal(teamUsage({ role: "assistant", content: "", usage: lead }), null);
});

test("成员最多 5 个，可以调整顺序", () => {
  let selected = [];
  for (const id of ["a", "b", "c", "d", "e", "f"]) selected = toggleMember(selected, id);
  assert.deepEqual(selected, ["a", "b", "c", "d", "e"]);
  assert.deepEqual(toggleMember(selected, "b"), ["a", "c", "d", "e"]);
  assert.deepEqual(moveMember(["a", "b", "c"], "c", -1), ["a", "c", "b"]);
  assert.deepEqual(moveMember(["a", "b", "c"], "a", -1), ["a", "b", "c"]);
});

test("流式委派事件被解析，历史消息保留委派记录和委派人", async () => {
  const lines = [
    { type: "delegation_started", member_id: "m", member_name: "研究员", child_conversation_id: "c", task: "查资料" },
    { type: "delegation_finished", member_id: "m", member_name: "研究员", child_conversation_id: "c", status: "complete", usage: usage(1, 1) },
    { type: "done" },
  ].map(event => `data: ${JSON.stringify(event)}\n\n`).join("");
  const body = new Response(lines).body;
  const seen = [];
  await consumeEventStream(body, { onDelta() {}, onApprovalRequired() {}, onDelegation: item => seen.push(item) });
  assert.deepEqual(seen.map(item => [item.status, item.task]), [["running", "查资料"], ["complete", undefined]]);
  const [lead, task] = restoreMessages([
    { role: "assistant", content: "汇总", delegations: [seen[1]] }, { role: "user", content: "查资料", delegated_by: "lead" }]);
  assert.equal(lead.delegations[0].child_conversation_id, "c");
  assert.equal(task.delegated_by, "lead");
});
