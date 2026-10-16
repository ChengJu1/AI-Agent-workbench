// 展示工时草稿和审批结果，已处理的操作保留状态但不再显示确认按钮。
import { actionStatusText } from "../lib/presentation";
import type { PendingAction } from "../types";

type Props = {
  actions: PendingAction[];
  disabled: boolean;
  decidingId: string;
  onDecision: (id: string, approved: boolean) => Promise<void>;
};

export function ApprovalList({ actions, disabled, decidingId, onDecision }: Props) {
  if (actions.length === 0) return null;
  return (
    <div className="approvalList">
      {actions.map((action) => (
        <section className="approvalCard" key={action.id}>
          <div className="approvalHeader">
            <div><strong>工时提交确认</strong><span>{actionStatusText(action.status)}</span></div>
            {action.params.draft && <b>{action.params.draft.total_hours} 小时</b>}
          </div>
          {action.params.draft && (
            <div className="timesheetRecords">
              {action.params.draft.records.map((record, index) => (
                <div className="timesheetRecord" key={`${record.date}-${record.task}-${index}`}>
                  <span>{record.date}</span><span>{record.task}</span>
                  <span>{record.hours} 小时</span><span>{record.note || "无备注"}</span>
                </div>
              ))}
            </div>
          )}
          {action.status === "pending" && (
            <div className="approvalButtons">
              <button className="cancelButton" type="button" disabled={disabled}
                onClick={() => void onDecision(action.id, false)}>取消</button>
              <button className="approveButton" type="button" disabled={disabled}
                onClick={() => void onDecision(action.id, true)}>
                {decidingId === action.id ? "处理中..." : "确认提交"}
              </button>
            </div>
          )}
          {action.result?.submission_id && (
            <p className="submissionId">提交编号：{action.result.submission_id}</p>
          )}
        </section>
      ))}
    </div>
  );
}
