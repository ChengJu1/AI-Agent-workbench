import assert from 'node:assert/strict';
import test from 'node:test';
import {returnBrowserControl} from '../src/lib/browserContinuation.ts';
import {shouldContinue} from '../src/lib/approvalState.ts';

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

test('只有已落定的结果才自动继续；失败时交给服务端判断，结果不确定时不继续', () => {
  const action = {id: 'a', action: 'browser_actions', params: {session_id: 's'}};
  assert.equal(shouldContinue({action: {...action, status: 'approved', continuation_available: true}, uncertain: false}), true);
  assert.equal(shouldContinue({action: {...action, status: 'cancelled', continuation_available: true}, uncertain: false}), true);
  assert.equal(shouldContinue({action: {...action, status: 'approved', continuation_available: false}, uncertain: false}), false);
  assert.equal(shouldContinue({action: {...action, status: 'failed'}, uncertain: false}), true);
  assert.equal(shouldContinue({action: {...action, status: 'approved'}, uncertain: false}), false);
  for (const status of ['pending', 'executing']) {
    assert.equal(shouldContinue({action: {...action, status, continuation_available: true}, uncertain: false}), false);
  }
  assert.equal(shouldContinue({action: {...action, status: 'failed'}, uncertain: true}), false);
  assert.equal(shouldContinue({uncertain: true}), false);
});
