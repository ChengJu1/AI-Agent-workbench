// 组合工作台组件；状态与异步流程由 useWorkbench 管理。
import { ApprovalList } from "./components/ApprovalList";
import { MessageComposer } from "./components/MessageComposer";
import { MessageList } from "./components/MessageList";
import { WorkbenchHeader } from "./components/WorkbenchHeader";
import { useWorkbench } from "./hooks/useWorkbench";
import { useState } from "react";
import { AgentCreator } from "./components/AgentCreator";

function App() {
  const workbench = useWorkbench();
  const [creatingAgent, setCreatingAgent] = useState(false);
  return (
    <main className="app">
      <section className="chatShell">
        <WorkbenchHeader agents={workbench.agents} agentId={workbench.selectedAgentId}
          conversations={workbench.conversations} conversationId={workbench.conversationId}
          disabled={workbench.busy} onAgentChange={workbench.selectAgent}
          onConversationChange={workbench.switchConversation}
          onCreateAgent={() => setCreatingAgent(true)}
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
    </main>
  );
}

export default App;
