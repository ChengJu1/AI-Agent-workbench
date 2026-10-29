// 按稳定 ID 更新流式消息，避免依赖“最后一条消息”的数组下标。
import type { ChatMessage, KnowledgeEvidence, PendingAction, SkillReference } from "../types";

export function createMessage(role: ChatMessage["role"], content: string): ChatMessage {
  return { id: crypto.randomUUID(), role, content, status: "complete" };
}

export function restoreMessages(messages: ChatMessage[]): ChatMessage[] {
  const restored: ChatMessage[] = [];
  for (const message of messages) restored.push({
    ...createMessage(message.role, message.content),
    ...(message.status ? { status: message.status } : {}),
    ...(message.knowledge ? { knowledge: message.knowledge } : {}),
    ...(message.skills ? { skills: message.skills } : {}),
    ...(message.skill_mode ? { skill_mode: message.skill_mode } : {}),
    ...(message.usage ? { usage: message.usage } : {}),
    ...(message.tool_activity ? { tool_activity: message.tool_activity } : {}),
    ...(message.attachments ? { attachments: message.attachments } : {}),
    ...(message.delegations ? { delegations: message.delegations } : {}),
    ...(message.delegated_by ? { delegated_by: message.delegated_by } : {}),
  });
  return restored;
}

export function appendMessageText(messages: ChatMessage[], id: string, text: string) {
  return messages.map((message) => {
    if (message.id !== id) return message;
    return { ...message, content: message.content + text };
  });
}

export function finishMessage(messages: ChatMessage[], id: string, failed = false) {
  const result: ChatMessage[] = [];
  for (const message of messages) {
    if (message.id !== id) {
      result.push(message);
    } else if (message.content || message.knowledge || message.skills !== undefined || message.usage || message.tool_activity?.length) {
      result.push({ ...message, status: failed ? "failed" : "complete" });
    }
  }
  return result;
}

/** The user stopped the reply: keep what arrived, or drop an empty placeholder. */
export function stopMessage(messages: ChatMessage[], id: string) {
  return messages.flatMap(message => message.id !== id ? [message]
    : message.content || message.knowledge || message.skills !== undefined ? [{ ...message, status: "stopped" as const }] : []);
}

export function applyKnowledgeEvidence(messages: ChatMessage[], id: string, knowledge: KnowledgeEvidence) {
  return messages.map((message) => message.id === id ? { ...message, knowledge } : message);
}

export function applySkills(messages: ChatMessage[], id: string, skills: SkillReference[], mode?: "on_demand") {
  return messages.map((message) => message.id === id ? { ...message, skills, ...(mode ? { skill_mode: mode } : {}) } : message);
}

export function upsertAction(actions: PendingAction[], updated: PendingAction): PendingAction[] {
  const result: PendingAction[] = [];
  let found = false;
  for (const action of actions) {
    if (action.id === updated.id) {
      // A late SSE event or an earlier poll must not revive a handled action.
      const terminal = !['pending', 'executing'].includes(action.status);
      result.push(terminal || action.status === 'executing' && updated.status === 'pending' ? action : updated);
      found = true;
    } else {
      result.push(action);
    }
  }
  if (!found) result.push(updated);
  return result;
}
