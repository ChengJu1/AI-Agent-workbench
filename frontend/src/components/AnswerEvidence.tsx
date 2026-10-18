import { useEffect, useRef } from "react";
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
    return <button type="button" key={source.citation_id} className="sourceCard"
      onClick={() => onOpen(source)} aria-label={`查看引用原文：${source.filename}，第 ${source.start_line}–${source.end_line} 行`}>
      <strong>[{index}] {source.filename}</strong>
      <span>{source.knowledge_base_name} · v{source.document_version} · 第 {source.start_line}–{source.end_line} 行</span>
      {source.section && <span>{source.section}</span>}
      <small>查看原文片段</small>
    </button>;
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

export function CitationPreview({ source, onClose }: { source: KnowledgeCitation; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return <dialog ref={dialog} className="citationPreview" aria-labelledby="citationPreviewTitle"
    onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <header><h2 id="citationPreviewTitle">引用原文</h2><button type="button" onClick={onClose}>关闭</button></header>
    <h3>{source.filename}</h3>
    <p>{source.knowledge_base_name} · 文档版本 v{source.document_version} · 第 {source.start_line}–{source.end_line} 行</p>
    {source.section && <p>章节：{source.section}</p>}
    <p className="citationSnapshotHint">以下为该轮检索时保存的原文快照，后续文档更新不会改变此处内容。</p>
    <pre>{source.content}</pre>
  </dialog>;
}
