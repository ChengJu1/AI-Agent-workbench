// 渲染聊天消息；未变化的历史消息复用组件，流式更新只重绘当前消息。
import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../types";

const MessageBubble = memo(function MessageBubble({ message }: { message: ChatMessage }) {
  return (
    <div className={`message ${message.role}`}>
      <strong>{message.role === "user" ? "你" : "Agent"}</strong>
      {message.role === "assistant" && message.content ? (
        <div className="markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
        </div>
      ) : <p>{message.content || "正在回复..."}</p>}
      {message.status === "failed" && (
        <p className="messageStatus">回复已中断，上方保留了已收到的内容。</p>
      )}
    </div>
  );
});

export function MessageList({ messages, loading }: { messages: ChatMessage[]; loading: boolean }) {
  return (
    <div className="messages" aria-label="聊天消息" aria-busy={loading}>
      {messages.length === 0 ? (
        <div className="empty">{loading ? "正在加载会话..." : "还没有消息，发送一条消息开始对话。"}</div>
      ) : messages.map((message, index) => (
        <MessageBubble key={message.id ?? `${message.role}-${index}`} message={message} />
      ))}
    </div>
  );
}
