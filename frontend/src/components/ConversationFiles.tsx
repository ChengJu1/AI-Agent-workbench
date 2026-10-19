import { useEffect, useRef, useState } from "react";
import { previewAttachment, type Attachment, type FilePreview } from "../api/platform";
export function ConversationFiles({ files, conversationId }: { files: Attachment[]; conversationId: string | null }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { if (preview) dialog.current?.showModal(); }, [preview]);
  return <><div className="conversationFiles" aria-label="当前会话附件">{files.map((file) => <button key={file.id} type="button" onClick={async () => {
    if (!conversationId) return; setError(""); try { setPreview(await previewAttachment(conversationId, file.id)); } catch (caught) { setError(caught instanceof Error ? caught.message : "读取失败。"); }
  }}>▤ {file.filename}<small>{file.text_length} 字</small></button>)}</div>{error && <p role="alert">{error}</p>}
    <dialog className="agentEditor platformDialog" ref={dialog} aria-label="附件文字预览" onCancel={() => setPreview(null)}>
      <h2>{preview?.filename}</h2><p className="agentEditorHint">解析文字预览（最多 12,000 字）。Agent 可分页读取全文；排版可能与原文不同。</p><pre className="attachmentText">{preview?.text}</pre>
      <button onClick={() => { dialog.current?.close(); setPreview(null); }}>关闭预览</button></dialog></>;
}
