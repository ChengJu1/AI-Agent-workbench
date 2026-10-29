import assert from "node:assert/strict";
import test from "node:test";
import { editedPlan, planProblem, removeParticipant, replaceParticipant, replacementOptions, updateParticipant, withOrigins } from "../src/lib/teamPlan.ts";

const agents = [
  { id: "lead", name: "负责人", description: "", platform_capabilities: ["files", "web"] },
  { id: "mine", name: "我的研究员", description: "", platform_capabilities: [] },
  { id: "old", name: "已归档", description: "", archived: true },
];
const proposed = { summary: "评审方案", participants: [
  { name: "安全评审", instructions: "只看安全。", capabilities: ["files", "web"], role: "挑安全问题" },
  { agent_id: "mine", name: "我的研究员", role: "查资料" },
] };

test("没改计划时按原计划批准；改过时只发回去掉内部字段的新版本", () => {
  const original = withOrigins(proposed);
  assert.equal(editedPlan(original, original), undefined);
  const trimmed = updateParticipant(original, 0, { capabilities: ["files"] });
  assert.deepEqual(editedPlan(original, trimmed).participants[0], { name: "安全评审", instructions: "只看安全。", capabilities: ["files"], role: "挑安全问题" });
});

test("可替换的 Agent 不含负责人、已归档和已在计划里的，替换后保留分工和原位置", () => {
  const original = withOrigins(proposed);
  assert.deepEqual(replacementOptions(original, 0, agents, "lead").map(agent => agent.id), []);
  const freed = removeParticipant(original, 1);
  assert.deepEqual(replacementOptions(freed, 0, agents, "lead").map(agent => agent.id), ["mine"]);
  const swapped = replaceParticipant(freed, 0, agents[1]);
  assert.deepEqual(swapped.participants[0], { agent_id: "mine", name: "我的研究员", role: "挑安全问题", origin: 0 });
  // 换回负责人原本提议的临时 Agent。
  assert.equal(replaceParticipant(swapped, 0, original.participants[0]).participants[0].instructions, "只看安全。");
});

test("页面提前拦下越权能力、空说明和空计划", () => {
  const original = withOrigins(proposed);
  assert.equal(planProblem(original, ["files", "web"]), "");
  assert.match(planProblem(original, ["files"]), /不能拥有负责人没有的能力：web/);
  assert.match(planProblem(updateParticipant(original, 0, { instructions: " " }), ["files", "web"]), /需要职责说明/);
  assert.match(planProblem({ summary: "x", participants: [] }, []), /至少保留一个/);
});
