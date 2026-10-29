// 团队计划确认：每个参与者可以换成自己的 Agent、修改临时 Agent 的说明和能力（只能减少）、或删除。
import { isTemporary, removeParticipant, replaceParticipant, replacementOptions, updateParticipant, type TeamPlan } from "../lib/teamPlan";
import type { AgentInfo } from "../types";

export function TeamPlanEditor({ original, plan, agents, leadId, editable, onChange }: {
  original: TeamPlan; plan: TeamPlan; agents: AgentInfo[]; leadId: string; editable: boolean; onChange: (plan: TeamPlan) => void;
}) {
  const lead = agents.find(agent => agent.id === leadId);
  return <div className="teamPlan">
    <p className="teamPlanSummary">{plan.summary}</p>
    <p className="agentEditorHint">{lead?.name ?? "负责人"}想请下面这些 Agent 协助。临时 Agent 是它按需创建的，只在这段对话里使用，能力不会超过{lead?.name ?? "负责人"}。
      你可以换成自己的 Agent、修改临时 Agent 的说明或去掉能力，也可以删掉某位参与者。</p>
    <ol className="teamPlanList">{plan.participants.map((item, index) => {
      const proposed = original.participants[item.origin ?? index];
      const proposedTemporary = proposed && isTemporary(proposed) ? proposed : undefined;
      const options = replacementOptions(plan, index, agents, leadId);
      return <li key={index}>
        <div className="teamPlanHead"><strong>{item.name}</strong><span className="teamPlanKind">{isTemporary(item) ? "临时" : "已有 Agent"}</span>
          {editable && plan.participants.length > 1 && <button type="button" onClick={() => onChange(removeParticipant(plan, index))}>删除</button>}</div>
        {item.role && <p className="teamPlanRole">分工：{item.role}</p>}
        {editable && <label className="teamPlanField"><span>由谁来做</span>
          <select value={item.agent_id ?? "temporary"} onChange={(event) => {
            const value = event.target.value;
            const choice = value === "temporary" ? proposedTemporary : options.find(agent => agent.id === value);
            if (choice) onChange(replaceParticipant(plan, index, choice));
          }}>
            {proposedTemporary && <option value="temporary">临时 Agent：{proposedTemporary.name}</option>}
            {!isTemporary(item) && !options.some(agent => agent.id === item.agent_id) && <option value={item.agent_id}>{item.name}</option>}
            {options.map(agent => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
          </select></label>}
        {isTemporary(item) && <>
          <label className="teamPlanField"><span>职责说明</span>
            <textarea rows={3} value={item.instructions ?? ""} readOnly={!editable} maxLength={2000}
              onChange={(event) => onChange(updateParticipant(plan, index, { instructions: event.target.value }))} /></label>
          <fieldset className="teamPlanCapabilities" disabled={!editable}><legend>能力</legend>
            {(proposedTemporary?.capabilities ?? item.capabilities ?? []).length === 0 && <small>不使用平台能力</small>}
            {(proposedTemporary?.capabilities ?? item.capabilities ?? []).map(capability => <label key={capability}>
              <input type="checkbox" checked={item.capabilities?.includes(capability) ?? false}
                onChange={(event) => onChange(updateParticipant(plan, index, { capabilities: event.target.checked
                  ? [...(item.capabilities ?? []), capability] : (item.capabilities ?? []).filter(value => value !== capability) }))} />
              {capability}</label>)}
          </fieldset>
        </>}
      </li>;
    })}</ol>
  </div>;
}
