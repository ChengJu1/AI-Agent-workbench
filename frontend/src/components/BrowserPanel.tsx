import { useEffect, useRef, useState } from "react";
import { browserScreenshot, browserTakeover, closeBrowser, fetchBrowsers, openBrowser, type BrowserSession } from "../api/platform";
import "./platform.css";
export function BrowserPanel({ conversationId, onClose }: { conversationId: string | null; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [sessions, setSessions] = useState<BrowserSession[]>([]);
  const [url, setUrl] = useState("");
  const [image, setImage] = useState("");
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  useEffect(() => { dialog.current?.showModal(); return () => dialog.current?.close(); }, []);
  useEffect(() => { if (!conversationId) return; const controller = new AbortController();
    void fetchBrowsers(conversationId, controller.signal).then((rows) => { setSessions(rows); setSelected(rows[0]?.id || ""); })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught.message); }); return () => controller.abort(); }, [conversationId]);
  useEffect(() => { if (!conversationId || !selected) { setImage(""); return; } const controller = new AbortController(); let objectUrl = "";
    void browserScreenshot(conversationId, selected, controller.signal).then((result) => { objectUrl = result; if (!controller.signal.aborted) setImage(result); else URL.revokeObjectURL(result); })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught.message); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); }; }, [conversationId, selected, sessions]);
  async function run(callback: () => Promise<unknown>) { if (pending.current || !conversationId) return; pending.current = true; setBusy(true); setError("");
    try { await callback(); setSessions(await fetchBrowsers(conversationId)); } catch (caught) { setError(caught instanceof Error ? caught.message : "浏览器操作失败。"); }
    finally { pending.current = false; setBusy(false); }
  }
  const current = sessions.find((item) => item.id === selected);
  return <dialog ref={dialog} className="agentEditor browserPanel" aria-labelledby="browserTitle" onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <header className="platformHeader"><div><h2 id="browserTitle">受控浏览器</h2><p className="agentEditorHint">独立于你的个人浏览器。页面操作限定当前站点；填表与点击需在对话中确认，关闭后清除登录状态。</p></div><button disabled={busy} onClick={onClose}>关闭面板</button></header>
    {!conversationId ? <p>先发送一条消息建立会话，再让 Agent 打开网页，或在此处输入网址。</p> : <>
      <form className="browserOpen" onSubmit={(event) => { event.preventDefault(); void run(async () => { const result = await openBrowser(conversationId, url); setSelected(result.session_id); setUrl(""); }); }}>
        <input aria-label="公开网页地址" type="url" required placeholder="https://目标网站/职位页面" value={url} disabled={busy} onChange={(event) => setUrl(event.target.value)} />
        <button type="submit" disabled={busy || !url}>打开网页</button></form>
      <div className="browserSessions">{sessions.map((session) => <button key={session.id} aria-pressed={selected === session.id} disabled={busy} onClick={() => setSelected(session.id)}>{session.url}</button>)}</div>
      {current && <><p className="browserAddress">当前接收网站：{current.url}</p><div className="platformActions">
        <button disabled={busy} onClick={() => void run(async () => undefined)}>刷新预览</button>
        <button disabled={busy} onClick={() => void run(() => browserTakeover(conversationId, selected, true))}>接手操作（60 秒）</button>
        <button disabled={busy} onClick={() => void run(() => browserTakeover(conversationId, selected, false))}>交回 Agent</button>
        <button disabled={busy} onClick={() => void run(async () => { await closeBrowser(conversationId, selected); setSelected(""); setImage(""); })}>关闭此浏览器</button>
      </div><p className="agentEditorHint">接手后，在弹出的独立浏览器中完成登录或验证；60 秒内允许你操作当前站点，Agent 暂停读取与规划。登录信息不会写入 Agent 配置。交回后 Agent 可以读取该页面内容。</p>
      {image && <img className="browserPreview" src={image} alt="独立浏览器当前页面预览" />}</>}
      {!sessions.length && !busy && <p className="agentEditorHint">当前会话还没有浏览器页面。</p>}
    </>}{busy && <p role="status">正在操作浏览器…</p>}{error && <p className="agentEditorError" role="alert">{error}</p>}
  </dialog>;
}
