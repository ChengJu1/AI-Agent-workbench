import type { Capability } from "./api/platform";
// 定义前端使用的 Agent、聊天消息、工时记录和审批操作数据结构。
// 这些类型用于约束 App.tsx 和 api.ts 之间传递的数据。
export type AgentInfo = {
    platform_capabilities?: Capability[];
    id: string;
    name: string;
    description: string;
}

export type SkillDefinition = { name: string; description: string; content: string };
export type SkillReference = { id: string; name: string; version: number };
export type SkillBinding = Pick<SkillReference, "id" | "version">;
export type SkillInfo = SkillDefinition & SkillReference & { created_at: string; updated_at: string };

export type KnowledgeBaseInfo = {
    id: string;
    name: string;
    description: string;
    document_count: number;
    chunk_count: number;
    created_at: string;
}

export type KnowledgeDocumentInfo = {
    id: string;
    knowledge_base_id: string;
    filename: string;
    byte_size: number;
    version: number;
    chunk_count: number;
    status: "ready";
    indexing_version: string;
    chunking_strategy: "markdown_headings" | "characters";
    created_at: string;
    updated_at: string;
}

export type KnowledgeDocumentVersion = {
    document_id: string;
    version: number;
    knowledge_base_id: string;
    knowledge_base_name: string;
    filename: string;
    content: string;
    created_at: string;
}

export type KnowledgeChunk = {
    id: number;
    document_id: string;
    ordinal: number;
    content: string;
    section: string;
    start_offset: number;
    end_offset: number;
    start_line: number;
    end_line: number;
}

export type KnowledgeChunkPage = {
    items: KnowledgeChunk[];
    total: number;
    offset: number;
    limit: number;
}

export type KnowledgeSearchResult = {
    query: string;
    method: "keyword";
    matches: (KnowledgeChunk & { filename: string; document_version: number; source_chunk_ids: number[] })[];
    diagnostics: SearchDiagnostics;
}

export type SearchDiagnostics = {
    candidate_count: number;
    unique_count: number;
    merge_limit_skipped: number;
    elapsed_ms: number;
    deduplication_ms: number;
}

export type DocumentUploadResult = {
    document: KnowledgeDocumentInfo;
    created: boolean;
    unchanged: boolean;
}

export type McpConnection = {
    name: string;
    transport: "http" | "sse";
    url: string;
    headers?: Record<string, string>;
}

export type McpToolInfo = {
    name: string;
    description: string;
    input_schema: Record<string, unknown>;
}

export type CreateAgentInput = {
    platform_capabilities?: Capability[];
    name: string;
    description: string;
    system_prompt: string;
    tools: (McpConnection & { type: "mcp"; actions: string[] })[];
    knowledge_base_ids: string[];
    skill_ids: string[];
    skill_versions?: Record<string, number>;
}

export type ChatMessage = {
    tool_activity?: ToolActivityEvent[];
    usage?: RuntimeUsage;
    id?: string;
    /** platform: a notice the workbench sent the Agent (decided action results), never the user's words. */
    role: "user" | "assistant" | "platform";
    content: string;
    /** Images or scanned PDFs the user sent with this message. */
    attachments?: { id: string; filename: string }[];
    status?: "streaming" | "complete" | "failed" | "stopped";
    knowledge?: KnowledgeEvidence;
    skills?: SkillReference[];
    skill_mode?: "on_demand";
}

export type KnowledgeCitation = {
    citation_id: string;
    knowledge_base_id: string;
    knowledge_base_name: string;
    document_id: string;
    document_version: number;
    chunk_id: number | null;
    source_kind?: "knowledge" | "notes_mcp";
    filename: string;
    section: string;
    start_line: number;
    end_line: number;
    content: string;
    start_offset?: number | null;
    end_offset?: number | null;
}

export type KnowledgeEvidence = {
    status: "matched" | "no_match" | "not_searched" | "failed";
    citations: KnowledgeCitation[];
    queries: string[];
    failed_searches: number;
    channels?: ("knowledge" | "notes_mcp")[];
    notes_calls?: number;
}

export type ConversationInfo = {
    /** From the retired Claude SDK runtime: readable, not continued. */
    archived?: boolean;
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
        url?: string;
        title?: string;
        filename?: string;
        file_id?: string;
        session_id?: string;
        snapshot_id?: string;
        expected_version?: number;
        operations?: {kind: string; label: string; value?: string; filename?: string; file_version?: number; destination?: string}[];
        connection_destinations?: string[];
        provider?: string;
        network_notice?: string;
        expires_at?: number;
        draft?: {
            records: TimesheetRecord[];
            total_hours: number;
        };
    };
    status: "pending" | "executing" | "approved" | "cancelled" | "failed";
    result: {
        error?: string;
        message?: string;
        status?: string;
        submission_id?: string;
        total_hours?: number;
    } | null;
    message?: string;
    /** Set by the decision endpoint: the Agent can resume now with this turn's results. */
    continuation_available?: boolean;
    created_at: string;
    updated_at: string;
}

export type ToolActivityEvent =
    | { type: "tool_started"; tool_name: string; call_id: string }
    | { type: "tool_finished"; tool_name: string; call_id: string; success: boolean };

export type RuntimeUsage = {
    runtime: "claude_sdk" | "deep_agents";  // Archived replies may carry claude_sdk.
    input_tokens: number | null;
    output_tokens: number | null;
    cache_read_input_tokens: number | null;
    cache_creation_input_tokens: number | null;
    model_calls: number | null;
    tool_calls: number;
    first_token_ms: number | null;
    duration_ms: number;
    status: "complete" | "failed";
    context_estimate: Record<string, unknown>;
    context_management?: Record<string, unknown>;
};

export type StreamEvent =
    | { type: "tool_started"; tool_name: string; call_id: string }
    | { type: "tool_finished"; tool_name: string; call_id: string; success: boolean }
    | { type: "usage"; usage: RuntimeUsage }
    | { type: "delta"; content: string }
    | { type: "approval_required"; action: PendingAction }
    | { type: "knowledge"; evidence: KnowledgeEvidence }
    | { type: "skills"; skills: SkillReference[]; mode?: "on_demand" }
    | { type: "platform_notice"; content: string }
    | { type: "error"; content: string }
    | { type: "done" };

export type RetrievalCase = {
    id: string;
    query: string;
    category: "keyword" | "question" | "paraphrase" | "negative";
    expected_filename: string | null;
    expected_texts: string[];
    expect_no_match: boolean;
}

export type RetrievalSuite = {
    name: string;
    description: string;
    limit: number;
    cases: RetrievalCase[];
}

export type RetrievalReport = {
    schema_version: 2;
    created_at: string;
    knowledge_base_id: string;
    knowledge_base_name: string;
    suite: RetrievalSuite;
    method: "keyword_bm25";
    chunk_size: number | null;
    chunk_overlap: number | null;
    chunk_unit: "heading_blocks" | "characters" | "mixed" | "none";
    corpus_fingerprint: string;
    index_chunk_count: number;
    elapsed_ms: number;
    average_retrieval_ms: number;
    retrieval_policy: string;
    candidate_multiplier: number;
    max_merged_characters: number;
    documents: { id: string; filename: string; version: number; content_hash: string;
        indexing_version: string; chunking_strategy: "markdown_headings" | "characters" }[];
    summary: {
        total: number; evaluated: number; passed: number; failed: number; not_applicable: number;
        positive_evaluated: number; top1_hits: number; top_k_hits: number;
        negative_evaluated: number; negative_correct: number;
        pass_rate: number | null; top1_hit_rate: number | null;
        top_k_hit_rate: number | null; negative_accuracy: number | null;
    };
    results: {
        case: RetrievalCase;
        status: "passed" | "failed" | "not_applicable";
        reason: string;
        rank: number | null;
        source_positions_valid: boolean;
        matches: KnowledgeSearchResult["matches"];
        diagnostics: SearchDiagnostics;
    }[];
}
