// 统一维护会话标题和操作状态文案。
import type { ConversationInfo, PendingAction } from "../types";

export function conversationLabel(conversation: ConversationInfo): string {
  const createdAt = conversation.created_at.replace("T", " ").slice(0, 16);
  const title = conversation.title?.trim().replace(/\s+/g, " ");
  if (!title) return `${createdAt} · ${conversation.id.slice(0, 8)}`;
  const shortTitle = title.length > 28 ? `${title.slice(0, 28)}…` : title;
  return `${shortTitle} · ${createdAt}`;
}

export function actionStatusText(status: PendingAction["status"]): string {
  const labels = {
    pending: "等待确认", executing: "处理中", approved: "已确认并提交",
    cancelled: "已取消", failed: "执行失败",
  };
  return labels[status] ?? "处理中";
}
