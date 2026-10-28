// 负责人提交的团队计划：用户在批准前可以替换、修改或删除参与者；规则和后端一致，提前在页面上提示。
import type { AgentInfo } from "../types";

export type PlanParticipant = {
  agent_id?: string; name: string; role?: string;
  instructions?: string; capabilities?: string[];
  /** 页面内部用：负责人原计划里的位置，删除别的参与者后仍能找回原提议。不发给后端。 */
  origin?: number;
};
export type TeamPlan = { summary: string; participants: PlanParticipant[] };

export const MAX_PLAN_PARTICIPANTS = 5;

export function isTemporary(participant: PlanParticipant) {
  return !participant.agent_id;
}

/** 可以换上的 Agent：工作区里除负责人以外未归档、且没在计划里的 Agent（当前这一位除外）。 */
export function replacementOptions(plan: TeamPlan, index: number, agents: AgentInfo[], leadId: string) {
  const used = new Set(plan.participants.filter((_, position) => position !== index).map(item => item.agent_id).filter(Boolean));
  return agents.filter(agent => agent.id !== leadId && !agent.archived && !used.has(agent.id));
}

export function withOrigins(plan: TeamPlan): TeamPlan {
  return { ...plan, participants: plan.participants.map((item, origin) => ({ ...item, origin })) };
}

function stripOrigins(plan: TeamPlan): TeamPlan {
  return { ...plan, participants: plan.participants.map(({ origin: _origin, ...item }) => item) };
}

/** 换成现有 Agent，或换回负责人原本提议的临时 Agent。 */
export function replaceParticipant(plan: TeamPlan, index: number, choice: AgentInfo | PlanParticipant): TeamPlan {
  const current = plan.participants[index];
  const next: PlanParticipant = "id" in choice
    ? { agent_id: choice.id, name: choice.name, role: current.role, origin: current.origin }
    : { ...choice, role: current.role, origin: current.origin };
  return { ...plan, participants: plan.participants.map((item, position) => position === index ? next : item) };
}

export function updateParticipant(plan: TeamPlan, index: number, change: Partial<PlanParticipant>): TeamPlan {
  return { ...plan, participants: plan.participants.map((item, position) => position === index ? { ...item, ...change } : item) };
}

export function removeParticipant(plan: TeamPlan, index: number): TeamPlan {
  return { ...plan, participants: plan.participants.filter((_, position) => position !== index) };
}

/** 页面上的提前检查；后端还会再校验一次。能力只能是负责人能力的子集。 */
export function planProblem(plan: TeamPlan, leadCapabilities: string[]): string {
  if (!plan.participants.length) return "至少保留一个参与者。";
  if (plan.participants.length > MAX_PLAN_PARTICIPANTS) return `参与者最多 ${MAX_PLAN_PARTICIPANTS} 个。`;
  for (const item of plan.participants) {
    if (!isTemporary(item)) continue;
    if (!item.instructions?.trim()) return `临时 Agent ${item.name} 需要职责说明。`;
    if (item.instructions.length > 2000) return `临时 Agent ${item.name} 的职责说明最多 2000 字。`;
    const extra = (item.capabilities ?? []).filter(value => !leadCapabilities.includes(value));
    if (extra.length) return `临时 Agent ${item.name} 不能拥有负责人没有的能力：${extra.join("、")}。`;
  }
  return "";
}

/** 只把用户改过的计划发回后端；没改时按负责人原本的计划批准。 */
export function editedPlan(original: TeamPlan, current: TeamPlan): TeamPlan | undefined {
  const sent = stripOrigins(current);
  return JSON.stringify(stripOrigins(original)) === JSON.stringify(sent) ? undefined : sent;
}
