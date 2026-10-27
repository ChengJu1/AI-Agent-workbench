import assert from "node:assert/strict";
import test from "node:test";
import { MAX_DOCUMENT_BYTES, milliseconds, rankingLabel, retrievalFeedback, validateKnowledgeFile } from "../src/lib/knowledge.ts";

test("上传入口接受支持的格式，并拒绝空文件、超限和不支持的格式", () => {
  for (const name of ["policy.md", "说明.TXT", "notes.markdown", "制度.PDF", "notes.docx"]) {
    assert.doesNotThrow(() => validateKnowledgeFile({ name, size: MAX_DOCUMENT_BYTES }));
  }
  assert.throws(() => validateKnowledgeFile({ name: "policy.md", size: 0 }), /内容为空/);
  assert.throws(() => validateKnowledgeFile({ name: "policy.md", size: MAX_DOCUMENT_BYTES + 1 }), /2 MB/);
  for (const name of ["sheet.xlsx", "old.doc", "script.md.exe", "no-extension"]) {
    assert.throws(() => validateKnowledgeFile({ name, size: 100 }), /支持 Markdown/);
  }
});

test("检索反馈区分候选、去重与返回数量，耗时明确包含去重", () => {
  const text = retrievalFeedback({candidate_count: 15, unique_count: 7, elapsed_ms: 12.345,
    deduplication_ms: 0.004, merge_limit_skipped: 0}, 5);
  assert.match(text, /候选 15 条 → 去重后 7 组 → 返回 5 组/);
  assert.match(text, /后端检索 12.3 ms（含去重 <0.1 ms）/);
  assert.equal(milliseconds(0), "<0.1 ms");
  assert.equal(milliseconds(1001.23), "1001.2 ms");
  assert.match(retrievalFeedback({candidate_count: 0, unique_count: 0, elapsed_ms: 0.2,
    deduplication_ms: 0.1, merge_limit_skipped: 0}, 0), /候选 0 条 → 去重后 0 组 → 返回 0 组/);
  assert.match(retrievalFeedback({candidate_count: 20, unique_count: 12, elapsed_ms: 300, deduplication_ms: 0.2,
    merge_limit_skipped: 0, vector_ms: 1.5, rerank_ms: 280, low_relevance: true, relevance_score: 0.0123}, 3), /向量 1.5 ms，重排序 280.0 ms · 相关度低（最高 0.012）/);
});

test("排序明细列出两路名次、分数和融合得分，未进入的一路显示 —", () => {
  assert.equal(rankingLabel({keyword_rank: null, keyword_score: null, vector_rank: 1, similarity: 0.8421,
    rrf_score: 0.016393, rerank_score: 0.91}), "关键词 — · 向量 #1（余弦 0.842） · RRF 0.0164 · 重排序 0.910");
  assert.equal(rankingLabel({keyword_rank: 2, keyword_score: 7.5, vector_rank: null, similarity: null, rrf_score: 0.016129}),
    "关键词 #2（7.50） · 向量 — · RRF 0.0161");
});
