// 组合工作台组件；状态与异步流程由 useWorkbench 管理。
import { ApprovalList } from "./components/ApprovalList";
import { MessageComposer } from "./components/MessageComposer";
import { MessageList } from "./components/MessageList";
import { WorkbenchHeader } from "./components/WorkbenchHeader";
import { useWorkbench } from "./hooks/useWorkbench";
import { useState } from "react";
import { AgentCreator } from "./components/AgentCreator";
import { KnowledgeManager } from "./components/KnowledgeManager";
import { AgentKnowledgeBindings } from "./components/AgentKnowledgeBindings";

function App() {
  const workbench = useWorkbench();
  const [creatingAgent, setCreatingAgent] = useState(false);
  const [managingKnowledge, setManagingKnowledge] = useState(false);
  const [bindingKnowledge, setBindingKnowledge] = useState(false);
  const selectedAgent = workbench.agents.find((agent) => agent.id === workbench.selectedAgentId);
  return (
    <main className="app">
      <section className="chatShell">
        <WorkbenchHeader agents={workbench.agents} agentId={workbench.selectedAgentId}
          conversations={workbench.conversations} conversationId={workbench.conversationId}
          disabled={workbench.busy} onAgentChange={workbench.selectAgent}
          onConversationChange={workbench.switchConversation}
          onCreateAgent={() => setCreatingAgent(true)}
          onKnowledge={() => setManagingKnowledge(true)}
          onAgentKnowledge={() => setBindingKnowledge(true)}
          onNewConversation={workbench.startNewConversation} />
        <MessageList messages={workbench.messages} loading={workbench.isLoading} />
        <ApprovalList actions={workbench.pendingActions} disabled={workbench.busy}
          decidingId={workbench.decidingActionId} onDecision={workbench.handleDecision} />
        {workbench.error && <p className="error" role="alert">{workbench.error}</p>}
        <MessageComposer value={workbench.input}
          disabled={workbench.busy || !workbench.selectedAgentId}
          sending={workbench.isSending} onChange={workbench.setInput}
          onSend={workbench.handleSend} />
      </section>
      {creatingAgent && <AgentCreator onCreate={workbench.handleCreateAgent}
        onClose={() => setCreatingAgent(false)} />}
      {managingKnowledge && <KnowledgeManager onClose={() => setManagingKnowledge(false)} />}
      {bindingKnowledge && selectedAgent && <AgentKnowledgeBindings agent={selectedAgent}
        onClose={() => setBindingKnowledge(false)} />}
    </main>
  );
}

export default App;
