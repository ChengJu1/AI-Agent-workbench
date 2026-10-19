// 组合工作台组件；状态与异步流程由 useWorkbench 管理。
import { useEffect, useRef, useState } from "react";
import { ApprovalList } from "./components/ApprovalList";
import { MessageComposer } from "./components/MessageComposer";
import { MessageList } from "./components/MessageList";
import { WorkbenchHeader } from "./components/WorkbenchHeader";
import { WorkbenchSidebar } from "./components/WorkbenchSidebar";
import { ConversationWelcome } from "./components/ConversationWelcome";
import { useWorkbench } from "./hooks/useWorkbench";
import { AgentCreator } from "./components/AgentCreator";
import { KnowledgeManager } from "./components/KnowledgeManager";
import { AgentKnowledgeBindings } from "./components/AgentKnowledgeBindings";
import { SkillManager } from "./components/SkillManager";
import { AgentSkillBindings } from "./components/AgentSkillBindings";

function App() {
  const workbench = useWorkbench();
  const [creatingAgent, setCreatingAgent] = useState(false);
  const [managingKnowledge, setManagingKnowledge] = useState(false);
  const [bindingKnowledge, setBindingKnowledge] = useState(false);
  const [managingSkills, setManagingSkills] = useState(false);
  const [bindingSkills, setBindingSkills] = useState(false);
  const [mobile, setMobile] = useState(() => window.matchMedia("(max-width: 860px)").matches);
  const [sidebarOpen, setSidebarOpen] = useState(() => !window.matchMedia("(max-width: 860px)").matches);
  const workspaceRef = useRef<HTMLElement>(null);
  const selectedAgent = workbench.agents.find((agent) => agent.id === workbench.selectedAgentId);
  const selectedConversation = workbench.conversations.find((item) => item.id === workbench.conversationId);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 860px)");
    const onChange = () => { setMobile(media.matches); setSidebarOpen(!media.matches); };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  const closeSidebar = () => {
    setSidebarOpen(false);
    requestAnimationFrame(() => workspaceRef.current?.querySelector<HTMLButtonElement>("[aria-controls='workbench-sidebar']")?.focus());
  };
  useEffect(() => {
    if (!mobile || !sidebarOpen) return;
    const sidebar = document.getElementById("workbench-sidebar");
    sidebar?.querySelector<HTMLButtonElement>("button")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSidebarOpen(false);
        requestAnimationFrame(() => workspaceRef.current?.querySelector<HTMLButtonElement>("[aria-controls='workbench-sidebar']")?.focus());
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mobile, sidebarOpen]);
  return <main className="app workspaceApp">
    <WorkbenchSidebar agents={workbench.agents} agentId={workbench.selectedAgentId}
      conversations={workbench.conversations} conversationId={workbench.conversationId}
      disabled={workbench.busy} open={sidebarOpen} mobile={mobile} onClose={closeSidebar}
      onAgentChange={workbench.selectAgent} onConversationChange={workbench.switchConversation}
      onCreateAgent={() => setCreatingAgent(true)} onKnowledge={() => setManagingKnowledge(true)}
      onSkills={() => setManagingSkills(true)}
      onNewConversation={workbench.startNewConversation} />
    <section className="workspaceMain" ref={workspaceRef} inert={mobile && sidebarOpen}>
      <WorkbenchHeader agents={workbench.agents} agentId={workbench.selectedAgentId}
        title={selectedConversation?.title || selectedAgent?.name || "对话工作台"}
        status={workbench.isSending ? "正在回复" : workbench.isLoading ? "正在加载" : workbench.conversationId ? "历史会话" : "新对话"}
        disabled={workbench.busy} sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        onAgentChange={workbench.selectAgent} onAgentKnowledge={() => setBindingKnowledge(true)} onAgentSkills={() => setBindingSkills(true)} />
      {workbench.messages.length === 0 && !workbench.isLoading ? <div className="welcomeScroll">
        <ConversationWelcome agent={selectedAgent} disabled={workbench.busy} onPrompt={(prompt) => {
          workbench.setInput(prompt); document.getElementById("message-input")?.focus();
        }} />
      </div> : <MessageList messages={workbench.messages} loading={workbench.isLoading} agentName={selectedAgent?.name} />}
      <ApprovalList actions={workbench.pendingActions} disabled={workbench.busy}
        decidingId={workbench.decidingActionId} onDecision={workbench.handleDecision} />
      {workbench.error && <p className="error" role="alert">{workbench.error}</p>}
      <MessageComposer value={workbench.input} disabled={workbench.busy || !workbench.selectedAgentId}
        sending={workbench.isSending} onChange={workbench.setInput} onSend={workbench.handleSend} />
    </section>
    {creatingAgent && <AgentCreator onCreate={workbench.handleCreateAgent} onClose={() => setCreatingAgent(false)} />}
    {managingKnowledge && <KnowledgeManager onClose={() => setManagingKnowledge(false)} />}
    {bindingKnowledge && selectedAgent && <AgentKnowledgeBindings agent={selectedAgent} onClose={() => setBindingKnowledge(false)} />}
    {managingSkills && <SkillManager onClose={() => setManagingSkills(false)} onBind={selectedAgent ? () => {
      setManagingSkills(false); setBindingSkills(true);
    } : undefined} />}
    {bindingSkills && selectedAgent && <AgentSkillBindings agent={selectedAgent} onClose={() => setBindingSkills(false)} />}
  </main>;
}

export default App;
