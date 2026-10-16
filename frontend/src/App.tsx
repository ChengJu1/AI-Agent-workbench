// 组合工作台组件；状态与异步流程由 useWorkbench 管理。
import { ApprovalList } from "./components/ApprovalList";
import { MessageComposer } from "./components/MessageComposer";
import { MessageList } from "./components/MessageList";
import { WorkbenchHeader } from "./components/WorkbenchHeader";
import { useWorkbench } from "./hooks/useWorkbench";

function App() {
  const workbench = useWorkbench();
  return (
    <main className="app">
      <section className="chatShell">
        <WorkbenchHeader agents={workbench.agents} agentId={workbench.selectedAgentId}
          conversations={workbench.conversations} conversationId={workbench.conversationId}
          disabled={workbench.busy} onAgentChange={workbench.selectAgent}
          onConversationChange={workbench.switchConversation}
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
    </main>
  );
}

export default App;
