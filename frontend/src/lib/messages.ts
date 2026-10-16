// 按稳定 ID 更新流式消息，避免依赖“最后一条消息”的数组下标。
import type { ChatMessage, PendingAction } from "../types";

export function createMessage(role: ChatMessage["role"], content: string): ChatMessage {
  return { id: crypto.randomUUID(), role, content, status: "complete" };
}

export function restoreMessages(messages: ChatMessage[]): ChatMessage[] {
  const restored: ChatMessage[] = [];
  for (const message of messages) restored.push(createMessage(message.role, message.content));
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
    } else if (message.content) {
      result.push({ ...message, status: failed ? "failed" : "complete" });
    }
  }
  return result;
}

export function upsertAction(actions: PendingAction[], updated: PendingAction): PendingAction[] {
  const result: PendingAction[] = [];
  let found = false;
  for (const action of actions) {
    if (action.id === updated.id) {
      result.push(updated);
      found = true;
    } else {
      result.push(action);
    }
  }
  if (!found) result.push(updated);
  return result;
}
