import { useEffect, useRef, useState } from "react";
import { agentDefinition, newMcpServer } from "../lib/agentDefinitions";
import type { CreateAgentInput } from "../types";
import { McpServerEditor } from "./McpServerEditor";

type Props = {
  onCreate: (definition: CreateAgentInput) => Promise<void>;
  onClose: () => void;
};

export function AgentCreator({ onCreate, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [prompt, setPrompt] = useState("");
  const [servers, setServers] = useState(() => [newMcpServer()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  return (
    <dialog className="agentEditor" ref={dialog} aria-labelledby="agentEditorTitle"
      onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}>
      <form onSubmit={async (event) => {
        event.preventDefault();
        if (saving) return;
        setError("");
        try {
          const definition = agentDefinition(name, description, prompt, servers);
          setSaving(true);
          await onCreate(definition);
          onClose();
        } catch (error) {
          setError(error instanceof Error ? error.message : "创建失败，请重试。");
        } finally {
          setSaving(false);
        }
      }}>
        <h2 id="agentEditorTitle">创建你的 Agent</h2>
        <p className="agentEditorHint">设置提示词，连接 MCP 服务，并选择允许 Agent 使用的工具。</p>
        <fieldset className="agentBasics" disabled={saving}>
          <label>Agent 名称<input autoFocus required maxLength={100} value={name}
            onChange={(event) => setName(event.target.value)} placeholder="例如：团队制度助理" /></label>
          <label>用途说明<input required maxLength={1000} value={description}
            onChange={(event) => setDescription(event.target.value)} placeholder="这个 Agent 可以帮你做什么" /></label>
          <label>提示词<textarea required maxLength={50000} rows={5} value={prompt}
            onChange={(event) => setPrompt(event.target.value)} placeholder="描述 Agent 的职责、回答方式和工具使用规则" /></label>
        </fieldset>
        {servers.map((server) => (
          <McpServerEditor key={server.id} server={server} disabled={saving} removable={servers.length > 1}
            onChange={(updated) => setServers((current) => current.map((item) => item.id === updated.id ? updated : item))}
            onRemove={() => setServers((current) => current.filter((item) => item.id !== server.id))} />
        ))}
        <button type="button" disabled={saving || servers.length >= 10}
          onClick={() => setServers((current) => [...current, newMcpServer()])}>添加 MCP 服务</button>
        <p className="agentEditorHint">配置保存在当前工作台。填写的认证令牌也会保存在工作台数据库中。</p>
        {error && <p className="agentEditorError" role="alert">{error}</p>}
        <div className="agentEditorActions agentEditorFooter">
          <button type="button" disabled={saving} onClick={onClose}>取消</button>
          <button type="submit" className="primaryButton" disabled={saving}>
            {saving ? "正在创建…" : "创建并使用"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
