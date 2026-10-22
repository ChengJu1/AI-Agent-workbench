import { useEffect, useRef, useState } from "react";
import { bindAgentKnowledgeBases, fetchAgentKnowledgeBases, fetchKnowledgeBases } from "../api/knowledge";
import type { AgentInfo, KnowledgeBaseInfo } from "../types";
import { KnowledgeBasePicker } from "./KnowledgeBasePicker";

export function AgentKnowledgeBindings({ agent, onClose }: { agent: AgentInfo; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const saveRequest = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  const [bases, setBases] = useState<KnowledgeBaseInfo[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => { element?.close(); saveRequest.current?.abort(); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoaded(false);
    setError("");
    void Promise.all([fetchKnowledgeBases(controller.signal), fetchAgentKnowledgeBases(agent.id, controller.signal)])
      .then(([available, bound]) => {
        if (controller.signal.aborted) return;
        setBases(available);
        setSelected(bound.map((base) => base.id));
        setLoaded(true);
      }).catch((error) => {
        if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "无法读取知识库绑定。");
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [agent.id, attempt]);

  return (
    <dialog className="agentEditor" ref={dialog} aria-labelledby="agentKnowledgeTitle"
      onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}>
      <form onSubmit={async (event) => {
        event.preventDefault();
        if (!loaded || submitting.current) return;
        submitting.current = true;
        const controller = new AbortController();
        saveRequest.current = controller;
        setSaving(true);
        setError("");
        try {
          await bindAgentKnowledgeBases(agent.id, selected, controller.signal);
          if (!controller.signal.aborted) onClose();
        } catch (error) {
          if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "保存失败，请重试。");
        } finally {
          submitting.current = false;
          if (!controller.signal.aborted) setSaving(false);
        }
      }}>
        <h2 id="agentKnowledgeTitle">为“{agent.name}”绑定知识库</h2>
        <p className="agentEditorHint">保存后从下一轮对话生效。取消全部选择可解除绑定；历史消息中的资料仍会保留。</p>
        {loading ? <p role="status">正在读取知识库…</p> : loaded &&
          <KnowledgeBasePicker bases={bases} selected={selected} disabled={saving} onChange={setSelected} />}
        {error && <p role="alert" className="agentEditorError">{error}</p>}
        {!loading && !loaded && <button type="button" onClick={() => setAttempt((current) => current + 1)}>重新读取</button>}
        <div className="agentEditorActions agentEditorFooter">
          <button type="button" disabled={saving} onClick={onClose}>取消</button>
          <button type="submit" className="primaryButton" disabled={loading || !loaded || saving}>
            {saving ? "正在保存…" : "保存绑定"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
