import { useEffect, useRef, useState } from "react";
import { saveDefaultRuntime } from "../api";
import type { AgentInfo, RuntimeName } from "../types";
import { runtimeLabel } from "../lib/runtime";

export function NewConversationRuntime({ enabled, conversationId, defaultRuntime, override, disabled, onChange }: {
  enabled: boolean; conversationId: string | null; defaultRuntime?: RuntimeName; override?: RuntimeName;
  disabled: boolean; onChange: (value: RuntimeName | undefined) => void;
}) {
  if (!enabled || conversationId) return null;
  return <details className="newRuntimeOptions"><summary>高级</summary>
    <label>本次运行时<select value={override ?? ""} disabled={disabled}
      onChange={event => onChange((event.target.value || undefined) as RuntimeName | undefined)}>
      <option value="">使用 Agent 默认（{runtimeLabel(defaultRuntime)}）</option>
      <option value="claude_sdk">Claude SDK</option><option value="deep_agents">Deep Agents</option>
    </select></label><p>仅用于这次新会话，创建后固定。</p>
  </details>;
}

export function AgentRuntimeSettings({ agent, onSaved, onClose }: {
  agent: AgentInfo; onSaved: (runtime: RuntimeName) => void; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [runtime, setRuntime] = useState<RuntimeName>(agent.default_runtime ?? "claude_sdk");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const mutation = useRef(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => { request.current?.abort(); element?.close(); }; }, []);
  return <dialog className="agentEditor runtimeDialog" ref={dialog} aria-labelledby="runtimeSettingsTitle"
    onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}>
    <form onSubmit={async event => {
      event.preventDefault(); if (mutation.current) return;
      mutation.current = true; setSaving(true); setError("");
      const controller = new AbortController(); request.current = controller;
      try { const saved = await saveDefaultRuntime(agent.id, runtime, controller.signal); if (!controller.signal.aborted) { onSaved(saved.runtime); onClose(); } }
      catch (caught) { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "保存失败。"); }
      finally { mutation.current = false; if (!controller.signal.aborted) setSaving(false); }
    }}>
      <h2 id="runtimeSettingsTitle">{agent.name} · 默认运行时</h2>
      <p className="agentEditorHint">只影响之后新建的会话，已有会话保持原运行时。</p>
      <label>默认运行时<select value={runtime} disabled={saving} onChange={event => setRuntime(event.target.value as RuntimeName)}>
        <option value="claude_sdk">Claude SDK</option><option value="deep_agents">Deep Agents</option>
      </select></label>
      {error && <p role="alert" className="agentEditorError">{error}</p>}
      <div className="agentEditorActions agentEditorFooter"><button type="button" disabled={saving} onClick={onClose}>取消</button>
        <button className="primaryButton" disabled={saving}>{saving ? "正在保存…" : "保存"}</button></div>
    </form>
  </dialog>;
}
