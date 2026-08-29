import { useEffect, useState } from "react";
import {
  createConversation,
  fetchAgents,
  fetchMessages,
  streamMessage,
} from "./api";
import type { AgentInfo, ChatMessage } from "./types";

function App() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);   // 定义状态
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { //  把agents列表提取出来，默认是第一个agent
    void fetchAgents()
      .then((data) => {
        setAgents(data);
        if (data.length > 0) {
          setSelectedAgentId(data[0].id);
        }
      })
      .catch((caughtError) => {
        setError(
          caughtError instanceof Error
            ? caughtError.message
            : "无法加载 Agent，请确认后端已经启动。",
        );
      });
  }, []);

  useEffect(() => {
    if (!selectedAgentId) {
      return;
    }

    let isCurrentAgent = true;
    const storageKey = `conversation:${selectedAgentId}`;
    const savedConversationId = localStorage.getItem(storageKey);

    if (!savedConversationId) {
      setConversationId(null);
      setMessages([]);
      return;
    }

    void fetchMessages(savedConversationId)
      .then((savedMessages) => {
        if (!isCurrentAgent) {
          return;
        }

        setConversationId(savedConversationId);
        setMessages(savedMessages);
      })
      .catch(() => {
        if (!isCurrentAgent) {
          return;
        }

        localStorage.removeItem(storageKey);
        setConversationId(null);
        setMessages([]);
        setError("历史会话已失效，请发送消息开始新会话。");
      });

    return () => {
      isCurrentAgent = false;
    };
  }, [selectedAgentId]);

  async function handleSend() {
    const content = input.trim(); // trim()删除开头结尾的空格 防止用户输入空格也发送消息

    if (!content || !selectedAgentId || isSending){ // "||" 代表 "or" 判断用户有没有输入 有没有选agent 上一条消息是不是还在发送或者接收中
      return;
    }

    setError("");
    setIsSending(true);
    setInput(""); // 用户输入后 输入的东西会从输入框中消失

    let activeConversationId = conversationId;

    try {
      if (activeConversationId === null) {
        activeConversationId = await createConversation(selectedAgentId); //以目前的agentid创建一个对话码 随机生成的
        setConversationId(activeConversationId);
        localStorage.setItem(
          `conversation:${selectedAgentId}`,
          activeConversationId,
        );
      }

      const userMessage: ChatMessage = {
        role: "user",
        content,
      };

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: "",
      };

      setMessages((currentMessages) => [ // 保留原消息，并追加用户消息和空的助手消息
        ...currentMessages,
        userMessage,
        assistantMessage,
      ]);

      await streamMessage(
        activeConversationId,
        content,
        (chunk) => {
          setMessages((currentMessages) =>
            currentMessages.map((message, index) => { // 遍历所有消息，message 是当前消息，index 是当前数组下标
              if (index !== currentMessages.length - 1) { // 非最后一条消息保持不变，只让最后一条继续执行下面的更新
                return message;
              }

              return { // 把最后一条消息拼接
                ...message,
                content: message.content + chunk,
              };
            }),
          );
        },
      );
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "发送失败，请确认后端已经启动。",
      );
    } finally {
      setIsSending(false);
    }
  }

  return ( // 网页前端设置
    <main className="app">
      <section className="chatShell">
        <header className="header">
          <div>
            <h1>AI Agent Workbench</h1>
            <p>选择一个 Agent，然后开始对话。</p>
          </div>

          <label className="agentSelector">
            <span>Agent</span>

             {/* 创建下拉选项框，选择不同的agent */}
            <select
              value={selectedAgentId}
              onChange={(event) => {
                setSelectedAgentId(event.target.value);
                setConversationId(null);
                setMessages([]);
              }}
            >
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
        </header>

        <div className="messages">
          {messages.length === 0 ? (
            <div className="empty">还没有消息，发送一条消息开始对话。</div>
          ) : (
            messages.map((message, index) => (
              <div
                className={`message ${message.role}`}
                key={`${message.role}-${index}`}
              >
                <strong>{message.role === "user" ? "你" : "Agent"}</strong>
                <p>{message.content || "正在回复..."}</p>
              </div>
            ))
          )}
        </div>

        {error && <p className="error">{error}</p>}

        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            void handleSend();
          }}
        >
          <input
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="输入你的消息"
            disabled={isSending}
          />

          <button
            type="submit"
            disabled={!input.trim() || !selectedAgentId || isSending}
          >
            {isSending ? "回复中..." : "发送"}
          </button>
        </form>
      </section>
    </main>
  );
}

export default App;
