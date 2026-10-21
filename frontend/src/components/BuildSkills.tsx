import { useEffect, useState } from "react";
import type { Build, ReusedSkill, SkillDraft } from "../api/builds";
import { fetchSkillVersion } from "../api/skills";
import type { SkillDefinition } from "../types";
import { MarkdownContent } from "./MarkdownContent";

const skillComponents = { img: ({ alt }: { alt?: string }) => <span className="markdownImagePlaceholder">图片：{alt || "未提供说明"}</span> };

function SkillReference({ skill }: { skill: ReusedSkill }) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setError(""); setContent("");
    void fetchSkillVersion(skill.skill_id, skill.version, controller.signal).then((item) => {
      if (!controller.signal.aborted) setContent(item.content);
    }).catch((caught) => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "读取失败。"); });
    return () => controller.abort();
  }, [open, skill.skill_id, skill.version]);
  return <article className="builderSkill">
    <strong>{skill.name} <small>v{skill.version} · {skill.coverage === "partial" ? "部分复用" : "直接复用"}</small></strong>
    <p>{skill.description}</p><p className="builderSkillReason">{skill.reason}</p>
    <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? "收起正文" : `查看 v${skill.version} 正文`}</button>
    {open && (error ? <p role="alert">{error}</p> : content ? <MarkdownContent components={skillComponents}>{content}</MarkdownContent> : <p role="status">正在读取…</p>)}
  </article>;
}

function DraftEditor({ draft, disabled, onResolve }: {
  draft: SkillDraft; disabled: boolean; onResolve: (action: "save" | "discard", definition?: SkillDefinition) => void;
}) {
  const [definition, setDefinition] = useState<SkillDefinition>({ name: draft.name, description: draft.description, content: draft.content });
  const [preview, setPreview] = useState(true);
  return <article className="builderSkill builderSkillDraft">
    <strong>建议新增 · {draft.name}</strong><p>{draft.reason}</p>
    <details><summary>审阅或编辑草稿</summary>
      <label>Skill 名称<input aria-label="草稿 Skill 名称" maxLength={100} disabled={disabled} value={definition.name} onChange={(event) => setDefinition({ ...definition, name: event.target.value })} /></label>
      <label>用途与适用场景<input aria-label="草稿 Skill 用途" maxLength={1000} disabled={disabled} value={definition.description} onChange={(event) => setDefinition({ ...definition, description: event.target.value })} /></label>
      <button type="button" disabled={disabled} onClick={() => setPreview((value) => !value)}>{preview ? "编辑正文" : "预览正文"}</button>
      {preview ? <MarkdownContent components={skillComponents}>{definition.content}</MarkdownContent> : <label>工作步骤与规则<textarea aria-label="草稿 Skill 正文" rows={10} maxLength={30000} disabled={disabled} value={definition.content} onChange={(event) => setDefinition({ ...definition, content: event.target.value })} /></label>}
    </details>
    <div className="builderSkillActions"><button type="button" disabled={disabled || !definition.name.trim() || !definition.description.trim() || !definition.content.trim()} onClick={() => onResolve("save", definition)}>保存 Skill 并用于此 Agent</button>
      <button type="button" disabled={disabled} onClick={() => onResolve("discard")}>不采用</button></div>
    <small>点击保存会加入你的 Skill 库；创建 Agent 时固定绑定该版本。</small>
  </article>;
}

export function BuildSkills({ build, pending, onResolve }: {
  build: Build; pending: boolean;
  onResolve: (index: number, action: "save" | "discard", definition?: SkillDefinition) => void;
}) {
  const refs = build.plan?.reused_skills || [];
  const drafts = build.plan?.skill_drafts || [];
  return <section className="builderSkills" aria-label="Skill 复用检查">
    <h4>Skill 复用检查</h4>
    {build.skill_review ? <p>已检查用途目录，实际读取 {build.skill_review.read_skills.length} 个 Skill 版本；计划使用 {refs.length} 个。</p> : <p>这份历史方案尚未进行 Skill 复用检查，可补充需求重新生成。</p>}
    {!!build.skill_review?.queries.length && <details><summary>查看目录查询记录</summary><ul>{build.skill_review.queries.map((query, index) => <li key={index}>{query.query || "浏览用途目录"} · 返回 {query.returned}/{query.total_matches} 项{query.offset ? ` · 从第 ${query.offset + 1} 项开始` : ""}</li>)}</ul><small>查询目录不代表已读正文，也不代表已检查全部条目。</small></details>}
    {refs.map((skill) => <SkillReference key={`${skill.skill_id}:${skill.version}`} skill={skill} />)}
    {!refs.length && build.skill_review && <p>当前方案没有绑定已有 Skill。可以补充要求，让构建助手重新检查。</p>}
    {drafts.map((draft, index) => <DraftEditor key={`${build.id}:${build.revision}:${index}`} draft={draft} disabled={pending || build.status !== "ready"} onResolve={(action, definition) => onResolve(index, action, definition)} />)}
    {(refs.length > 0 || drafts.length > 0) && <small>Skill 提供工作方法，工具权限单独配置；发布新版本不会自动升级本 Agent。</small>}
  </section>;
}
