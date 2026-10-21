import assert from 'node:assert/strict';
import test from 'node:test';
import {approvedBrowserContinuation, returnBrowserControl} from '../src/lib/browserContinuation.ts';

test('交回成功后才发送一次可见续接消息，不把交回当作业务审批', async () => {
  const calls = [];
  await returnBrowserControl('s', async () => {calls.push('handback');}, async message => {
    calls.push(message);
    assert.match(message, /重新读取当前页面/);
    assert.match(message, /最终提交单独/);
    assert.match(message, /不要重放/);
  });
  assert.equal(calls.length, 2);
  assert.equal(calls[0], 'handback');
});

test('交回失败不发送续接，也不自动重试', async () => {
  let handbacks = 0, turns = 0;
  await assert.rejects(returnBrowserControl('s', async () => {handbacks++;throw Error('closed');}, async () => {turns++;}), /closed/);
  assert.equal(handbacks, 1);
  assert.equal(turns, 0);
});

test('只有成功执行的浏览器批次续接，取消失败等待中或其他审批不触发', () => {
  const action = {action: 'browser_actions', status: 'approved', params: {session_id: 's'}};
  assert.match(approvedBrowserContinuation(action), /核对实际状态/);
  for (const status of ['pending','executing','failed','cancelled']) {
    assert.equal(approvedBrowserContinuation({...action, status}), null);
  }
  assert.equal(approvedBrowserContinuation({...action, action: 'update_file'}), null);
  assert.equal(approvedBrowserContinuation({...action, params: {}}), null);
});
