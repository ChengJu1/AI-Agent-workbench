import type { Application, DateValue, KitItem, Stage } from "../api/applications";

export const STAGES: { id: Stage; label: string }[] = [
  { id: "saved", label: "待投递" }, { id: "preparing", label: "准备中" }, { id: "applied", label: "已投递" }, { id: "test", label: "笔试/测评" },
  { id: "interview", label: "面试" }, { id: "offer", label: "offer" }, { id: "rejected", label: "未通过" }, { id: "withdrawn", label: "放弃" },
];
const OPEN: Stage[] = ["saved", "preparing"];
const CLOSED: Stage[] = ["offer", "rejected", "withdrawn"];

export const FLAG_LABELS: Record<string, string> = {
  draft: "Agent 起草，请改成你的话", chat: "你在对话中提供", converted: "已换成页面选项说法", file: "需上传的文件", missing: "资料中没有，请自行填写",
};

/** Days from `now` to a YYYY-MM-DD[ HH:MM] value, counted by calendar date; null when empty or malformed. */
export function daysUntil(value: string, now = new Date()): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  const day = Date.UTC(+match[1], +match[2] - 1, +match[3]);
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((day - today) / 86400000);
}

export type AgendaEntry = { id: string; kind: "deadline" | "event"; when: string; days: number; title: string; detail: string };

/** Deadlines of jobs not yet applied to (within `deadlineDays`, overdue included) and scheduled events (within `eventDays`). */
export function agenda(items: Application[], now = new Date(), deadlineDays = 3, eventDays = 7): AgendaEntry[] {
  const rows: AgendaEntry[] = [];
  for (const item of items) {
    const title = [item.company, item.position].filter(Boolean).join(" · ");
    const due = daysUntil(item.deadline, now);
    if (due !== null && due <= deadlineDays && OPEN.includes(item.stage)) rows.push({ id: item.id, kind: "deadline", when: item.deadline, days: due, title, detail: "投递截止" });
    const next = daysUntil(item.next_event_at, now);
    if (next !== null && next >= 0 && next <= eventDays && !CLOSED.includes(item.stage)) rows.push({ id: item.id, kind: "event", when: item.next_event_at, days: next, title, detail: item.next_event });
  }
  return rows.sort((a, b) => a.when.localeCompare(b.when));
}

export function whenLabel(days: number): string {
  return days < 0 ? `已过 ${-days} 天` : days === 0 ? "今天" : days === 1 ? "明天" : `${days} 天后`;
}

export function sourceLabel(item: Pick<KitItem, "source" | "transform">): string {
  const { kind, ref } = item.source;
  const base = ({ profile: `资料 ${ref}`, file: "附件", user: "你在对话中提供", inferred: "Agent 起草", none: "—" } as Record<string, string>)[kind] ?? kind;
  return item.transform.startsWith("option:") ? `${base} → 选项转换` : base;
}

export function formatDate(value: DateValue | null | undefined): string {
  if (!value) return "";
  return [String(value.year).padStart(4, "0"), value.month ? String(value.month).padStart(2, "0") : "", value.day ? String(value.day).padStart(2, "0") : ""]
    .filter(Boolean).join("-");
}

/** Parse "2024", "2024-09" or "2024-09-01" keeping exactly the precision the user typed. */
export function parseDate(text: string): DateValue | null {
  const match = /^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$/.exec(text.trim());
  if (!match) return null;
  const [, year, month, day] = match;
  if (day) return { precision: "day", year: +year, month: +month, day: +day };
  if (month) return { precision: "month", year: +year, month: +month };
  return { precision: "year", year: +year };
}
