// 覆盖真实网络分块、UTF-8、结束事件和断流错误；不需要浏览器或模型密钥。
import assert from "node:assert/strict";
import test from "node:test";
import { SseParser, consumeEventStream } from "../src/api/sse.ts";

const frame = (event) => `data: ${JSON.stringify(event)}\n\n`;

function streamFrom(chunks) {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

test("SSE 事件可以在任意字符边界分块", () => {
  const input = frame({ type: "delta", content: "中文回复" });
  for (let index = 1; index < input.length; index += 1) {
    const parser = new SseParser();
    const result = [...parser.push(input.slice(0, index)), ...parser.push(input.slice(index))];
    assert.deepEqual(result, [{ type: "delta", content: "中文回复" }]);
  }
});

test("支持 CRLF、多行 data 和无冒号空格", () => {
  const parser = new SseParser();
  const result = parser.push('data:{"type":"delta",\r\ndata: "content":"你好"}\r\n\r\n');
  assert.deepEqual(result, [{ type: "delta", content: "你好" }]);
});

test("心跳注释和未知事件不会污染文本", () => {
  const parser = new SseParser();
  assert.deepEqual(parser.push(': ping\n\ndata: {"type":"future-event"}\n\n'), []);
});

test("无效 JSON 和缺失文本被明确拒绝", () => {
  assert.throws(() => new SseParser().push("data: invalid\n\n"), /无法解析/);
  assert.throws(() => new SseParser().push(frame({ type: "delta" })), /缺少文本/);
});

test("UTF-8 中文按单字节到达也能正常还原", async () => {
  const input = new TextEncoder().encode(
    frame({ type: "delta", content: "工时已提交✅" }) + frame({ type: "done" }),
  );
  const chunks = [];
  for (const byte of input) chunks.push(new Uint8Array([byte]));
  let text = "";
  await consumeEventStream(streamFrom(chunks), {
    onDelta: (chunk) => { text += chunk; }, onApprovalRequired: () => {},
  });
  assert.equal(text, "工时已提交✅");
});

test("审批事件独立分发", async () => {
  const events = frame({ type: "approval_required", action: { id: "action-1" } })
    + frame({ type: "done" });
  const actions = [];
  await consumeEventStream(streamFrom([new TextEncoder().encode(events)]), {
    onDelta: () => assert.fail("不应产生文本"),
    onApprovalRequired: (action) => actions.push(action.id),
  });
  assert.deepEqual(actions, ["action-1"]);
});

test("没有 done 的断流不能被当作成功", async () => {
  let text = "";
  await assert.rejects(consumeEventStream(streamFrom([
    new TextEncoder().encode(frame({ type: "delta", content: "部分内容" })),
  ]), {
    onDelta: (chunk) => { text += chunk; }, onApprovalRequired: () => {},
  }), /意外中断/);
  assert.equal(text, "部分内容");
});

test("后端错误事件中断读取并保留此前文本", async () => {
  let text = "";
  const events = frame({ type: "delta", content: "部分内容" })
    + frame({ type: "error", content: "服务不可用" });
  await assert.rejects(consumeEventStream(streamFrom([new TextEncoder().encode(events)]), {
    onDelta: (chunk) => { text += chunk; }, onApprovalRequired: () => {},
  }), /服务不可用/);
  assert.equal(text, "部分内容");
});

test("收到 done 后会关闭持续打开的读取器", async () => {
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) { controller.enqueue(new TextEncoder().encode(frame({ type: "done" }))); },
    cancel() { cancelled = true; },
  });
  await consumeEventStream(stream, { onDelta: () => {}, onApprovalRequired: () => {} });
  assert.equal(cancelled, true);
  assert.equal(stream.locked, false);
});
