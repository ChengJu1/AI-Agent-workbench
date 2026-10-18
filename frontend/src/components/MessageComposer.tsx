import { useLayoutEffect, useRef } from "react";
import { WorkbenchIcon } from "./WorkbenchIcon";

type Props = {
  value: string;
  disabled: boolean;
  sending: boolean;
  onChange: (value: string) => void;
  onSend: () => Promise<void>;
};

export function MessageComposer({ value, disabled, sending, onChange, onSend }: Props) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const input = inputRef.current;
    if (input) { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 180)}px`; }
  }, [value]);
  return <div className="composerDock">
    <form className="composer" onSubmit={(event) => {
      event.preventDefault();
      if (!disabled && value.trim()) void onSend();
    }}>
      <textarea id="message-input" ref={inputRef} aria-label="输入消息" rows={2} value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) {
            event.preventDefault();
            if (!disabled && value.trim()) void onSend();
          }
        }}
        placeholder="输入问题，让想法向前一步…" disabled={disabled} maxLength={50000} />
      <div className="composerBottom"><span>{sending ? "Agent 正在思考并回复…" : "Enter 发送 · Shift + Enter 换行"}</span>
        <button type="submit" aria-label={sending ? "正在回复" : "发送消息"} title="发送消息" disabled={disabled || !value.trim()}>
          <WorkbenchIcon name="arrow" />
        </button>
      </div>
    </form>
    <p className="composerNote">AI 的回答可能存在疏漏，请结合原文核实重要信息。</p>
  </div>;
}
