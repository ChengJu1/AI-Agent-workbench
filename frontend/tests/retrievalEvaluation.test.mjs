import assert from "node:assert/strict";
import test from "node:test";
import { parseRetrievalSuite, percentage } from "../src/lib/retrievalEvaluation.ts";

const positive = { id: "p1", query: "GPU", expected_filename: "gpu.md", expected_texts: ["审批"] };
const encode = (update) => JSON.stringify({ name: "团队题集", cases: [positive], ...update });

test("导入题集保留同义词挑战和空结果题，不能自动删去困难题", () => {
  const suite = parseRetrievalSuite(encode({ cases: [
    { ...positive, id: "gpu-synonym", query: "显卡", category: "paraphrase" },
    { id: "negative", query: "missingxyz", category: "negative", expect_no_match: true },
  ] }));
  assert.equal(suite.cases.length, 2);
  assert.equal(suite.cases[0].query, "显卡");
  assert.equal(suite.cases[0].category, "paraphrase");
  assert.equal(suite.cases[1].expect_no_match, true);
});

test("自定义题集补充默认值并保留正例和空结果题的含义", () => {
  const suite = parseRetrievalSuite(encode({ cases: [positive, { id: "n1", query: "unknownxyz", expect_no_match: true }] }));
  assert.equal(suite.limit, 5);
  assert.equal(suite.cases[0].category, "keyword");
  assert.equal(suite.cases[0].expect_no_match, false);
  assert.equal(suite.cases[1].expected_filename, null);
  assert.deepEqual(suite.cases[1].expected_texts, []);
});

test("拒绝无效 JSON、重复 ID、超限、歧义预期和未知字段", () => {
  assert.throws(() => parseRetrievalSuite("broken"), /JSON/);
  for (const update of [
    { cases: [] }, { cases: [positive, positive] }, { limit: true }, { limit: 21 },
    { cases: Array.from({ length: 51 }, (_, index) => ({ ...positive, id: `p${index}` })) },
    { cases: [{ ...positive, expect_no_match: true }] }, { cases: [{ ...positive, expect_no_match: "true" }] },
    { cases: [{ ...positive, expected_texts: [] }] }, { cases: [{ ...positive, query: " " }] },
    { cases: [{ ...positive, category: "unknown" }] }, { cases: [{ ...positive, run_code: "bad" }] },
    { arbitrary: "field" },
    { limit: null }, { description: null },
    { cases: [{ ...positive, category: ["keyword"] }] },
    { cases: [{ ...positive, expect_no_match: null }] },
  ]) assert.throws(() => parseRetrievalSuite(encode(update)));
});

test("没有有效分母时显示横线，零分不能显示成未评估", () => {
  assert.equal(percentage(null), "—");
  assert.equal(percentage(0), "0.0%");
  assert.equal(percentage(1), "100.0%");
});
