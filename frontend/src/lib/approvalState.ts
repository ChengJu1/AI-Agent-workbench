import type {PendingAction} from '../types';

export function approvalState(action: PendingAction, now = Date.now() / 1000) {
  const expired = action.status === 'pending' && action.params.expires_at !== undefined && action.params.expires_at <= now;
  return {expired, canApprove: action.status === 'pending' && !expired,
    label: expired ? '清单已过期' : ({pending:'等待确认',executing:'正在执行',approved:'操作已执行',cancelled:'已取消',failed:'执行失败'})[action.status]};
}

type DecisionResult = {action?: PendingAction; error?: string; uncertain: boolean; executedHere: boolean};

// Never retry a write. Even an HTTP failure can have a persisted terminal result.
export async function decideAndReconcile(
  decide: () => Promise<PendingAction>, read: () => Promise<PendingAction>, sideEffectFree = false,
): Promise<DecisionResult> {
  try { return {action: await decide(), uncertain:false, executedHere:true}; }
  catch (error) {
    try {
      const action = await read();
      // 没有副作用的确认（团队计划）被拒绝时仍是待确认：直接给出原因，用户改了可以再批。
      if (sideEffectFree && action.status === 'pending') {
        return {action, uncertain:false, executedHere:false, error: error instanceof Error ? error.message : '没有批准，请检查后重试。'};
      }
      return {action, uncertain:action.status === 'pending', executedHere:false,
        error: action.status === 'failed' ? action.result?.error || '执行失败，请查看当前结果。'
          : action.status === 'pending' ? '暂未确认执行结果，请先刷新状态，勿重复确认。'
          : '状态已同步，这条操作不能重复执行。'};
    } catch {
      return {uncertain:true, executedHere:false, error:'暂时无法核对操作结果，请刷新状态后再处理，勿重复确认。'};
    }
  }
}

/** Resume the Agent only on a settled result; the server re-checks every condition (same turn, all decided, once). */
export function shouldContinue(outcome: DecisionResult) {
  const action = outcome.action;
  if (!action || outcome.uncertain || !['approved', 'failed', 'cancelled'].includes(action.status)) return false;
  // A failed execution answers with an error, so its reconciled record carries no flag; let the server decide.
  return action.continuation_available ?? action.status === 'failed';
}

/** Only one request is current: one executing, else the newest still-confirmable one. Everything else is history. */
export function splitApprovals(actions: PendingAction[], now = Date.now() / 1000) {
  const ordered = [...actions].sort((a, b) => String(a.created_at ?? '').localeCompare(String(b.created_at ?? '')));
  const current = ordered.filter(a => a.status === 'executing').pop()
    ?? ordered.filter(a => approvalState(a, now).canApprove).pop() ?? null;
  return {current, history: ordered.filter(a => a !== current).reverse()};
}
