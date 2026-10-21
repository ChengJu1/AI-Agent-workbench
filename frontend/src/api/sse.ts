// 解析 SSE 事件和跨网络分块的 UTF-8 字节，识别正常结束与意外断流。
import type { KnowledgeEvidence, RuntimeUsage, PendingAction, SkillReference, StreamEvent, ToolActivityEvent } from "../types";
import { parseKnowledgeEvidence } from "../lib/knowledgeCitations.ts";
import { parseSkillReferences } from "../lib/skills.ts";

export class SseParser {
  private buffer = "";

  push(text: string): StreamEvent[] {
    this.buffer += text;
    const frames = this.buffer.split(/\r?\n\r?\n/);
    this.buffer = frames.pop() ?? "";
    const events: StreamEvent[] = [];
    for (const frame of frames) {
      const lines = frame.split(/\r?\n/);
      const dataLines: string[] = [];
      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        let data = line.slice(5);
        if (data.startsWith(" ")) data = data.slice(1);
        dataLines.push(data);
      }
      if (dataLines.length === 0) continue;
      const event = parseEvent(dataLines.join("\n"));
      if (event) events.push(event);
    }
    return events;
  }
}

function parseEvent(data: string): StreamEvent | null {
  let value;
  try {
    value = JSON.parse(data);
  } catch {
    throw new Error("后端返回了无法解析的流式消息。");
  }
  if (!value || typeof value !== "object") throw new Error("流式消息格式不正确。");
  if (value.type === "tool_started" || value.type === "tool_finished") {
    if (typeof value.tool_name !== "string" || typeof value.call_id !== "string") {
      throw new Error("工具状态格式不正确。");
    }
    if (value.type === "tool_finished") {
      if (typeof value.success !== "boolean") throw new Error("工具结果缺少执行状态。");
      return { type: "tool_finished", tool_name: value.tool_name, call_id: value.call_id, success: value.success };
    }
    return { type: "tool_started", tool_name: value.tool_name, call_id: value.call_id };
  }
  if (value.type === "usage") {
    const usage = value.usage;
    if (!usage || !["claude_sdk", "deep_agents"].includes(usage.runtime) || !["complete", "failed"].includes(usage.status)) {
      throw new Error("用量统计格式不正确。");
    }
    for (const field of ["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "model_calls", "tool_calls", "first_token_ms", "duration_ms"]) {
      if (usage[field] !== null && (typeof usage[field] !== "number" || !Number.isFinite(usage[field]) || usage[field] < 0)) {
        throw new Error("用量统计数值不正确。");
      }
    }
    return { type: "usage", usage: usage as RuntimeUsage };
  }
  if (value.type === "done") return { type: "done" };
  if (value.type === "knowledge") return { type: "knowledge", evidence: parseKnowledgeEvidence(value.evidence) };
  if (value.type === "skills") {
    if (value.mode !== undefined && value.mode !== "on_demand") throw new Error("Skill 加载方式不正确。");
    return { type: "skills", skills: parseSkillReferences(value.skills), ...(value.mode ? { mode: value.mode } : {}) };
  }
  if (value.type === "delta" || value.type === "error") {
    if (typeof value.content !== "string") throw new Error("流式消息缺少文本内容。");
    return { type: value.type, content: value.content };
  }
  if (value.type === "approval_required") {
    if (!value.action || typeof value.action.id !== "string") {
      throw new Error("确认操作缺少有效的操作 ID。");
    }
    return { type: "approval_required", action: value.action as PendingAction };
  }
  return null;
}

type StreamHandlers = {
  onToolActivity?: (event: ToolActivityEvent) => void;
  onUsage?: (usage: RuntimeUsage) => void;
  onDelta: (text: string) => void;
  onApprovalRequired: (action: PendingAction) => void;
  onKnowledge?: (evidence: KnowledgeEvidence) => void;
  onSkills?: (skills: SkillReference[], mode?: "on_demand") => void;
};

export async function consumeEventStream(
  body: ReadableStream<Uint8Array>, handlers: StreamHandlers,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const parser = new SseParser();
  try {
    while (true) {
      const { value, done } = await reader.read();
      const text = done ? decoder.decode() : decoder.decode(value, { stream: true });
      for (const event of parser.push(text)) {
        if (event.type === "done") return;
        if (event.type === "error") throw new Error(event.content);
        if (event.type === "usage") handlers.onUsage?.(event.usage);
        if (event.type === "tool_started" || event.type === "tool_finished") handlers.onToolActivity?.(event);
        if (event.type === "delta") handlers.onDelta(event.content);
        if (event.type === "approval_required") handlers.onApprovalRequired(event.action);
        if (event.type === "knowledge") handlers.onKnowledge?.(event.evidence);
        if (event.type === "skills") handlers.onSkills?.(event.skills, event.mode);
      }
      if (done) throw new Error("回复连接意外中断，已保留收到的内容。");
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      // 请求已被取消时，不用取消错误覆盖原始错误。
    }
    reader.releaseLock();
  }
}
