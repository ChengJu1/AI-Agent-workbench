// Keep the chat compact; review the full current action in a dedicated dialog.
import {useEffect, useRef, useState, type ReactElement} from 'react';
import {approvalState,splitApprovals} from '../lib/approvalState';
import type {AgentInfo, PendingAction} from '../types';
import {editedPlan, planProblem, withOrigins, type TeamPlan} from '../lib/teamPlan';
import {TeamPlanEditor} from './TeamPlanEditor';
import './approvals.css';

type Props = {
  actions:PendingAction[]; disabled:boolean; decidingId:string;
  onDecision:(id:string,approved:boolean,plan?:TeamPlan)=>Promise<void>;
  agents?:AgentInfo[];
  onPreview?:(id:string,index:number)=>void;
  onRefresh:()=>Promise<void>; refreshing:boolean; syncError:string;
  errors:Record<string,string>; uncertainIds:string[];
  historyOpen:boolean; onHistoryClose:()=>void;
};
const isTeamPlan=(a:PendingAction)=>a.tool_name==='workbench_team';
const actionTitle=(a:PendingAction)=>isTeamPlan(a)?'团队计划确认':a.action==='update_file'?'文件更新确认':a.tool_name==='workbench_platform'?'浏览器操作确认':'工时提交确认';
const operationName=(kind:string)=>(({fill:'填写',select:'选择',check:'勾选',upload:'上传附件',click:'点击',key:'按键'} as Record<string,string>)[kind]||kind);

export function ApprovalList(props:Props) {
  const [selected,setSelected]=useState<string|null>(null);
  const [now,setNow]=useState(Date.now()/1000);
  const seen=useRef<Set<string>|null>(null);
  useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()/1000),1000);return()=>clearInterval(timer);},[]);
  const {current,history}=splitApprovals(props.actions,now);
  // A request that arrives while the page is open pops up once; requests already present on load do not.
  useEffect(()=>{
    if (seen.current===null) { seen.current=new Set(props.actions.map(a=>a.id)); return; }
    if (current&&current.status==='pending'&&!seen.current.has(current.id)) setSelected(current.id);
    props.actions.forEach(a=>seen.current?.add(a.id));
  },[props.actions,current?.id]);
  const action=props.actions.find(a=>a.id===selected);
  const row=(a:PendingAction,onOpen:()=>void)=>{
    const state=approvalState(a,now),working=props.decidingId===a.id||a.status==='executing';
    return <section className="approvalSummary" key={a.id} aria-label={`${actionTitle(a)} · ${state.label}`}>
      <div><strong>{actionTitle(a)}</strong><span className={`approvalStatus status-${working?'executing':state.expired?'expired':a.status}`}>{working?'正在处理':state.label}</span>
        <p>{isTeamPlan(a)?(a.params as unknown as TeamPlan).participants.map(item=>item.name).join('、'):a.params.operations?.map(op=>`${operationName(op.kind)}：${op.label||'页面控件'}`).join('；')||a.params.filename||`${a.params.draft?.total_hours||0} 小时`}</p>
        {a.created_at&&<small className="approvalTime">{a.created_at}</small>}
      </div><button type="button" className="reviewApproval" onClick={onOpen}>{working?'查看进度':state.canApprove?'查看并确认':'查看详情'}</button>
    </section>;
  };
  // The bar takes room only while something waits for the user; past requests open from the shortcut bar.
  return <>
    {(current||props.syncError)&&<section className="approvalList" aria-label="操作确认">
      {props.syncError&&<p role="alert" className="approvalInlineError">{props.syncError}</p>}
      {current&&<div className="approvalSummaries">{row(current,()=>setSelected(current.id))}</div>}
    </section>}
    {props.historyOpen&&<HistoryDialog history={history} refreshing={props.refreshing} onRefresh={props.onRefresh}
      row={a=>row(a,()=>{props.onHistoryClose();setSelected(a.id);})} onClose={props.onHistoryClose}/>}
    {action&&<ApprovalDialog key={action.id} {...props} action={action} now={now} onDismiss={()=>setSelected(null)}/>}
  </>;
}

function HistoryDialog({history,row,onClose,refreshing,onRefresh}:{history:PendingAction[];row:(a:PendingAction)=>ReactElement;onClose:()=>void;refreshing:boolean;onRefresh:()=>Promise<void>}) {
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const element=dialog.current;element?.showModal();return()=>element?.close();},[]);
  return <dialog ref={dialog} className="agentEditor approvalDialog" aria-labelledby="approvalHistoryTitle" onCancel={e=>{e.preventDefault();onClose();}}>
    <header className="approvalDialogHeader"><div><h2 id="approvalHistoryTitle">操作记录</h2><p>已执行、已取消、已过期或被新请求取代的操作，按时间倒序。过期清单不能再确认，需要时请让 Agent 重新生成。</p></div>
      <div className="approvalHeaderActions"><button type="button" disabled={refreshing} onClick={()=>void onRefresh()}>{refreshing?'正在同步…':'刷新状态'}</button><button type="button" onClick={onClose}>关闭</button></div></header>
    <div className="approvalDialogBody">{history.length?<div className="approvalSummaries">{history.map(row)}</div>:<p className="agentEditorHint">还没有操作记录。</p>}</div>
  </dialog>;
}

function ApprovalDialog({action,now,onDismiss,...props}:Props&{action:PendingAction;now:number;onDismiss:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{
    const previous=document.activeElement instanceof HTMLElement?document.activeElement:null;
    dialog.current?.showModal();
    return()=>{dialog.current?.close();if(previous?.isConnected)previous.focus();};
  },[]);
  const state=approvalState(action,now);
  const working=props.decidingId===action.id||action.status==='executing';
  const uncertain=props.uncertainIds.includes(action.id);
  const blocked=props.disabled||working||uncertain||!!props.syncError;
  const error=action.result?.error||props.errors[action.id];
  const teamPlan=isTeamPlan(action)?action.params as unknown as TeamPlan:null;
  const [original]=useState(()=>teamPlan?withOrigins(teamPlan):null);
  const [plan,setPlan]=useState(original);
  const problem=plan&&action.status==='pending'?planProblem(plan,props.agents?.find(a=>a.id===action.agent_id)?.platform_capabilities??[]):'';
  return <dialog ref={dialog} className="agentEditor approvalDialog" aria-labelledby="approvalDialogTitle" aria-describedby="approvalDialogStatus" onCancel={e=>{e.preventDefault();onDismiss();}}>
    <header className="approvalDialogHeader"><div><h2 id="approvalDialogTitle">{actionTitle(action)}</h2><p id="approvalDialogStatus" role="status">{working?'正在处理，请勿重复点击。关闭弹框不会中断已发起的操作。':uncertain?'正在核对结果，请先刷新状态。':state.label}</p></div><button type="button" onClick={onDismiss} aria-label="关闭操作确认">关闭</button></header>
    <div className="approvalDialogBody">
      {action.params.operations&&<><p className="approvalDestination">接收页面：<strong>{action.params.title||'目标网页'}</strong><span>{action.params.url}</span></p>
        {action.params.network_notice&&<p>{action.params.network_notice}</p>}
        {!!action.params.connection_destinations?.length&&<p>本批资料也可能发送到已授权连接：{action.params.connection_destinations.join('、')}。</p>}
        <ol className="approvalOperations">{action.params.operations.map((op,index)=><li key={index}><strong>{operationName(op.kind)}：{op.label||'页面控件'}</strong>
          {op.value&&<p className="approvalValue">{op.value}</p>}{op.filename&&<p className="approvalValue">{op.filename}{op.file_version?` · v${op.file_version}`:''}</p>}
          <small>接收网站：{op.destination}</small>{props.onPreview&&state.canApprove&&!working&&<button type="button" onClick={()=>{onDismiss();props.onPreview?.(action.id,index);}}>预览此步</button>}</li>)}</ol>
        <p>确认后才执行本清单。操作执行完成不代表业务提交成功，仍需核对回执。</p></>}
      {action.params.operations&&props.onPreview&&!state.canApprove&&<button type="button" onClick={()=>{onDismiss();props.onPreview?.(action.id,0);}}>查看当前页面</button>}
      {plan&&original&&<TeamPlanEditor original={original} plan={plan} agents={props.agents??[]} leadId={action.agent_id}
        editable={state.canApprove&&!working&&!uncertain} onChange={setPlan}/>}
      {teamPlan&&action.status==='approved'&&<p>计划已批准，负责人会按批准的版本继续。</p>}
      {action.action==='update_file'&&<p>准备更新 {action.params.filename}，当前版本 v{action.params.expected_version}。确认后保存新版本，旧版本保留。</p>}
      {action.params.draft&&<><p>合计 {action.params.draft.total_hours} 小时</p><div className="approvalTimesheet">{action.params.draft.records.map((record,index)=><div key={index}><strong>{record.date} · {record.hours} 小时</strong><p>{record.task}</p>{record.note&&<small>{record.note}</small>}</div>)}</div></>}
      {action.result?.submission_id&&<p>提交编号：{action.result.submission_id}</p>}
    </div>
    <div className="approvalDialogFeedback">
      {state.expired&&<p role="status">清单已过期，尚未执行。请重新生成清单；不能继续使用旧清单。</p>}
      {problem&&<p role="alert">{problem}</p>}
      {(error||props.syncError)&&<p role="alert">{error||props.syncError}</p>}
      {action.status==='failed'&&<p>本清单已停止，不能再次确认。请核对失败原因后生成新清单。</p>}
    </div>
    <footer className="approvalDialogFooter"><button type="button" disabled={props.refreshing} onClick={()=>void props.onRefresh()}>{props.refreshing?'正在同步…':'刷新状态'}</button><div>
      {action.status==='pending'&&!working&&<button type="button" className="cancelButton" disabled={blocked} onClick={()=>void props.onDecision(action.id,false)}>{teamPlan?'不批准':'取消本次操作'}</button>}
      {state.canApprove&&!uncertain&&<button type="button" className="approveButton" disabled={blocked||!!problem}
        onClick={()=>void props.onDecision(action.id,true,plan&&original?editedPlan(original,plan):undefined)}>{working?'处理中…':teamPlan?'批准计划':action.tool_name==='workbench_platform'?'确认执行以上操作':'确认提交'}</button>}
      {(!state.canApprove||uncertain)&&<button type="button" onClick={onDismiss}>关闭</button>}
    </div></footer>
  </dialog>;
}
