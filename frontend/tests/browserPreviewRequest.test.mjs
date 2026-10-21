import test from 'node:test';
import assert from 'node:assert/strict';
import {previewRequest,browserFrame} from '../src/lib/browserPreviewRequest.ts';
test('预览请求卡住时按时退出并取消，不会无限等待',async()=>{
 let requestSignal;
 await assert.rejects(previewRequest(signal=>{requestSignal=signal;return new Promise(()=>{});},undefined,10),/超时/);
 assert.equal(requestSignal.aborted,true);
});
test('切换会话取消预览，已取消时不再请求旧页',async()=>{
 const controller=new AbortController();let calls=0;
 controller.abort();
 await assert.rejects(previewRequest(async()=>{calls++;},controller.signal),{name:'AbortError'});
 assert.equal(calls,0);
});
test('正常预览请求返回原数据',async()=>{
 assert.equal(await previewRequest(async()=>42),42);
});
test('预览响应缺失字段不会进入渲染，旧响应缺少进度时安全兼容',()=>{
 for(const value of [null,{}, {image:'data:image/png;base64,',viewport:{width:0,height:100}}])assert.throws(()=>browserFrame(value),/数据不完整/);
 const frame=browserFrame({image:'data:image/png;base64,abc',url:'https://example.com',captured_at:100,viewport:{width:1200,height:800}});
 assert.deepEqual(frame.progress,{});assert.equal(frame.target,null);
});
