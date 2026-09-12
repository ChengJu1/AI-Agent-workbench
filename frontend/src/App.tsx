// 实现工作台的主要聊天界面、会话恢复和工时审批卡片。
// 它负责管理页面状态并调用 api.ts 与后端通信。
import { useEffect, useState } from "react";
import {
  createConversation,
  decidePendingAction,
  fetchAgents,
  fetchMessages,
  fetchPendingActions,
  streamMessage,
} from "./api";
import type {
  AgentInfo,
  ChatMessage,
  PendingAction,
} from "./types";

function App() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);   // 定义状态
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [decidingActionId, setDecidingActionId] = useState("");
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
      setPendingActions([]);
      return;
    }

    const activeSavedConversationId = savedConversationId;

    async function loadSavedConversation() {
      try {
        const savedMessages = await fetchMessages(
          activeSavedConversationId,
        );
        const savedPendingActions = await fetchPendingActions(
          activeSavedConversationId,
        );

        if (!isCurrentAgent) {
          return;
        }

        setConversationId(activeSavedConversationId);
        setMessages(savedMessages);
        setPendingActions(savedPendingActions);
      } catch {
        if (!isCurrentAgent) {
          return;
        }

        localStorage.removeItem(storageKey);
        setConversationId(null);
        setMessages([]);
        setPendingActions([]);
        setError("历史会话已失效，请发送消息开始新会话。");
      }
    }

    void loadSavedConversation();

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
    let receivedAssistantText = false;
    let assistantPlaceholderAdded = false;

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
      assistantPlaceholderAdded = true;

      await streamMessage(
        activeConversationId,
        content,
        (chunk) => {
          receivedAssistantText = true;

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
        (pendingAction) => {
          setPendingActions((currentActions) => {
            let alreadyExists = false;

            for (const currentAction of currentActions) {
              if (currentAction.id === pendingAction.id) {
                alreadyExists = true;
                break;
              }
            }

            if (alreadyExists) {
              return currentActions;
            }

            return [
              ...currentActions,
              pendingAction,
            ];
          });
        },
      );

      if (!receivedAssistantText) {
        setMessages((currentMessages) => {
          const messagesWithoutPlaceholder = (
            currentMessages.slice(0, -1)
          );

          return messagesWithoutPlaceholder;
        });
      }
    } catch (caughtError) {
      if (assistantPlaceholderAdded && !receivedAssistantText) {
        setMessages((currentMessages) => (
          currentMessages.slice(0, -1)
        ));
      }

      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "发送失败，请确认后端已经启动。",
      );
    } finally {
      setIsSending(false);
    }
  }

  async function handleDecision(
    pendingActionId: string,
    approved: boolean,
  ) {
    if (decidingActionId) {
      return;
    }

    setError("");
    setDecidingActionId(pendingActionId);

    try {
      const updatedAction = await decidePendingAction(
        pendingActionId,
        approved,
      );

      setPendingActions((currentActions) => {
        const updatedActions = [];

        for (const currentAction of currentActions) {
          if (currentAction.id === updatedAction.id) {
            updatedActions.push(updatedAction);
          } else {
            updatedActions.push(currentAction);
          }
        }

        return updatedActions;
      });

      if (updatedAction.message) {
        const resultMessage: ChatMessage = {
          role: "assistant",
          content: updatedAction.message,
        };

        setMessages((currentMessages) => [
          ...currentMessages,
          resultMessage,
        ]);
      }
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "处理确认操作失败。",
      );
    } finally {
      setDecidingActionId("");
    }
  }

  function getActionStatusText(status: string) {
    if (status === "pending") {
      return "等待确认";
    }

    if (status === "approved") {
      return "已确认并提交";
    }

    if (status === "cancelled") {
      return "已取消";
    }

    if (status === "failed") {
      return "执行失败";
    }

    return "处理中";
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
                setPendingActions([]);
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

        {pendingActions.length > 0 && (
          <div className="approvalList">
            {pendingActions.map((pendingAction) => (
              <section
                className="approvalCard"
                key={pendingAction.id}
              >
                <div className="approvalHeader">
                  <div>
                    <strong>工时提交确认</strong>
                    <span>
                      {getActionStatusText(pendingAction.status)}
                    </span>
                  </div>

                  {pendingAction.params.draft && (
                    <b>
                      {pendingAction.params.draft.total_hours} 小时
                    </b>
                  )}
                </div>

                {pendingAction.params.draft && (
                  <div className="timesheetRecords">
                    {pendingAction.params.draft.records.map(
                      (record, index) => (
                        <div
                          className="timesheetRecord"
                          key={`${record.date}-${record.task}-${index}`}
                        >
                          <span>{record.date}</span>
                          <span>{record.task}</span>
                          <span>{record.hours} 小时</span>
                          <span>{record.note || "无备注"}</span>
                        </div>
                      ),
                    )}
                  </div>
                )}

                {pendingAction.status === "pending" && (
                  <div className="approvalButtons">
                    <button
                      className="cancelButton"
                      disabled={Boolean(decidingActionId)}
                      onClick={() => {
                        void handleDecision(
                          pendingAction.id,
                          false,
                        );
                      }}
                      type="button"
                    >
                      取消
                    </button>

                    <button
                      className="approveButton"
                      disabled={Boolean(decidingActionId)}
                      onClick={() => {
                        void handleDecision(
                          pendingAction.id,
                          true,
                        );
                      }}
                      type="button"
                    >
                      {decidingActionId === pendingAction.id
                        ? "处理中..."
                        : "确认提交"}
                    </button>
                  </div>
                )}

                {pendingAction.result?.submission_id && (
                  <p className="submissionId">
                    提交编号：{pendingAction.result.submission_id}
                  </p>
                )}
              </section>
            ))}
          </div>
        )}

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
