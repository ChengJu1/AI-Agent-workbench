// 定义前端使用的 Agent、聊天消息、工时记录和审批操作数据结构。
// 这些类型用于约束 App.tsx 和 api.ts 之间传递的数据。
export type AgentInfo = {
    id: string;
    name: string;
    description: string;
}

export type ChatMessage = {
    id?: string;
    role: "user" | "assistant";
    content: string;
    status?: "streaming" | "complete" | "failed";
}

export type ConversationInfo = {
    id: string;
    agent_id: string;
    created_at: string;
    title: string | null;
}

export type TimesheetRecord = {
    date: string;
    task: string;
    hours: number;
    note: string;
}

export type PendingAction = {
    id: string;
    conversation_id: string;
    agent_id: string;
    tool_name: string;
    action: string;
    params: {
        draft?: {
            records: TimesheetRecord[];
            total_hours: number;
        };
    };
    status: "pending" | "executing" | "approved" | "cancelled" | "failed";
    result: {
        status?: string;
        submission_id?: string;
        total_hours?: number;
    } | null;
    message?: string;
    created_at: string;
    updated_at: string;
}

export type StreamEvent =
    | { type: "delta"; content: string }
    | { type: "approval_required"; action: PendingAction }
    | { type: "error"; content: string }
    | { type: "done" };
