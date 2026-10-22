import type { RetrievalCase, RetrievalSuite } from "../types";

export const MAX_SUITE_BYTES = 100 * 1024;

function record(value: unknown, allowed: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("题集必须是 JSON 对象。");
  if (Object.keys(value).some((key) => !allowed.includes(key))) throw new Error("题集包含不支持的字段，请按导出的题集格式填写。");
  return value as Record<string, unknown>;
}

function text(value: unknown, label: string, max: number) {
  if (typeof value !== "string" || !value.trim() || value.trim().length > max) throw new Error(`${label}不能为空或超过 ${max} 字符。`);
  return value.trim();
}

export function parseRetrievalSuite(input: string): RetrievalSuite {
  let parsed: unknown;
  try { parsed = JSON.parse(input); } catch { throw new Error("题集不是有效的 JSON 文件。"); }
  const suite = record(parsed, ["name", "description", "limit", "cases"]);
  const limit = suite.limit === undefined ? 5 : suite.limit;
  if (!Number.isInteger(limit) || typeof limit !== "number" || limit < 1 || limit > 20) throw new Error("返回条数必须是 1–20 的整数。");
  if (!Array.isArray(suite.cases) || suite.cases.length < 1 || suite.cases.length > 50) throw new Error("题集需要包含 1–50 道题。");
  const ids = new Set<string>();
  const cases = suite.cases.map((raw): RetrievalCase => {
    const value = record(raw, ["id", "query", "category", "expected_filename", "expected_texts", "expect_no_match"]);
    const id = text(value.id, "题目 ID", 64);
    if (!/^[A-Za-z0-9_-]+$/.test(id) || ids.has(id)) throw new Error("题目 ID 只能使用英文、数字、横线或下划线，且不能重复。");
    ids.add(id);
    const category = value.category === undefined ? "keyword" : value.category;
    if (typeof category !== "string" || !["keyword", "question", "paraphrase", "negative"].includes(category)) throw new Error("题目类别不正确。");
    const noMatch = value.expect_no_match === undefined ? false : value.expect_no_match;
    if (typeof noMatch !== "boolean") throw new Error("expect_no_match 必须为 true 或 false。");
    const expected = value.expected_texts === undefined ? [] : value.expected_texts;
    if (!Array.isArray(expected) || expected.length > 8) throw new Error("每题最多填写 8 段关键原文。");
    const texts = expected.map((item) => text(item, "关键原文", 200));
    const filename = value.expected_filename == null ? null : text(value.expected_filename, "预期文件名", 200);
    if (noMatch && (filename || texts.length)) throw new Error("空结果题不能同时填写预期文件和关键原文。");
    if (!noMatch && (!filename || !texts.length)) throw new Error("正例题需要预期文件名和至少一段关键原文。");
    return { id, query: text(value.query, "查询词", 200), category: category as RetrievalCase["category"],
      expected_filename: filename, expected_texts: texts, expect_no_match: noMatch };
  });
  const description = suite.description === undefined ? "" : suite.description;
  if (typeof description !== "string" || description.trim().length > 1000) throw new Error("题集说明不能超过 1000 字符。");
  return { name: text(suite.name, "题集名称", 100), description: description.trim(), limit, cases };
}

export function percentage(value: number | null) {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function downloadEvaluationJson(filename: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
