// 团队成员：负责人可以把任务委派给这些 Agent，成员在各自的子会话里用自己的能力完成。
import { useEffect, useRef, useState } from "react";
import { fetchTeam, saveTeam } from "../api";
import { MAX_TEAM_MEMBERS, moveMember, toggleMember } from "../lib/team";
import type { AgentInfo } from "../types";

export function AgentTeam({ agent, agents, onClose }: { agent: AgentInfo; agents: AgentInfo[]; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const candidates = agents.filter((item) => item.id !== agent.id && !item.archived);
  const name = (id: string) => agents.find((item) => item.id === id)?.name ?? "未知 Agent";

  useEffect(() => {
    dialog.current?.showModal();
    const controller = new AbortController();
    void fetchTeam(agent.id, controller.signal)
      .then((members) => { if (!controller.signal.aborted) setSelected(members.map((member) => member.id)); })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "无法读取团队成员。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); dialog.current?.close(); };
  }, [agent.id]);

  async function save() {
    setSaving(true);
    setError("");
    try { await saveTeam(agent.id, selected); onClose(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "保存失败。"); }
    finally { setSaving(false); }
  }

  return <dialog className="agentEditor teamDialog" ref={dialog} aria-labelledby="teamTitle"
    onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}>
    <h2 id="teamTitle">{agent.name} · 团队成员</h2>
    <p className="agentEditorHint">{agent.name} 会根据任务自己决定怎么用这些成员：把任务分给某位成员独立完成，或者让成员轮流讨论。
      成员在单独的子会话里用自己的能力工作，看不到本会话的历史和附件。最多 {MAX_TEAM_MEMBERS} 个，讨论时按这个顺序发言。</p>
    {loading ? <p role="status">正在读取…</p> : <>
      {selected.length > 0 && <ol className="teamOrder" aria-label="已选成员">{selected.map((id, index) => <li key={id}>
        <span>{name(id)}</span>
        <button type="button" aria-label={`上移 ${name(id)}`} disabled={saving || index === 0} onClick={() => setSelected(moveMember(selected, id, -1))}>↑</button>
        <button type="button" aria-label={`下移 ${name(id)}`} disabled={saving || index === selected.length - 1} onClick={() => setSelected(moveMember(selected, id, 1))}>↓</button>
      </li>)}</ol>}
      <fieldset className="teamCandidates" disabled={saving}><legend>选择成员（{selected.length}/{MAX_TEAM_MEMBERS}）</legend>
        {candidates.length === 0 && <p className="archiveEmpty">没有其他可选的 Agent</p>}
        {candidates.map((item) => <label key={item.id}>
          <input type="checkbox" checked={selected.includes(item.id)}
            disabled={!selected.includes(item.id) && selected.length >= MAX_TEAM_MEMBERS}
            onChange={() => setSelected(toggleMember(selected, item.id))} />
          <span><strong>{item.name}</strong><small>{item.description || "没有描述"}
            {item.platform_capabilities?.length ? ` · 能力：${item.platform_capabilities.join("、")}` : ""}</small></span>
        </label>)}
      </fieldset>
    </>}
    {error && <p className="agentEditorError" role="alert">{error}</p>}
    <div className="agentEditorActions agentEditorFooter">
      <button disabled={saving} onClick={onClose}>取消</button>
      <button className="primaryButton" disabled={saving || loading} onClick={() => void save()}>{saving ? "正在保存…" : "保存团队"}</button>
    </div>
  </dialog>;
}
