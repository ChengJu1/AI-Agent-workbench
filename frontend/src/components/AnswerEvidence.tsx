import type { KnowledgeCitation, KnowledgeEvidence } from "../types";
import { citationReferences, knowledgeStatusText } from "../lib/knowledgeCitations";
import "./AnswerEvidence.css";

type Props = {
  knowledge: KnowledgeEvidence;
  content: string;
  streaming: boolean;
  onOpen: (citation: KnowledgeCitation) => void;
};

export function AnswerEvidence({ knowledge, content, streaming, onOpen }: Props) {
  const refs = citationReferences(content, knowledge.citations);
  const hasNotes = knowledge.channels?.includes("notes_mcp") || (knowledge.notes_calls ?? 0) > 0;
  function sourceCard(source: KnowledgeCitation) {
    const index = knowledge.citations.findIndex((item) => item.citation_id === source.citation_id) + 1;
    return <a href={`#source-${source.citation_id}`} key={source.citation_id} className="sourceCard"
      aria-haspopup="dialog" onClick={(event) => { event.preventDefault(); onOpen(source); }}
      aria-label={`查看引用原文：${source.filename}，第 ${source.start_line}–${source.end_line} 行`}>
      <strong>[{index}] {source.filename}</strong>
      <span>{source.knowledge_base_name} · v{source.document_version} · 第 {source.start_line}–{source.end_line} 行</span>
      {source.section && <span>{source.section}</span>}
      <small>打开原文并定位引用片段 ↗</small>
    </a>;
  }
  const statusText = knowledgeStatusText(knowledge, refs.used.length, streaming);
  return <section className="answerEvidence" aria-label="回答依据">
    <p className={refs.used.length ? "evidenceStatus verified" : "evidenceStatus"}>{statusText}</p>
    {hasNotes && <p className="evidenceQueries">本轮调用笔记 MCP {knowledge.notes_calls ?? 0} 次</p>}
    {knowledge.queries.length > 0 && <p className="evidenceQueries">查询 / 读取：{[...new Set(knowledge.queries)].join(" · ")}</p>}
    {refs.unknown.length > 0 && <p className="evidenceWarning" role="status">回答含无法核验的引用，请核对原文。</p>}
    {knowledge.failed_searches > 0 && knowledge.status !== "failed" &&
      <p className="evidenceWarning">部分检索失败，展示的是成功返回的资料。</p>}
    <div className="sourceCards">{refs.used.map(sourceCard)}</div>
    {refs.unused.length > 0 && <details className="unusedSources">
      <summary>其他返回原文（{refs.unused.length}）</summary>
      <p>这些原文由工具返回，回答尚未引用。返回原文不代表已被回答采用。</p>
      <div className="sourceCards">{refs.unused.map(sourceCard)}</div>
    </details>}
  </section>;
}
