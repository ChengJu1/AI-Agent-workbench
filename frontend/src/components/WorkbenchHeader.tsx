import type { AgentInfo } from "../types";
import { WorkbenchIcon } from "./WorkbenchIcon";

type Props = {
  agents: AgentInfo[]; agentId: string; title: string; status: string;
  disabled: boolean; sidebarOpen: boolean;
  onAgentChange: (id: string) => void; onToggleSidebar: () => void;
  onAgentKnowledge: () => void;
  onAgentSkills: () => void;
};

export function WorkbenchHeader(props: Props) {
  return <header className="workspaceHeader">
    <button className="iconButton" aria-label={props.sidebarOpen ? "收起侧栏" : "展开侧栏"}
      aria-expanded={props.sidebarOpen} aria-controls="workbench-sidebar" onClick={props.onToggleSidebar}>
      <WorkbenchIcon name="panel" />
    </button>
    <div className="workspaceBreadcrumb"><span>工作区</span><span aria-hidden="true">/</span><strong title={props.title}>{props.title}</strong></div>
    <span className="conversationState">{props.status}</span>
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
