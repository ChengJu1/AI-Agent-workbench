import { useEffect, useMemo, useRef, useState } from "react";
import type { KnowledgeCitation, KnowledgeDocumentVersion } from "../types";
import { fetchDocumentVersion } from "../api/knowledge";
import { citationPreview } from "../lib/citationPreview";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { rehypeCitationPosition } from "../lib/markdownCitationPosition";

export function CitationPreview({ source, onClose }: { source: KnowledgeCitation; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const selectedLine = useRef<HTMLDivElement>(null);
  const markdownBody = useRef<HTMLDivElement>(null);
  const markdown = /\.(md|markdown)$/i.test(source.filename);
  const [view, setView] = useState<"rendered" | "source">(markdown ? "rendered" : "source");
  const [document, setDocument] = useState<KnowledgeDocumentVersion | null>(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const preview = useMemo(() => citationPreview(source, document), [source, document]);
  const firstSelected = preview.lines.find((line) => line.selected)?.number;

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setDocument(null); setUnavailable(false);
    fetchDocumentVersion(source, controller.signal).then((value) => {
      if (!controller.signal.aborted) setDocument(value);
    }).catch(() => {
      if (!controller.signal.aborted) setUnavailable(true);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [source]);

  function locate() {
    const target = view === "rendered" ? markdownBody.current?.querySelector("[data-citation-position]") : selectedLine.current;
    target?.scrollIntoView({ block: "center", behavior: "auto" });
  }
  useEffect(() => { if (!loading) locate(); }, [loading, document, view]);

  return <dialog ref={dialog} className="citationPreview" aria-labelledby="citationPreviewTitle"
    onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <header><div><h2 id="citationPreviewTitle">原文预览</h2><h3>{source.filename}</h3></div>
      <button type="button" onClick={onClose} aria-label="关闭原文预览">关闭</button></header>
    <div className="citationPreviewMeta">
      <p>{source.knowledge_base_name} · 文档版本 v{source.document_version}</p>
      <button type="button" onClick={locate}>定位引用片段：第 {source.start_line}–{source.end_line} 行</button>
    </div>
    {source.section && <p className="citationPreviewSection">{source.section}</p>}
    {markdown && <div className="previewViewToggle" role="group" aria-label="原文显示方式">
      <button type="button" aria-pressed={view === "rendered"} onClick={() => setView("rendered")}>Markdown 预览</button>
      <button type="button" aria-pressed={view === "source"} onClick={() => setView("source")}>原文与行号</button>
    </div>}
    <p className="citationSnapshotHint" role="status">{loading ? "正在加载完整原文…" :
      preview.fullDocument ? preview.notice : unavailable ? "该版本的完整原文暂不可用，以下为当轮保存的引用片段。" :
      "完整原文与引用位置无法准确对应，以下为当轮保存的引用片段。"}</p>
    {view === "rendered" ? <div ref={markdownBody} className="markdownDocument" aria-label="Markdown 原文预览"
      tabIndex={0} aria-busy={loading}>
      <ReactMarkdown skipHtml remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeCitationPosition, { start: preview.highlightStart, end: preview.highlightEnd }]]}
        components={{
          img: ({ alt }) => <span className="previewImagePlaceholder" role="img" aria-label={alt || "笔记图片"}>图片：{alt || "原笔记附件"}</span>,
          a: ({ href, children }) => href && /^(https?:|mailto:)/i.test(href)
            ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
            : <span className="previewLocalLink" title={href ? `原笔记链接：${href}` : undefined}>{children}</span>,
        }}>{preview.text}</ReactMarkdown>
    </div> : <div className="documentLines" aria-label={preview.fullDocument ? "完整原文与行号" : "引用片段快照"}
      tabIndex={0} aria-busy={loading}>
      {preview.lines.map((line) => <div className="documentLine"
        key={line.number} ref={line.number === firstSelected ? selectedLine : undefined}>
        <span className="documentLineNumber" aria-hidden="true">{line.number}</span>
        <code>{line.before + line.highlighted + line.after || "\u200b"}</code>
      </div>)}
    </div>}
    <footer>原文按引用版本显示，后续文档更新不会改变此处引用位置。</footer>
  </dialog>;
}
