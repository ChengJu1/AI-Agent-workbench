// 统一维护会话标题文案。
import type { ConversationInfo } from "../types";

export function conversationLabel(conversation: ConversationInfo): string {
  const createdAt = conversation.created_at.replace("T", " ").slice(0, 16);
  const title = conversation.title?.trim().replace(/\s+/g, " ");
  if (!title) return `${createdAt} · ${conversation.id.slice(0, 8)}`;
  const shortTitle = title.length > 28 ? `${title.slice(0, 28)}…` : title;
  return `${shortTitle} · ${createdAt}`;
}

