import { useEffect, useRef, useState } from "react";
import { agentDefinition, newMcpServer } from "../lib/agentDefinitions";
import type { CreateAgentInput } from "../types";
import { McpServerEditor } from "./McpServerEditor";
import { fetchKnowledgeBases } from "../api/knowledge";
import { KnowledgeBasePicker } from "./KnowledgeBasePicker";
import type { KnowledgeBaseInfo } from "../types";
import type { McpServerDraft } from "../lib/agentDefinitions";
import { fetchSkills } from "../api/skills";
import type { SkillBinding, SkillInfo } from "../types";
import { skillBindingFields } from "../lib/skills";
import { CapabilityPicker } from "./CapabilityPicker";
import type { Capability } from "../api/platform";
import "./platform.css";
import { SkillPicker } from "./SkillPicker";

type Props = {
  onCreate: (definition: CreateAgentInput) => Promise<void>;
  onClose: () => void;
};

export function AgentCreator({ onCreate, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [platformCapabilities, setPlatformCapabilities] = useState<Capability[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [prompt, setPrompt] = useState("");
  const [servers, setServers] = useState<McpServerDraft[]>([]);
  const [bases, setBases] = useState<KnowledgeBaseInfo[]>([]);
  const [selectedBases, setSelectedBases] = useState<string[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [selectedSkills, setSelectedSkills] = useState<SkillBinding[]>([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(true);
  const [knowledgeError, setKnowledgeError] = useState("");
  const [knowledgeAttempt, setKnowledgeAttempt] = useState(0);
  const submitting = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setKnowledgeLoading(true);
    setKnowledgeError("");
    void Promise.all([fetchKnowledgeBases(controller.signal), fetchSkills(controller.signal)]).then(([result, availableSkills]) => {
      if (!controller.signal.aborted) { setBases(result); setSkills(availableSkills); }
    }).catch((error) => {
      if (!controller.signal.aborted) setKnowledgeError(error instanceof Error ? error.message : "无法读取知识库。");
    }).finally(() => { if (!controller.signal.aborted) setKnowledgeLoading(false); });
    return () => controller.abort();
  }, [knowledgeAttempt]);

  return (
    <dialog className="agentEditor" ref={dialog} aria-labelledby="agentEditorTitle"
      onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}>
      <form onSubmit={async (event) => {
        event.preventDefault();
        if (submitting.current || knowledgeLoading) return;
        setError("");
        try {
          const fields = skillBindingFields(selectedSkills);
          const definition = agentDefinition(name, description, prompt, servers, selectedBases, fields.skill_ids, fields.skill_versions, platformCapabilities);
          submitting.current = true;
          setSaving(true);
          await onCreate(definition);
          onClose();
        } catch (error) {
          setError(error instanceof Error ? error.message : "创建失败，请重试。");
        } finally {
          submitting.current = false;
          setSaving(false);
        }
      }}>
        <h2 id="agentEditorTitle">创建你的 Agent</h2>
        <p className="agentEditorHint">设置提示词，绑定 Skill、知识库或连接 MCP 工具；也可以只使用 Skill。</p>
        <fieldset className="agentBasics" disabled={saving}>
          <label>Agent 名称<input autoFocus required maxLength={100} value={name}
            onChange={(event) => setName(event.target.value)} placeholder="例如：团队制度助理" /></label>
          <label>用途说明<input required maxLength={1000} value={description}
            onChange={(event) => setDescription(event.target.value)} placeholder="这个 Agent 可以帮你做什么" /></label>
          <label>提示词<textarea required maxLength={50000} rows={5} value={prompt}
            onChange={(event) => setPrompt(event.target.value)} placeholder="描述 Agent 的职责、回答方式和工具使用规则" /></label>
        </fieldset>
        <CapabilityPicker selected={platformCapabilities} onChange={setPlatformCapabilities} disabled={saving} />
        {knowledgeLoading ? <p role="status">正在读取知识库…</p> :
          <KnowledgeBasePicker bases={bases} selected={selectedBases} disabled={saving} onChange={setSelectedBases} />}
        {knowledgeError && <p role="alert" className="agentEditorError">{knowledgeError}
          <button type="button" disabled={saving} onClick={() => setKnowledgeAttempt((current) => current + 1)}>重新读取配置</button>
        </p>}
        {!knowledgeLoading && <SkillPicker skills={skills} selected={selectedSkills} disabled={saving} onChange={setSelectedSkills} />}
        {servers.map((server) => (
          <McpServerEditor key={server.id} server={server} disabled={saving} removable
            onChange={(updated) => setServers((current) => current.map((item) => item.id === updated.id ? updated : item))}
            onRemove={() => setServers((current) => current.filter((item) => item.id !== server.id))} />
        ))}
        <button type="button" disabled={saving || servers.length >= 10}
          onClick={() => setServers((current) => [...current, newMcpServer()])}>添加 MCP 服务</button>
        <p className="agentEditorHint">配置保存在当前工作台。填写的认证令牌也会保存在工作台数据库中。</p>
        {error && <p className="agentEditorError" role="alert">{error}</p>}
        <div className="agentEditorActions agentEditorFooter">
          <button type="button" disabled={saving} onClick={onClose}>取消</button>
          <button type="submit" className="primaryButton" disabled={saving || knowledgeLoading}>
            {saving ? "正在创建…" : "创建并使用"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
