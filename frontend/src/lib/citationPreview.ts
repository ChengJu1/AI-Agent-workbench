import type { KnowledgeCitation, KnowledgeDocumentVersion } from "../types";

export type PreviewLine = { number: number; before: string; highlighted: string; after: string; selected: boolean };

export function citationPreview(source: KnowledgeCitation, document?: KnowledgeDocumentVersion | null) {
  const fallback = () => ({ fullDocument: false, lines: makeLines(source.content, 0,
    Array.from(source.content).length, source.start_line), notice: "当前仅展示当轮保存的引用片段。" });
  if (!document || document.document_id !== source.document_id || document.version !== source.document_version
      || document.knowledge_base_id !== source.knowledge_base_id || document.filename !== source.filename) return fallback();
  const points = Array.from(document.content);
  let start = source.start_offset;
  let end = source.end_offset;
  if (start == null && end == null) {
    // 旧引用没有字符位置，只在其标明的起始行内尝试唯一的精确匹配。
    const lines = document.content.split("\n");
    if (source.start_line > lines.length) return fallback();
    const lineStart = lines.slice(0, source.start_line - 1).reduce((size, line) => size + line.length + 1, 0);
    const lineEnd = lineStart + lines[source.start_line - 1].length;
    const found = document.content.indexOf(source.content, lineStart);
    const repeated = found >= 0 ? document.content.indexOf(source.content, found + 1) : -1;
    if (found < lineStart || found > lineEnd || (repeated >= 0 && repeated <= lineEnd)) return fallback();
    start = Array.from(document.content.slice(0, found)).length;
    end = start + Array.from(source.content).length;
  }
  if (start == null || end == null || !Number.isInteger(start) || !Number.isInteger(end)
      || start < 0 || end <= start || end > points.length
      || points.slice(start, end).join("") !== source.content) return fallback();
  const actualStartLine = points.slice(0, start).filter((point) => point === "\n").length + 1;
  const actualEndLine = points.slice(0, end - 1).filter((point) => point === "\n").length + 1;
  if (actualStartLine !== source.start_line || actualEndLine !== source.end_line) return fallback();
  return { fullDocument: true, lines: makeLines(document.content, start, end, 1),
    notice: "展示该引用版本的完整原文，黄色区域为本次引用片段。" };
}

function makeLines(text: string, start: number, end: number, firstLine: number): PreviewLine[] {
  let position = 0;
  return text.split("\n").map((line, index) => {
    const points = Array.from(line);
    const left = Math.max(0, Math.min(points.length, start - position));
    const right = Math.max(left, Math.min(points.length, end - position));
    const selected = start < position + points.length + 1 && end > position;
    position += points.length + 1;
    return { number: firstLine + index, before: points.slice(0, left).join(""),
      highlighted: points.slice(left, right).join(""), after: points.slice(right).join(""), selected };
  });
}
