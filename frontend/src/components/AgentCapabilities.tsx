import { useEffect, useRef, useState } from "react";
import { fetchCapabilities, saveCapabilities, type Capability } from "../api/platform";
import type { AgentInfo } from "../types";
import { CapabilityPicker } from "./CapabilityPicker";
import "./platform.css";
export function AgentCapabilities({ agent, onClose, onSaved }: { agent: AgentInfo; onClose: () => void; onSaved: (capabilities: Capability[]) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [selected, setSelected] = useState<Capability[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const mutation = useRef(false);
  useEffect(() => {
    dialog.current?.showModal(); const controller = new AbortController();
    void fetchCapabilities(agent.id, controller.signal).then((result) => { if (!controller.signal.aborted) setSelected(result.capabilities); })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); dialog.current?.close(); };
  }, [agent.id]);
  return <dialog className="agentEditor platformDialog" ref={dialog} aria-labelledby="capabilityTitle" onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}>
    <h2 id="capabilityTitle">{agent.name} · 基础能力</h2><p className="agentEditorHint">只向此 Agent 开放你选择的工具。修改后从下一轮对话生效，已读取的内容可能仍在历史中。</p>
    {loading ? <p role="status">正在读取配置…</p> : <CapabilityPicker selected={selected} onChange={setSelected} disabled={saving} />}
    {error && <p className="agentEditorError" role="alert">{error}</p>}
    <div className="agentEditorActions agentEditorFooter"><button disabled={saving} onClick={onClose}>取消</button><button className="primaryButton" disabled={saving || loading} onClick={async () => {
      if (mutation.current) return; mutation.current = true; setSaving(true); setError("");
      try { const result = await saveCapabilities(agent.id, selected); onSaved(result.capabilities); onClose(); }
      catch (caught) { setError(caught instanceof Error ? caught.message : "保存失败。"); }
      finally { mutation.current = false; setSaving(false); }
    }}>{saving ? "正在保存…" : "保存授权"}</button></div>
  </dialog>;
}
