// Header button and browser reminders for the ledger; kept apart so the ledger dialog itself loads on demand.
import { useEffect, useState } from "react";
import { fetchApplications, type Application } from "../api/applications";
import { agenda, dueAlerts } from "../lib/applications";

const NOTIFY_KEY = "ledgerNotify", SENT_KEY = "ledgerNotified";
const storage = {
  get: (key: string) => { try { return localStorage.getItem(key); } catch { return null; } },
  set: (key: string, value: string) => { try { localStorage.setItem(key, value); } catch { /* Private mode: reminders just repeat. */ } },
};
const notificationsOn = () => typeof Notification !== "undefined" && Notification.permission === "granted" && storage.get(NOTIFY_KEY) === "on";

export function NotifyToggle() {
  const [on, setOn] = useState(notificationsOn());
  if (typeof Notification === "undefined") return null;
  const toggle = async () => {
    if (on) { storage.set(NOTIFY_KEY, "off"); setOn(false); return; }
    const permission = Notification.permission === "default" ? await Notification.requestPermission() : Notification.permission;
    if (permission === "granted") { storage.set(NOTIFY_KEY, "on"); setOn(true); }
    else window.alert("浏览器拒绝了通知权限，可在浏览器的网站设置里重新允许。");
  };
  return <button aria-pressed={on} onClick={() => void toggle()} title="页面开着时，截止当天和日程前两小时弹出通知">浏览器提醒{on ? "：开" : ""}</button>;
}

/** Shows each reminder once; keys of the last 30 days are kept. */
function notify(rows: Application[]) {
  if (!notificationsOn()) return;
  let sent: Record<string, number> = {};
  try { sent = JSON.parse(storage.get(SENT_KEY) || "{}"); } catch { sent = {}; }
  const now = Date.now();
  for (const alert of dueAlerts(rows)) {
    if (sent[alert.key]) continue;
    new Notification(alert.title, { body: alert.body, tag: alert.key });
    sent[alert.key] = now;
  }
  storage.set(SENT_KEY, JSON.stringify(Object.fromEntries(Object.entries(sent).filter(([, t]) => now - t < 30 * 86400000))));
}

/** Header button with a count of deadlines and events coming up, refreshed every minute. */
export function LedgerButton({ disabled, onClick }: { disabled: boolean; onClick: () => void }) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const rows = await fetchApplications(controller.signal); if (!controller.signal.aborted) { setCount(agenda(rows).length); notify(rows); } }
      catch { /* The badge is a hint; the ledger itself shows errors. */ }
      finally { if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 60000); }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);
  return <button disabled={disabled} onClick={onClick}>投递台账{count ? ` · ${count} 项临近` : ""}</button>;
}
