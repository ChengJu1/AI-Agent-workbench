import {useEffect,useRef,useState} from 'react';
import {fetchBrowsers,browserTakeover,type BrowserSession} from '../api/platform';
import type {PendingAction} from '../types';
import {BrowserLiveFrame} from './BrowserLiveFrame';
import './operationPreview.css';
import {browserPreviewContext,type PreviewSelection} from '../lib/browserPreviewContext';
import {previewRequest} from '../lib/browserPreviewRequest';
export type {PreviewSelection} from '../lib/browserPreviewContext';
export function OperationPreview({conversationId,actions,selection,forceOpen,paused,busy,onResume,onSelect,onManage,onClose}:{onClose:()=>void;conversationId:string;actions:PendingAction[];selection:PreviewSelection;forceOpen:number;paused:boolean;busy:boolean;onResume:(sessionId:string)=>Promise<void>;onSelect:(selection:PreviewSelection)=>void;onManage:(sessionId?:string,url?:string)=>void}){
 const [sessions,setSessions]=useState<BrowserSession[]>([]),[chosen,setChosen]=useState(''),[error,setError]=useState(''),[taking,setTaking]=useState(false);
 const {action,source,session,index}=browserPreviewContext(conversationId,sessions,actions,selection,chosen);
 const lastPage=useRef<BrowserSession|null>(null);if(session)lastPage.current=session;
 useEffect(()=>{const c=new AbortController();let timer:ReturnType<typeof setTimeout>;
  async function poll(){try{if(document.visibilityState!=='hidden'){const rows=await previewRequest(s=>fetchBrowsers(conversationId,s),c.signal);if(!c.signal.aborted){setSessions(rows);setError('');}}}catch(e){if(!c.signal.aborted)setError(e instanceof Error?e.message:'无法读取浏览器。');}finally{if(!c.signal.aborted)timer=setTimeout(()=>void poll(),3000);}}
  void poll();return()=>{c.abort();clearTimeout(timer);};},[conversationId]);
 async function takeover(active:boolean){if(!session||taking)return;setTaking(true);setError('');try{await browserTakeover(conversationId,session.id,active,undefined,300);}catch(e){setError(e instanceof Error?e.message:'接手失败。');}finally{setTaking(false);}}
 return <aside className="operationPreview" aria-label="浏览器预览"><header><div><strong>浏览器</strong><small>{session?.browser_name||'未连接'} · 当前对话</small></div><button onClick={onClose}>关闭</button></header>
 <div className="operationPreviewBody">{error&&<p role="alert">{error}</p>}{!session?<div className="browserEmptyNotice"><p>{source?'此清单关联的页面已关闭或尚未连接，请重新打开页面并让 Agent 生成新清单。':lastPage.current?'浏览器连接已断开。窗口关闭或后端重启后，需要重新打开网页。':'当前没有连接的浏览器页面。打开网页后，可在这里查看页面信息和刷新画面。'}</p><button onClick={()=>onManage(undefined,source?.params.url||lastPage.current?.url)}>打开 / 重新连接网页</button><p>重新打开会使用当前浏览器方案的登录配置，不会重复执行已确认的操作。</p></div>:<>
 <p className="browserAddress">{session.url}</p>{sessions.length>1&&!action&&<label>查看页面<select value={session.id} onChange={e=>setChosen(e.target.value)}>{sessions.map(s=><option key={s.id} value={s.id}>{s.url}</option>)}</select></label>}
 {action&&<div className="previewSteps"><strong>待确认清单 · {action.params.operations?.length} 步</strong>{action.params.operations?.map((op,i)=><button key={i} aria-pressed={i===index} onClick={()=>onSelect({actionId:action.id,index:i})}>{i+1}. {op.label||op.kind}</button>)}</div>}
 {source&&!action&&<p role="status">此清单已停止或已处理。这里只查看关联浏览器的当前页面，不会重放旧操作。</p>}
 <BrowserLiveFrame reviewStatus={source?.status} captureRequest={source?.id===selection?.actionId?forceOpen:0} conversationId={conversationId} sessionId={session.id} actionId={action?.id} index={index} active={!paused} onUnavailable={id=>setSessions(rows=>rows.filter(row=>row.id!==id))}/>
 <div className="previewControls"><button disabled={taking||session.can_takeover===false} onClick={()=>void takeover(true)}>接手操作 / 续期（5 分钟）</button><button disabled={taking||busy} onClick={()=>void onResume(session.id)}>交回并继续</button><button onClick={()=>onManage(session.id)}>放大预览 / 浏览器管理</button></div>
 <p>完成登录后点击「交回并继续」，助手会重新读取页面并准备后续操作清单；填写、上传和最终提交仍由你审阅确认。</p>
 <p>{session.provider==='native_mcp'?'接手后请切换到专用 Chrome；五分钟内 Agent 暂停操作，可续期。网站正常联网，画面手动刷新。':'接手后请切换到独立 Chrome 操作；有效期五分钟，可续期，到期后暂停手动发送请求。'}此处预览不能直接输入。</p>{session.can_takeover===false&&<p>当前浏览器没有可见窗口，需在有桌面的后端环境完成登录。</p>}</>}
 </div></aside>;
}
