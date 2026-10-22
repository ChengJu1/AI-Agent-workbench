import type { ToolActivityEvent } from "../types";

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
