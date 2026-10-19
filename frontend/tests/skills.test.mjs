import assert from "node:assert/strict";
import test from "node:test";
import { agentDefinition } from "../src/lib/agentDefinitions.ts";
import { applySkills, createMessage, finishMessage, restoreMessages } from "../src/lib/messages.ts";
import { parseSkillReferences, skillBindingFields, skillLoadLabel, skillMarkdown } from "../src/lib/skills.ts";
import { consumeEventStream, SseParser } from "../src/api/sse.ts";

const skills = [{ id: "skill-1", name: "需求拆解", version: 1 }];
const frame = (value) => `data: ${JSON.stringify(value)}\n\n`;

test("创建和切换绑定保留明确版本，修改选择不改写已生成的请求", () => {
  const selected = [{ id: "first", version: 2 }, { id: "second", version: 3 }];
  const fields = skillBindingFields(selected);
  const definition = agentDefinition("项目助理", "拆解", "依据规则", [], [], fields.skill_ids, fields.skill_versions);
  assert.deepEqual(fields, { skill_ids: ["first", "second"], skill_versions: { first: 2, second: 3 } });
  selected[0].version = 3;
  fields.skill_versions.second = 1;
  assert.deepEqual(definition.skill_versions, { first: 2, second: 3 });
  assert.deepEqual(skillBindingFields([]), { skill_ids: [], skill_versions: {} });
});

test("版本选择拒绝无效版本、重复选择和未绑定的版本映射", () => {
  for (const version of [0, -1, 1.5, true, "2", undefined]) {
    assert.throws(() => skillBindingFields([{ id: "first", version }]), /版本/);
    assert.throws(() => agentDefinition("助理", "说明", "规则", [], [], ["first"], { first: version }), /版本/);
  }
  assert.throws(() => skillBindingFields([{ id: "first", version: 1 }, { id: "first", version: 2 }]), /重复/);
  assert.throws(() => agentDefinition("助理", "说明", "规则", [], [], ["first"], { other: 1 }), /版本/);
});

test("仅绑定 Skill 可以创建 Agent，且不能重复或隐式添加工具", () => {
  const ids = ["skill-1"];
  const result = agentDefinition("项目助理", "拆解需求", "按规则整理", [], [], ids);
  assert.deepEqual(result.tools, []);
  assert.deepEqual(result.skill_ids, ids);
  result.skill_ids.push("other");
  assert.deepEqual(ids, ["skill-1"]);
  for (const invalid of [[""], ["a", "a"]]) {
    assert.throws(() => agentDefinition("助理", "说明", "规则", [], [], invalid), /Skill/);
  }
});

test("超过五个 Skill 的绑定、流式读取记录与历史恢复不受数量限制", () => {
  const refs = Array.from({length: 12}, (_, i) => ({ id: `skill-${i}`, name: `规则 ${i}`, version: i + 1 }));
  const fields = skillBindingFields(refs);
  const definition = agentDefinition("项目助理", "处理项目", "按需读取", [], [], fields.skill_ids, fields.skill_versions);
  assert.equal(definition.skill_ids.length, 12);
  assert.equal(definition.skill_versions["skill-11"], 12);
  assert.deepEqual(parseSkillReferences(refs), refs);
  const parser = new SseParser();
  assert.deepEqual(parser.push(frame({type: "skills", skills: refs, mode: "on_demand"}))[0].skills, refs);
  const message = createMessage("assistant", "已按需读取");
  const restored = restoreMessages(finishMessage(applySkills([message], message.id, refs, "on_demand"), message.id));
  assert.deepEqual(restored[0].skills, refs);
});

test("Skill 导出转义名称和说明，保持 Markdown 正文", () => {
  const result = skillMarkdown({ name: '需求: "拆解"', description: "第一行\n第二行", content: "# 步骤\n```text\n示例\n```" });
  assert.ok(result.startsWith('---\nname: "需求: \\"拆解\\""\n'));
  assert.ok(result.includes('description: "第一行\\n第二行"'));
  assert.ok(result.endsWith("# 步骤\n```text\n示例\n```\n"));
});

test("Skill 流事件支持任意分块，并拒绝非法版本或重复记录", () => {
  const input = frame({ type: "skills", skills });
  for (let i = 1; i < input.length; i++) {
    const parser = new SseParser();
    assert.deepEqual([...parser.push(input.slice(0, i)), ...parser.push(input.slice(i))], [{ type: "skills", skills }]);
  }
  for (const invalid of [null, [...skills, ...skills], [{ ...skills[0], version: 0 }], [{ ...skills[0], version: true }], [{ ...skills[0], name: "" }]]) {
    assert.throws(() => parseSkillReferences(invalid), /Skill/);
  }
});

test("Skill 事件独立分发，不混入回答文字", async () => {
  const received = []; const text = [];
  const body = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode(frame({ type: "skills", skills }) + frame({ type: "delta", content: "回答" }) + frame({ type: "done" })));
    controller.close();
  } });
  await consumeEventStream(body, { onDelta: (value) => text.push(value), onApprovalRequired() {}, onSkills: (value) => received.push(value) });
  assert.deepEqual(received, [skills]);
  assert.deepEqual(text, ["回答"]);
});

test("历史与中断回复保留当轮 Skill 版本，不改写其他消息", () => {
  const first = createMessage("assistant", "历史回答");
  first.skills = skills;
  const current = createMessage("assistant", "");
  const updated = applySkills([first, current], current.id, [{ ...skills[0], version: 2 }]);
  assert.equal(updated[0].skills[0].version, 1);
  const failed = finishMessage(updated, current.id, true);
  assert.equal(failed.length, 2);
  assert.equal(failed[1].status, "failed");
  assert.equal(restoreMessages(failed)[1].skills[0].version, 2);
});

test("按需读取与旧预载记录分别显示，空记录不会伪报使用 Skill", () => {
  assert.equal(skillLoadLabel({}), null);
  assert.equal(skillLoadLabel({ skills }), "预载 Skill（旧记录）");
  assert.equal(skillLoadLabel({ skills, skill_mode: "on_demand" }), "本轮按需读取");
  assert.equal(skillLoadLabel({ skills: [], skill_mode: "on_demand" }), "本轮未读取 Skill");
  assert.equal(skillLoadLabel({ skills: [], skill_mode: "on_demand", status: "streaming" }), "本轮尚未读取 Skill");
  const message = createMessage("assistant", "");
  const updated = applySkills([message], message.id, [], "on_demand");
  const restored = restoreMessages(finishMessage(updated, message.id, true));
  assert.deepEqual(restored[0].skills, []);
  assert.equal(restored[0].skill_mode, "on_demand");
});

test("流式读取事件保留按需模式，不接受未知模式", async () => {
  const parser = new SseParser();
  assert.deepEqual(parser.push(frame({ type: "skills", skills: [], mode: "on_demand" })), [{ type: "skills", skills: [], mode: "on_demand" }]);
  assert.throws(() => parser.push(frame({ type: "skills", skills, mode: "automatic" })), /加载方式/);
  const received = [];
  const body = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode(frame({ type: "skills", skills, mode: "on_demand" }) + frame({ type: "done" })));
    controller.close();
  } });
  await consumeEventStream(body, { onDelta() {}, onApprovalRequired() {}, onSkills: (value, mode) => received.push({ value, mode }) });
  assert.deepEqual(received, [{ value: skills, mode: "on_demand" }]);
});
