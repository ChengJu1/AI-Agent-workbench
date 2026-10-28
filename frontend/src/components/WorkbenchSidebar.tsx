import { Fragment, useEffect, useRef, useState } from "react";
import type { AgentInfo, ConversationInfo, Delegation } from "../types";
import { conversationLabel } from "../lib/presentation";
import { WorkbenchIcon } from "./WorkbenchIcon";
import { readSectionOpen, saveSectionOpen } from "../lib/storage";
import { confirmAgentDelete, confirmConversationDelete, conversationTitle } from "../lib/confirmDelete";

type Props = {
  agents: AgentInfo[]; agentId: string; conversations: ConversationInfo[];
  conversationId: string | null; disabled: boolean; open: boolean; mobile: boolean;
  onClose: () => void; onAgentChange: (id: string) => void;
  onConversationChange: (id: string) => Promise<void>; onNewConversation: () => void;
  onArchiveAgent: (id: string, archived: boolean) => Promise<string | null>; onDeleteAgent: (id: string) => Promise<string | null>;
  onArchiveConversation: (id: string, archived: boolean) => Promise<string | null>; onDeleteConversation: (id: string) => Promise<string | null>;
  childConversations: Delegation[]; rootConversationId: string | null;
  onCreateAgent: () => void; onKnowledge: () => void; onSkills: () => void; onTracking: () => void; onArchive: () => void;
};

// 可折叠区块的标题：点击展开或收起，状态记在浏览器里。
function useSection(name: string) {
  const [open, setOpen] = useState(() => readSectionOpen(name));
  const toggle = () => setOpen((value) => { saveSectionOpen(name, !value); return !value; });
  return [open, toggle] as const;
}

function SectionToggle({ open, onToggle, controls, title, hint }: {
  open: boolean; onToggle: () => void; controls: string; title: string; hint?: string;
}) {
  return <button type="button" className="sectionToggle" aria-expanded={open} aria-controls={controls} onClick={onToggle}>
    <WorkbenchIcon name="chevron" /><h2>{title}</h2>{hint && <span className="sectionHint">{hint}</span>}
  </button>;
}

// 行尾的小操作按钮：悬停或键盘聚焦时出现，触屏上常驻。
function RowAction({ icon, label, danger, disabled, onClick }: {
  icon: "archive" | "trash"; label: string; danger?: boolean; disabled: boolean; onClick: () => void;
}) {
  return <button type="button" className={`rowAction ${danger ? "isDanger" : ""}`} aria-label={label} title={label}
    disabled={disabled} onClick={onClick}><WorkbenchIcon name={icon} /></button>;
}

export function WorkbenchSidebar(props: Props) {
  const [query, setQuery] = useState("");
  const [agentsOpen, toggleAgents] = useSection("agents");
  const [historyOpen, toggleHistory] = useSection("history");
  const currentAgent = props.agents.find((agent) => agent.id === props.agentId);
  const agentList = useRef<HTMLDivElement>(null);
  useEffect(() => setQuery(""), [props.agentId]);
  // Agent 列表可滚动；刷新后恢复的 Agent 可能在列表下方，滚到能看见的位置。
  useEffect(() => {
    agentList.current?.querySelector(".agentItem.isSelected")?.scrollIntoView({ block: "nearest" });
  }, [props.agentId, props.agents.length, agentsOpen]);
  const conversations = props.conversations.filter((item) =>
    `${item.title ?? ""} ${conversationLabel(item)}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  // 归档的 Agent 和会话不在侧边栏出现，到"归档"窗口里恢复或删除。
  const activeConversations = conversations.filter((item) => !item.archived);
  const activeAgents = props.agents.filter((agent) => !agent.archived);
  const archivedCount = props.agents.length - activeAgents.length;
  const navigate = (action: () => void) => { action(); if (props.mobile) props.onClose(); };
  const deleteAgent = (agent: AgentInfo) => { if (confirmAgentDelete(agent.name)) void props.onDeleteAgent(agent.id); };
  const deleteConversation = (item: ConversationInfo) => { if (confirmConversationDelete(item.title)) void props.onDeleteConversation(item.id); };
  const agentButton = (agent: AgentInfo) => {
    const index = props.agents.indexOf(agent);
    return <button className={`agentItem ${agent.id === props.agentId ? "isSelected" : ""}`} aria-pressed={agent.id === props.agentId}
      disabled={props.disabled} title={agent.description} onClick={() => navigate(() => props.onAgentChange(agent.id))}>
      <span className={`agentAvatar tone${index % 3}`}>{agent.name.slice(0, 1)}</span>
      <span>{agent.name}</span>{agent.id === props.agentId && <i aria-hidden="true" />}
    </button>;
  };
  const conversationButton = (item: ConversationInfo) => <button
    className={`historyItem ${item.id === props.conversationId ? "isSelected" : ""}`}
    aria-current={item.id === props.conversationId ? "true" : undefined} disabled={props.disabled}
    title={conversationLabel(item)} onClick={() => navigate(() => void props.onConversationChange(item.id))}>
    <WorkbenchIcon name="chat" /><span>{conversationTitle(item.title)}</span>
    {item.read_only && <small className="runtimeBadge" title="已停用的运行时创建，只能查看">只读</small>}
  </button>;
  return <>
    {props.mobile && props.open && <button className="sidebarBackdrop" aria-label="关闭导航" onClick={props.onClose} />}
    <aside id="workbench-sidebar" className={`workbenchSidebar ${props.open ? "isOpen" : ""}`} inert={!props.open} aria-label="工作区导航">
      <div className="workspaceBrand"><span className="brandMark"><WorkbenchIcon name="spark" /></span>
        <div><strong>Workbench<span>AI</span></strong><small>让想法成为行动</small></div>
        {props.mobile && <button className="iconButton sidebarClose" aria-label="收起导航" onClick={props.onClose}><WorkbenchIcon name="close" /></button>}
      </div>
      <button className="newChatButton" disabled={props.disabled || !props.agentId} onClick={() => navigate(props.onNewConversation)}>
        <WorkbenchIcon name="plus" />新建对话<span>＋</span>
      </button>
      <nav className="workspaceNav" aria-label="主要功能">
        <button className="navItem isCurrent" aria-current="page" onClick={() => navigate(() => document.getElementById("message-input")?.focus())}>
          <WorkbenchIcon name="chat" />对话工作台</button>
        <button className="navItem" disabled={props.disabled} onClick={() => navigate(props.onKnowledge)}>
          <WorkbenchIcon name="book" />知识库</button>
        <button className="navItem" disabled={props.disabled} onClick={() => navigate(props.onSkills)}>
          <WorkbenchIcon name="spark" />Skill 管理</button>
        <button className="navItem" disabled={props.disabled} onClick={()=>navigate(props.onTracking)}><WorkbenchIcon name="book"/>记录与跟踪</button>
        <button className="navItem" disabled={props.disabled} onClick={() => navigate(props.onArchive)}><WorkbenchIcon name="archive" />归档</button>
      </nav>
      <section className={`sidebarAgents ${agentsOpen ? "" : "isCollapsed"}`} aria-label="我的 Agent">
        <div className="sidebarSectionTitle"><SectionToggle open={agentsOpen} onToggle={toggleAgents} controls="sidebar-agents"
          title="我的 Agent" hint={agentsOpen ? undefined : currentAgent?.name} /><button className="iconButton" aria-label="创建 Agent" title="创建 Agent"
          disabled={props.disabled} onClick={() => navigate(props.onCreateAgent)}><WorkbenchIcon name="plus" /></button></div>
        <div className="agentItems" id="sidebar-agents" ref={agentList} hidden={!agentsOpen}>
          {activeAgents.map((agent) => <div className="sidebarRow" key={agent.id}>{agentButton(agent)}
            <span className="rowActions">
              <RowAction icon="archive" label={`归档 ${agent.name}`} disabled={props.disabled} onClick={() => void props.onArchiveAgent(agent.id, true)} />
              {agent.deletable !== false && <RowAction icon="trash" label={`删除 ${agent.name}`} danger disabled={props.disabled} onClick={() => deleteAgent(agent)} />}
            </span></div>)}
          {activeAgents.length === 0 && <p className="sidebarEmpty">{archivedCount ? "所有 Agent 都已归档，可在“归档”中恢复" : "暂未加载到 Agent"}</p>}
        </div>
      </section>
      <section className={`sidebarHistory ${historyOpen ? "" : "isCollapsed"}`} aria-label="历史会话">
        <div className="sidebarSectionTitle"><SectionToggle open={historyOpen} onToggle={toggleHistory} controls="sidebar-history"
          title="历史会话" /><span>{props.conversations.filter((item) => !item.archived).length}</span></div>
        <div className="historyBody" id="sidebar-history" hidden={!historyOpen}>
        <label className="historySearch"><WorkbenchIcon name="search" /><input aria-label="搜索当前 Agent 的会话" placeholder="搜索会话…"
          value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <div className="historyItems">
          {activeConversations.map((item) => <Fragment key={item.id}><div className="sidebarRow">{conversationButton(item)}
            <span className="rowActions">
              <RowAction icon="archive" label="归档这段对话" disabled={props.disabled} onClick={() => void props.onArchiveConversation(item.id, true)} />
              <RowAction icon="trash" label="删除这段对话" danger disabled={props.disabled} onClick={() => deleteConversation(item)} />
            </span></div>
            {item.id === props.rootConversationId && props.childConversations.length > 0 && <ul className="childConversations" aria-label="委派的子会话">
              {props.childConversations.map((child) => <li key={child.child_conversation_id}><button type="button"
                className={`historyItem childItem ${child.child_conversation_id === props.conversationId ? "isSelected" : ""}`}
                aria-current={child.child_conversation_id === props.conversationId ? "true" : undefined} disabled={props.disabled}
                onClick={() => navigate(() => void props.onConversationChange(child.child_conversation_id))}>
                <span>↳ {child.member_name}</span></button></li>)}
            </ul>}</Fragment>)}
          {activeConversations.length === 0 && <p className="sidebarEmpty">{query ? "没有匹配的会话" : "新的灵感，从一段对话开始"}</p>}
        </div>
        </div>
      </section>
      <footer className="sidebarFooter"><span className="workspaceAvatar">W</span><div><strong>个人工作区</strong><small>本地工作台</small></div></footer>
    </aside>
  </>;
}
