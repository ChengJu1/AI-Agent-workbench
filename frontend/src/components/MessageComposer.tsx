import { useLayoutEffect, useRef } from "react";
import { ConversationFiles } from "./ConversationFiles";
import type { Attachment } from "../api/platform";
import "./platform.css";
import { WorkbenchIcon } from "./WorkbenchIcon";

type Props = {
  attachments?: Attachment[];
  conversationId?: string | null;
  allowUpload?: boolean;
  uploading?: boolean;
  onUpload?: (file: File) => Promise<void>;
  value: string;
  disabled: boolean;
  sending: boolean;
  onChange: (value: string) => void;
  onSend: () => Promise<void>;
};

export function MessageComposer({ value, disabled, sending, onChange, onSend, attachments = [], conversationId = null, allowUpload, uploading, onUpload }: Props) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const input = inputRef.current;
    // Grow with the text up to about a third of the window, then scroll inside.
    if (input) { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, Math.max(160, window.innerHeight * 0.35))}px`; }
  }, [value]);
  return <div className="composerDock">
    <ConversationFiles files={attachments} conversationId={conversationId} />
    <form className="composer" onSubmit={(event) => {
      event.preventDefault();
      if (!disabled && value.trim()) void onSend();
    }}>
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
        {uploading ? "正在解析…" : "＋ 添加附件"}<input type="file" aria-label="上传会话附件" accept=".pdf,.docx,.txt,.md,.csv,.json" disabled={disabled}
          onChange={(event) => { const file = event.target.files?.[0]; if (file && onUpload) void onUpload(file); event.target.value = ""; }} /></label>}<span>{sending ? "Agent 正在思考并回复…" : "Enter 发送 · Shift + Enter 换行"}</span>
        <button type="submit" aria-label={sending ? "正在回复" : "发送消息"} title="发送消息" disabled={disabled || !value.trim()}>
          <WorkbenchIcon name="arrow" />
        </button>
      </div>
    </form>
    <p className="composerNote">AI 的回答可能存在疏漏，请结合原文核实重要信息。</p>
  </div>;
}
