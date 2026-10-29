// 归档窗口：归档的 Agent 和所有 Agent 的已归档会话集中在这里恢复或永久删除，不占侧边栏。
import { useEffect, useRef, useState } from "react";
import { fetchArchivedConversations } from "../api";
import { confirmAgentDelete, confirmConversationDelete, conversationTitle } from "../lib/confirmDelete";
import type { AgentInfo, ConversationInfo } from "../types";
import { WorkbenchIcon } from "./WorkbenchIcon";

type ArchivedConversation = ConversationInfo & { archived_at: string };
type Result = Promise<string | null>;

export function ArchiveCenter({ agents, onArchiveAgent, onDeleteAgent, onArchiveConversation, onDeleteConversation, onClose }: {
  agents: AgentInfo[];
  onArchiveAgent: (id: string, archived: boolean) => Result; onDeleteAgent: (id: string) => Result;
  onArchiveConversation: (id: string, archived: boolean) => Result; onDeleteConversation: (id: string) => Result;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [tab, setTab] = useState<"agents" | "conversations">("agents");
  const [conversations, setConversations] = useState<ArchivedConversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const archivedAgents = agents.filter((agent) => agent.archived);
  const agentName = (id: string) => agents.find((agent) => agent.id === id)?.name ?? "未知 Agent";

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchArchivedConversations(controller.signal)
      .then((rows) => { if (!controller.signal.aborted) setConversations(rows); })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "无法读取已归档的对话。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  async function run(action: () => Result, onDone?: () => void) {
    setWorking(true);
    setError("");
    const failure = await action();
    setWorking(false);
    if (failure) setError(failure);
    else onDone?.();
  }

  const dropConversation = (id: string) => setConversations((rows) => rows.filter((row) => row.id !== id));
  // 删除 Agent 会连带删除它的会话，这里同步去掉。
  const dropAgentConversations = (agentId: string) => setConversations((rows) => rows.filter((row) => row.agent_id !== agentId));

  return <dialog className="agentEditor archiveCenter" ref={dialog} aria-labelledby="archiveTitle"
    onCancel={(event) => { event.preventDefault(); if (!working) onClose(); }}>
    <div className="archiveHeader">
      <h2 id="archiveTitle">归档</h2>
      <button type="button" className="iconButton" aria-label="关闭" disabled={working} onClick={onClose}><WorkbenchIcon name="close" /></button>
    </div>
    <p className="agentEditorHint">归档的内容不会出现在侧边栏。恢复后回到原来的位置；删除后无法恢复。</p>
    <div className="archiveTabs" role="tablist">
      <button type="button" role="tab" aria-selected={tab === "agents"} onClick={() => setTab("agents")}>Agent<span>{archivedAgents.length}</span></button>
      <button type="button" role="tab" aria-selected={tab === "conversations"} onClick={() => setTab("conversations")}>对话<span>{loading ? "…" : conversations.length}</span></button>
    </div>
    {error && <p role="alert" className="agentEditorError">{error}</p>}
    <div className="archiveList" role="tabpanel">
      {tab === "agents" && (archivedAgents.length === 0 ? <p className="archiveEmpty">没有归档的 Agent</p> : archivedAgents.map((agent) =>
        <div className="archiveRow" key={agent.id}>
          <div><strong>{agent.name}</strong><small>{agent.description || "没有描述"}</small></div>
          <button type="button" disabled={working} onClick={() => void run(() => onArchiveAgent(agent.id, false))}>恢复</button>
          {agent.deletable !== false && <button type="button" className="dangerButton" disabled={working}
            onClick={() => { if (confirmAgentDelete(agent.name)) void run(() => onDeleteAgent(agent.id), () => dropAgentConversations(agent.id)); }}>删除</button>}
        </div>))}
      {tab === "conversations" && (loading ? <p className="archiveEmpty" role="status">正在读取…</p>
        : conversations.length === 0 ? <p className="archiveEmpty">没有归档的对话</p> : conversations.map((item) =>
        <div className="archiveRow" key={item.id}>
          <div><strong>{conversationTitle(item.title)}</strong>
            <small>{agentName(item.agent_id)} · 归档于 {item.archived_at.replace("T", " ").slice(0, 16)}</small></div>
          <button type="button" disabled={working} onClick={() => void run(() => onArchiveConversation(item.id, false), () => dropConversation(item.id))}>恢复</button>
          <button type="button" className="dangerButton" disabled={working}
            onClick={() => { if (confirmConversationDelete(item.title)) void run(() => onDeleteConversation(item.id), () => dropConversation(item.id)); }}>删除</button>
        </div>))}
    </div>
  </dialog>;
}
