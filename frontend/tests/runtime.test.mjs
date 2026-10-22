import assert from "node:assert/strict";
import test from "node:test";
import { tokenLabel, toolActivityRows } from "../src/lib/runtime.ts";
import { finishMessage, restoreMessages } from "../src/lib/messages.ts";
import { consumeEventStream } from "../src/api/sse.ts";

test("未知 token 与真实的 0 分开显示", () => {
  assert.equal(tokenLabel(null), "未提供");
  assert.equal(tokenLabel(undefined), "未提供");
  assert.equal(tokenLabel(Number.NaN), "未提供");
  assert.equal(tokenLabel(0), "0");
  assert.equal(tokenLabel(1234), "1,234");
});

test("工具事件按调用配对，重复或延迟的开始事件不覆盖完成状态", () => {
  assert.deepEqual(toolActivityRows([
    { type: "tool_started", call_id: "a", tool_name: "read" },
    { type: "tool_finished", call_id: "a", tool_name: "read", success: false },
    { type: "tool_started", call_id: "a", tool_name: "read" },
    { type: "tool_finished", call_id: "b", tool_name: "list", success: true },
  ]), [{ id: "a", name: "read", status: "failed" }, { id: "b", name: "list", status: "success" }]);
});

test("没有回答正文时仍保留用量和工具失败，并能恢复历史", () => {
  const usage = { runtime: "deep_agents", input_tokens: null, output_tokens: 0 };
  const tool_activity = [{ type: "tool_finished", call_id: "a", tool_name: "read", success: false }];
  const result = finishMessage([{ id: "a", role: "assistant", content: "", usage, tool_activity }], "a", true);
  assert.equal(result[0].status, "failed");
  const restored = restoreMessages(result);
  assert.deepEqual(restored[0].usage, usage);
  assert.deepEqual(restored[0].tool_activity, tool_activity);
  assert.equal(restored[0].status, "failed");
  assert.equal(restoreMessages([{ role: "assistant", content: "原有回答" }])[0].usage, undefined);
});

test("工具状态与用量在错误事件之前交给页面，不会被错误丢弃", async () => {
  const usage = { runtime: "claude_sdk", input_tokens: null, output_tokens: 3, cache_read_input_tokens: null,
    cache_creation_input_tokens: null, model_calls: 1, tool_calls: 1, first_token_ms: null, duration_ms: 1,
    status: "failed", context_estimate: {} };
  const events = [{ type: "tool_started", call_id: "a", tool_name: "read" },
    { type: "tool_finished", call_id: "a", tool_name: "read", success: false },
    { type: "usage", usage }, { type: "error", content: "合成失败" }];
  const body = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join("")));
    controller.close();
  } });
  const observed = [];
  await assert.rejects(consumeEventStream(body, { onDelta() {}, onApprovalRequired() {},
    onToolActivity: event => observed.push(event.type), onUsage: () => observed.push("usage") }), /合成失败/);
  assert.deepEqual(observed, ["tool_started", "tool_finished", "usage"]);
});
