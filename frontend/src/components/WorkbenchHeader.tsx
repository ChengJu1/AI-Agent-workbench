import { useEffect, useRef, useState, type ReactNode } from "react";
import type { AgentInfo, RuntimeName } from "../types";
import { runtimeLabel } from "../lib/runtime";
import { WorkbenchIcon } from "./WorkbenchIcon";

type Props = {
  agents: AgentInfo[]; agentId: string; title: string; status: string;
  disabled: boolean; sidebarOpen: boolean;
  runtime?: RuntimeName;
  showRuntime?: boolean;
  onAgentChange: (id: string) => void; onToggleSidebar: () => void;
  onAgentKnowledge: () => void;
  onAgentSkills: () => void;
  tools?: ReactNode;
};

export function WorkbenchHeader(props: Props) {
  return <header className="workspaceHeader">
    <button className="iconButton" aria-label={props.sidebarOpen ? "收起侧栏" : "展开侧栏"}
      aria-expanded={props.sidebarOpen} aria-controls="workbench-sidebar" onClick={props.onToggleSidebar}>
      <WorkbenchIcon name="panel" />
    </button>
    <div className="workspaceBreadcrumb"><span>工作区</span><span aria-hidden="true">/</span><strong title={props.title}>{props.title}</strong></div>
    <span className="conversationState">{props.status}</span>
    {props.showRuntime && <span className="runtimeBadge" aria-label={`会话运行时：${runtimeLabel(props.runtime)}`}>{runtimeLabel(props.runtime)}</span>}
    {props.tools && <HeaderTools>{props.tools}</HeaderTools>}
    <div className="workspaceHeaderActions">
      <button className="bindingButton" aria-label="绑定 Skill" title="绑定 Skill" disabled={props.disabled || !props.agentId} onClick={props.onAgentSkills}>
        <WorkbenchIcon name="spark" /><span>绑定 Skill</span>
      </button>
      <button className="bindingButton" aria-label="绑定知识库" title="绑定知识库" disabled={props.disabled || !props.agentId} onClick={props.onAgentKnowledge}>
        <WorkbenchIcon name="link" /><span>绑定知识库</span>
      </button>
      <label className="compactAgentSelector"><span className="srOnly">切换 Agent</span>
        <select aria-label="切换 Agent" value={props.agentId} disabled={props.disabled} onChange={(event) => props.onAgentChange(event.target.value)}>
          {props.agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
        </select>
      </label>
    </div>
  </header>;
}

/** Shortcuts sit inline on wide screens and fold into one “工具” menu on narrow ones (one DOM, CSS decides). */
function HeaderTools({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => { if (!box.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", escape); };
  }, [open]);
  return <div className="headerToolsBox" ref={box}>
    <button type="button" className="headerToolsToggle" aria-expanded={open} aria-controls="header-tools" onClick={() => setOpen(!open)}>工具</button>
    <div id="header-tools" className={`platformShortcuts headerTools${open ? " isOpen" : ""}`}
      onClick={(event) => { if ((event.target as HTMLElement).closest("button,a")) setOpen(false); }}>{children}</div>
  </div>;
}
