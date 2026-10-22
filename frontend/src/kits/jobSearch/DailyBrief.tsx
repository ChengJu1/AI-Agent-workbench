// Today's to-do list from the ledger, approvals and tracking; shown above the welcome prompts when anything needs attention.
import { useEffect, useState } from "react";
import { fetchBrief, type Brief } from "./api";

export function DailyBrief({ onOpenApplication, onOpenTracking }: { onOpenApplication: (id: string) => void; onOpenTracking: () => void }) {
  const [brief, setBrief] = useState<Brief | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchBrief(controller.signal).then(setBrief).catch(() => { /* The brief is optional; the ledger shows real errors. */ });
    return () => controller.abort();
  }, []);
  if (!brief?.total) return null;
  const [, month, day] = brief.date.split("-");
  const open = (ref: string) => ref === "tracking" ? onOpenTracking() : ref !== "approvals" ? onOpenApplication(ref) : undefined;
  return <section className="dailyBrief" aria-label="今日简报">
    <header><strong>今日简报</strong><span>{+month} 月 {+day} 日 · {brief.total} 项</span></header>
    {brief.sections.map(section => <div key={section.id} className={`briefSection brief-${section.id}`}>
      <h3>{section.title}</h3>
      <ul>{section.items.map(item => <li key={section.id + item.ref}>
        {item.ref === "approvals" ? <span className="briefItem"><b>{item.text}</b><small>{item.detail}</small></span>
          : <button type="button" className="briefItem" onClick={() => open(item.ref)}><b>{item.text}</b><small>{item.detail}</small></button>}
      </li>)}</ul>
    </div>)}
  </section>;
}
