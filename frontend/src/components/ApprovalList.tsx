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
            <div><strong>{action.tool_name === "workbench_platform" ? "浏览器操作确认" : "工时提交确认"}</strong><span>{actionStatusText(action.status)}</span></div>
            {action.params.draft && <b>{action.params.draft.total_hours} 小时</b>}
          </div>
          {action.params.operations && <div className="browserApproval"><p>接收页面：{action.params.title}<br />{action.params.url}</p><ol>
            {action.params.operations.map((operation, index) => <li key={index}><strong>{({fill:"填写",select:"选择",check:"勾选",upload:"上传附件",click:"点击"} as Record<string,string>)[operation.kind] || operation.kind}：{operation.label || "页面控件"}</strong>
              {operation.value && <span className="actionValue">{operation.value}</span>}{operation.filename && <span className="actionValue">{operation.filename}</span>}
              <small>接收网站：{operation.destination}</small></li>)}</ol><p>确认后会向该网站发送以上内容。页面变化或超时会停止；操作完成仍需核对回执。</p></div>}
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
                {decidingId === action.id ? "处理中..." : action.tool_name === "workbench_platform" ? "确认执行以上操作" : "确认提交"}
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
