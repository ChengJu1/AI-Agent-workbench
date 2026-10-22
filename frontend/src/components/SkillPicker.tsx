import { useEffect, useState } from "react";
import { fetchSkillVersions } from "../api/skills";
import type { SkillBinding, SkillInfo } from "../types";

function SkillChoice({ skill, binding, disabled, onToggle, onVersion }: {
  skill: SkillInfo; binding?: SkillBinding; disabled: boolean;
  onToggle: (checked: boolean) => void; onVersion: (version: number) => void;
}) {
  const [versions, setVersions] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const checked = Boolean(binding);
  useEffect(() => {
    if (!checked) return;
    const controller = new AbortController();
    setLoading(true); setError(""); setVersions([]);
    void fetchSkillVersions(skill.id, controller.signal).then((items) => {
      if (!controller.signal.aborted) setVersions(items);
    }).catch((error) => {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "读取版本失败。");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [skill.id, skill.version, checked, attempt]);
  const current = versions.find((item) => item.version === binding?.version);
  return <div className="skillChoiceRow">
    <label className="skillChoice">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onToggle(event.target.checked)} />
      <span><strong>{current?.name ?? skill.name}</strong><small>{binding ? `已选 v${binding.version}` : `最新 v${skill.version}`}</small>
        <span>{current?.description ?? (binding && binding.version !== skill.version ? "读取所选版本的用途…" : skill.description)}</span></span>
    </label>
    {binding && <div className="skillVersionChoice">
      <label>使用版本<select aria-label={`${skill.name}使用版本`} value={binding.version} disabled={disabled || loading || !versions.length}
        onChange={(event) => onVersion(Number(event.target.value))}>
        {!versions.some((item) => item.version === binding.version) && <option value={binding.version}>v{binding.version}（已选）</option>}
        {versions.map((item) => <option key={item.version} value={item.version}>v{item.version}{item.version === skill.version ? "（最新）" : ""}</option>)}
      </select></label>
      {loading && <span role="status">正在读取版本…</span>}
      {error && <div className="agentEditorError" role="alert">{error}
        <button type="button" disabled={disabled} onClick={() => setAttempt((value) => value + 1)}>重试读取版本</button>
      </div>}
    </div>}
  </div>;
}

export function SkillPicker({ skills, selected, disabled, onChange }: {
  skills: SkillInfo[]; selected: SkillBinding[]; disabled: boolean; onChange: (bindings: SkillBinding[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [selectedOnly, setSelectedOnly] = useState(false);
  const [visibleCount, setVisibleCount] = useState(25);
  const selectedIds = new Set(selected.map((item) => item.id));
  const filtered = skills.filter((skill) => (!selectedOnly || selectedIds.has(skill.id)) &&
    `${skill.name} ${skill.description}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <fieldset className="skillPicker" disabled={disabled}>
    <legend>绑定 Skill</legend>
    <p className="agentEditorHint">绑定数量与正文总量不限，版本由你选择并固定。模型按需读取正文，本轮实际读取量受可配置的上下文预算约束；用途目录较大时先搜索。</p>
    {skills.length > 0 && <div className="skillPickerFilters">
      <label>搜索 Skill<input type="search" value={query} placeholder="按名称或用途筛选"
        onChange={(event) => { setQuery(event.target.value); setVisibleCount(25); }} /></label>
      <label className="skillSelectedFilter"><input type="checkbox" checked={selectedOnly}
        onChange={(event) => { setSelectedOnly(event.target.checked); setVisibleCount(25); }} />仅看已选</label>
      <p className="agentEditorHint" role="status">已选 {selected.length} 个 · 共 {skills.length} 个可用。筛选不会解除已有绑定。</p>
    </div>}
    {!skills.length && <p className="agentEditorHint">暂无自定义 Skill，请先到侧栏的 Skill 管理中创建或导入。</p>}
    {skills.length > 0 && !filtered.length && <p className="agentEditorHint">没有匹配的 Skill，请调整筛选条件。</p>}
    {filtered.slice(0, visibleCount).map((skill) => {
      const binding = selected.find((item) => item.id === skill.id);
      return <SkillChoice key={skill.id} skill={skill} binding={binding} disabled={disabled}
        onToggle={(checked) => onChange(checked ? [...selected, { id: skill.id, version: skill.version }] : selected.filter((item) => item.id !== skill.id))}
        onVersion={(version) => onChange(selected.map((item) => item.id === skill.id ? { ...item, version } : item))} />;
    })}
    {filtered.length > visibleCount && <button type="button" onClick={() => setVisibleCount((count) => count + 25)}>
      显示更多（已显示 {visibleCount} / {filtered.length}）
    </button>}
  </fieldset>;
}
