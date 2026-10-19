import { useEffect, useRef, useState } from "react";
import { bindAgentSkills, fetchAgentSkills, fetchSkills } from "../api/skills";
import type { AgentInfo, SkillBinding, SkillInfo } from "../types";
import { SkillPicker } from "./SkillPicker";

export function AgentSkillBindings({ agent, onClose }: { agent: AgentInfo; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const request = useRef<AbortController | null>(null);
  const savingRef = useRef(false);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [selected, setSelected] = useState<SkillBinding[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => { element?.close(); request.current?.abort(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setLoaded(false); setError("");
    void Promise.all([fetchSkills(controller.signal), fetchAgentSkills(agent.id, controller.signal)])
      .then(([available, bound]) => {
        if (controller.signal.aborted) return;
        setSkills(available); setSelected(bound.map(({ id, version }) => ({ id, version }))); setLoaded(true);
      }).catch((error) => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "读取 Skill 失败。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [agent.id, attempt]);
  return <dialog className="agentEditor" ref={dialog} aria-labelledby="agentSkillTitle"
    onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}>
    <form onSubmit={async (event) => {
      event.preventDefault();
      if (!loaded || savingRef.current) return;
      savingRef.current = true;
      const controller = new AbortController(); request.current = controller;
      setSaving(true); setError("");
      try {
        await bindAgentSkills(agent.id, selected, controller.signal);
        if (!controller.signal.aborted) onClose();
      } catch (error) { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "保存失败。"); }
      finally { savingRef.current = false; if (!controller.signal.aborted) setSaving(false); }
    }}>
      <h2 id="agentSkillTitle">为“{agent.name}”绑定 Skill</h2>
      <p className="agentEditorHint">选择具体版本并保存，下一轮按需读取该版本。保存新版本不会自动升级已绑定版本。取消全部选择可解除绑定，内置规则继续保留。</p>
      {loading ? <p role="status">正在读取 Skill…</p> : loaded &&
        <SkillPicker skills={skills} selected={selected} disabled={saving} onChange={setSelected} />}
      {error && <p className="agentEditorError" role="alert">{error}</p>}
      {!loading && !loaded && <button type="button" onClick={() => setAttempt((value) => value + 1)}>重新读取</button>}
      <div className="agentEditorActions agentEditorFooter">
        <button type="button" disabled={saving} onClick={onClose}>取消</button>
        <button type="submit" className="primaryButton" disabled={!loaded || loading || saving}>{saving ? "正在保存…" : "保存绑定"}</button>
      </div>
    </form>
  </dialog>;
}
