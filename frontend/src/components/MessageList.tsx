// 渲染聊天消息；未变化的历史消息复用组件，流式更新只重绘当前消息。
import { memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage, KnowledgeCitation } from "../types";
import { AnswerEvidence } from "./AnswerEvidence";
import { CitationPreview } from "./CitationPreview";
import { citationIdFromLink } from "../lib/knowledgeCitations";
import { WorkbenchIcon } from "./WorkbenchIcon";

const MessageBubble = memo(function MessageBubble({ message, agentName }: { message: ChatMessage; agentName?: string }) {
  const [activeSource, setActiveSource] = useState<KnowledgeCitation | null>(null);
  return (
    <div className={`message ${message.role}`}>
      <div className="messageSpeaker"><span className="speakerAvatar" aria-hidden="true">{message.role === "user" ? "你" : <WorkbenchIcon name="spark" />}</span>
        <strong>{message.role === "user" ? "你" : agentName || "Agent"}</strong></div>
      {message.role === "assistant" && message.content ? (
        <div className="markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
            a: ({ href, children }) => {
              const id = citationIdFromLink(href);
              if (id !== null) {
                const index = message.knowledge?.citations.findIndex((source) => source.citation_id === id) ?? -1;
                const source = message.knowledge?.citations[index];
                return source ? <a href={href} className="citationButton" aria-haspopup="dialog"
                  aria-label={`引用 ${index + 1}：${source.filename}`} title={`预览 ${source.filename} 并定位引用片段`}
                  onClick={(event) => { event.preventDefault(); setActiveSource(source); }}>[{index + 1}]</a>
                  : <span className="unverifiedCitation" title="此引用没有对应的本轮检索来源">{children}（未核验）</span>;
              }
              return <a href={href}>{children}</a>;
            },
          }}>{message.content}</ReactMarkdown>
        </div>
      ) : <p>{message.content || (message.status === "streaming" ? "正在回复..." : "本轮未生成回答。")}</p>}
      {message.role === "assistant" && message.knowledge && <AnswerEvidence knowledge={message.knowledge}
        content={message.content} streaming={message.status === "streaming"} onOpen={setActiveSource} />}
      {message.status === "failed" && (
        <p className="messageStatus">回复已中断，上方保留了已收到的内容。</p>
      )}
      {message.role === "assistant" && Boolean(message.skills?.length) && <div className="messageSkills" aria-label="本轮加载的 Skill">
        本轮加载{message.skills!.map((skill) => <span key={skill.id}>{skill.name} · v{skill.version}</span>)}
      </div>}
      {activeSource && <CitationPreview source={activeSource} onClose={() => setActiveSource(null)} />}
    </div>
  );
});

export function MessageList({ messages, loading, agentName }: { messages: ChatMessage[]; loading: boolean; agentName?: string }) {
  return (
    <div className="messages" aria-label="聊天消息" aria-busy={loading}>
      {messages.length === 0 ? (
        <div className="empty">{loading ? "正在加载会话..." : "还没有消息，发送一条消息开始对话。"}</div>
      ) : messages.map((message, index) => (
        <MessageBubble key={message.id ?? `${message.role}-${index}`} message={message} agentName={agentName} />
      ))}
    </div>
  );
}
