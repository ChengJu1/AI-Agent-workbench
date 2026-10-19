import type { SkillInfo } from "../types";

export function SkillPicker({ skills, selected, disabled, onChange }: {
  skills: SkillInfo[]; selected: string[]; disabled: boolean; onChange: (ids: string[]) => void;
}) {
  return <fieldset className="skillPicker" disabled={disabled}>
    <legend>绑定 Skill</legend>
    <p className="agentEditorHint">最多 5 个，正文合计不超过 80000 字符。每轮加载当前版本，工具权限仍由 Agent 配置决定。</p>
    {!skills.length && <p className="agentEditorHint">暂无自定义 Skill，请先到侧栏的 Skill 管理中创建或导入。</p>}
    {skills.map((skill) => <label className="skillChoice" key={skill.id}>
      <input type="checkbox" checked={selected.includes(skill.id)} disabled={!selected.includes(skill.id) && selected.length >= 5}
        onChange={(event) => onChange(event.target.checked ? [...selected, skill.id] : selected.filter((id) => id !== skill.id))} />
      <span><strong>{skill.name}</strong><small>v{skill.version}</small><span>{skill.description}</span></span>
    </label>)}
  </fieldset>;
}
