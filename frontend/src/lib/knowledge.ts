import type { SearchDiagnostics } from "../types.ts";

export const MAX_DOCUMENT_BYTES = 2 * 1024 * 1024;

export function milliseconds(value: number) {
  return value < 0.1 ? "<0.1 ms" : `${value.toFixed(1)} ms`;
}

export function retrievalFeedback(diagnostics: SearchDiagnostics, returned: number) {
  return `候选 ${diagnostics.candidate_count} 条 → 去重后 ${diagnostics.unique_count} 组 → 返回 ${returned} 组 · 后端检索 ${milliseconds(diagnostics.elapsed_ms)}（含去重 ${milliseconds(diagnostics.deduplication_ms)}）`;
}

export function chunkingLabel(strategy: "markdown_headings" | "characters") {
  return strategy === "markdown_headings"
    ? "按标题分段 · 每段 2 个相邻标题块，重叠 1 块"
    : "按字符分段 · 最长 800 字符，重叠 100 字符";
}

export function validateKnowledgeFile(file: Pick<File, "name" | "size">) {
  if (!/\.(md|markdown|txt)$/i.test(file.name)) throw new Error("目前支持 Markdown 和 TXT 文档。");
  if (file.size === 0) throw new Error("文档内容为空。");
  if (file.size > MAX_DOCUMENT_BYTES) throw new Error("单个文档不能超过 2 MB。");
}

export function documentSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}
