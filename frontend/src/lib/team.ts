// 负责人委派给团队成员的状态和合计用量；纯函数，便于测试。
import type { ChatMessage, Delegation, DelegationUsage } from "../types";

export const MAX_TEAM_MEMBERS = 5;

/** 开始事件新增一张卡片；结束事件更新同一子会话里最近一张进行中的卡片，保留开始时的任务摘要。 */
export function applyDelegation(list: Delegation[], event: Delegation): Delegation[] {
  if (event.status === "running") return [...list, event];
  for (let index = list.length - 1; index >= 0; index--) {
    const item = list[index];
    if (item.child_conversation_id === event.child_conversation_id && item.status === "running") {
      return [...list.slice(0, index), { ...item, ...event, task: item.task }, ...list.slice(index + 1)];
    }
  }
  return [...list, event];
}

export const delegationStatusLabel: Record<Delegation["status"], string> = {
  running: "进行中", complete: "完成", failed: "失败", needs_approval: "待确认",
};

const FIELDS = ["input_tokens", "output_tokens", "model_calls", "tool_calls"] as const;

/** 负责人本轮加上所有成员的用量；任何一方未提供某项时该项为 null，不按 0 计算。 */
export function teamUsage(message: ChatMessage): DelegationUsage | null {
  const delegations = message.delegations ?? [];
  if (!delegations.length || !message.usage) return null;
  const parts: Partial<DelegationUsage>[] = [message.usage, ...delegations.map(item => item.usage ?? {})];
  const total = { input_tokens: null, output_tokens: null, cache_read_input_tokens: null, model_calls: null, tool_calls: null } as DelegationUsage;
  for (const field of FIELDS) {
    const values = parts.map(part => part[field]);
    total[field] = values.every(value => typeof value === "number") ? (values as number[]).reduce((sum, value) => sum + value, 0) : null;
  }
  return total;
}

/** 团队成员只能从其他未归档的 Agent 中选，最多 MAX_TEAM_MEMBERS 个。 */
export function toggleMember(selected: string[], id: string): string[] {
  if (selected.includes(id)) return selected.filter(item => item !== id);
  return selected.length >= MAX_TEAM_MEMBERS ? selected : [...selected, id];
}

export function moveMember(selected: string[], id: string, offset: -1 | 1): string[] {
  const index = selected.indexOf(id);
  const target = index + offset;
  if (index < 0 || target < 0 || target >= selected.length) return selected;
  const next = [...selected];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
