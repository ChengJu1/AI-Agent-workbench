import assert from 'node:assert/strict';
import test from 'node:test';
import {browserPreviewContext} from '../src/lib/browserPreviewContext.ts';
const page=id=>({id,url:`https://example.com/${id}`,manual_until:0});
const plan=(id,session='s1',conversation='c')=>({id,conversation_id:conversation,action:'browser_actions',status:'pending',params:{session_id:session,operations:[{kind:'click',label:'A'},{kind:'fill',label:'B'}]}});
test('选择确认步骤时预览绑定对应页面，而不是最近打开的其他页',()=>{
 const actual=browserPreviewContext('c',[page('s1'),page('s2')],[plan('a')],{actionId:'a',index:1},'s2');
 assert.equal(actual.session.id,'s1');assert.equal(actual.index,1);
});
test('清单页面关闭后不把目标叠加到另一页面',()=>{
 const actual=browserPreviewContext('c',[page('other')],[plan('a')],null,'other');
 assert.equal(actual.session,undefined);assert.equal(actual.action.id,'a');
});
test('其他会话与已结束操作不会成为当前待确认目标',()=>{
 const actual=browserPreviewContext('c',[page('s1')],[plan('foreign','s1','other'),{...plan('done'),status:'approved'}],{actionId:'foreign',index:1},'');
 assert.equal(actual.action,undefined);assert.equal(actual.session.id,'s1');assert.equal(actual.index,0);
});
test('默认预览最新待确认清单，非法步骤回到首步',()=>{
 const actions=[plan('a'),plan('b')];
 assert.equal(browserPreviewContext('c',[page('s1')],actions,null,'').action.id,'b');
 assert.equal(browserPreviewContext('c',[page('s1')],actions,{actionId:'b',index:99},'').index,0);
});
test('失败清单仍能定位其当前浏览器供只读截图，不恢复为可执行目标',()=>{
 const stopped={...plan('failed','s2'),status:'failed'};
 const result=browserPreviewContext('c',[page('s1'),page('s2')],[plan('pending','s1'),stopped],{actionId:'failed',index:1},'s1');
 assert.equal(result.action,undefined);assert.equal(result.session.id,'s2');assert.equal(result.source.id,'failed');
 const missing=browserPreviewContext('c',[page('s1')],[stopped],{actionId:'failed',index:0},'s1');
 assert.equal(missing.session,undefined);
});
