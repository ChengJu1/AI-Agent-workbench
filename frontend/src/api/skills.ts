import type { SkillBinding, SkillDefinition, SkillInfo } from "../types";
import { skillBindingFields } from "../lib/skills";
import { jsonBody, requestJson } from "./http";

export const fetchSkills = (signal?: AbortSignal) => requestJson<SkillInfo[]>("/api/skills", { signal });
export function saveSkill(definition: SkillDefinition, existing?: SkillInfo, signal?: AbortSignal) {
  return requestJson<SkillInfo>(existing ? `/api/skills/${encodeURIComponent(existing.id)}` : "/api/skills", {
    ...jsonBody(existing ? { ...definition, expected_version: existing.version } : definition),
    method: existing ? "PUT" : "POST", signal,
  });
}
export function previewSkillImport(filename: string, content: string, signal?: AbortSignal) {
  return requestJson<SkillDefinition & { ignored_fields: string[] }>("/api/skills/import-preview", {
    ...jsonBody({ filename, content }), signal,
  });
}
export const fetchSkillVersions = (id: string, signal?: AbortSignal) =>
  requestJson<SkillInfo[]>(`/api/skills/${encodeURIComponent(id)}/versions`, { signal });
export const fetchAgentSkills = (id: string, signal?: AbortSignal) =>
  requestJson<SkillInfo[]>(`/api/agents/${encodeURIComponent(id)}/skills`, { signal });
export const bindAgentSkills = (id: string, bindings: SkillBinding[], signal?: AbortSignal) =>
  requestJson<SkillInfo[]>(`/api/agents/${encodeURIComponent(id)}/skills`, {
    ...jsonBody(skillBindingFields(bindings)), method: "PUT", signal,
  });
