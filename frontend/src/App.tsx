// 组合工作台组件；状态与异步流程由 useWorkbench 管理。
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { ApprovalList } from "./components/ApprovalList";
import { splitApprovals } from "./lib/approvalState";
import { MessageComposer } from "./components/MessageComposer";
import { MessageList } from "./components/MessageList";
import { WorkbenchHeader } from "./components/WorkbenchHeader";
import { WorkbenchSidebar } from "./components/WorkbenchSidebar";
import { ConversationWelcome } from "./components/ConversationWelcome";
import { useWorkbench } from "./hooks/useWorkbench";
import {OperationPreview,type PreviewSelection} from "./components/OperationPreview";

import {TrackingIndicator} from "./components/TrackingIndicator";
import { LedgerButton } from "./components/LedgerButton";

// Dialogs load on first open, keeping them out of the initial bundle.
const AgentBuilder = lazy(() => import("./components/AgentBuilder").then(m => ({ default: m.AgentBuilder })));
const AgentCapabilities = lazy(() => import("./components/AgentCapabilities").then(m => ({ default: m.AgentCapabilities })));
const BrowserPanel = lazy(() => import("./components/BrowserPanel").then(m => ({ default: m.BrowserPanel })));
const AgentCreator = lazy(() => import("./components/AgentCreator").then(m => ({ default: m.AgentCreator })));
const KnowledgeManager = lazy(() => import("./components/KnowledgeManager").then(m => ({ default: m.KnowledgeManager })));
const AgentKnowledgeBindings = lazy(() => import("./components/AgentKnowledgeBindings").then(m => ({ default: m.AgentKnowledgeBindings })));
const SkillManager = lazy(() => import("./components/SkillManager").then(m => ({ default: m.SkillManager })));
const AgentSkillBindings = lazy(() => import("./components/AgentSkillBindings").then(m => ({ default: m.AgentSkillBindings })));
const TrackingCenter = lazy(() => import("./components/TrackingCenter").then(m => ({ default: m.TrackingCenter })));
const FileManager = lazy(() => import("./components/FileManager").then(m => ({ default: m.FileManager })));
const ApplicationCenter = lazy(() => import("./components/ApplicationCenter").then(m => ({ default: m.ApplicationCenter })));

function App() {
  const workbench = useWorkbench();
  const [viewingTracking,setViewingTracking]=useState(false);
  const [viewingFiles,setViewingFiles]=useState(false);
  const [viewingLedger,setViewingLedger]=useState(false);
  const [managingCapabilities, setManagingCapabilities] = useState(false);
  const [previewSelection,setPreviewSelection]=useState<PreviewSelection>(null);
  const [previewRequest,setPreviewRequest]=useState(0);
  const [previewOpen,setPreviewOpen]=useState(false);
  const [historyOpen,setHistoryOpen]=useState(false);
  useEffect(()=>{setPreviewSelection(null);setPreviewRequest(0);setPreviewOpen(false);},[workbench.conversationId]);
  // The preview panel appears on request, or when a browser action is waiting for the user's confirmation.
  const waitingBrowserAction=workbench.pendingActions.find(a=>a.status==='pending'&&a.tool_name==='workbench_platform'&&a.params.operations)?.id;
  useEffect(()=>{if(previewRequest)setPreviewOpen(true);},[previewRequest]);
  useEffect(()=>{if(waitingBrowserAction)setPreviewOpen(true);},[waitingBrowserAction]);
  const pastActions=splitApprovals(workbench.pendingActions).history.length;
  const previewStep=(actionId:string,index:number)=>{setPreviewSelection({actionId,index});setPreviewRequest(v=>v+1);};
  const [viewingBrowser, setViewingBrowser] = useState(false);
  const [browserSessionId,setBrowserSessionId]=useState<string>();
  const [browserUrl,setBrowserUrl]=useState<string>();
  const [creatingAgent, setCreatingAgent] = useState(false);
  const [manualAgent, setManualAgent] = useState(false);
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
      onSkills={() => setManagingSkills(true)} onTracking={() => setViewingTracking(true)}
      onNewConversation={workbench.startNewConversation} />
    <section className="workspaceMain" ref={workspaceRef} inert={mobile && sidebarOpen}>
      <WorkbenchHeader agents={workbench.agents} agentId={workbench.selectedAgentId}
        title={selectedConversation?.title || selectedAgent?.name || "对话工作台"}
        status={workbench.isSending ? "正在回复" : workbench.isLoading ? "正在加载" : workbench.conversationId ? "历史会话" : "新对话"}
        disabled={workbench.busy} sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        onAgentChange={workbench.selectAgent} onAgentKnowledge={() => setBindingKnowledge(true)} onAgentSkills={() => setBindingSkills(true)}
        tools={<><TrackingIndicator disabled={workbench.busy} onOpen={()=>setViewingTracking(true)}/>
        {selectedAgent?.platform_capabilities?.includes("applications")&&<LedgerButton disabled={workbench.busy} onClick={()=>setViewingLedger(true)}/>}
        {selectedAgent?.platform_capabilities?.includes("files")&&workbench.conversationId&&<button disabled={workbench.busy} onClick={()=>setViewingFiles(true)}>文件与版本</button>}<button disabled={workbench.busy || !selectedAgent} onClick={() => setManagingCapabilities(true)}>基础能力</button>
        {selectedAgent?.platform_capabilities?.includes("browser") && <button aria-pressed={previewOpen} onClick={()=>workbench.conversationId?(previewOpen?setPreviewOpen(false):setPreviewRequest(v=>v+1)):setViewingBrowser(true)}>浏览器</button>}
        {!!pastActions&&<button onClick={()=>setHistoryOpen(true)}>操作记录 · {pastActions}</button>}</>} />
      <div className="workspaceBody"><div className="conversationColumn">
      {workbench.messages.length === 0 && !workbench.isLoading ? <div className="welcomeScroll">
        <ConversationWelcome agent={selectedAgent} disabled={workbench.busy} onPrompt={(prompt) => {
          workbench.setInput(prompt); document.getElementById("message-input")?.focus();
        }} />
      </div> : <MessageList messages={workbench.messages} loading={workbench.isLoading} agentName={selectedAgent?.name} />}
      <ApprovalList actions={workbench.pendingActions} disabled={workbench.busy}
        decidingId={workbench.decidingActionId} onDecision={workbench.handleDecision} onPreview={previewStep}
        onRefresh={workbench.refreshActions} refreshing={workbench.isRefreshingActions} syncError={workbench.actionSyncError}
        errors={workbench.actionErrors} uncertainIds={workbench.uncertainActions} historyOpen={historyOpen} onHistoryClose={()=>setHistoryOpen(false)} />
      {workbench.error && <p className="error" role="alert">{workbench.error}</p>}
      <MessageComposer attachments={workbench.attachments} conversationId={workbench.conversationId} allowUpload={selectedAgent?.platform_capabilities?.includes("files")}
        uploading={workbench.isUploading} onUpload={workbench.handleUpload} value={workbench.input} disabled={workbench.busy || !workbench.selectedAgentId}
        sending={workbench.isSending} onChange={workbench.setInput} onSend={workbench.handleSend} onStop={workbench.stopReply} />
      </div>{selectedAgent?.platform_capabilities?.includes("browser")&&workbench.conversationId&&previewOpen&&<OperationPreview onClose={()=>setPreviewOpen(false)} key={workbench.conversationId} conversationId={workbench.conversationId} actions={workbench.pendingActions} selection={previewSelection} forceOpen={previewRequest} paused={viewingBrowser} busy={workbench.busy} onResume={workbench.resumeBrowser} onSelect={s=>{setPreviewSelection(s);setPreviewRequest(v=>v+1);}} onManage={(sessionId,url)=>{setBrowserSessionId(sessionId);setBrowserUrl(url);setViewingBrowser(true);}}/>}</div>
    </section>
    <Suspense fallback={null}>
    {viewingTracking&&<TrackingCenter agents={workbench.agents} conversationId={workbench.conversationId} onClose={()=>setViewingTracking(false)}/>}
    {viewingLedger&&<ApplicationCenter onClose={()=>setViewingLedger(false)}/>}
    {viewingFiles&&workbench.conversationId&&<FileManager conversationId={workbench.conversationId} onChanged={workbench.refreshAttachments} onClose={()=>{setViewingFiles(false);workbench.refreshAttachments();}}/>}
    {managingCapabilities && selectedAgent && <AgentCapabilities agent={selectedAgent} onSaved={workbench.updateCapabilities} onClose={() => setManagingCapabilities(false)} />}
    {viewingBrowser && <BrowserPanel key={workbench.conversationId||'new'} initialSessionId={browserSessionId} initialUrl={browserUrl} actions={workbench.pendingActions} previewSelection={previewSelection} conversationId={workbench.conversationId} agentBusy={workbench.busy} onResume={workbench.resumeBrowser} onClose={() => {setViewingBrowser(false);setBrowserSessionId(undefined);setBrowserUrl(undefined);}} />}
    {creatingAgent && <AgentBuilder onCreated={workbench.handleBuiltAgent} onClose={() => setCreatingAgent(false)}
      onManual={() => { setCreatingAgent(false); setManualAgent(true); }} />}
    {manualAgent && <AgentCreator onCreate={workbench.handleCreateAgent} onClose={() => setManualAgent(false)} />}
    {managingKnowledge && <KnowledgeManager onClose={() => setManagingKnowledge(false)} />}
    {bindingKnowledge && selectedAgent && <AgentKnowledgeBindings agent={selectedAgent} onClose={() => setBindingKnowledge(false)} />}
    {managingSkills && <SkillManager onClose={() => setManagingSkills(false)} onBind={selectedAgent ? () => {
      setManagingSkills(false); setBindingSkills(true);
    } : undefined} />}
    {bindingSkills && selectedAgent && <AgentSkillBindings agent={selectedAgent} onClose={() => setBindingSkills(false)} />}
    </Suspense>
  </main>;
}

export default App;
