import type { MatchRanking, SearchDiagnostics } from "../types.ts";

export const MAX_DOCUMENT_BYTES = 2 * 1024 * 1024;

export function milliseconds(value: number) {
  return value < 0.1 ? "<0.1 ms" : `${value.toFixed(1)} ms`;
}

export function retrievalFeedback(diagnostics: SearchDiagnostics, returned: number) {
  const steps = [diagnostics.vector_ms != null && `向量 ${milliseconds(diagnostics.vector_ms)}`,
    diagnostics.rerank_ms != null && `重排序 ${milliseconds(diagnostics.rerank_ms)}`].filter(Boolean).join("，");
  const rejected = diagnostics.low_relevance ? ` · 相关度低（最高 ${diagnostics.relevance_score?.toFixed(3)}）` : "";
  return `候选 ${diagnostics.candidate_count} 条 → 去重后 ${diagnostics.unique_count} 组 → 返回 ${returned} 组 · 后端检索 ${milliseconds(diagnostics.elapsed_ms)}（含去重 ${milliseconds(diagnostics.deduplication_ms)}）${steps ? ` · ${steps}` : ""}${rejected}`;
}

// 一条结果在各路的名次和分数；“—”表示没有进入该路的候选。
export function rankingLabel(ranking: MatchRanking) {
  const keyword = ranking.keyword_rank == null ? "关键词 —" : `关键词 #${ranking.keyword_rank}（${ranking.keyword_score?.toFixed(2)}）`;
  const vector = ranking.vector_rank == null ? "向量 —" : `向量 #${ranking.vector_rank}（余弦 ${ranking.similarity?.toFixed(3)}）`;
  const rerank = ranking.rerank_score == null ? "" : ` · 重排序 ${ranking.rerank_score.toFixed(3)}`;
  return `${keyword} · ${vector} · RRF ${ranking.rrf_score.toFixed(4)}${rerank}`;
}

export function chunkingLabel(strategy: "markdown_headings" | "characters") {
  return strategy === "markdown_headings"
    ? "按标题分段 · 每段 2 个相邻标题块，重叠 1 块"
    : "按字符分段 · 最长 800 字符，重叠 100 字符";
}

export function validateKnowledgeFile(file: Pick<File, "name" | "size">) {
  if (!/\.(md|markdown|txt|pdf|docx)$/i.test(file.name)) throw new Error("目前支持 Markdown、TXT、PDF 和 DOCX 文档。");
  if (file.size === 0) throw new Error("文档内容为空。");
  if (file.size > MAX_DOCUMENT_BYTES) throw new Error("单个文档不能超过 2 MB。");
}

export function documentSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}
