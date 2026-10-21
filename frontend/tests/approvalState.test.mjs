import assert from 'node:assert/strict';
import test from 'node:test';
import {approvalState,decideAndReconcile} from '../src/lib/approvalState.ts';
import {upsertAction} from '../src/lib/messages.ts';
const action=(status='pending')=>({id:'a',conversation_id:'c',status,params:{expires_at:100},result:null});
test('过期前可确认，到期后立即禁用，终态不能再次确认',()=>{
 assert.equal(approvalState(action(),99).canApprove,true);
 assert.equal(approvalState(action(),100).canApprove,false);
 assert.equal(approvalState(action(),100).label,'清单已过期');
 for(const status of ['executing','approved','cancelled','failed']) assert.equal(approvalState(action(status),0).canApprove,false);
});
test('迟到的待确认事件不能把执行中或终态恢复成可点击',()=>{
 for(const status of ['executing','approved','cancelled','failed']) assert.equal(upsertAction([action(status)],action())[0].status,status);
 assert.equal(upsertAction([action('pending')],action('failed'))[0].status,'failed');
});
test('502 后读取已持久化失败结果，旧按钮不继续显示待确认，也不重试写入',async()=>{
 let writes=0,reads=0;
 const outcome=await decideAndReconcile(async()=>{writes++;throw Error('502');},async()=>{reads++;return {...action('failed'),result:{error:'页面已变化'}};});
 assert.equal(outcome.action.status,'failed');assert.equal(outcome.error,'页面已变化');
 assert.equal(outcome.uncertain,false);assert.equal(outcome.executedHere,false);
 assert.equal(writes,1);assert.equal(reads,1);
});
test('409 已处理时同步真实终态，不重放执行或自动续接',async()=>{
 const outcome=await decideAndReconcile(async()=>{throw Error('already handled');},async()=>action('approved'));
 assert.equal(outcome.action.status,'approved');assert.equal(outcome.executedHere,false);assert.equal(outcome.uncertain,false);
});
test('响应丢失且无法核对时阻止重复确认，读到 pending 也不擅自认定未执行',async()=>{
 for(const read of [async()=>{throw Error('offline');},async()=>action()]){
  let writes=0;const result=await decideAndReconcile(async()=>{writes++;throw Error('lost response');},read);
  assert.equal(result.uncertain,true);assert.equal(result.executedHere,false);assert.equal(writes,1);
 }
});
test('正常响应不额外读写，保持一次审批对应一次续接',async()=>{
 let reads=0;const result=await decideAndReconcile(async()=>action('approved'),async()=>{reads++;return action();});
 assert.equal(result.executedHere,true);assert.equal(reads,0);
});
import {splitApprovals} from '../src/lib/approvalState.ts';
const item=(id,status,created_at,expires_at=200)=>({id,conversation_id:'c',status,created_at,params:{expires_at},result:null});
test('只显示一个当前请求，过期、已处理和被新请求取代的都进入历史',()=>{
 const rows=[item('old','pending','2026-10-21 10:00'),item('expired','pending','2026-10-21 10:05',50),item('done','approved','2026-10-21 10:06'),item('new','pending','2026-10-21 10:07')];
 const {current,history}=splitApprovals(rows,100);
 assert.equal(current.id,'new');
 assert.deepEqual(history.map(a=>a.id),['done','expired','old']);
 assert.equal(splitApprovals([item('run','executing','1'),item('later','pending','2')],100).current.id,'run');
 assert.equal(splitApprovals([item('x','pending','1',50)],100).current,null);
 assert.equal(splitApprovals([],100).history.length,0);
});
