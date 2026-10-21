import type {PendingAction} from '../types';

export function browserContinuation(sessionId: string, reason: 'handoff' | 'approved'): string {
  return `${reason === 'handoff' ? '我已结束浏览器接手，请继续原任务。' : '刚才的浏览器确认操作已执行，请核对结果并继续原任务。'}当前浏览器会话：${sessionId}。先查询浏览器会话并重新读取当前页面，核对实际状态；需要附件时核对当前文件版本。继续准备填写、上传等待确认清单，仅询问缺失的必填信息。不要重放已执行的操作；最终提交单独生成确认清单，不因这条消息直接提交。`;
}

// Run only from an explicit handback click; a failed handback never sends a turn.
export async function returnBrowserControl(sessionId: string, handback: () => Promise<unknown>, continueTask: (message: string) => Promise<void>) {
  await handback();
  await continueTask(browserContinuation(sessionId, 'handoff'));
}

export function approvedBrowserContinuation(action: PendingAction): string | null {
  return action.status === 'approved' && action.action === 'browser_actions' && action.params.session_id
    ? browserContinuation(action.params.session_id, 'approved') : null;
}
