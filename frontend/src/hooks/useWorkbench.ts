// 组织工作台状态和异步操作；组件只负责渲染，API 模块只负责通信。
import { useEffect, useRef, useState } from "react";
import {
  createAgent, createConversation, decidePendingAction, fetchAgents, fetchConversations,
  fetchMessages, fetchActions, fetchAction, streamMessage,
} from "../api";
import {
  appendMessageText, applyKnowledgeEvidence, applySkills, createMessage, finishMessage, restoreMessages, upsertAction,
} from "../lib/messages";
import { browserTakeover, fetchAttachments, uploadAttachment, type Attachment, type Capability } from "../api/platform";
import {approvedBrowserContinuation, returnBrowserControl} from '../lib/browserContinuation';
import {approvalState, decideAndReconcile} from '../lib/approvalState';
import { readConversationId, saveConversationId } from "../lib/storage";
import type { AgentInfo, ChatMessage, ConversationInfo, CreateAgentInput, PendingAction } from "../types";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

export function useWorkbench() {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const activeConversation = useRef(conversationId);
  activeConversation.current = conversationId;
  const [conversations, setConversations] = useState<ConversationInfo[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);
  const [actionErrors, setActionErrors] = useState<Record<string,string>>({});
  const [uncertainActions, setUncertainActions] = useState<string[]>([]);
  const [actionSyncError, setActionSyncError] = useState('');
  const [isRefreshingActions, setIsRefreshingActions] = useState(false);
  const syncingActions = useRef(false);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [isCreatingAgent, setIsCreatingAgent] = useState(false);
  const [decidingActionId, setDecidingActionId] = useState("");
  const activeRequest = useRef<AbortController | null>(null);
  const operationRunning = useRef(false);
  const mounted = useRef(true);
  const busy = isUploading || isLoading || isSending || isCreatingAgent || Boolean(decidingActionId);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    async function loadAgents() {
      try {
        const result = await fetchAgents(controller.signal);
        if (controller.signal.aborted) return;
        setAgents(result);
        if (result.length) setSelectedAgentId(result[0].id);
        else setIsLoading(false);
      } catch (caughtError) {
        if (controller.signal.aborted) return;
        setError(errorText(caughtError));
        setIsLoading(false);
      }
    }
    void loadAgents();
    return () => {
      mounted.current = false;
      controller.abort();
      activeRequest.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!selectedAgentId) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    setIsLoading(true);
    async function loadConversations() {
      try {
        const result = await fetchConversations(selectedAgentId, controller.signal);
        if (controller.signal.aborted) return;
        setConversations(result);
        const savedId = readConversationId(selectedAgentId);
        let savedExists = false;
        for (const conversation of result) {
          if (conversation.id === savedId) savedExists = true;
        }
        if (!savedId || !savedExists) {
          saveConversationId(selectedAgentId, null);
          setConversationId(null);
          setMessages([]);
          setPendingActions([]);
          return;
        }
        const [history, actions] = await Promise.all([
          fetchMessages(savedId, controller.signal),
          fetchActions(savedId, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        setConversationId(savedId);
        setMessages(restoreMessages(history));
        setPendingActions(actions);
      } catch (caughtError) {
        // 网络暂时失败时保留存储中的会话 ID，便于下一次恢复。
        if (!controller.signal.aborted) setError(errorText(caughtError));
      } finally {
        if (!controller.signal.aborted) setIsLoading(false);
      }
    }
    void loadConversations();
    return () => controller.abort();
  }, [selectedAgentId]);

  useEffect(() => {
    setAttachments([]);
    if (!conversationId) return;
    const controller = new AbortController();
    void fetchAttachments(conversationId, controller.signal).then((rows) => {
      if (!controller.signal.aborted) setAttachments((current) => [...rows, ...current.filter((file) => !rows.some((row) => row.id === file.id))]);
    }).catch((caught) => { if (!controller.signal.aborted) setError(errorText(caught)); });
    return () => controller.abort();
  }, [conversationId]);

  async function syncActions(manual=false, signal?:AbortSignal) {
    if (!conversationId || syncingActions.current) return;
    const id = conversationId;
    syncingActions.current = true;
    if (manual) setIsRefreshingActions(true);
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, {once:true});
    if (signal?.aborted) controller.abort();
    const timeout = setTimeout(abort, 8000);
    try {
      const rows = await fetchActions(id, controller.signal);
      if (!mounted.current || activeConversation.current !== id || signal?.aborted) return;
      setPendingActions(current => rows.reduce(upsertAction, current));
      setActionSyncError('');
      setError(current=>current.startsWith('Pending action')?'':current);
      setUncertainActions(current => current.filter(key => !rows.some(row => row.id===key && (manual || !['pending','executing'].includes(row.status)))));
      if (manual) setActionErrors(current => Object.fromEntries(Object.entries(current).filter(([key]) => !rows.some(row => row.id===key))));
    } catch {
      if (mounted.current && activeConversation.current===id && !signal?.aborted) setActionSyncError('操作状态同步失败，请刷新状态后再确认。');
    } finally {
      clearTimeout(timeout);signal?.removeEventListener('abort', abort);
      syncingActions.current = false;
      if (mounted.current && manual) setIsRefreshingActions(false);
    }
  }

  useEffect(() => {
    if (!conversationId) return;
    setActionErrors({});setUncertainActions([]);setActionSyncError('');
    const controller = new AbortController();
    let timer:ReturnType<typeof setTimeout>;
    async function poll() {
      if (document.visibilityState!=='hidden') await syncActions(false,controller.signal);
      if (!controller.signal.aborted) timer=setTimeout(()=>void poll(),3000);
    }
    const visible = () => {if (document.visibilityState==='visible') void syncActions(false,controller.signal);};
    void poll();document.addEventListener('visibilitychange',visible);
    return()=>{controller.abort();clearTimeout(timer);document.removeEventListener('visibilitychange',visible);};
  },[conversationId]);

  function refreshAttachments() {
    if (!conversationId) return;
    const id = conversationId;
    void fetchAttachments(id).then(rows=>{if(mounted.current&&activeConversation.current===id)setAttachments(rows);}).catch(caught=>{if(mounted.current&&activeConversation.current===id)setError(errorText(caught));});
  }

  function updateCapabilities(capabilities: Capability[]) {
    setAgents((current) => current.map((agent) => agent.id === selectedAgentId ? { ...agent, platform_capabilities: capabilities } : agent));
  }

  async function handleUpload(file: File) {
    if (busy || operationRunning.current || !selectedAgentId) return;
    if (file.size > 2_000_000) { setError("单个附件不能超过 2 MB。"); return; }
    operationRunning.current = true; setIsUploading(true); setError("");
    const controller = new AbortController(); activeRequest.current = controller;
    try {
      let id = conversationId;
      if (!id) {
        id = await createConversation(selectedAgentId, controller.signal);
        if (controller.signal.aborted) return;
        setConversationId(id); saveConversationId(selectedAgentId, id);
        const conversation = {id, agent_id: selectedAgentId, title: "附件分析", created_at: new Date().toISOString()};
        setConversations((current) => [conversation, ...current]);
      }
      const uploaded = await uploadAttachment(id, file, controller.signal);
      if (!controller.signal.aborted) setAttachments((current) => [...current.filter((item) => item.id !== uploaded.id), uploaded]);
    } catch (caught) { if (!controller.signal.aborted) setError(errorText(caught)); }
    finally { operationRunning.current = false; if (mounted.current) setIsUploading(false); }
  }

  function selectAgent(agentId: string) {
    if (busy || operationRunning.current || agentId === selectedAgentId) return;
    activateAgent(agentId);
  }

  function activateAgent(agentId: string) {
    setSelectedAgentId(agentId);
    setConversationId(null);
    setConversations([]);
    setMessages([]);
    setPendingActions([]);
    setError("");
    setIsLoading(true);
  }

  function handleBuiltAgent(agent: AgentInfo) {
    setAgents((current) => current.some((item) => item.id === agent.id) ? current : [...current, agent]);
    if (agent.id !== selectedAgentId) activateAgent(agent.id);
  }

  async function handleCreateAgent(definition: CreateAgentInput) {
    if (busy || operationRunning.current) throw new Error("请等待当前操作完成后再创建 Agent。");
    operationRunning.current = true;
    const controller = new AbortController();
    activeRequest.current = controller;
    setIsCreatingAgent(true);
    try {
      const created = await createAgent(definition, controller.signal);
      if (controller.signal.aborted) return;
      setAgents((current) => [...current, created]);
      activateAgent(created.id);
    } finally {
      operationRunning.current = false;
      if (mounted.current) setIsCreatingAgent(false);
    }
  }

  function startNewConversation() {
    if (busy || operationRunning.current || !selectedAgentId) return;
    saveConversationId(selectedAgentId, null);
    setConversationId(null);
    setMessages([]);
    setPendingActions([]);
    setError("");
  }

  async function switchConversation(id: string) {
    if (!id) return startNewConversation();
    if (busy || operationRunning.current || id === conversationId) return;
    operationRunning.current = true;
    const controller = new AbortController();
    activeRequest.current = controller;
    setIsLoading(true);
    setError("");
    try {
      const [history, actions] = await Promise.all([
        fetchMessages(id, controller.signal), fetchActions(id, controller.signal),
      ]);
      if (controller.signal.aborted) return;
      setConversationId(id);
      setMessages(restoreMessages(history));
      setPendingActions(actions);
      saveConversationId(selectedAgentId, id);
    } catch (caughtError) {
      if (!controller.signal.aborted) setError(errorText(caughtError));
    } finally {
      operationRunning.current = false;
      if (mounted.current) setIsLoading(false);
    }
  }

  async function handleSend() {
    const content = input.trim();
    if (!content || !selectedAgentId || busy || operationRunning.current) return;
    operationRunning.current = true;
    setInput("");
    try { await sendContent(content); }
    finally { operationRunning.current = false; }
  }

  // Caller owns the operation lock. Browser continuation preserves a user's draft.
  async function sendContent(content: string) {
    const controller = new AbortController();
    activeRequest.current = controller;
    const assistant = createMessage("assistant", "");
    const assistantId = assistant.id!;
    assistant.status = "streaming";
    setIsSending(true);
    setError("");
    let id = conversationId;
    try {
      if (id === null) {
        id = await createConversation(selectedAgentId, controller.signal);
        if (controller.signal.aborted) return;
        setConversationId(id);
        saveConversationId(selectedAgentId, id);
        const newConversation = {
          id, agent_id: selectedAgentId, created_at: new Date().toISOString(), title: content,
        };
        setConversations((current) => [newConversation, ...current]);
      }
      setMessages((current) => [...current, createMessage("user", content), assistant]);
      await streamMessage(
        id, content,
        (text) => setMessages((current) => appendMessageText(current, assistantId, text)),
        (action) => setPendingActions((current) => upsertAction(current, action)),
        controller.signal,
        (evidence) => setMessages((current) => applyKnowledgeEvidence(current, assistantId, evidence)),
        (skills, mode) => setMessages((current) => applySkills(current, assistantId, skills, mode)),
        (usage) => setMessages((current) => current.map((message) => message.id === assistantId ? { ...message, usage } : message)),
      );
      if (!controller.signal.aborted) {
        setMessages((current) => finishMessage(current, assistantId));
      }
    } catch (caughtError) {
      if (!controller.signal.aborted) {
        setMessages((current) => finishMessage(current, assistantId, true));
        setError(errorText(caughtError));
      }
    } finally {
      if (mounted.current) setIsSending(false);
    }
  }

  async function resumeBrowser(sessionId: string) {
    if (!conversationId || busy || operationRunning.current) return;
    operationRunning.current = true;
    setIsSending(true);
    setError('');
    try {
      await returnBrowserControl(sessionId,
        () => browserTakeover(conversationId, sessionId, false),
        message => mounted.current && activeConversation.current === conversationId ? sendContent(message) : Promise.resolve());
    } catch (caughtError) { if (mounted.current) setError(errorText(caughtError)); }
    finally { operationRunning.current = false; if (mounted.current) setIsSending(false); }
  }

  async function handleDecision(id: string, approved: boolean) {
    const current = pendingActions.find(action=>action.id===id);
    if (!conversationId || !current || busy || operationRunning.current || uncertainActions.includes(id)) return;
    if (current.status!=='pending') return;
    if (approved && !approvalState(current).canApprove) {
      setActionErrors(errors=>({...errors,[id]:'清单已过期，请重新生成，尚未执行。'}));return;
    }
    const owner = conversationId;
    operationRunning.current = true;
    const controller = new AbortController();
    const timeout = setTimeout(()=>controller.abort(),45000);
    activeRequest.current = controller;
    setDecidingActionId(id);
    setActionErrors(errors=>({...errors,[id]:''}));
    setError("");
    try {
      const outcome = await decideAndReconcile(
        ()=>decidePendingAction(id, approved, controller.signal),
        ()=>fetchAction(owner,id,AbortSignal.timeout(8000)),
      );
      clearTimeout(timeout);
      if (!mounted.current || activeConversation.current!==owner) return;
      if (outcome.action) setPendingActions(actions=>upsertAction(actions,outcome.action!));
      setUncertainActions(actions=>outcome.uncertain ? [...actions.filter(key=>key!==id),id] : actions.filter(key=>key!==id));
      setActionErrors(errors=>({...errors,[id]:outcome.error||''}));
      if (outcome.executedHere && outcome.action) {
        refreshAttachments();
        if (outcome.action.message) setMessages(messages=>[...messages,createMessage('assistant',outcome.action!.message!)]);
        const continuation = approvedBrowserContinuation(outcome.action);
        if (continuation) await sendContent(continuation);
      }
    } finally {
      clearTimeout(timeout);
      operationRunning.current = false;
      if (mounted.current) setDecidingActionId("");
    }
  }

  return {
    attachments, isUploading, handleUpload, updateCapabilities, refreshAttachments,
    agents, selectedAgentId, conversationId, conversations, messages, pendingActions,
    input, setInput, error, busy, isLoading, isSending, decidingActionId,
    actionErrors, uncertainActions, actionSyncError, isRefreshingActions, refreshActions:()=>syncActions(true),
    selectAgent, startNewConversation, switchConversation, handleSend, handleDecision, handleCreateAgent, handleBuiltAgent, resumeBrowser,
  };
}
