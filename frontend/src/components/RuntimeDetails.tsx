import type { ChatMessage } from "../types";
import { runtimeLabel, tokenLabel, toolActivityRows } from "../lib/runtime";

export function RuntimeDetails({ message }: { message: ChatMessage }) {
  const usage = message.usage;
  const tools = toolActivityRows(message.tool_activity ?? []);
  if (!usage && !tools.length) return null;
  return <details className="runtimeDetails">
    <summary>{usage ? `本轮用量 · 输入 ${tokenLabel(usage.input_tokens)} · 输出 ${tokenLabel(usage.output_tokens)} token` : `工具活动 · ${tools.length} 项`}</summary>
    {usage && <dl>
      <dt>运行时</dt><dd>{runtimeLabel(usage.runtime)}</dd>
      <dt>输入 / 输出 token</dt><dd>{tokenLabel(usage.input_tokens)} / {tokenLabel(usage.output_tokens)}</dd>
      <dt>缓存读取 / 写入 token</dt><dd>{tokenLabel(usage.cache_read_input_tokens)} / {tokenLabel(usage.cache_creation_input_tokens)}</dd>
      <dt>模型 / 工具调用</dt><dd>{tokenLabel(usage.model_calls)} / {tokenLabel(usage.tool_calls)}</dd>
      <dt>首字 / 总耗时</dt><dd>{usage.first_token_ms === null ? "未提供" : `${(usage.first_token_ms / 1000).toFixed(2)} 秒`} / {(usage.duration_ms / 1000).toFixed(2)} 秒</dd>
    </dl>}
    {tools.length > 0 && <ul aria-label="本轮工具状态">{tools.map(tool => <li key={tool.id}>
      <span>{tool.name.replace(/^mcp__/, "").replace(/__/g, " · ")}</span>
      <span>{tool.status === "running" ? (message.status === "streaming" ? "处理中" : "未收到完成结果") : tool.status === "success" ? "已返回" : "失败"}</span>
    </li>)}</ul>}
    <p>未提供的用量不按 0 计算。工具返回不代表审批通过或业务已提交。</p>
  </details>;
}
