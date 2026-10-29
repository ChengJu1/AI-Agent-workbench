// 删除不可恢复，统一在这里写确认文案，侧边栏和归档窗口共用。
export function confirmAgentDelete(name: string) {
  return window.confirm(`永久删除 Agent「${name}」？\n它的所有对话、文件和执行记录也会一起删除，无法恢复。`);
}

export function conversationTitle(title: string | null | undefined) {
  return title?.trim() || "未命名对话";
}

export function confirmConversationDelete(title: string | null | undefined) {
  return window.confirm(`永久删除对话「${conversationTitle(title)}」？\n删除后无法恢复。`);
}
