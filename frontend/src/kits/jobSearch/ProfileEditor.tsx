// Reviewable resume profile; every save creates an immutable version that kits pin.
import { useEffect, useState } from "react";
import { deleteProfile, fetchProfile, fetchProfiles, saveProfile, type Education, type Period, type Profile, type ProfileData, type ProfileSummary } from "./api";
import { formatDate, parseDate } from "./lib";

const BASICS = [["name", "姓名"], ["phone", "手机"], ["email", "邮箱"], ["city", "所在城市"]] as const;
const EMPTY: ProfileData = { basics: {}, education: [], experience: [], projects: [], skills: [], answers: {} };
type EducationDraft = { school: string; degree: string; major: string; start: string; end: string; present: boolean };

const toDraft = (e: Education): EducationDraft => ({ school: e.school, degree: e.degree, major: e.major, start: formatDate(e.period.start),
  end: formatDate(e.period.end), present: e.period.present });

export function ProfileEditor({ initialId }: { initialId?: string } = {}) {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [current, setCurrent] = useState<Profile | null>(null);
  const [name, setName] = useState("我的简历");
  const [basics, setBasics] = useState<Record<string, string>>({});
  const [education, setEducation] = useState<EducationDraft[]>([]);
  const [skills, setSkills] = useState("");
  const [periods, setPeriods] = useState<{ experience: Period[]; projects: Period[] }>({ experience: [], projects: [] });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = (profile: Profile | null) => {
    setCurrent(profile);
    const data = profile?.data ?? EMPTY;
    setName(profile?.name ?? "我的简历");
    setBasics(data.basics);
    setEducation(data.education.map(toDraft));
    setSkills(data.skills.join("、"));
    setPeriods({ experience: data.experience, projects: data.projects });
  };
  useEffect(() => { void fetchProfiles().then(setProfiles); }, []);
  useEffect(() => { if (initialId) void fetchProfile(initialId).then(load); }, [initialId]);

  async function save() {
    setBusy(true); setMessage("");
    try {
      const rows: Education[] = education.map(e => {
        const start = parseDate(e.start), end = e.present ? null : parseDate(e.end);
        if (!start || (!e.present && !end)) throw new Error(`“${e.school || "教育经历"}”的时间请写成 2024 或 2024-09，结束时间与“至今”二选一。`);
        return { school: e.school, degree: e.degree, major: e.major, period: { start, end, present: e.present } };
      });
      const data: ProfileData = { ...(current?.data ?? EMPTY), basics: Object.fromEntries(Object.entries(basics).filter(([, v]) => v.trim())),
        education: rows, ...periods, skills: skills.split(/[、,，\n]/).map(s => s.trim()).filter(Boolean) };
      const saved = await saveProfile(name, data, current);
      load(saved);
      setProfiles(await fetchProfiles());
      setMessage(`已保存 v${saved.version}。已生成的资料包继续使用各自当时的版本。`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "保存失败。");
    } finally { setBusy(false); }
  }
  const setRow = (index: number, patch: Partial<EducationDraft>) => setEducation(education.map((row, i) => i === index ? { ...row, ...patch } : row));

  return <div className="profileEditor">
    <div className="taskToolbar">
      <select aria-label="选择资料档案" value={current?.id ?? ""} onChange={e => void (e.target.value ? fetchProfile(e.target.value).then(load) : Promise.resolve(load(null)))}>
        <option value="">新建资料档案</option>{profiles.map(p => <option key={p.id} value={p.id}>{p.name} · v{p.latest_version}</option>)}
      </select>
      {current && <button className="cancelButton" disabled={busy} onClick={() => void deleteProfile(current.id).then(async () => { load(null); setProfiles(await fetchProfiles()); setMessage("已删除该资料档案及全部版本。"); })}>删除档案</button>}
    </div>
    <p className="taskNotice">资料只保存在本机。身份证号、银行卡号等不能写在这里。Agent 生成资料包时按字段路径取值（如 basics.name、education.0.school），不会自行改写。</p>
    {current?.review_state === "draft" && <p className="taskNotice draftNotice">这是 Agent 生成的草稿（比如按岗位定制的简历），还不能用于资料包。请逐项核对，尤其是经历描述，确认无误后点下方保存。</p>}
    <label>档案名称<input value={name} onChange={e => setName(e.target.value)} /></label>
    <div className="taskRow">{BASICS.map(([key, label]) => <label key={key}>{label}<input value={basics[key] ?? ""} onChange={e => setBasics({ ...basics, [key]: e.target.value })} /></label>)}</div>
    <h4>教育经历</h4>
    {education.map((row, index) => <fieldset key={index} className="taskFieldset">
      <legend>education.{index}</legend>
      <div className="taskRow">
        <label>学校<input value={row.school} onChange={e => setRow(index, { school: e.target.value })} /></label>
        <label>学历<input value={row.degree} placeholder="本科" onChange={e => setRow(index, { degree: e.target.value })} /></label>
        <label>专业<input value={row.major} onChange={e => setRow(index, { major: e.target.value })} /></label>
      </div>
      <div className="taskRow">
        <label>开始<input value={row.start} placeholder="2020-09" onChange={e => setRow(index, { start: e.target.value })} /></label>
        <label>结束<input value={row.end} disabled={row.present} placeholder="2024-06" onChange={e => setRow(index, { end: e.target.value })} /></label>
        <label className="taskCheck"><input type="checkbox" checked={row.present} onChange={e => setRow(index, { present: e.target.checked, end: "" })} />至今</label>
      </div>
      <small>只写到月份就保存为月份精度，表单需要具体日期时会询问你，不会自动补“01 日”。</small>
      <button type="button" onClick={() => setEducation(education.filter((_, i) => i !== index))}>移除</button>
    </fieldset>)}
    <button type="button" onClick={() => setEducation([...education, { school: "", degree: "", major: "", start: "", end: "", present: false }])}>添加教育经历</button>
    {(["experience", "projects"] as const).map(group => !!periods[group].length && <div key={group}>
      <h4>{group === "experience" ? "工作与实习经历" : "项目经历"}</h4>
      {periods[group].map((row, index) => <fieldset key={index} className="taskFieldset">
        <legend>{group}.{index}</legend>
        <p className="periodHead"><b>{row.organization}</b>{row.title && ` · ${row.title}`}<span>{formatDate(row.period.start)} – {row.period.present ? "至今" : formatDate(row.period.end)}</span></p>
        <label>描述<textarea rows={3} value={row.description} onChange={e => setPeriods({ ...periods,
          [group]: periods[group].map((p, i) => i === index ? { ...p, description: e.target.value } : p) })} /></label>
      </fieldset>)}
    </div>)}
    <label>技能（用顿号或逗号分隔）<textarea value={skills} onChange={e => setSkills(e.target.value)} /></label>
    {message && <p role="status" className="taskNotice">{message}</p>}
    <footer><button className="approveButton" disabled={busy} onClick={() => void save()}>{current ? `保存为 v${current.latest_version + 1}` : "保存 v1"}</button></footer>
  </div>;
}
