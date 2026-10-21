import type { RuntimeName, ToolActivityEvent } from "../types";

export function runtimeLabel(runtime?: RuntimeName) {
  return runtime === "deep_agents" ? "Deep Agents" : "Claude SDK";
}

export function effectiveRuntime(defaultRuntime: RuntimeName | undefined, override: RuntimeName | undefined, enabled: boolean): RuntimeName {
  return enabled ? (override ?? defaultRuntime ?? "claude_sdk") : "claude_sdk";
}

export function tokenLabel(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value.toLocaleString("zh-CN") : "未提供";
}

export function toolActivityRows(events: ToolActivityEvent[]) {
  const rows = new Map<string, { id: string; name: string; status: "running" | "success" | "failed" }>();
  for (const event of events) {
    const previous = rows.get(event.call_id);
    if (event.type === "tool_started" && previous && previous.status !== "running") continue;
    rows.set(event.call_id, { id: event.call_id, name: event.tool_name,
      status: event.type === "tool_started" ? "running" : event.success ? "success" : "failed" });
  }
  return [...rows.values()];
}
