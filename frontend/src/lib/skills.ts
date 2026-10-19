import type { SkillDefinition, SkillReference } from "../types";

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
