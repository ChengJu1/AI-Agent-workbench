import type { Application, DateValue, KitItem, Stage } from "./api";

export const STAGES: { id: Stage; label: string }[] = [
  { id: "saved", label: "待投递" }, { id: "preparing", label: "准备中" }, { id: "applied", label: "已投递" }, { id: "test", label: "笔试/测评" },
  { id: "interview", label: "面试" }, { id: "offer", label: "offer" }, { id: "rejected", label: "未通过" }, { id: "withdrawn", label: "放弃" },
];
const OPEN: Stage[] = ["saved", "preparing"];
const CLOSED: Stage[] = ["offer", "rejected", "withdrawn"];

export const FLAG_LABELS: Record<string, string> = {
  draft: "Agent 起草", chat: "对话中提供", converted: "选项转换", file: "需上传", missing: "请自行填写",
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

/** The main pipeline in order; rejected and withdrawn sit outside it. */
export const PIPELINE: Stage[] = ["saved", "preparing", "applied", "test", "interview", "offer"];

export const GROUPS: { id: string; label: string; stages: Stage[] }[] = [
  { id: "todo", label: "待投递", stages: ["saved", "preparing"] },
  { id: "applied", label: "已投递", stages: ["applied"] },
  { id: "process", label: "笔试面试", stages: ["test", "interview"] },
  { id: "offer", label: "offer", stages: ["offer"] },
  { id: "closed", label: "已结束", stages: ["rejected", "withdrawn"] },
];

export type Tone = "urgent" | "soon" | "calm" | "muted";

/** Countdown for jobs still to apply to; once applied the deadline no longer matters. */
export function deadlineBadge(item: Pick<Application, "deadline" | "stage">, now = new Date()): { text: string; tone: Tone } | null {
  const days = daysUntil(item.deadline, now);
  if (days === null || !OPEN.includes(item.stage)) return null;
  if (days < 0) return { text: "已截止", tone: "muted" };
  if (days === 0) return { text: "今天截止", tone: "urgent" };
  return { text: `还剩 ${days} 天`, tone: days <= 3 ? "urgent" : days <= 7 ? "soon" : "calm" };
}

/** "10-23 19:00" for this year, the full date otherwise. */
export function shortWhen(value: string, now = new Date()): string {
  const match = /^(\d{4})-(\d{2}-\d{2})(?: (\d{2}:\d{2}))?$/.exec(value);
  if (!match) return value;
  const day = +match[1] === now.getFullYear() ? match[2] : `${match[1]}-${match[2]}`;
  return match[3] ? `${day} ${match[3]}` : day;
}

export type Alert = { key: string; title: string; body: string };

/** Browser reminders: deadlines due today for jobs not yet applied to, and events starting within two hours. */
export function dueAlerts(items: Application[], now = new Date()): Alert[] {
  const alerts: Alert[] = [];
  for (const item of items) {
    const title = [item.company, item.position].filter(Boolean).join(" · ");
    if (OPEN.includes(item.stage) && daysUntil(item.deadline, now) === 0)
      alerts.push({ key: `${item.id}:deadline:${item.deadline}`, title: "今天投递截止", body: title });
    const match = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/.exec(item.next_event_at);
    if (match && !CLOSED.includes(item.stage)) {
      const start = new Date(+match[1], +match[2] - 1, +match[3], +match[4], +match[5]);
      const minutes = (start.getTime() - now.getTime()) / 60000;
      if (minutes >= 0 && minutes <= 120)
        alerts.push({ key: `${item.id}:event:${item.next_event_at}`, title: `${Math.max(1, Math.round(minutes))} 分钟后：${item.next_event}`, body: title });
    }
  }
  return alerts;
}
