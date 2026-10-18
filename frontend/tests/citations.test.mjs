import assert from "node:assert/strict";
import test from "node:test";
import { citationReferences, parseKnowledgeEvidence } from "../src/lib/knowledgeCitations.ts";
import { applyKnowledgeEvidence, finishMessage, restoreMessages } from "../src/lib/messages.ts";
import { consumeEventStream, SseParser } from "../src/api/sse.ts";

const source = {
  citation_id: "S123456abcdef-1", knowledge_base_id: "base", knowledge_base_name: "团队制度",
  document_id: "doc", document_version: 1, chunk_id: 3, filename: "gpu.md", section: "申请条件",
  start_line: 4, end_line: 8, content: "两张 GPU 需要共同审批。",
};
const evidence = { status: "matched", citations: [source], queries: ["GPU"], failed_searches: 0 };
const frame = (event) => `data: ${JSON.stringify(event)}\n\n`;

test("引用只采用实际来源，未知编号与其他检索结果分别识别", () => {
  const extra = { ...source, citation_id: "S123456abcdef-2", chunk_id: 4 };
  const refs = citationReferences("规则 [1](#source-S123456abcdef-1)，错误 [99](#source-Sold-99)。", [source, extra]);
  assert.deepEqual(refs.used, [source]);
  assert.deepEqual(refs.unused, [extra]);
  assert.deepEqual(refs.unknown, ["Sold-99"]);
});

test("代码中的引用示例不被当作真实引用，Markdown 引用式链接仍能识别", () => {
  const content = "`[1](#source-S123456abcdef-1)`\n\n```md\n[1](#source-S123456abcdef-1)\n```";
  assert.deepEqual(citationReferences(content, [source]).used, []);
  const refs = citationReferences("规则 [依据][ref]\n\n[ref]: #source-S123456abcdef-1", [source]);
  assert.deepEqual(refs.used, [source]);
});

test("来源事件拒绝重复编号、伪造位置和不一致的检索状态", () => {
  assert.equal(parseKnowledgeEvidence(evidence), evidence);
  for (const value of [
    { ...evidence, citations: [source, source] },
    { ...evidence, citations: [{ ...source, end_line: 1 }] },
    { ...evidence, citations: [{ ...source, content: null }] },
    { ...evidence, status: "no_match" },
    { ...evidence, status: "matched", citations: [] },
  ]) assert.throws(() => parseKnowledgeEvidence(value), /来源|引用|状态/);
});

test("流式来源不混入回答文字，任意字符分块后能独立分发", async () => {
  const input = frame({ type: "knowledge", evidence });
  for (let index = 1; index < input.length; index += 1) {
    const parser = new SseParser();
    assert.deepEqual([...parser.push(input.slice(0, index)), ...parser.push(input.slice(index))], [{ type: "knowledge", evidence }]);
  }
  const snapshots = [];
  let text = "";
  const body = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode(input + frame({ type: "delta", content: "答案" }) + frame({ type: "done" })));
    controller.close();
  } });
  await consumeEventStream(body, { onKnowledge: (item) => snapshots.push(item), onDelta: (item) => { text += item; }, onApprovalRequired: () => {} });
  assert.deepEqual(snapshots, [evidence]);
  assert.equal(text, "答案");
});

test("来源只更新目标回答，刷新与中断时仍保留来源快照", () => {
  const other = { id: "other", role: "assistant", content: "旧回答" };
  const messages = [{ id: "current", role: "assistant", content: "", status: "streaming" }, other];
  const updated = applyKnowledgeEvidence(messages, "current", evidence);
  assert.equal(updated[1], other);
  const finished = finishMessage(updated, "current", true);
  assert.equal(finished[0].status, "failed");
  assert.deepEqual(finished[0].knowledge, evidence);
  const restored = restoreMessages(finished);
  assert.equal(restored[0].status, "failed");
  assert.deepEqual(restored[0].knowledge.citations[0], source);
});
