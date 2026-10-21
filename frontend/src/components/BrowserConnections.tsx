import {useEffect,useRef,useState} from 'react';
import {allowBrowserConnections,fetchBrowserConnections,revokeBrowserConnections,reloadBrowser,browserTakeover,type BrowserConnectionView} from '../api/platform';
import {previewRequest} from '../lib/browserPreviewRequest';
import {restoreBrowserResources} from '../lib/restoreBrowserResources';

export function BrowserConnections({conversationId,sessionId,manual,manualUntil,onChanged}:{conversationId:string;sessionId:string;manual:boolean;manualUntil:number;onChanged:()=>void}){
 const mounted=useRef(true);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 const [view,setView]=useState<BrowserConnectionView|null>(null),[selected,setSelected]=useState<string[]>([]),[confirmData,setConfirmData]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[refresh,setRefresh]=useState(0);
 useEffect(()=>{const c=new AbortController();let timer:ReturnType<typeof setTimeout>;
  async function load(){try{if(document.visibilityState!=='hidden'){const data=await previewRequest(s=>fetchBrowserConnections(conversationId,sessionId,s),c.signal);if(!c.signal.aborted){setView(data);setSelected(ids=>ids.filter(id=>data.pending.some(row=>row.id===id)));}}}catch(e){if(!c.signal.aborted)setError(e instanceof Error?e.message:'无法读取连接清单。');}finally{if(!c.signal.aborted)timer=setTimeout(()=>void load(),3000);}}
  void load();return()=>{c.abort();clearTimeout(timer);};
 },[conversationId,sessionId,refresh]);
 const rows=view?.pending||[],reads=rows.filter(row=>row.method==='GET'),sends=rows.filter(row=>row.method!=='GET');
 const picked=(write:boolean)=>rows.filter(row=>selected.includes(row.id)&&(row.method!=='GET')===write).map(row=>row.id);
 async function allow(write:boolean){if(!view||busy)return;setBusy(true);setError('');setNotice('');try{
  const result=await allowBrowserConnections(conversationId,sessionId,picked(write),view.page_url,write&&confirmData);
  if(!mounted.current)return;
  setSelected([]);setConfirmData(false);setNotice(result.message);setRefresh(n=>n+1);
  if(!write){const result=await restoreBrowserResources({manualUntil,isCurrent:()=>mounted.current,
   handoff:()=>browserTakeover(conversationId,sessionId,false),reload:()=>reloadBrowser(conversationId,sessionId),
   resume:seconds=>browserTakeover(conversationId,sessionId,true,undefined,seconds)});
   if(mounted.current)setNotice(result?.warning||'所选资源已授权并重新加载。原接手尚有效时，按剩余时间恢复；不会自动延长接手或重发提交请求。');}
  if(mounted.current)onChanged();
 }catch(e){setError(e instanceof Error?e.message:'连接授权失败。');}finally{setBusy(false);}}
 async function revoke(){setBusy(true);setError('');try{await revokeBrowserConnections(conversationId,sessionId);setNotice('已撤销本会话的额外连接；已发送的请求无法撤回。');setRefresh(n=>n+1);onChanged();}catch(e){setError(e instanceof Error?e.message:'撤销失败。');}finally{setBusy(false);}}
 const renderRows=(write:boolean)=>(write?sends:reads).map(row=><label className="browserConnectionRow" key={row.id}><input type="checkbox" checked={selected.includes(row.id)} disabled={busy} onChange={e=>setSelected(ids=>e.target.checked?[...ids,row.id]:ids.filter(id=>id!==row.id))}/><span><strong>{row.host} · {row.method} · {row.kind}</strong><details><summary>查看具体请求地址</summary><code>{row.url}</code></details></span></label>);
 return <details className="browserConnections" open={reads.length>0||undefined}><summary>{reads.length?'页面加载受阻，请确认资源':'页面连接'} · {reads.length} 个加载请求 / {sends.length} 个发送请求待确认</summary>
 <p>仅当前浏览器会话、列表中的固定地址和方法生效，十分钟后过期。授权连接不会重放已被拦的请求，也不会代替提交确认。</p>
 {error&&<p role="alert" className="agentEditorError">{error}</p>}{notice&&<p role="status">{notice}</p>}
 {!view&&<p>正在读取连接清单…</p>}
 {!!reads.length&&<section><h4>加载页面资源</h4><p>只发送所列地址的 GET 请求，不携带 Cookie、认证头、自定义令牌或填写内容；网址中的参数仍会发送。请展开地址核对。</p>
 <button disabled={busy} onClick={()=>setSelected(ids=>[...new Set([...ids,...reads.map(row=>row.id)])])}>选择全部加载请求</button><div className="browserConnectionRows">{renderRows(false)}</div>
 <button disabled={busy||!picked(false).length} onClick={()=>void allow(false)}>允许所选资源并恢复当前页面</button><p>这会重新加载当前网址，请先保存未完成的填写内容。{manual?'将短暂交回以加载，成功后按原剩余时间恢复接手，不延长授权。':''}不会重新打开浏览器、清除登录状态或重发提交请求。</p></section>}
 {!!sends.length&&<section><h4>发送资料的连接</h4><p>这些请求可能发送你填写的登录或表单资料。请求方法为 POST 不代表它一定是提交接口，请核对地址与用途。授权后仍只能在接手期间，或执行已确认的操作时发送。</p>
 <div className="browserConnectionRows">{renderRows(true)}</div><label className="browserConnectionConsent"><input type="checkbox" checked={confirmData} disabled={busy} onChange={e=>setConfirmData(e.target.checked)}/>我允许将本网站填写的资料发送到所选固定地址；具体操作仍需接手或单独确认。</label>
 <button disabled={busy||!confirmData||!picked(true).length} onClick={()=>void allow(true)}>仅授权所选发送连接</button></section>}
 {view&&!rows.length&&<p>当前没有待确认连接。若页面仍空白，可重新加载后刷新连接清单。</p>}
 <p>已授权 {view?.granted.length||0} 条连接</p>{!!view?.granted.length&&<><details><summary>查看已授权地址</summary>{view.granted.map((row,i)=><p key={i}>{row.method} · {row.url}</p>)}</details><button disabled={busy} onClick={()=>void revoke()}>撤销全部额外连接</button></>}
 <button disabled={busy} onClick={()=>{setError('');setRefresh(n=>n+1);}}>刷新连接清单</button>
 </details>;
}
