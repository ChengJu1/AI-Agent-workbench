import assert from "node:assert/strict";
import test from "node:test";
import { citationPreview } from "../src/lib/citationPreview.ts";
import { parseKnowledgeEvidence } from "../src/lib/knowledgeCitations.ts";

function fixture(text, snippet, at = text.indexOf(snippet)) {
  const before = text.slice(0, at);
  const source = { citation_id: "S123456abcdef-1", knowledge_base_id: "base", knowledge_base_name: "笔记",
    document_id: "doc", document_version: 1, chunk_id: null, source_kind: "notes_mcp", filename: "notes.md",
    section: "", content: snippet, start_offset: Array.from(before).length,
    end_offset: Array.from(before + snippet).length,
    start_line: before.split("\n").length, end_line: (before + snippet.slice(0, -1)).split("\n").length };
  const document = { document_id: "doc", version: 1, knowledge_base_id: "base", filename: "notes.md", content: text };
  return { source, document };
}

test("完整原文保留上下文和行号，只高亮实际来源区间中的重复内容", () => {
  const text = "# 标题\n重复片段\n\n第二次重复片段及解释\n后文。";
  const { source, document } = fixture(text, "重复片段", text.lastIndexOf("重复片段"));
  const preview = citationPreview(source, document);
  assert.equal(preview.fullDocument, true);
  assert.deepEqual(preview.lines.filter((line) => line.selected).map((line) => line.number), [4]);
  assert.equal(preview.lines[3].before, "第二次");
  assert.equal(preview.lines[3].highlighted, "重复片段");
  assert.equal(preview.lines[3].after, "及解释");
  assert.equal(preview.lines[1].highlighted, "");
});

test("Python 字符偏移包含 emoji 时仍然准确高亮多行切片", () => {
  const { source, document } = fixture("😀前文\n资料✅\n下一行内容\n结尾", "资料✅\n下一行");
  const preview = citationPreview(source, document);
  assert.equal(preview.fullDocument, true);
  assert.deepEqual(preview.lines.filter((line) => line.selected).map((line) => line.number), [2, 3]);
  assert.equal(preview.lines[1].highlighted, "资料✅");
  assert.equal(preview.lines[2].highlighted, "下一行");
  assert.equal(preview.lines[2].after, "内容");
  const knowledge = { status: "matched", citations: [source], queries: [], failed_searches: 0 };
  assert.equal(parseKnowledgeEvidence(knowledge), knowledge);
  assert.throws(() => parseKnowledgeEvidence({ ...knowledge, citations: [{ ...source, end_offset: 999 }] }));
});

test("版本不符、伪造偏移或内容不一致时只显示当轮片段，不误高亮其他原文", () => {
  const { source, document } = fixture("前文\n引用内容\n后文", "引用内容");
  for (const value of [null, { ...document, version: 2 }, { ...document, document_id: "another" },
    { ...document, content: "不同的正文" }]) {
    const preview = citationPreview(source, value);
    assert.equal(preview.fullDocument, false);
    assert.equal(preview.lines[0].number, 2);
    assert.equal(preview.lines[0].highlighted, "引用内容");
  }
  assert.equal(citationPreview({ ...source, start_offset: 0 }, document).fullDocument, false);
});

test("旧消息按标明行号精确定位，位置有歧义时保留片段预览", () => {
  const { source, document } = fixture("前文\n引用内容\n后文", "引用内容");
  const legacy = { ...source }; delete legacy.start_offset; delete legacy.end_offset;
  assert.equal(citationPreview(legacy, document).fullDocument, true);
  assert.equal(citationPreview({ ...legacy, start_line: 1 }, document).fullDocument, false);
  assert.equal(citationPreview({ ...legacy, content: "内容" }, { ...document, content: "前文\n内容内容\n后文" }).fullDocument, false);
});
