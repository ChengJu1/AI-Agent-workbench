import type { AgentInfo, ChatMessage } from "./types";

const API_BASE = "http://localhost:8000";

async function request(url: string, options?: RequestInit): Promise<Response> {
  let response: Response;

  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("无法连接后端，请先启动后端服务。");
  }

  if (!response.ok) {
    if (response.status === 404) {
      throw new Error("请求的会话或服务不存在，请刷新页面后重试。");
    }

    throw new Error("后端服务暂时不可用，请稍后重试。");
  }

  return response;
}

export async function fetchAgents(): Promise<AgentInfo[]> { // 向后端 GET /api/agents 发送请求，并将 JSON 响应解析为 AgentInfo 数组
  const response = await request(`${API_BASE}/api/agents`);
  return response.json();
}

export async function createConversation(agentId: string): Promise<string> { // 用户在前端创建对话之后post给后端，同时提取response中的对话id并返回
  const response = await request(`${API_BASE}/api/conversations`, {
    method: "POST",
    headers: { // 告诉后端请求体使用 JSON 格式
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ agent_id: agentId }), // 将 JavaScript 对象转换为 JSON 字符串，作为请求正文发送
  });

  const data = await response.json();
  return data.conversation_id;
}

export async function fetchMessages(
  conversationId: string,
): Promise<ChatMessage[]> {
  const response = await request(
    `${API_BASE}/api/conversations/${conversationId}/messages`,
  );

  return response.json();
}

export async function streamMessage( // 发送用户消息，读取后端的流式响应，并通过 onDelta 逐段通知 App.tsx
  conversationId: string,
  content: string,
  onDelta: (chunk: string) => void,
): Promise<void> {
  const response = await request(
    `${API_BASE}/api/conversations/${conversationId}/messages/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ content }),
    },
  );

  if (!response.body) {
    throw new Error("后端没有返回可读取的回复，请稍后重试。");
  }

  const reader = response.body.getReader(); // 从responsebody以二进制的形式提取agent回复
  const decoder = new TextDecoder(); // 定义解码器 从二进制转回文字
  let buffer = "";

  while (true) { // 持续读取数据流；每次 read() 返回本次数据 value 和结束标记 done
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });// 将本次收到的字节解码为文字，并追加到缓冲区
    const events = buffer.split("\n\n"); // SSE 事件以两个换行结束，据此拆分完整事件
    buffer = events.pop() ?? ""; // 保留最后一段可能不完整的数据，等待下一批字节到达后继续拼接

    for (const event of events) {
      if (!event.startsWith("data: ")) {
        continue;
      }

      const payload = JSON.parse(event.slice(6));  // 去掉 "data: " 并将 JSON 字符串解析为对象
      if (payload.type === "delta") { // 把本次回复片段交给 App.tsx 更新页面
        onDelta(payload.content);
      }
      if (payload.type === "error") {
        throw new Error("模型回复失败，请检查后端日志和模型配置。");
      }
    }
  }
}
