import { useEffect, useRef, useState } from "react";
import { MarkdownContent } from "./MarkdownContent";
import { fetchSkills, fetchSkillVersions, previewSkillImport, saveSkill } from "../api/skills";
import { skillMarkdown } from "../lib/skills";
import type { SkillDefinition, SkillInfo } from "../types";
import "./skills.css";

const blank: SkillDefinition = { name: "", description: "", content: "" };
const definitionOf = (skill: SkillDefinition): SkillDefinition => ({ name: skill.name, description: skill.description, content: skill.content });
const errorText = (error: unknown) => error instanceof Error ? error.message : "操作失败，请重试。";

export function SkillManager({ onClose, onBind }: { onClose: () => void; onBind?: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const operation = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [selected, setSelected] = useState<SkillInfo | null>(null);
  const [draft, setDraft] = useState<SkillDefinition>(blank);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [preview, setPreview] = useState(false);
  const [history, setHistory] = useState(false);
  const [versions, setVersions] = useState<SkillInfo[]>([]);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [historyError, setHistoryError] = useState("");
  const dirty = JSON.stringify(draft) !== JSON.stringify(selected ? definitionOf(selected) : blank);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => { element?.close(); operation.current?.abort(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    void fetchSkills(controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setSkills(items); setLoaded(true);
    }).catch((error) => { if (!controller.signal.aborted) setError(errorText(error)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);
  useEffect(() => {
    const controller = new AbortController();
    setVersions([]); setHistoryError(""); setHistoryVersion(0);
    if (selected && history) {
      void fetchSkillVersions(selected.id, controller.signal).then((items) => {
        if (!controller.signal.aborted) { setVersions(items); setHistoryVersion(items[0]?.version ?? 0); }
      }).catch((error) => { if (!controller.signal.aborted) setHistoryError(errorText(error)); });
    }
    return () => controller.abort();
  }, [selected, history]);

  function canLeave() {
    if (busy) return false;
    if (dirty) { setError("有未保存的修改，请先保存，或点击“放弃修改”。"); return false; }
    return true;
  }
  function choose(skill: SkillInfo | null) {
    if (!canLeave()) return;
    setSelected(skill); setDraft(skill ? definitionOf(skill) : blank);
    setError(""); setNotice(""); setPreview(false); setHistory(false);
  }
  function exportFile() {
    const target = history ? versions.find((item) => item.version === historyVersion) : draft;
    if (!target) return;
    const url = URL.createObjectURL(new Blob([skillMarkdown(target)], { type: "text/markdown;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "SKILL.md"; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const historical = versions.find((item) => item.version === historyVersion);
  const displayed = history ? historical : draft;
  return <dialog className="agentEditor skillManager" ref={dialog} aria-labelledby="skillManagerTitle"
    onCancel={(event) => { event.preventDefault(); if (canLeave()) onClose(); }}>
    <header className="skillManagerHeader"><div><h2 id="skillManagerTitle">Skill 管理</h2>
      <p className="agentEditorHint">保存可复用的工作方法，绑定为可用目录，由 Agent 按任务读取正文。</p></div>
      <button type="button" disabled={busy} onClick={() => { if (canLeave()) onClose(); }}>关闭</button>
    </header>
    <div className="skillManagerToolbar">
      <button type="button" disabled={loading || busy || !loaded} onClick={() => choose(null)}>新建 Skill</button>
      <button type="button" disabled={loading || busy || !loaded} onClick={() => { if (canLeave()) fileInput.current?.click(); }}>导入 SKILL.md</button>
      {onBind && <button type="button" disabled={busy || loading} onClick={() => { if (canLeave()) onBind(); }}>绑定到当前 Agent</button>}
      <input ref={fileInput} type="file" accept=".md,text/markdown" className="srOnly" tabIndex={-1} aria-label="选择 Skill 文件"
        onChange={async (event) => {
          const file = event.target.files?.[0]; event.target.value = "";
          if (!file || submitting.current) return;
          setError(""); setNotice("");
          if (file.size > 128 * 1024) { setError("Skill 文件不能超过 128 KB。"); return; }
          submitting.current = true; setBusy(true);
          const controller = new AbortController(); operation.current = controller;
          try {
            const content = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
            const imported = await previewSkillImport(file.name, content, controller.signal);
            if (controller.signal.aborted) return;
            setSelected(null); setDraft(definitionOf(imported)); setHistory(false); setPreview(false);
            setNotice(`已读取文件，请检查后保存。${imported.ignored_fields.length ? `以下元信息未启用：${imported.ignored_fields.join("、")}。` : ""}`);
          } catch (error) { if (!controller.signal.aborted) setError(errorText(error)); }
          finally { submitting.current = false; if (!controller.signal.aborted) setBusy(false); }
        }} />
    </div>
    {error && <p className="agentEditorError" role="alert">{error}</p>}
    {notice && <p className="skillNotice" role="status">{notice}</p>}
    {loading ? <p role="status">正在读取 Skill…</p> : !loaded ?
      <button type="button" onClick={() => setAttempt((value) => value + 1)}>重新读取</button> :
      <div className="skillManagerBody">
        <aside className="skillLibrary" aria-label="Skill 列表"><span className="skillLibraryCount">我的 Skill · {skills.length}</span>
          {skills.map((skill) => <button type="button" className={selected?.id === skill.id ? "isSelected" : ""}
            key={skill.id} aria-pressed={selected?.id === skill.id} disabled={busy} onClick={() => choose(skill)}>
            <strong>{skill.name}<small>v{skill.version}</small></strong><span>{skill.description}</span>
          </button>)}
          {!skills.length && <p className="agentEditorHint">从一个工作方法开始，例如需求拆解、接口检查或周报整理。</p>}
        </aside>
        <form className="skillEditForm" onSubmit={async (event) => {
          event.preventDefault();
          if (submitting.current || !dirty) return;
          submitting.current = true; setBusy(true); setError(""); setNotice("");
          const controller = new AbortController(); operation.current = controller;
          try {
            const saved = await saveSkill(draft, selected ?? undefined, controller.signal);
            if (controller.signal.aborted) return;
            setSkills((items) => [saved, ...items.filter((item) => item.id !== saved.id)]);
            setSelected(saved); setDraft(definitionOf(saved));
            setNotice(`已保存 ${saved.name} · v${saved.version}。已绑定的 Agent 从下一轮可按需读取此版本。`);
          } catch (error) { if (!controller.signal.aborted) setError(errorText(error)); }
          finally { submitting.current = false; if (!controller.signal.aborted) setBusy(false); }
        }}>
          <div className="skillEditTitle"><h3>{selected ? selected.name : "新建 Skill"}</h3>
            <span>{selected ? `v${selected.version}` : "文本规则"}{dirty ? " · 未保存" : ""}</span></div>
          <fieldset disabled={busy || history} className="skillFields">
            <label>Skill 名称<input required maxLength={100} value={draft.name} placeholder="例如：需求拆解"
              onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
            <label>用途与适用场景<input required maxLength={1000} value={draft.description} placeholder="说明什么时候使用，以及要解决的问题"
              onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
          </fieldset>
          <div className="skillViewActions">
            <button type="button" disabled={busy} aria-pressed={!preview && !history} onClick={() => { setPreview(false); setHistory(false); }}>编辑正文</button>
            <button type="button" disabled={busy} aria-pressed={preview && !history} onClick={() => { setPreview(true); setHistory(false); }}>预览</button>
            {selected && <><button type="button" disabled={busy} aria-pressed={history} onClick={() => setHistory(true)}>版本记录</button>
              <button type="button" disabled={busy || dirty || (history && !historical)} onClick={exportFile}>导出 SKILL.md</button></>}
          </div>
          {history && <div className="skillHistory" aria-label="Skill 版本记录">
            {historyError ? <p role="alert">{historyError}</p> : !versions.length ? <p role="status">正在读取版本…</p> :
              <label>查看版本<select aria-label="查看版本" value={historyVersion} onChange={(event) => setHistoryVersion(Number(event.target.value))}>
                {versions.map((item) => <option key={item.version} value={item.version}>v{item.version} · {new Date(`${item.updated_at.replace(" ", "T")}Z`).toLocaleString("zh-CN", { hour12: false })}</option>)}
              </select></label>}
            {historical && <p><strong>{historical.name}</strong> · {historical.description}</p>}
          </div>}
          {preview || history ? <MarkdownContent className="skillMarkdown" label="Skill 正文预览"
            components={{ img: ({ alt }) => <span className="markdownImagePlaceholder">图片：{alt || "未提供说明"}</span> }}>
              {displayed?.content || "尚无正文。"}
          </MarkdownContent> : <label>工作步骤与规则<textarea required rows={12} maxLength={30000} value={draft.content}
            placeholder={"## 适用场景\n\n## 工作步骤\n1. …\n\n## 输出要求\n\n## 无法完成时的处理"}
            disabled={busy} onChange={(event) => setDraft({ ...draft, content: event.target.value })} /></label>}
          <p className="agentEditorHint">支持 Markdown 正文，每个 Skill 最多 30000 字符。本版不加载脚本、附件或额外工具权限。</p>
          <div className="agentEditorActions agentEditorFooter">
            {dirty && <button type="button" disabled={busy} onClick={() => {
              setDraft(selected ? definitionOf(selected) : blank); setError(""); setNotice("");
            }}>放弃修改</button>}
            <button type="submit" className="primaryButton" disabled={busy || !dirty || history}>{busy ? "正在处理…" : "保存 Skill"}</button>
          </div>
        </form>
      </div>}
  </dialog>;
}
