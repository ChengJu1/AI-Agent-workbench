// Application ledger: jobs, stages, upcoming deadlines and events, and copy-ready kits. Nothing here writes to an employer site.
import { useEffect, useRef, useState } from "react";
import {
  changeStage, createApplication, deleteApplication, editKitItem, fetchApplication, fetchApplications, updateApplication,
  type Application, type ApplicationFields, type KitItem,
} from "../api/applications";
import { FLAG_LABELS, STAGES, agenda, sourceLabel, whenLabel } from "../lib/applications";
import { ProfileEditor } from "./ProfileEditor";
import "./applications.css";

type Act = (task: () => Promise<void>) => Promise<void>;
type View = "list" | "create" | "profiles";
const BLANK: ApplicationFields = { company: "", position: "", url: "", deadline: "", next_event_at: "", next_event: "", note: "" };

export function ApplicationCenter({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [view, setView] = useState<View>("list");
  const [items, setItems] = useState<Application[]>([]);
  const [selected, setSelected] = useState<Application | null>(null);
  const [showClosed, setShowClosed] = useState(false);
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

  const closed = new Set(["offer", "rejected", "withdrawn"]);
  const visible = items.filter(i => showClosed || !closed.has(i.stage));
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
      {view === "list" && <label className="taskCheck"><input type="checkbox" checked={showClosed} onChange={e => setShowClosed(e.target.checked)} />显示已结束</label>}
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
        <div className="taskSplit">
          <ul className="taskList">
            {visible.map(item => <li key={item.id}><button aria-current={selected?.id === item.id} onClick={() => void act(() => open(item.id))}>
              <strong>{item.company}{item.position ? ` · ${item.position}` : ""}</strong><span className={`taskBadge stage-${item.stage}`}>{item.stage_label}</span>
              <small>{item.deadline ? `截止 ${item.deadline}` : "未填截止日期"}{item.has_kit ? " · 有资料包" : ""}</small></button></li>)}
            {!visible.length && <li className="taskEmpty">还没有岗位。可以在这里新增，或在对话里把岗位链接发给 Agent。</li>}
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
  return <section className="taskDetail" aria-label="岗位详情">
    <header>
      <div><h3>{item.company}{item.position ? ` · ${item.position}` : ""}</h3>
        <p>{item.url ? <a href={item.url} target="_blank" rel="noreferrer noopener">{item.url}</a> : "未填链接"}</p>
        <p>{item.deadline ? `截止 ${item.deadline}` : "未填截止日期"}{item.applied_at ? ` · 投递于 ${item.applied_at}` : ""}
          {item.next_event_at ? ` · ${item.next_event} ${item.next_event_at}` : ""}</p></div>
      <span className={`taskBadge stage-${item.stage}`}>{item.stage_label}</span>
    </header>
    <div className="taskControls" role="group" aria-label="阶段">{STAGES.map(stage =>
      <button key={stage.id} aria-pressed={item.stage === stage.id} disabled={busy || item.stage === stage.id}
        onClick={() => void act(async () => onChanged(await changeStage(item, stage.id)))}>{stage.label}</button>)}</div>
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
      <thead><tr><th>字段</th><th>填写内容</th><th>来源</th><th></th></tr></thead>
      <tbody>{kit.items.map((row, index) => <tr key={index} className={`kit-${row.flag || "plain"}`}>
        <td>{row.section ? <small>{row.section}</small> : null}{row.label}{row.required ? <span className="kitRequired">*</span> : null}</td>
        <td>{editing?.index === index
          ? <form className="kitEdit" onSubmit={e => { e.preventDefault(); void act(async () => { await onChanged(await editKitItem(item, index, editing.value)); setEditing(null); }); }}>
              <textarea rows={Math.min(8, Math.max(2, editing.value.length / 40))} value={editing.value} onChange={e => setEditing({ index, value: e.target.value })} />
              <div><button type="button" onClick={() => setEditing(null)}>取消</button><button type="submit" className="approveButton" disabled={busy}>保存</button></div></form>
          : <>{row.value || <span className="kitEmpty">（待你填写）</span>}{optionHint(row)}</>}</td>
        <td>{sourceLabel(row)}{(row.flag && FLAG_LABELS[row.flag]) || row.edited ? <small className="kitFlag">{row.edited ? "你已修改" : FLAG_LABELS[row.flag]}</small> : null}
          {row.note && row.flag !== "missing" ? <small>{row.note}</small> : null}</td>
        <td className="kitActions">{row.value && <button disabled={busy} onClick={() => void copy(row.value, index)}>{copied === index ? "已复制" : "复制"}</button>}
          {row.flag !== "file" && editing?.index !== index && <button disabled={busy} onClick={() => setEditing({ index, value: row.value })}>改</button>}</td>
      </tr>)}</tbody>
    </table></div>
  </>;
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

/** Header button with a count of deadlines and events coming up, refreshed every minute. */
export function LedgerButton({ disabled, onClick }: { disabled: boolean; onClick: () => void }) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const rows = await fetchApplications(controller.signal); if (!controller.signal.aborted) setCount(agenda(rows).length); }
      catch { /* The badge is a hint; the ledger itself shows errors. */ }
      finally { if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 60000); }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);
  return <button disabled={disabled} onClick={onClick}>投递台账{count ? ` · ${count} 项临近` : ""}</button>;
}
