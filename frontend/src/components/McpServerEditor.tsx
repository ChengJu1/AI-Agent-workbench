import { useEffect, useRef, useState } from "react";
import { discoverMcpTools } from "../api";
import { mcpConnection, type McpServerDraft } from "../lib/agentDefinitions";
import type { McpToolInfo } from "../types";

type Props = {
  server: McpServerDraft;
  disabled: boolean;
  removable: boolean;
  onChange: (server: McpServerDraft) => void;
  onRemove: () => void;
};

export function McpServerEditor({ server, disabled, removable, onChange, onRemove }: Props) {
  const [tools, setTools] = useState<McpToolInfo[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  function changeConnection(update: Partial<McpServerDraft>) {
    request.current?.abort();
    setLoading(false);
    setTools(null);
    setError("");
    onChange({ ...server, ...update, actions: [] });
  }

  async function discover() {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError("");
    setTools(null);
    onChange({ ...server, actions: [] });
    try {
      const result = await discoverMcpTools(mcpConnection(server), controller.signal);
      if (!controller.signal.aborted) setTools(result);
    } catch (error) {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "无法读取工具。");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return (
    <fieldset className="mcpServer" disabled={disabled}>
      <legend>MCP 服务</legend>
      <div className="agentFieldRow">
        <label>连接名称（英文）
          <input required value={server.name} maxLength={64} pattern="[A-Za-z][A-Za-z0-9_\-]*"
            onChange={(event) => changeConnection({ name: event.target.value })} />
        </label>
        <label>连接方式
          <select value={server.transport} onChange={(event) => changeConnection({
            transport: event.target.value as "http" | "sse",
          })}>
            <option value="http">Streamable HTTP</option><option value="sse">SSE</option>
          </select>
        </label>
      </div>
      <label>服务地址
        <input type="url" required value={server.url} placeholder="http://localhost:8059/mcp"
          onChange={(event) => changeConnection({ url: event.target.value })} />
      </label>
      <label>Bearer 令牌（可选）
        <input type="password" value={server.token} autoComplete="off"
          onChange={(event) => changeConnection({ token: event.target.value })} />
      </label>
      <div className="agentEditorActions">
        <button type="button" disabled={loading || !server.url.trim() || !server.name.trim()}
          onClick={() => void discover()}>{loading ? "正在连接…" : "连接并读取工具"}</button>
        {removable && <button type="button" onClick={onRemove}>移除此服务</button>}
      </div>
      {error && <p role="alert" className="agentEditorError">{error}</p>}
      {tools && tools.length === 0 && <p className="agentEditorHint">连接成功，此服务没有提供工具。</p>}
      {tools && tools.length > 0 && (
        <div className="mcpTools" aria-label={`${server.name} 的工具`}>
          <p className="agentEditorHint">已读取 {tools.length} 个工具，已选择 {server.actions.length} 个。</p>
          {tools.map((tool) => (
            <div className="mcpTool" key={tool.name}>
              <label className="toolChoice">
                <input type="checkbox" checked={server.actions.includes(tool.name)}
                  onChange={(event) => onChange({ ...server, actions: event.target.checked
                    ? [...server.actions, tool.name] : server.actions.filter((name) => name !== tool.name) })} />
                <span><strong>{tool.name}</strong>{tool.description && <span>{tool.description}</span>}</span>
              </label>
              <details><summary>查看参数</summary><pre>{JSON.stringify(tool.input_schema, null, 2)}</pre></details>
            </div>
          ))}
        </div>
      )}
    </fieldset>
  );
}
