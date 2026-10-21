import { useEffect, useRef, useState } from "react";
import { fetchWorkSummary } from "../api";
import type { RuntimeName } from "../types";
import { runtimeLabel } from "../lib/runtime";

export function CopyWorkSummary({ conversationId, onCopy, onClose }: {
  conversationId: string; onCopy: (runtime: RuntimeName, summary: string) => Promise<void>; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [summary, setSummary] = useState("");
  const [target, setTarget] = useState<RuntimeName>("deep_agents");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const mutation = useRef(false);
  const mounted = useRef(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => { mounted.current = true; const element = dialog.current; element?.showModal(); return () => { mounted.current = false; element?.close(); }; }, []);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    void fetchWorkSummary(conversationId, controller.signal).then(result => {
      if (!controller.signal.aborted) { setSummary(result.summary); setTarget(result.source_runtime === "claude_sdk" ? "deep_agents" : "claude_sdk"); }
    }).catch(caught => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "读取摘要失败。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [conversationId, attempt]);
  return <dialog className="agentEditor summaryDialog" ref={dialog} aria-labelledby="copySummaryTitle"
    onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}>
    <form onSubmit={async event => {
      event.preventDefault(); if (mutation.current || loading || !summary.trim()) return;
      mutation.current = true; setSaving(true); setError("");
      try { await onCopy(target, summary); if (mounted.current) onClose(); }
      catch (caught) { if (mounted.current) setError(caught instanceof Error ? caught.message : "创建失败。"); }
      finally { mutation.current = false; if (mounted.current) setSaving(false); }
    }}>
      <h2 id="copySummaryTitle">复制工作摘要到新会话</h2>
      <p className="agentEditorHint">新会话使用 {runtimeLabel(target)}。原会话和完整聊天保留；待确认操作不迁移。创建后由你发送下一条消息继续。</p>
      {loading ? <p role="status">正在整理摘要…</p> : <label>工作摘要（可编辑）<textarea value={summary} maxLength={40000} rows={14}
        disabled={saving} onChange={event => setSummary(event.target.value)} /></label>}
      {error && <p role="alert" className="agentEditorError">{error}<button type="button" disabled={saving} onClick={() => setAttempt(value => value + 1)}>重新读取</button></p>}
      <div className="agentEditorActions agentEditorFooter"><button type="button" disabled={saving} onClick={onClose}>取消</button>
        <button className="primaryButton" disabled={saving || loading || !summary.trim()}>{saving ? "正在创建…" : `在 ${runtimeLabel(target)} 中新建会话`}</button></div>
    </form>
  </dialog>;
}
