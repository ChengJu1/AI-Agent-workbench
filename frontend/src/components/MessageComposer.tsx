import { useLayoutEffect, useRef } from "react";
import { ConversationFiles } from "./ConversationFiles";
import type { Attachment } from "../api/platform";
import "./platform.css";
import { WorkbenchIcon } from "./WorkbenchIcon";

type Props = {
  attachments?: Attachment[];
  pendingImages?: Attachment[];
  onRemovePending?: (id: string) => void;
  conversationId?: string | null;
  allowUpload?: boolean;
  uploading?: boolean;
  onUpload?: (file: File) => Promise<void>;
  value: string;
  disabled: boolean;
  sending: boolean;
  onChange: (value: string) => void;
  onSend: () => Promise<void>;
  onStop?: () => void;
};

export function MessageComposer({ value, disabled, sending, onChange, onSend, onStop, attachments = [], pendingImages = [], onRemovePending, conversationId = null, allowUpload, uploading, onUpload }: Props) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const input = inputRef.current;
    // Grow with the text up to about a third of the window, then scroll inside.
    if (input) { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, Math.max(160, window.innerHeight * 0.35))}px`; }
  }, [value]);
  return <div className="composerDock">
    <form className="composer" onSubmit={(event) => {
      event.preventDefault();
      if (!disabled && value.trim()) void onSend();
    }}>
      {pendingImages.length > 0 && <div className="pendingImages" aria-label="将随消息发送的图片">
        <span>随消息发送</span>{pendingImages.map(image => <span key={image.id} className="pendingImage">
          {image.kind === "scanned_pdf" ? "扫描 PDF" : "图片"} · {image.filename}
          {onRemovePending && <button type="button" aria-label={`不发送 ${image.filename}`} disabled={disabled} onClick={() => onRemovePending(image.id)}>×</button>}
        </span>)}</div>}
      <textarea id="message-input" ref={inputRef} aria-label="输入消息" rows={1} value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) {
            event.preventDefault();
            if (!disabled && value.trim()) void onSend();
          }
        }}
        placeholder="输入问题，让想法向前一步…" disabled={disabled} maxLength={50000} />
      <div className="composerBottom">{allowUpload && <label className={`uploadAttachment ${disabled ? "isDisabled" : ""}`}>
        {uploading ? "正在解析…" : "＋ 添加附件"}<input type="file" aria-label="上传会话附件" accept=".pdf,.docx,.txt,.md,.csv,.json,.png,.jpg,.jpeg,.webp" disabled={disabled}
          onChange={(event) => { const file = event.target.files?.[0]; if (file && onUpload) void onUpload(file); event.target.value = ""; }} /></label>}
        <ConversationFiles files={attachments} conversationId={conversationId} /><span>{sending ? "Agent 正在思考并回复…" : "Enter 发送 · Shift + Enter 换行"}</span>
        {sending && onStop
          ? <button type="button" className="stopReply" aria-label="停止生成" title="停止生成，保留已生成的内容" onClick={onStop}><span aria-hidden="true" /></button>
          : <button type="submit" aria-label="发送消息" title="发送消息" disabled={disabled || !value.trim()}>
            <WorkbenchIcon name="arrow" />
          </button>}
      </div>
    </form>
    <p className="composerNote">AI 的回答可能存在疏漏，请结合原文核实重要信息。</p>
  </div>;
}
