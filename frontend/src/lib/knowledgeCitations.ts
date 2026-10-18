import { fromMarkdown } from "mdast-util-from-markdown";
import type { KnowledgeCitation, KnowledgeEvidence } from "../types";

type MarkdownNode = {
  type: string;
  url?: string;
  identifier?: string;
  children?: MarkdownNode[];
};

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
  const ids = new Set<string>();
  for (const source of evidence.citations) {
    if (!source || typeof source !== "object"
        || ![source.citation_id, source.knowledge_base_id, source.knowledge_base_name,
          source.document_id, source.filename, source.section, source.content].every((item) => typeof item === "string")
        || !/^S[0-9a-f]{12}-[1-9]\d*$/.test(source.citation_id)
        || ids.has(source.citation_id)
        || ![source.document_version, source.chunk_id, source.start_line, source.end_line]
          .every((number) => Number.isInteger(number) && number > 0)
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
