import { useEffect, useMemo, useRef, useState } from "react";
import type { KnowledgeCitation, KnowledgeDocumentVersion } from "../types";
import { fetchDocumentVersion } from "../api/knowledge";
import { citationPreview } from "../lib/citationPreview";

export function CitationPreview({ source, onClose }: { source: KnowledgeCitation; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const selectedLine = useRef<HTMLDivElement>(null);
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

  function locate() { selectedLine.current?.scrollIntoView({ block: "center", behavior: "auto" }); }
  useEffect(() => { if (!loading) locate(); }, [loading, document]);

  return <dialog ref={dialog} className="citationPreview" aria-labelledby="citationPreviewTitle"
    onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <header><div><h2 id="citationPreviewTitle">原文预览</h2><h3>{source.filename}</h3></div>
      <button type="button" onClick={onClose} aria-label="关闭原文预览">关闭</button></header>
    <div className="citationPreviewMeta">
      <p>{source.knowledge_base_name} · 文档版本 v{source.document_version}</p>
      <button type="button" onClick={locate}>定位引用片段：第 {source.start_line}–{source.end_line} 行</button>
    </div>
    {source.section && <p className="citationPreviewSection">{source.section}</p>}
    <p className="citationSnapshotHint" role="status">{loading ? "正在加载完整原文…" :
      preview.fullDocument ? preview.notice : unavailable ? "该版本的完整原文暂不可用，以下为当轮保存的引用片段。" :
      "完整原文与引用位置无法准确对应，以下为当轮保存的引用片段。"}</p>
    <div className="documentLines" aria-label={preview.fullDocument ? "完整原文，引用片段已高亮" : "引用片段快照"}
      tabIndex={0} aria-busy={loading}>
      {preview.lines.map((line) => <div className={`documentLine${line.selected ? " selected" : ""}`}
        key={line.number} ref={line.number === firstSelected ? selectedLine : undefined}>
        <span className="documentLineNumber" aria-hidden="true">{line.number}</span>
        <code>{line.before}{line.highlighted ? <mark>{line.highlighted}</mark> : null}{line.after || (!line.before && !line.highlighted ? "\u200b" : "")}</code>
      </div>)}
    </div>
    <footer>原文按引用版本显示，后续文档更新不会改变此处引用位置。</footer>
  </dialog>;
}
