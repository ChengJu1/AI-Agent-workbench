import { useEffect, useRef, useState } from "react";
import { inspectBrowser, browserTakeover, closeBrowser, fetchBrowsers, openBrowser, reloadBrowser, type BrowserSession } from "../api/platform";
import "./platform.css";
import {BrowserLiveFrame} from "./BrowserLiveFrame";
import type {PendingAction} from "../types";
import {previewRequest} from '../lib/browserPreviewRequest';
import {BrowserConnections} from './BrowserConnections';
export function BrowserPanel({ conversationId, onClose,actions=[],previewSelection,initialSessionId,initialUrl,agentBusy,onResume }: { conversationId: string | null; onClose: () => void;actions?:PendingAction[];previewSelection?:{actionId:string;index:number}|null;initialSessionId?:string;initialUrl?:string;agentBusy:boolean;onResume:(sessionId:string)=>Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [sessions, setSessions] = useState<BrowserSession[]>([]);
  const [url, setUrl] = useState(initialUrl||"");
  const [disconnected,setDisconnected]=useState(false);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef(false);
  async function inspect(tabIndex?:number) {
    if (!conversationId) return;
    const result = await inspectBrowser(conversationId, selected, tabIndex);
    const states:Record<string,string>={ready:'已读到页面',blank:'页面无正文',loading:'文档仍在加载',choose_tab:'需选择已有网页标签',snapshot_unavailable:'正文与快照不一致，需检查读取'};
    setNotice(`${states[result.page_state]||result.page_state}；正文 ${result.text_length} 字符，可操作元素 ${result.element_count} 个。登录和提交状态仍需按页面实际内容核实。${result.diagnostics?.failed_resources?.length?` 资源异常：${result.diagnostics.failed_resources.map(r=>`${r.host} ${r.error||r.status}`).join("；")}`:""}`);
  }
  useEffect(() => { dialog.current?.showModal(); return () => dialog.current?.close(); }, []);
  useEffect(() => { if (!conversationId) return; const controller = new AbortController();
    void previewRequest(s=>fetchBrowsers(conversationId,s),controller.signal).then((rows) => { setSessions(rows); setSelected(rows.some(row=>row.id===initialSessionId)?initialSessionId!:rows[0]?.id || ""); })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught.message); }); return () => controller.abort(); }, [conversationId]);
  async function run(callback: () => Promise<unknown>) { if (pending.current || !conversationId) return; pending.current = true; setBusy(true); setError("");
    try { await callback(); setSessions(await fetchBrowsers(conversationId)); } catch (caught) { setError(caught instanceof Error ? caught.message : "浏览器操作失败。"); }
    finally { pending.current = false; setBusy(false); }
  }
  const browserActions=actions.filter(a=>a.action==="browser_actions"&&a.params.session_id===selected&&["pending","executing"].includes(a.status));
  const action=browserActions.find(a=>a.id===previewSelection?.actionId)||browserActions[browserActions.length-1];
  const current = sessions.find((item) => item.id === selected);
  return <dialog ref={dialog} className="agentEditor browserPanel" aria-labelledby="browserTitle" onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <header className="platformHeader"><div><h2 id="browserTitle">浏览器与登录</h2><p className="agentEditorHint">使用专用窗口。Agent 填写、上传和点击需在确认清单中审阅；登录由你操作。</p></div><button disabled={busy} onClick={onClose}>关闭面板</button></header>
    {!conversationId ? <p>先发送一条消息建立会话，再让 Agent 打开网页，或在此处输入网址。</p> : <>
      <form className="browserOpen" onSubmit={(event) => { event.preventDefault(); setNotice(""); void run(async () => { const result = await openBrowser(conversationId, url); setSelected(result.session_id); setNotice([result.http_status?`页面响应：HTTP ${result.http_status}`:'',result.warning||''].filter(Boolean).join('。')); setUrl(""); }); }}>
        <input aria-label="公开网页地址" type="url" required placeholder="https://目标网站/页面" value={url} disabled={busy} onChange={(event) => setUrl(event.target.value)} />
        <button type="submit" disabled={busy || !url}>打开网页</button></form>
      <div className="browserSessions">{sessions.map((session) => <button key={session.id} aria-pressed={selected === session.id} disabled={busy} onClick={() => setSelected(session.id)}>{session.url}</button>)}</div>
      {current && <><p className="agentEditorHint">运行浏览器：{current.browser_name||'独立浏览器'} · 工作台独立会话</p><p className="browserAddress">当前接收网站：{current.url}</p><div className="platformActions">
        <button disabled={busy} onClick={() => void run(async () => undefined)}>刷新页面列表</button>
        {current.provider==='native_mcp'&&<button disabled={busy||agentBusy||current.manual_until>Date.now()/1000} onClick={()=>void run(()=>inspect())}>检查页面与标签</button>}
        <button disabled={busy||current.manual_until>Date.now()/1000} onClick={()=>void run(async()=>{const result=await reloadBrowser(conversationId,selected);setNotice(result.warning||'网页已重新加载，旧操作清单需要重新生成。');})}>重新加载网页</button>
        <button disabled={busy||current.can_takeover===false} onClick={() => void run(() => browserTakeover(conversationId, selected, true,undefined,300))}>接手操作 / 续期（5 分钟）</button>
        <button disabled={busy||agentBusy} onClick={() => {onClose();void onResume(selected);}}>交回并继续</button>
        <button disabled={busy} onClick={() => void run(async () => { await closeBrowser(conversationId, selected); setSelected(""); })}>关闭此浏览器</button>
      </div><p className="agentEditorHint">{current.provider==='native_mcp'?'网站按正常浏览器方式联网。接手会暂停 Agent 读取和操作，五分钟后可续期；计时不控制网站网络。关闭窗口保留当前对话的专用登录配置。画面仅在你点击刷新时拍摄。':'接手后请切换到后端电脑的独立 Chrome 完成登录。接手有效期五分钟，可续期；到期后发送请求会暂停。接手期间暂停截图及 Agent 读取，关闭窗口清除临时登录状态。'} 登录信息不会写入 Agent 配置。</p>
      {current.provider==='native_mcp'&&!!current.tabs?.length&&<div className="browserSessions" aria-label="专用浏览器中的标签">{current.tabs.map(tab=><button key={tab.index} aria-pressed={tab.current} disabled={busy||agentBusy||current.manual_until>Date.now()/1000||!tab.url.startsWith('http')} onClick={()=>void run(()=>inspect(tab.index))}>{tab.current?'当前 · ':''}{tab.title||tab.url}</button>)}</div>}
      {current.provider!=='native_mcp'&&<BrowserConnections key={selected+'-connections'} conversationId={conversationId} sessionId={selected} manual={current.manual_until>Date.now()/1000} manualUntil={current.manual_until} onChanged={()=>void run(async()=>undefined)}/>}
      {conversationId&&<BrowserLiveFrame key={selected} conversationId={conversationId} sessionId={selected} actionId={action?.id} index={action?.id===previewSelection?.actionId?(previewSelection?.index??0):0} onMetadata={value=>setSessions(rows=>rows.some(row=>row.id===selected&&(row.url!==value.url||row.manual_until!==value.manual_until))?rows.map(row=>row.id===selected?{...row,...value}:row):rows)} onUnavailable={id=>{setUrl(current.url);setNotice('');setDisconnected(true);setSessions(rows=>rows.filter(row=>row.id!==id));setSelected('');}}/>}</>}
      {!sessions.length && !busy && <p role="status" className="agentEditorHint">{disconnected?'浏览器窗口已关闭或会话已失效。上方已填回原网址，点击“打开网页”重新连接；不会重复执行原操作。':'当前会话还没有浏览器页面。请在上方输入目标网址并点击“打开网页”。'}</p>}
    </>}{busy && <p role="status">正在操作浏览器…</p>}{notice&&<p role="status" className="agentEditorHint">{notice}</p>}{error && <p className="agentEditorError" role="alert">{error}</p>}
  </dialog>;
}
