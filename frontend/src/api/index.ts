// 定义工作台 API；请求、流式解析和页面状态分别维护。
import type {
  AgentInfo, ChatMessage, ConversationInfo, CreateAgentInput,
  KnowledgeEvidence, McpConnection, McpToolInfo, PendingAction, SkillReference, RuntimeName, ToolActivityEvent,
} from "../types";
import { jsonBody, request, requestJson } from "./http";
import { consumeEventStream } from "./sse";

export function fetchAgents(signal?: AbortSignal) {
  return requestJson<AgentInfo[]>("/api/agents", { signal });
}

export function createAgent(definition: CreateAgentInput, signal?: AbortSignal) {
  return requestJson<AgentInfo>("/api/agents", { ...jsonBody(definition), signal });
}

export function discoverMcpTools(connection: McpConnection, signal?: AbortSignal) {
  return requestJson<McpToolInfo[]>("/api/mcp/tools", { ...jsonBody(connection), signal });
}

export async function createConversation(agentId: string, signal?: AbortSignal, runtime?: RuntimeName) {
  return requestJson<{ conversation_id: string; runtime: RuntimeName }>(
    "/api/conversations", { ...jsonBody({ agent_id: agentId, ...(runtime ? { runtime } : {}) }), signal },
  );
}

export function fetchRuntimeOptions(signal?: AbortSignal) {
  return requestJson<{ deep_agents_enabled: boolean }>("/api/runtime-options", { signal });
}

export function saveDefaultRuntime(agentId: string, runtime: RuntimeName, signal?: AbortSignal) {
  return requestJson<{ runtime: RuntimeName }>(`/api/agents/${encodeURIComponent(agentId)}/runtime`, { ...jsonBody({ runtime }), method: "PUT", signal });
}

export function fetchWorkSummary(id: string, signal?: AbortSignal) {
  return requestJson<{ summary: string; source_runtime: RuntimeName }>(`/api/conversations/${encodeURIComponent(id)}/work-summary`, { signal });
}

export function copyWorkSummary(id: string, runtime: RuntimeName, summary: string, signal?: AbortSignal) {
  return requestJson<{ conversation_id: string; runtime: RuntimeName }>(`/api/conversations/${encodeURIComponent(id)}/copy-summary`, { ...jsonBody({ runtime, summary }), signal });
}

export function fetchConversations(agentId: string, signal?: AbortSignal) {
  return requestJson<ConversationInfo[]>(
    `/api/agents/${encodeURIComponent(agentId)}/conversations`, { signal },
  );
}

export function fetchMessages(conversationId: string, signal?: AbortSignal) {
  return requestJson<ChatMessage[]>(
    `/api/conversations/${encodeURIComponent(conversationId)}/messages`, { signal },
  );
}

export function fetchActions(conversationId: string, signal?: AbortSignal) {
  return requestJson<PendingAction[]>(`/api/conversations/${encodeURIComponent(conversationId)}/actions`, {signal});
}

export function fetchAction(conversationId: string, actionId: string, signal?: AbortSignal) {
  return requestJson<PendingAction>(`/api/conversations/${encodeURIComponent(conversationId)}/actions/${encodeURIComponent(actionId)}`, {signal});
}

export function decidePendingAction(actionId: string, approved: boolean, signal?: AbortSignal) {
  return requestJson<PendingAction>(
    `/api/pending-actions/${encodeURIComponent(actionId)}/decision`,
    { ...jsonBody({ approved }), signal },
  );
}

export async function streamMessage(
  conversationId: string, content: string,
  onDelta: (text: string) => void,
  onApprovalRequired: (action: PendingAction) => void,
  signal?: AbortSignal,
  onKnowledge?: (evidence: KnowledgeEvidence) => void,
  onSkills?: (skills: SkillReference[], mode?: "on_demand") => void,
  onUsage?: (usage: import("../types").RuntimeUsage) => void,
  onToolActivity?: (event: ToolActivityEvent) => void,
) {
  const response = await request(
    `/api/conversations/${encodeURIComponent(conversationId)}/messages/stream`,
    { ...jsonBody({ content }), signal },
  );
  if (!response.body) throw new Error("后端没有返回可读取的回复。");
  await consumeEventStream(response.body, { onDelta, onApprovalRequired, onKnowledge, onSkills, onUsage, onToolActivity });
}
