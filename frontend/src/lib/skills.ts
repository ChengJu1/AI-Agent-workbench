import type { ChatMessage, SkillBinding, SkillDefinition, SkillReference } from "../types";

export function skillBindingFields(bindings: SkillBinding[]) {
  const ids = new Set<string>();
  if (bindings.length > 5) throw new Error("最多选择 5 个 Skill。");
  for (const binding of bindings) {
    if (!binding.id.trim() || ids.has(binding.id) || !Number.isSafeInteger(binding.version) || binding.version < 1) {
      throw new Error("请选择有效且不重复的 Skill 及版本。");
    }
    ids.add(binding.id);
  }
  return { skill_ids: [...ids], skill_versions: Object.fromEntries(bindings.map(({ id, version }) => [id, version])) };
}

export function skillLoadLabel(message: Pick<ChatMessage, "skills" | "skill_mode" | "status">): string | null {
  if (message.skills === undefined) return null;
  if (message.skill_mode === "on_demand") {
    if (message.skills.length) return "本轮按需读取";
    return message.status === "streaming" ? "本轮尚未读取 Skill" : "本轮未读取 Skill";
  }
  return message.skills.length ? "预载 Skill（旧记录）" : null;
}

export function skillMarkdown(skill: SkillDefinition): string {
  return `---\nname: ${JSON.stringify(skill.name)}\ndescription: ${JSON.stringify(skill.description)}\n---\n\n${skill.content}\n`;
}

export function parseSkillReferences(value: unknown): SkillReference[] {
  if (!Array.isArray(value) || value.length > 5) throw new Error("Skill 版本记录格式不正确。");
  const ids = new Set<string>();
  return value.map((item) => {
    if (!item || typeof item !== "object" || typeof item.id !== "string" || !item.id || item.id.length > 100 ||
        typeof item.name !== "string" || !item.name || item.name.length > 100 ||
        !Number.isSafeInteger(item.version) || item.version < 1 || ids.has(item.id)) {
      throw new Error("Skill 版本记录格式不正确。");
    }
    ids.add(item.id);
    return { id: item.id, name: item.name, version: item.version };
  });
}
