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
  return <fieldset className="skillPicker" disabled={disabled}>
    <legend>绑定 Skill</legend>
    <p className="agentEditorHint">最多 5 个，所选版本正文合计不超过 80000 字符。初始只提供名称和用途，正文按需读取；版本由你选择并固定。</p>
    {!skills.length && <p className="agentEditorHint">暂无自定义 Skill，请先到侧栏的 Skill 管理中创建或导入。</p>}
    {skills.map((skill) => {
      const binding = selected.find((item) => item.id === skill.id);
      return <SkillChoice key={skill.id} skill={skill} binding={binding} disabled={disabled || (!binding && selected.length >= 5)}
        onToggle={(checked) => onChange(checked ? [...selected, { id: skill.id, version: skill.version }] : selected.filter((item) => item.id !== skill.id))}
        onVersion={(version) => onChange(selected.map((item) => item.id === skill.id ? { ...item, version } : item))} />;
    })}
  </fieldset>;
}
