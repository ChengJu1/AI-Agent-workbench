// 负责人本轮的委派：成员、任务摘要、状态和用量，可以打开成员的子会话查看过程。
import { delegationStatusLabel } from "../lib/team";
import { tokenLabel } from "../lib/runtime";
import type { Delegation } from "../types";

export function DelegationCards({ delegations, onOpen }: { delegations: Delegation[]; onOpen?: (conversationId: string) => void }) {
  return <ul className="delegationCards" aria-label="委派给团队成员">
    {delegations.map((item, index) => <li key={`${item.child_conversation_id}-${index}`} className={`delegationCard is-${item.status}`}>
      <div className="delegationHead"><strong>委派给 {item.member_name || "成员"}</strong>
        <span className="delegationStatus" role={item.status === "running" ? "status" : undefined}>{delegationStatusLabel[item.status]}</span></div>
      {item.task && <p className="delegationTask" title={item.task}>{item.task}</p>}
      <div className="delegationFoot">
        {item.usage && <small>输入 {tokenLabel(item.usage.input_tokens)} · 输出 {tokenLabel(item.usage.output_tokens)} token · 工具 {tokenLabel(item.usage.tool_calls)} 次</small>}
        {item.status === "needs_approval" && <small>有操作等待你在子会话里确认</small>}
        {onOpen && <button type="button" onClick={() => onOpen(item.child_conversation_id)}>查看子会话</button>}
      </div>
    </li>)}
  </ul>;
}
