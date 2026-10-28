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

const AGENT_KEY = "workbench:agent";

// 记住上次选择的 Agent，刷新后回到它；不可用时退回第一个。
export function readAgentId(): string | null {
  try {
    return localStorage.getItem(AGENT_KEY);
  } catch {
    return null;
  }
}

export function saveAgentId(agentId: string) {
  try {
    localStorage.setItem(AGENT_KEY, agentId);
  } catch {
    // 禁用 localStorage 时只是不记住选择。
  }
}

// 侧边栏各区块的展开状态，默认展开。
export function readSectionOpen(section: string): boolean {
  try {
    return localStorage.getItem(`sidebar:${section}`) !== "closed";
  } catch {
    return true;
  }
}

export function saveSectionOpen(section: string, open: boolean) {
  try {
    localStorage.setItem(`sidebar:${section}`, open ? "open" : "closed");
  } catch {
    // 禁用 localStorage 时只是不记住展开状态。
  }
}
