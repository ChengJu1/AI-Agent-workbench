import type { AgentInfo } from "../types";
import { WorkbenchIcon } from "./WorkbenchIcon";

export function ConversationWelcome({ agent, disabled, onPrompt }: {
  agent?: AgentInfo; disabled: boolean; onPrompt: (prompt: string) => void;
}) {
  const isTimesheet = /工时/.test(agent?.name ?? "");
  const isNotes = /笔记/.test(agent?.name ?? "");
  const isKnowledge = /知识|制度/.test(agent?.name ?? "");
  const prompts = isTimesheet ? [
    { title: "整理本周工时", text: "帮我整理本周工时。请先询问日期、任务和时长，再生成草稿供我确认。", detail: "从工作记录到清晰的工时草稿", icon: "chat" as const },
    { title: "拆解工作记录", text: "我想把今天的工作记录整理成工时条目，请先告诉我需要提供哪些信息。", detail: "把零散记录整理成任务条目", icon: "book" as const },
    { title: "了解助理能力", text: "介绍一下你可以帮我完成哪些任务，以及开始前需要哪些信息。", detail: "了解可以交给 Agent 的事情", icon: "spark" as const },
  ] : isNotes ? [
    { title: "查找笔记内容", text: "请查找我的笔记中关于 Transformer 工作流程的解释，并提供原文引用。", detail: "带着问题，找到对应的原文", icon: "search" as const },
    { title: "梳理一个主题", text: "我想梳理笔记中的一个主题，请先询问我要整理的主题，再检索相关内容并附上引用。", detail: "将分散的知识串成清晰脉络", icon: "book" as const },
    { title: "理解核心概念", text: "请帮我理解笔记中的一个概念，先询问具体概念，再结合检索到的原文和例子解释。", detail: "结合笔记和例子，加深理解", icon: "spark" as const },
  ] : isKnowledge ? [
    { title: "查找相关资料", text: "我想查找一项制度或资料，请先询问我的具体问题，再检索相关内容并提供原文引用。", detail: "从具体问题，找到有据可查的答案", icon: "search" as const },
    { title: "梳理办理流程", text: "请帮我梳理一项事务的办理流程，先询问具体事项，再结合检索到的资料列出步骤和注意事项。", detail: "整理步骤、条件与注意事项", icon: "book" as const },
    { title: "了解 Agent 能力", text: "介绍一下你可以帮我查询哪些资料，以及你目前可以使用哪些工具。", detail: "了解可查询的资料和协作方式", icon: "spark" as const },
  ] : [
    { title: "开始一项任务", text: "我想完成一项新任务，请先帮我明确目标、所需信息和下一步。", detail: "把目标拆成可以执行的步骤", icon: "chat" as const },
    { title: "整理我的想法", text: "帮我整理一些零散的想法。请先询问我想讨论的主题，再一起梳理。", detail: "从零散灵感，走向清晰思路", icon: "book" as const },
    { title: "了解 Agent 能力", text: "介绍一下你可以帮我做什么，以及你目前可以使用哪些工具。", detail: "找到适合当前任务的协作方式", icon: "spark" as const },
  ];
  return <div className="conversationWelcome">
    <div className="welcomeEyebrow"><span className="welcomeAgentIcon"><WorkbenchIcon name="spark" /></span>{agent?.name ?? "AI Agent Workbench"}</div>
    <h1>今天，想完成什么？</h1>
    <p className="welcomeDescription">{agent?.description || "选择一个 Agent，一起探索想法、查找知识、推进工作。"}</p>
    <div className="promptGrid">{prompts.map((prompt) => <button key={prompt.title} className="promptCard"
      disabled={disabled || !agent} onClick={() => onPrompt(prompt.text)}>
      <WorkbenchIcon name={prompt.icon} /><strong>{prompt.title}</strong><span>{prompt.detail}</span><b aria-hidden="true">↗</b>
    </button>)}</div>
    <p className="welcomeHint">选择一个灵感，或在下方输入你的问题</p>
  </div>;
}
