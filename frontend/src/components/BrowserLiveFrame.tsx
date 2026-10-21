import {useEffect,useRef,useState} from 'react';
import {fetchBrowserFrame,focusBrowserStep,captureBrowserFrame,type BrowserFrame} from '../api/platform';
import {previewRequest,browserFrame} from '../lib/browserPreviewRequest';
import {ApiError} from '../api/http';
import type {PendingAction} from '../types';
export function BrowserLiveFrame({conversationId,sessionId,actionId,index=0,active=true,captureRequest=0,reviewStatus,onUnavailable,onMetadata}:{conversationId:string;sessionId:string;actionId?:string;index?:number;active?:boolean;captureRequest?:number;reviewStatus?:PendingAction['status'];onUnavailable?:(sessionId:string)=>void;onMetadata?:(value:{url:string;manual_until:number})=>void}){
 const key=[conversationId,sessionId,actionId,index].join('/'),currentKey=useRef(key);currentKey.current=key;
 const [saved,setSaved]=useState<{key:string;frame:BrowserFrame}|null>(null),[issue,setIssue]=useState({key:'',text:''}),[focusing,setFocusing]=useState(false);
 const focusRequest=useRef<AbortController|null>(null),lastCaptureRequest=useRef(0);
 const [now,setNow]=useState(Date.now()/1000);
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()/1000),1000);return()=>clearInterval(timer);},[]);
 const unavailable=useRef(onUnavailable);unavailable.current=onUnavailable;
 const metadata=useRef(onMetadata);metadata.current=onMetadata;
 const frame=saved?.key===key?saved.frame:null,error=issue.key===key?issue.text:'';
 function accept(data:BrowserFrame){if(currentKey.current!==key)return;setSaved(old=>old?.key===key&&old.frame.captured_at>data.captured_at?old:{key,frame:data});setIssue({key,text:''});metadata.current?.({url:data.url,manual_until:data.manual_until});}
 useEffect(()=>{setFocusing(false);if(!active)return;const c=new AbortController();let timer:ReturnType<typeof setTimeout>,running=false;
  async function tick(){if(running||c.signal.aborted)return;running=true;try{if(document.visibilityState!=='hidden'){const captureNow=captureRequest>0&&lastCaptureRequest.current!==captureRequest;if(captureNow){lastCaptureRequest.current=captureRequest;setFocusing(true);}try{const data=await previewRequest(s=>captureNow?captureBrowserFrame(conversationId,sessionId,actionId,index,s):fetchBrowserFrame(conversationId,sessionId,actionId,index,s),c.signal,captureNow?45000:8000);if(!c.signal.aborted)accept(browserFrame(data));}finally{if(captureNow&&!c.signal.aborted)setFocusing(false);}}}catch(e){if(!c.signal.aborted){setIssue({key,text:e instanceof Error?e.message:'预览暂不可用。'});if(e instanceof ApiError&&[404,410].includes(e.status))unavailable.current?.(sessionId);}}finally{running=false;if(!c.signal.aborted)timer=setTimeout(()=>void tick(),2000);}}
  const visible=()=>{if(document.visibilityState==='visible'&&!running){clearTimeout(timer);void tick();}};void tick();document.addEventListener('visibilitychange',visible);
  return()=>{c.abort();clearTimeout(timer);focusRequest.current?.abort();document.removeEventListener('visibilitychange',visible);};
 },[key,active,captureRequest]);
 async function focus(){if(!actionId||focusing)return;const c=new AbortController();focusRequest.current=c;setFocusing(true);try{accept(browserFrame(await previewRequest(s=>focusBrowserStep(conversationId,sessionId,actionId,index,s),c.signal)));}catch(e){if(!c.signal.aborted&&currentKey.current===key)setIssue({key,text:e instanceof Error?e.message:'定位失败。'});}finally{if(!c.signal.aborted)setFocusing(false);}}
 async function capture(){if(focusing)return;const c=new AbortController();focusRequest.current=c;setFocusing(true);try{accept(browserFrame(await previewRequest(s=>captureBrowserFrame(conversationId,sessionId,actionId,index,s),c.signal,45000)));}catch(e){if(!c.signal.aborted&&currentKey.current===key)setIssue({key,text:e instanceof Error?e.message:'画面获取失败。'});}finally{if(!c.signal.aborted)setFocusing(false);}}
 const box=frame?.target?.box,viewport=frame?.viewport;
 const manual=!!frame&&frame.manual_until>now;
 const manualExpired=!!frame&&frame.manual_until>0&&frame.manual_until<=now;
 const status=manual?'你正在接手操作':frame?.progress.phase==='executing'?`正在执行第 ${(frame.progress.index||0)+1}/${frame.progress.total} 步`:
  reviewStatus==='failed'?'清单执行失败，当前页面只读':reviewStatus==='cancelled'?'清单已取消，当前页面只读':actionId&&frame?.plan_state==='stale'?'清单已失效，可查看当前画面':actionId?'等待你确认操作':frame?.progress.phase==='failed'?'执行中断，请核对页面':frame?.progress.phase==='completed'?'操作已结束，请核对回执':frame?.manual_refresh_only?'最近一次浏览器画面':'当前浏览器画面';
 return <div className="liveBrowserFrame"><div className="liveBrowserStatus"><strong>{status}</strong><button type="button" disabled={focusing||manual} onClick={()=>void capture()}>{focusing?'正在获取…':'刷新画面'}</button></div>
 {frame?.progress.phase==='executing'&&<p>{frame.progress.label}</p>}
 {manual&&<p role="status">你正在接手，剩余 {Math.ceil(frame!.manual_until-now)} 秒。预览暂停截图，避免干扰独立 Chrome；下方为接手前画面。可点击“接手操作 / 续期”继续计时。</p>}
 {manualExpired&&<p role="status" className="browserEmptyNotice">{frame?.manual_refresh_only?'接手计时已结束，Agent 可以恢复读取和规划。网页仍正常联网；继续手动操作前请续期，避免与 Agent 同时操作。':'手动操作已到期，点击按钮触发的发送请求可能被阻止。请点击“接手操作 / 续期”，或交回后让 Agent 生成待确认清单。不要连续点击投递。'}</p>}
 {error&&<p role="alert" className="agentEditorError">{error} 画面暂停更新，请勿把旧画面当成最新结果。</p>}
 {!frame&&!error&&<p role="status">正在连接操作预览…</p>}
 {frame&&<>{frame.captured_at>0?<div className={`liveBrowserCanvas${error?' isStale':''}`}><img src={frame.image} alt="浏览器最近一次画面"/>{box&&viewport&&frame.plan_state==='current'&&<span className="browserTarget" aria-label={`当前预览目标：${frame.target?.label}`} style={{left:`${100*box.x/viewport.width}%`,top:`${100*box.y/viewport.height}%`,width:`${100*box.width/viewport.width}%`,height:`${100*box.height/viewport.height}%`}}/>}</div>:<p className="browserEmptyNotice">尚未获取画面。交回浏览器后点击“刷新画面”查看网页，登录和手动操作请在专用 Chrome 窗口完成。</p>}
 {frame.manual_refresh_only&&frame.page_state&&frame.page_state!=='ready'&&<p role="status" className="browserEmptyNotice">当前页面尚未核对。请在「浏览器与登录」检查页面与标签；不要关闭或重开已登录的填写页。保存配置不代表已登录或已提交。</p>}
 {frame.page_state==='empty'&&<p role="status" className="browserEmptyNotice">目标网页尚未显示正文或控件。正在继续更新画面；如果持续空白，可从浏览器管理重新打开网页。</p>}
 {!!frame.connection_review?.pending_resources&&<p role="status">有 {frame.connection_review.pending_resources} 个新页面资源等待确认。请打开“浏览器与登录”中的“页面连接”，审阅地址并授权加载；不能仅因 POST 被拦就判断投递无法完成。</p>}
 {frame.interaction_warning&&<p role="status" className="browserEmptyNotice">{frame.interaction_warning}</p>}
 {frame.resource_warning&&<p role="status">页面资源提示：{frame.resource_warning}</p>}
 {frame.resource_issues?.length? <details><summary>页面资源详情</summary>{frame.resource_issues.map((issue,i)=><p key={i}>{issue.host}{issue.path||''} · {issue.kind||"资源"} · {issue.method||""}：{issue.error}{issue.mime?` [${issue.mime}; ${issue.extension}; ${issue.cache_policy}]`:""}</p>)}</details>:null}
 <p className="browserFrameTime">{frame.captured_at?new Date(frame.captured_at*1000).toLocaleTimeString('zh-CN')+' 拍摄':'尚未拍摄，请点击刷新画面'} · {frame.capture_paused?'接手期间暂停截图':frame.manual_refresh_only?'手动截图；页面信息定时更新':'可见时每 2 秒刷新'}</p>
 {actionId&&frame.plan_state==='stale'&&<p role="status">{frame.plan_error||'清单已过期或页面已变化，请让 Agent 重新读取并生成清单。'} 当前画面可查看，旧清单不能继续执行。</p>}
 {actionId&&frame.plan_state==='current'&&<div className="browserTargetHint"><span>预览目标：{frame.target?.label}</span>{!frame.manual_refresh_only&&<button type="button" disabled={focusing||manual} onClick={()=>void focus()}>{focusing?'定位中…':'定位此控件'}</button>}</div>}
 </>}
 <p className="browserViewHint">这是只读预览。手动点击和登录请先接手独立 Chrome；Agent 操作请使用确认清单中的按钮。</p></div>;
}
