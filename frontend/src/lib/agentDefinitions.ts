import type { CreateAgentInput, McpConnection } from "../types";

export type McpServerDraft = {
  id: string;
  name: string;
  transport: "http" | "sse";
  url: string;
  token: string;
  actions: string[];
};

export function newMcpServer(): McpServerDraft {
  const id = crypto.randomUUID();
  return { id, name: `mcp_${id.slice(0, 8)}`, transport: "http", url: "", token: "", actions: [] };
}

export function mcpConnection(server: McpServerDraft): McpConnection {
  const connection: McpConnection = {
    name: server.name.trim(), transport: server.transport, url: server.url.trim(),
  };
  if (server.token.trim()) connection.headers = { Authorization: `Bearer ${server.token.trim()}` };
  return connection;
}

export function agentDefinition(
  name: string, description: string, prompt: string, servers: McpServerDraft[],
): CreateAgentInput {
  if (!name.trim() || !description.trim() || !prompt.trim()) {
    throw new Error("请填写 Agent 名称、说明和提示词。");
  }
  if (!servers.length || servers.some((server) => !server.actions.length)) {
    throw new Error("请为每个 MCP 服务读取工具，并至少选择一个工具。");
  }
  const names = servers.map((server) => server.name.trim());
  if (new Set(names).size !== names.length) throw new Error("每个 MCP 连接需要使用不同的名称。");
  return {
    name: name.trim(), description: description.trim(), system_prompt: prompt.trim(),
    tools: servers.map((server) => ({ type: "mcp", ...mcpConnection(server), actions: [...server.actions] })),
  };
}
