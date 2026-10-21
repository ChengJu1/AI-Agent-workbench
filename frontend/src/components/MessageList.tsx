// 渲染聊天消息；未变化的历史消息复用组件，流式更新只重绘当前消息。
import { memo, useEffect, useLayoutEffect, useRef, useState } from "react";
import { MarkdownContent } from "./MarkdownContent";
import type { ChatMessage, KnowledgeCitation } from "../types";
import { AnswerEvidence } from "./AnswerEvidence";
import { CitationPreview } from "./CitationPreview";
import { citationIdFromLink } from "../lib/knowledgeCitations";
import { WorkbenchIcon } from "./WorkbenchIcon";
import { skillLoadLabel } from "../lib/skills";

const MessageBubble = memo(function MessageBubble({ message, agentName }: { message: ChatMessage; agentName?: string }) {
  const [activeSource, setActiveSource] = useState<KnowledgeCitation | null>(null);
  const [copied, setCopied] = useState(false);
  const skillLabel = skillLoadLabel(message);
  const copy = async () => {
    try { await navigator.clipboard.writeText(message.content); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* Clipboard may be blocked; nothing to undo. */ }
  };
  return (
    <div className={`message ${message.role}${message.status === "streaming" ? " isStreaming" : ""}`}>
      {/* The bubble's side already says who wrote it; only the Agent gets a name line. */}
      {message.role === "user" ? <span className="srOnly">你：</span>
        : <div className="messageSpeaker"><span className="speakerAvatar" aria-hidden="true"><WorkbenchIcon name="spark" /></span><strong>{agentName || "Agent"}</strong></div>}
      {message.role === "assistant" && message.content ? (
          <MarkdownContent components={{
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
              return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
            },
          }}>{message.content}</MarkdownContent>
      ) : message.status === "streaming" && !message.content
        ? <p className="typingDots" role="status" aria-label="正在回复"><span /><span /><span /></p>
        : <p>{message.content || "本轮未生成回答。"}</p>}
      {message.role === "assistant" && message.knowledge && <AnswerEvidence knowledge={message.knowledge}
        content={message.content} streaming={message.status === "streaming"} onOpen={setActiveSource} />}
      {message.status === "stopped" && <p className="messageStatus">已停止生成，上方保留了已生成的内容。</p>}
      {message.status === "failed" && (
        <p className="messageStatus">回复已中断，上方保留了已收到的内容。</p>
      )}
      {message.role === "assistant" && skillLabel && <div className="messageSkills" aria-label="Skill 读取记录">
        {skillLabel}{message.skills!.map((skill) => <span key={skill.id}>{skill.name} · v{skill.version}</span>)}
      </div>}
      {message.role === "assistant" && message.content && message.status !== "streaming" && <div className="messageActions">
        <button type="button" onClick={() => void copy()} aria-label="复制这条回答">{copied ? "已复制" : "复制"}</button>
      </div>}
      {activeSource && <CitationPreview source={activeSource} onClose={() => setActiveSource(null)} />}
    </div>
  );
});

// Within this distance of the bottom the list keeps following new output; further up, the user is reading and is left alone.
const FOLLOW_DISTANCE = 80;

export function MessageList({ messages, loading, agentName }: { messages: ChatMessage[]; loading: boolean; agentName?: string }) {
  const list = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const seen = useRef({ count: 0, loading: true });
  const [away, setAway] = useState(false);

  const toBottom = (smooth: boolean) => {
    const element = list.current;
    if (!element) return;
    follow.current = true;
    setAway(false);
    element.scrollTo({ top: element.scrollHeight, behavior: smooth && !reducedMotion() ? "smooth" : "auto" });
  };

  useLayoutEffect(() => {
    const previous = seen.current;
    seen.current = { count: messages.length, loading };
    const last = messages[messages.length - 1];
    const sentNow = messages.length > previous.count && messages.slice(previous.count).some(m => m.role === "user");
    if (previous.loading && !loading) toBottom(false);  // A conversation just opened: start at its latest message.
    else if (sentNow) toBottom(true);                    // The user sent something: always bring it into view.
    else if (follow.current) toBottom(last?.status !== "streaming");
  }, [messages, loading]);

  // Markdown, tables and evidence can grow after render; keep following while the user has not scrolled away.
  useEffect(() => {
    const element = list.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => { if (follow.current) element.scrollTop = element.scrollHeight; });
    for (const child of Array.from(element.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [messages.length]);

  const onScroll = () => {
    const element = list.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    follow.current = distance < FOLLOW_DISTANCE;
    setAway(distance > FOLLOW_DISTANCE * 3);
  };

  return (
    <div className="messagesFrame">
      <div className="messages" ref={list} onScroll={onScroll} aria-label="聊天消息" aria-busy={loading}>
        {messages.length === 0 ? (
          <div className="empty">{loading ? "正在加载会话..." : "还没有消息，发送一条消息开始对话。"}</div>
        ) : messages.map((message, index) => (
          <MessageBubble key={message.id ?? `${message.role}-${index}`} message={message} agentName={agentName} />
        ))}
      </div>
      {away && <button type="button" className="jumpToLatest" onClick={() => toBottom(true)}>
        {messages[messages.length - 1]?.status === "streaming" ? "正在回复 · 回到最新" : "回到最新"}</button>}
    </div>
  );
}

function reducedMotion() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}
