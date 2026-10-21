import test from 'node:test';
import assert from 'node:assert/strict';
import {restoreBrowserResources} from '../src/lib/restoreBrowserResources.ts';

test('资源确认后先交回再加载，按原截止时间恢复而非重新授权五分钟',async()=>{
 const calls=[];let clock=100;
 const result=await restoreBrowserResources({manualUntil:300,isCurrent:()=>true,now:()=>clock,
  handoff:async()=>{calls.push('handoff');clock+=2;},reload:async()=>{calls.push('reload');clock+=8;return {url:'/login'};},
  resume:async seconds=>calls.push(['resume',seconds])});
 assert.deepEqual(calls,['handoff','reload',['resume',190]]);assert.equal(result.url,'/login');
});
test('原接手已过期时只恢复资源，不擅自启用手动操作',async()=>{
 const calls=[];
 await restoreBrowserResources({manualUntil:90,now:()=>100,isCurrent:()=>true,handoff:async()=>calls.push('handoff'),
  reload:async()=>calls.push('reload'),resume:async()=>calls.push('resume')});
 assert.deepEqual(calls,['reload']);
});
test('加载过程中接手时间不足时不以最短时长延长授权',async()=>{
 const calls=[];let clock=100;
 await restoreBrowserResources({manualUntil:150,now:()=>clock,isCurrent:()=>true,handoff:async()=>calls.push('handoff'),
  reload:async()=>{clock=140;calls.push('reload');},resume:async()=>calls.push('resume')});
 assert.deepEqual(calls,['handoff','reload']);
});
test('页面恢复失败不自动重试、恢复手动权限或重发操作',async()=>{
 const calls=[];
 await assert.rejects(restoreBrowserResources({manualUntil:300,now:()=>100,isCurrent:()=>true,
  handoff:async()=>calls.push('handoff'),reload:async()=>{calls.push('reload');throw new Error('failed');},resume:async()=>calls.push('resume')}),/failed/);
 assert.deepEqual(calls,['handoff','reload']);
});
test('用户关闭面板或切换页面时停止后续加载和接手恢复',async()=>{
 let current=true;const calls=[];
 await restoreBrowserResources({manualUntil:300,now:()=>100,isCurrent:()=>current,
  handoff:async()=>{calls.push('handoff');current=false;},reload:async()=>calls.push('reload'),resume:async()=>calls.push('resume')});
 assert.deepEqual(calls,['handoff']);
});
