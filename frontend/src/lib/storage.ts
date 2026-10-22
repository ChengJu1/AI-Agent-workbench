// 浏览器存储只记住选择的会话；不可用时不影响正常聊天。
export function readConversationId(agentId: string): string | null {
  try {
    return localStorage.getItem(`conversation:${agentId}`);
  } catch {
    return null;
  }
}

export function saveConversationId(agentId: string, conversationId: string | null) {
  try {
    if (conversationId) localStorage.setItem(`conversation:${agentId}`, conversationId);
    else localStorage.removeItem(`conversation:${agentId}`);
  } catch {
    // 禁用 localStorage 的浏览器仍可使用本次会话。
  }
}
