// 展示 Agent 和会话选择器，操作交给工作台状态层。
import { conversationLabel } from "../lib/presentation";
import type { AgentInfo, ConversationInfo } from "../types";

type Props = {
  agents: AgentInfo[];
  agentId: string;
  conversations: ConversationInfo[];
  conversationId: string | null;
  disabled: boolean;
  onAgentChange: (id: string) => void;
  onConversationChange: (id: string) => Promise<void>;
  onNewConversation: () => void;
  onCreateAgent: () => void;
};

export function WorkbenchHeader(props: Props) {
  return (
    <>
      <header className="header">
        <div>
          <h1>AI Agent Workbench</h1>
          <p>选择一个 Agent，然后开始对话。</p>
        </div>
        <label className="agentSelector">
          <span>Agent</span>
          <select value={props.agentId} disabled={props.disabled}
            onChange={(event) => props.onAgentChange(event.target.value)}>
            {props.agents.map((agent) => (
              <option key={agent.id} value={agent.id}>{agent.name}</option>
            ))}
          </select>
        </label>
      </header>
      <div className="conversationToolbar">
        <label>
          <span>当前会话</span>
          <select value={props.conversationId ?? ""} disabled={props.disabled}
            onChange={(event) => void props.onConversationChange(event.target.value)}>
            <option value="">新对话</option>
            {props.conversations.map((conversation) => (
              <option key={conversation.id} value={conversation.id}>
                {conversationLabel(conversation)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" disabled={props.disabled}
          onClick={props.onCreateAgent}>创建 Agent</button>
        <button type="button" disabled={props.disabled || !props.agentId}
          onClick={props.onNewConversation}>新建对话</button>
      </div>
    </>
  );
}
