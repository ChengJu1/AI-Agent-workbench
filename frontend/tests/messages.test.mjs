// 验证流式消息按 ID 更新、失败清理和审批状态替换。
import assert from "node:assert/strict";
import test from "node:test";
import { appendMessageText, finishMessage, upsertAction } from "../src/lib/messages.ts";

test("流式文本更新目标 ID，不会误写最后一条消息", () => {
  const messages = [
    { id: "reply", role: "assistant", content: "你好" },
    { id: "other", role: "user", content: "别的消息" },
  ];
  const result = appendMessageText(messages, "reply", "世界");
  assert.equal(result[0].content, "你好世界");
  assert.equal(result[1], messages[1]);
  assert.equal(messages[0].content, "你好");
});

test("失败后只删除对应的空占位，不删除其他消息", () => {
  const messages = [
    { id: "empty", role: "assistant", content: "" },
    { id: "other", role: "assistant", content: "保留" },
  ];
  assert.deepEqual(finishMessage(messages, "empty", true), [messages[1]]);
});

test("已收到的部分回复保留并标记失败", () => {
  const result = finishMessage([{ id: "reply", role: "assistant", content: "部分内容" }], "reply", true);
  assert.equal(result[0].content, "部分内容");
  assert.equal(result[0].status, "failed");
});

test("审批成功替换原卡片，重复事件不会增加卡片", () => {
  const approved = { id: "action-1", status: "approved" };
  const result = upsertAction([{ id: "action-1", status: "pending" }], approved);
  assert.deepEqual(result, [approved]);
  assert.deepEqual(upsertAction(result, approved), [approved]);
});
