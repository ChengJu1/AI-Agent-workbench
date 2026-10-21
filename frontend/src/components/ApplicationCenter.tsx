// Application ledger: jobs, stages, upcoming deadlines and events, and copy-ready kits. Nothing here writes to an employer site.
import { useEffect, useRef, useState } from "react";
import {
  changeStage, createApplication, deleteApplication, editKitItem, fetchApplication, fetchApplications, updateApplication,
  type Application, type ApplicationFields, type KitItem,
} from "../api/applications";
import { apiUrl } from "../api/http";
import { NotifyToggle } from "./LedgerButton";
import { FLAG_LABELS, GROUPS, PIPELINE, STAGES, agenda, deadlineBadge, shortWhen, sourceLabel, whenLabel } from "../lib/applications";
import { ProfileEditor } from "./ProfileEditor";
import "./applications.css";

type Act = (task: () => Promise<void>) => Promise<void>;
type View = "list" | "create" | "profiles";
const TRACK_LABELS: Record<string, string> = { test: "笔试", interview: "面试" };
const BLANK: ApplicationFields = { company: "", position: "", url: "", deadline: "", next_event_at: "", next_event: "", note: "" };

export function ApplicationCenter({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [view, setView] = useState<View>("list");
  const [items, setItems] = useState<Application[]>([]);
  const [selected, setSelected] = useState<Application | null>(null);
  const [group, setGroup] = useState("active");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function reload(signal?: AbortSignal) {
    const rows = await fetchApplications(signal);
    if (!signal?.aborted) setItems(rows);
  }
  async function open(id: string) {
    setSelected(await fetchApplication(id));
    setView("list");
  }
  const act: Act = async task => {
    if (busy) return;
    setBusy(true); setError("");
    try { await task(); } catch (e) { setError(e instanceof Error ? e.message : "操作失败。"); } finally { setBusy(false); }
  };
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    const controller = new AbortController();
    void reload(controller.signal).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => { controller.abort(); element?.close(); };
  }, []);

  const inGroup = (id: string) => (item: Application) => id === "all" || (id === "active"
    ? !GROUPS.find(g => g.id === "closed")!.stages.includes(item.stage) : GROUPS.find(g => g.id === id)!.stages.includes(item.stage));
  const visible = items.filter(inGroup(group));
  const upcoming = agenda(items);
  return <dialog ref={dialog} className="agentEditor taskCenter" aria-labelledby="ledgerTitle" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <header className="taskHeader">
      <div><h2 id="ledgerTitle">投递台账</h2><p>记录岗位、截止日期和进展。Agent 只帮你读表和准备资料包，不会替你填写或提交；网申请对照资料包自己填写。</p></div>
      <button disabled={busy} onClick={onClose}>关闭</button>
    </header>
    <nav className="taskToolbar">
      <button aria-pressed={view === "list"} onClick={() => setView("list")}>岗位 · {visible.length}</button>
      <button aria-pressed={view === "create"} onClick={() => setView("create")}>新增岗位</button>
      <button aria-pressed={view === "profiles"} onClick={() => setView("profiles")}>资料档案</button>
      <a className="ledgerLink" href={apiUrl("/api/applications/calendar.ics")} download title="导入手机或电脑日历，由系统提醒截止日期和笔面试">导出日历</a>
      <NotifyToggle />
      <button disabled={busy} onClick={() => void act(async () => { await reload(); if (selected) await open(selected.id); })}>刷新</button>
    </nav>
    {error && <p role="alert" className="taskError">{error}</p>}
    <div className="taskBody">
      {view === "create" && <ApplicationForm initial={BLANK} busy={busy} submitLabel="加入台账"
        onSubmit={fields => act(async () => { const item = await createApplication(fields); await reload(); await open(item.id); })} />}
      {view === "profiles" && <ProfileEditor />}
      {view === "list" && <>
        {!!upcoming.length && <section className="ledgerAgenda" aria-label="近期提醒"><h4>近期提醒</h4><ul>{upcoming.map(entry =>
          <li key={entry.id + entry.kind} className={entry.kind === "deadline" && entry.days <= 1 ? "urgent" : ""}>
            <button onClick={() => void act(() => open(entry.id))}><strong>{whenLabel(entry.days)}</strong> {entry.detail} · {entry.title}<small>{entry.when}</small></button></li>)}</ul></section>}
        <div className="ledgerSummary" role="group" aria-label="按阶段筛选">
          {[{ id: "active", label: "进行中" }, ...GROUPS, { id: "all", label: "全部" }].map(g =>
            <button key={g.id} aria-pressed={group === g.id} onClick={() => setGroup(g.id)}><span>{g.label}</span><strong>{items.filter(inGroup(g.id)).length}</strong></button>)}
        </div>
        <div className="taskSplit">
          <ul className="taskList">
            {visible.map(item => <li key={item.id}><ListRow item={item} current={selected?.id === item.id} onOpen={() => void act(() => open(item.id))} /></li>)}
            {!visible.length && <li className="taskEmpty">{items.length ? "这个阶段没有岗位。" : "还没有岗位。可以在这里新增，或在对话里把岗位链接发给 Agent。"}</li>}
          </ul>
          {selected && <Detail item={selected} busy={busy} act={act} onChanged={async next => { setSelected(next); await reload(); }}
            onDeleted={async () => { setSelected(null); await reload(); }} />}
        </div>
      </>}
    </div>
  </dialog>;
}

function ApplicationForm({ initial, busy, submitLabel, onSubmit, onCancel }: {
  initial: ApplicationFields; busy: boolean; submitLabel: string; onSubmit: (fields: ApplicationFields) => Promise<void>; onCancel?: () => void;
}) {
  const [fields, setFields] = useState(initial);
  const set = (key: keyof ApplicationFields) => (e: { target: { value: string } }) => setFields({ ...fields, [key]: e.target.value });
  return <form className="taskForm" onSubmit={e => { e.preventDefault(); void onSubmit(fields); }}>
    <div className="taskRow">
      <label>公司<input required value={fields.company} onChange={set("company")} /></label>
      <label>岗位<input value={fields.position} onChange={set("position")} /></label>
    </div>
    <label>岗位或网申链接<input type="url" value={fields.url} placeholder="https://…" onChange={set("url")} /></label>
    <div className="taskRow">
      <label>投递截止<input type="date" value={fields.deadline} onChange={set("deadline")} /></label>
      <label>下一个日程时间<input type="datetime-local" value={fields.next_event_at.replace(" ", "T")}
        onChange={e => setFields({ ...fields, next_event_at: e.target.value.replace("T", " ") })} /></label>
      <label>日程内容<input value={fields.next_event} placeholder="如：笔试、一面" required={!!fields.next_event_at} onChange={set("next_event")} /></label>
    </div>
    <label>备注<textarea rows={3} value={fields.note} onChange={set("note")} /></label>
    <footer>{onCancel && <button type="button" onClick={onCancel}>取消</button>}<button type="submit" className="approveButton" disabled={busy}>{submitLabel}</button></footer>
  </form>;
}

function Detail({ item, busy, act, onChanged, onDeleted }: {
  item: Application; busy: boolean; act: Act; onChanged: (next: Application) => Promise<void>; onDeleted: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  useEffect(() => setEditing(false), [item.id]);
  const badge = deadlineBadge(item);
  const closedStage = item.stage === "rejected" || item.stage === "withdrawn";
  return <section className="taskDetail" aria-label="岗位详情">
    <header>
      <div><h3>{item.company}</h3><p className="ledgerPosition">{item.position || "未填岗位"}</p>
        {item.url && <p><a href={item.url} target="_blank" rel="noreferrer noopener">{item.url}</a></p>}</div>
      <span className={`taskBadge stage-${item.stage}`}>{item.stage_label}</span>
    </header>
    <dl className="ledgerFacts">
      <div><dt>投递截止</dt><dd>{item.deadline || "—"}{badge && <span className={`ledgerDue due-${badge.tone}`}>{badge.text}</span>}</dd></div>
      <div><dt>投递时间</dt><dd>{item.applied_at ? shortWhen(item.applied_at) : "—"}</dd></div>
      <div><dt>下一个日程</dt><dd>{item.next_event_at ? `${item.next_event} · ${shortWhen(item.next_event_at)}` : "—"}</dd></div>
      <div><dt>资料包</dt><dd>{kitSummary(item)}</dd></div>
    </dl>
    <div className="ledgerTrack" role="group" aria-label="阶段">
      <ol>{PIPELINE.map((stage, index) => {
        const reached = closedStage ? false : index <= PIPELINE.indexOf(item.stage);
        return <li key={stage} className={item.stage === stage ? "current" : reached ? "done" : ""}>
          <button disabled={busy || item.stage === stage} aria-pressed={item.stage === stage}
            onClick={() => void act(async () => onChanged(await changeStage(item, stage)))}>{TRACK_LABELS[stage] ?? STAGES.find(s => s.id === stage)!.label}</button></li>;
      })}</ol>
      <div>{(["rejected", "withdrawn"] as const).map(stage => <button key={stage} className="ledgerExit" aria-pressed={item.stage === stage} disabled={busy || item.stage === stage}
        onClick={() => void act(async () => onChanged(await changeStage(item, stage)))}>{STAGES.find(s => s.id === stage)!.label}</button>)}</div>
    </div>
    {item.note && !editing && <p className="taskNotice">{item.note}</p>}
    {editing ? <ApplicationForm initial={item} busy={busy} submitLabel="保存" onCancel={() => setEditing(false)}
      onSubmit={fields => act(async () => { await onChanged(await updateApplication(item, fields)); setEditing(false); })} />
      : <div className="taskControls"><button disabled={busy} onClick={() => setEditing(true)}>编辑信息</button>
        <button className="cancelButton" disabled={busy} onClick={() => { if (window.confirm(`删除“${item.company}”的台账记录和资料包？`)) void act(async () => { await deleteApplication(item.id); await onDeleted(); }); }}>删除</button></div>}

    <h4>资料包</h4>
    {item.kit ? <KitTable item={item} busy={busy} act={act} onChanged={onChanged} />
      : <p className="taskNotice">还没有资料包。在对话里打开这个岗位的网申页面，让 Agent“为这个岗位生成资料包”；没有表单时也可以只按岗位描述生成。</p>}

    {!!item.events?.length && <details className="taskEvents"><summary>变更记录 · {item.events.length}</summary>
      <ul>{[...item.events].reverse().map(e => <li key={e.id}><time>{e.created_at}</time> {e.actor === "agent" ? "Agent" : "你"} · {eventText(e.body)}</li>)}</ul></details>}
  </section>;
}

function KitTable({ item, busy, act, onChanged }: { item: Application; busy: boolean; act: Act; onChanged: (next: Application) => Promise<void> }) {
  const kit = item.kit!;
  const [copied, setCopied] = useState<number | "all" | null>(null);
  const [editing, setEditing] = useState<{ index: number; value: string } | null>(null);
  const copy = (text: string, key: number | "all") => act(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(key);
    setTimeout(() => setCopied(current => current === key ? null : current), 1500);
  });
  const all = kit.items.filter(i => i.value).map(i => `${i.label}：${i.value}`).join("\n");
  const drafts = kit.items.filter(i => i.flag === "draft" && !i.edited).length;
  const missing = kit.items.filter(i => i.flag === "missing").length;
  return <>
    <p className="taskNotice">按页面顺序排列，逐项复制到网申表单。{drafts ? `${drafts} 项是 Agent 起草的，提交前请改成你自己的话。` : ""}{missing ? `${missing} 项资料中没有，需要你自己填写。` : ""}
      {kit.form_url && <> 表单：<a href={kit.form_url} target="_blank" rel="noreferrer noopener">{kit.form_url}</a></>}</p>
    <div className="taskControls"><button disabled={busy || !all} onClick={() => void copy(all, "all")}>{copied === "all" ? "已复制" : "复制全部"}</button></div>
    <div className="taskTableWrap"><table className="taskTable ledgerKit">
      <thead><tr><th>字段</th><th>填写内容</th><th>来源</th><th><span className="srOnly">操作</span></th></tr></thead>
      <tbody>{kit.items.map((row, index) => <tr key={index} className={`kit-${row.flag || "plain"}`}>
        <td>{row.section ? <small>{row.section}</small> : null}{row.label}{row.required ? <span className="kitRequired">*</span> : null}</td>
        <td>{editing?.index === index
          ? <form className="kitEdit" onSubmit={e => { e.preventDefault(); void act(async () => { await onChanged(await editKitItem(item, index, editing.value)); setEditing(null); }); }}>
              <textarea rows={Math.min(8, Math.max(2, editing.value.length / 40))} value={editing.value} onChange={e => setEditing({ index, value: e.target.value })} />
              <div><button type="button" onClick={() => setEditing(null)}>取消</button><button type="submit" className="approveButton" disabled={busy}>保存</button></div></form>
          : <>{row.value || <span className="kitEmpty">（待你填写）</span>}{optionHint(row)}</>}</td>
        <td>{row.edited || row.flag ? <span className={`kitTag tag-${row.edited ? "edited" : row.flag}`}>{row.edited ? "你已修改" : FLAG_LABELS[row.flag]}</span> : null}
          {row.source.kind === "profile" && <small title={sourceLabel(row)}>{row.source.ref}</small>}
          {row.note && row.flag !== "missing" ? <small>{row.note}</small> : null}</td>
        <td className="kitActions">{row.value && <button disabled={busy} onClick={() => void copy(row.value, index)}>{copied === index ? "已复制" : "复制"}</button>}
          {row.flag !== "file" && editing?.index !== index && <button disabled={busy} onClick={() => setEditing({ index, value: row.value })}>改</button>}</td>
      </tr>)}</tbody>
    </table></div>
  </>;
}

function ListRow({ item, current, onOpen }: { item: Application; current: boolean; onOpen: () => void }) {
  const badge = deadlineBadge(item);
  return <button className="ledgerRow" aria-current={current} onClick={onOpen}>
    <span className="ledgerRowTop"><strong>{item.company}</strong><span className={`taskBadge stage-${item.stage}`}>{item.stage_label}</span></span>
    {item.position && <span className="ledgerRowPosition">{item.position}</span>}
    <span className="ledgerRowMeta">
      {badge && <span className={`ledgerDue due-${badge.tone}`}>{badge.text}</span>}
      {item.next_event_at && <span>{item.next_event} · {shortWhen(item.next_event_at)}</span>}
      {item.has_kit && <span>资料包</span>}
      {!badge && !item.next_event_at && !item.has_kit && <span>更新于 {shortWhen(item.updated_at.slice(0, 10))}</span>}
    </span>
  </button>;
}

function kitSummary(item: Application): string {
  if (!item.kit) return "未生成";
  const missing = item.kit.items.filter(i => i.flag === "missing").length;
  const drafts = item.kit.items.filter(i => i.flag === "draft" && !i.edited).length;
  return [`${item.kit.items.length} 项`, missing && `${missing} 项待填`, drafts && `${drafts} 项草稿`].filter(Boolean).join(" · ");
}

function optionHint(row: KitItem) {
  if (!["select", "custom_select", "cascader", "radio", "checkbox"].includes(row.type)) return null;
  return <small className="kitHint">{row.options.length ? `页面选项：${row.options.slice(0, 8).join("、")}${row.options.length > 8 ? " 等" : ""}` : "在页面下拉中选择"}</small>;
}

function eventText(body: Record<string, unknown>): string {
  const label = (id: unknown) => STAGES.find(s => s.id === id)?.label ?? String(id);
  switch (body.action) {
    case "created": return "加入台账";
    case "edited": return `修改 ${(body.fields as string[] | undefined)?.join("、") || "信息"}`;
    case "stage": return `阶段 ${label(body.from)} → ${label(body.to)}`;
    case "kit": return `生成资料包（${body.items} 项）`;
    case "kit_edited": return `修改资料包：${body.label}`;
    default: return String(body.action);
  }
}
