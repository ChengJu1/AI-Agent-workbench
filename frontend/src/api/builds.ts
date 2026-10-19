import type { AgentInfo } from "../types";
import { jsonBody, requestJson } from "./http";

export type BuildStatus = "generating" | "testing" | "needs_input" | "ready" | "failed" | "published";
export type BuildPlan = {
  status: "ready" | "needs_input"; message: string; name: string; description: string; system_prompt: string;
  tools: { name: string; description: string; input_schema: object; output_schema: object; code: string }[];
};
export type Build = {
  id: string; package_id: string; base_version: number; status: BuildStatus; revision: number;
  history: { role: "user" | "assistant"; content: string }[];
  plan: BuildPlan | null; tests: { method: string; name: string; passed: boolean; error?: string }[];
  error: string | null; published_agent: AgentInfo | null;
};
export type BuildSummary = { id: string; status: BuildStatus; name: string };
export type CapabilityPackage = { id: string; version: number; name: string };
export type BuildRuntime = { available: boolean; message: string };
export const working = (status?: BuildStatus) => status === "generating" || status === "testing";
export const buildLabels: Record<BuildStatus, string> = {
  generating: "正在编写方法", testing: "正在运行测试", needs_input: "需要补充信息",
  ready: "测试通过，等待创建", failed: "需要调整", published: "已创建",
};
const ROOT = "/api/agent-builds";
export const fetchBuilds = (signal?: AbortSignal) => requestJson<BuildSummary[]>(ROOT, { signal });
export const fetchBuild = (id: string, signal?: AbortSignal) => requestJson<Build>(`${ROOT}/${encodeURIComponent(id)}`, { signal });
export const fetchPackages = (signal?: AbortSignal) => requestJson<CapabilityPackage[]>(`${ROOT}/packages`, { signal });
export const fetchBuildRuntime = (signal?: AbortSignal) => requestJson<BuildRuntime>(`${ROOT}/runtime`, { signal });
export const startBuild = (requestId: string, message: string, base: string | null, signal?: AbortSignal) =>
  requestJson<Build>(ROOT, { ...jsonBody({ request_id: requestId, message, base_package_id: base }), signal });
export const reviseBuild = (build: Build, message: string, signal?: AbortSignal) =>
  requestJson<Build>(`${ROOT}/${build.id}/messages`, { ...jsonBody({ message, expected_revision: build.revision }), signal });
export const publishBuild = (build: Build, signal?: AbortSignal) =>
  requestJson<AgentInfo>(`${ROOT}/${build.id}/publish`, { ...jsonBody({ expected_revision: build.revision }), signal });
