import { fromMarkdown } from "mdast-util-from-markdown";
import type { KnowledgeCitation, KnowledgeEvidence } from "../types";

type MarkdownNode = {
  type: string;
  url?: string;
  identifier?: string;
  children?: MarkdownNode[];
};

export function knowledgeStatusText(knowledge: KnowledgeEvidence, usedCount: number, streaming: boolean): string {
  const hasNotes = knowledge.channels?.includes("notes_mcp") || (knowledge.notes_calls ?? 0) > 0;
  const subject = hasNotes ? "笔记 / 资料" : "知识库";
  switch (knowledge.status) {
    case "matched": return usedCount ? `回答引用了 ${usedCount} 处资料`
      : streaming ? "已返回原文，正在组织回答…" : "已返回原文，但回答未标注可核验引用。";
    case "no_match": return `已查询${subject}，未找到匹配原文；当前回答缺少本轮资料依据。`;
    case "not_searched": return hasNotes ? "已查看笔记目录，本轮尚未搜索或读取原文。"
      : "本轮未检索知识库，回答没有新增知识库依据。";
    case "failed": return `${subject}查询失败或来源记录不完整，当前回答无法核验资料依据。`;
  }
}

export function citationIdFromLink(url: string | undefined): string | null {
  return url?.startsWith("#source-") ? url.slice("#source-".length) : null;
}

export function citationReferences(content: string, sources: KnowledgeCitation[]) {
  const tree: MarkdownNode = fromMarkdown(content);
  const definitions = new Map<string, string>();
  const links: string[] = [];
  function visit(node: MarkdownNode, action: (node: MarkdownNode) => void) {
    action(node);
    for (const child of node.children ?? []) visit(child, action);
  }
  visit(tree, (node) => {
    if (node.type === "definition" && node.identifier && node.url) definitions.set(node.identifier, node.url);
  });
  visit(tree, (node) => {
    const url = node.type === "link" ? node.url
      : node.type === "linkReference" ? definitions.get(node.identifier ?? "") : undefined;
    const id = citationIdFromLink(url);
    if (id !== null && !links.includes(id)) links.push(id);
  });
  const byId = new Map(sources.map((source) => [source.citation_id, source]));
  return {
    used: links.flatMap((id) => byId.has(id) ? [byId.get(id)!] : []),
    unknown: links.filter((id) => !byId.has(id)),
    unused: sources.filter((source) => !links.includes(source.citation_id)),
  };
}

export function parseKnowledgeEvidence(value: unknown): KnowledgeEvidence {
  if (!value || typeof value !== "object") throw new Error("知识库来源格式不正确。");
  const evidence = value as KnowledgeEvidence;
  if (!["matched", "no_match", "not_searched", "failed"].includes(evidence.status)
      || !Array.isArray(evidence.citations) || !Array.isArray(evidence.queries)
      || !evidence.queries.every((query) => typeof query === "string")
      || !Number.isInteger(evidence.failed_searches) || evidence.failed_searches < 0) {
    throw new Error("知识库来源格式不正确。");
  }
  if ((evidence.channels !== undefined && (!Array.isArray(evidence.channels)
      || !evidence.channels.every((channel) => ["knowledge", "notes_mcp"].includes(channel))))
      || (evidence.notes_calls !== undefined && (!Number.isInteger(evidence.notes_calls) || evidence.notes_calls < 0))) {
    throw new Error("资料查询渠道格式不正确。");
  }
  const ids = new Set<string>();
  for (const source of evidence.citations) {
    if (!source || typeof source !== "object"
        || ![source.citation_id, source.knowledge_base_id, source.knowledge_base_name,
          source.document_id, source.filename, source.section, source.content].every((item) => typeof item === "string")
        || !/^S[0-9a-f]{12}-[1-9]\d*$/.test(source.citation_id)
        || ids.has(source.citation_id)
        || ![source.document_version, source.start_line, source.end_line]
          .every((number) => Number.isInteger(number) && number > 0)
        || (source.chunk_id !== null && (!Number.isInteger(source.chunk_id) || source.chunk_id <= 0))
        || (source.chunk_id === null && source.source_kind !== "notes_mcp")
        || (source.source_kind !== undefined && !["knowledge", "notes_mcp"].includes(source.source_kind))
        || source.end_line < source.start_line) {
      throw new Error("知识库引用缺少有效的原文或来源位置。");
    }
    ids.add(source.citation_id);
  }
  if ((evidence.status === "matched") !== (evidence.citations.length > 0)) {
    throw new Error("知识库检索状态与来源不一致。");
  }
  return evidence;
}
