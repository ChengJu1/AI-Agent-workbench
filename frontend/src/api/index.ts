// 定义工作台 API；请求、流式解析和页面状态分别维护。
import type {
  AgentInfo, ChatMessage, ConversationInfo, CreateAgentInput,
  KnowledgeEvidence, McpConnection, McpToolInfo, PendingAction, SkillReference, ToolActivityEvent,
} from "../types";
import { jsonBody, request, requestJson } from "./http";
import { consumeEventStream } from "./sse";

export function fetchAgents(signal?: AbortSignal) {
  return requestJson<AgentInfo[]>("/api/agents", { signal });
}

export function createAgent(definition: CreateAgentInput, signal?: AbortSignal) {
  return requestJson<AgentInfo>("/api/agents", { ...jsonBody(definition), signal });
}

export function setAgentArchived(agentId: string, archived: boolean) {
  return requestJson<AgentInfo>(`/api/agents/${encodeURIComponent(agentId)}/archived`,
    { ...jsonBody({ archived }), method: "PUT" });
}

export function deleteAgent(agentId: string) {
  return requestJson<{ deleted: boolean; conversations: number }>(
    `/api/agents/${encodeURIComponent(agentId)}`, { method: "DELETE" });
}

export function setConversationArchived(conversationId: string, archived: boolean) {
  return requestJson<{ archived: boolean }>(`/api/conversations/${encodeURIComponent(conversationId)}/archived`,
    { ...jsonBody({ archived }), method: "PUT" });
}

export function fetchArchivedConversations(signal?: AbortSignal) {
  return requestJson<(ConversationInfo & { archived_at: string })[]>("/api/conversations/archived", { signal });
}

export function deleteConversation(conversationId: string) {
  return requestJson<{ deleted: boolean }>(
    `/api/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
}

export function discoverMcpTools(connection: McpConnection, signal?: AbortSignal) {
  return requestJson<McpToolInfo[]>("/api/mcp/tools", { ...jsonBody(connection), signal });
}

export async function createConversation(agentId: string, signal?: AbortSignal) {
  return requestJson<{ conversation_id: string }>(
    "/api/conversations", { ...jsonBody({ agent_id: agentId }), signal },
  );
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
  attachmentIds: string[] = [],
) {
  await streamReply(`/api/conversations/${encodeURIComponent(conversationId)}/messages/stream`,
    { content, ...(attachmentIds.length ? { attachment_ids: attachmentIds } : {}) }, signal,
    { onDelta, onApprovalRequired, onKnowledge, onSkills, onUsage, onToolActivity });
}

/** Resume the Agent once after this turn's actions were decided; the server builds the notice from its records. */
export function continueAfterActions(
  conversationId: string, actionId: string, signal: AbortSignal, handlers: Parameters<typeof consumeEventStream>[1],
) {
  return streamReply(`/api/conversations/${encodeURIComponent(conversationId)}/continue`, { action_id: actionId }, signal, handlers);
}

async function streamReply(path: string, body: unknown, signal: AbortSignal | undefined, handlers: Parameters<typeof consumeEventStream>[1]) {
  const response = await request(path, { ...jsonBody(body), signal });
  if (!response.body) throw new Error("后端没有返回可读取的回复。");
  await consumeEventStream(response.body, handlers);
}
