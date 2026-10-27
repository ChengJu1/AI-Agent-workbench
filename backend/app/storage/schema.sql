-- 保留已有表和字段；升级时只增加缺失的表、字段和索引。
CREATE TABLE IF NOT EXISTS custom_agents (
    id TEXT PRIMARY KEY,
    definition TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_knowledge_bases (
    agent_id TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL,
    PRIMARY KEY (agent_id, knowledge_base_id),
    FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id TEXT PRIMARY KEY,
    knowledge_base_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    indexing_version TEXT NOT NULL DEFAULT '',
    chunking_strategy TEXT NOT NULL DEFAULT 'characters',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (knowledge_base_id, filename),
    FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    content TEXT NOT NULL,
    section TEXT NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    UNIQUE (document_id, ordinal),
    FOREIGN KEY (document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
);

-- 独立保留文档版本，供历史引用预览；文档更新或删除不改变已引用的原文。
CREATE TABLE IF NOT EXISTS knowledge_document_versions (
    document_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    knowledge_base_id TEXT NOT NULL,
    knowledge_base_name TEXT NOT NULL,
    filename TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (document_id, version)
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunk_search USING fts5(tokens);

CREATE TRIGGER IF NOT EXISTS knowledge_chunks_remove_search
AFTER DELETE ON knowledge_chunks BEGIN
    DELETE FROM knowledge_chunk_search WHERE rowid = OLD.id;
END;

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document
    ON knowledge_chunks(document_id, ordinal);

-- 片段向量（归一化 float32）。换嵌入模型时按 model 整体重建；片段删除或重新切分时一并删除。
CREATE TABLE IF NOT EXISTS knowledge_chunk_vectors (
    chunk_id INTEGER PRIMARY KEY,
    model TEXT NOT NULL,
    vector BLOB NOT NULL
);

CREATE TRIGGER IF NOT EXISTS knowledge_chunks_remove_vector
AFTER DELETE ON knowledge_chunks BEGIN
    DELETE FROM knowledge_chunk_vectors WHERE chunk_id = OLD.id;
END;

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    -- claude_sdk rows are archived conversations from the retired runtime: readable, not continued.
    runtime TEXT NOT NULL DEFAULT 'deep_agents' CHECK(runtime IN ('claude_sdk','deep_agents')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pending_actions (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    action TEXT NOT NULL,
    params TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tool_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    tool_type TEXT NOT NULL DEFAULT 'cli',
    tool_name TEXT NOT NULL,
    action TEXT NOT NULL,
    params TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversations_agent
    ON conversations(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_pending_actions_conversation
    ON pending_actions(conversation_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_audit_conversation
    ON tool_audit_logs(conversation_id, id);

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skill_versions (
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS agent_skills (
    agent_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    skill_version INTEGER NOT NULL,
    PRIMARY KEY (agent_id, skill_id),
    FOREIGN KEY (skill_id) REFERENCES skills(id),
    FOREIGN KEY (skill_id, skill_version) REFERENCES skill_versions(id, version)
);

CREATE TABLE IF NOT EXISTS agent_builds (
    id TEXT PRIMARY KEY,
    definition TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS capability_packages (
    id TEXT NOT NULL,
    version INTEGER NOT NULL,
    definition TEXT NOT NULL,
    PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS conversation_files (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    content TEXT NOT NULL,
    data BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_conversation_files ON conversation_files(conversation_id);
CREATE TABLE IF NOT EXISTS agent_platform_capabilities (
    agent_id TEXT PRIMARY KEY,
    capabilities TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_code_projects (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    name TEXT NOT NULL,
    root TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(agent_id, root)
);

CREATE TABLE IF NOT EXISTS execution_records (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE REFERENCES pending_actions(id),
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    title TEXT NOT NULL,
    target_url TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tracking_tasks (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    record_id TEXT REFERENCES execution_records(id),
    definition TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'paused',
    business_status TEXT NOT NULL DEFAULT '',
    next_check_at REAL,
    lease_token TEXT,
    lease_until REAL,
    last_checked_at REAL,
    last_error TEXT,
    unread INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tracking_due ON tracking_tasks(state,next_check_at,lease_until);
CREATE TABLE IF NOT EXISTS tracking_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tracking_tasks(id),
    previous_status TEXT NOT NULL,
    status TEXT NOT NULL,
    outcome TEXT NOT NULL,
    evidence TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS work_items (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    agent_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    title TEXT NOT NULL,
    target_url TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'planned' CHECK(state IN ('planned','blocked','cancelled')),
    note TEXT NOT NULL DEFAULT '',
    next_step TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(conversation_id,item_key)
);
CREATE TABLE IF NOT EXISTS work_item_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES work_items(id),
    revision INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS work_item_actions (
    action_id TEXT PRIMARY KEY REFERENCES pending_actions(id),
    item_id TEXT NOT NULL REFERENCES work_items(id)
);
CREATE TABLE IF NOT EXISTS work_item_attempts (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES work_items(id),
    target_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    http_status INTEGER,
    error TEXT NOT NULL DEFAULT '',
    notice TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_work_item_attempts ON work_item_attempts(item_id,created_at);
CREATE TABLE IF NOT EXISTS conversation_file_versions (
    id TEXT NOT NULL,
    version INTEGER NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    content TEXT NOT NULL,
    data BLOB NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(id,version)
);

CREATE TABLE IF NOT EXISTS runtime_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    usage TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS runtime_usage_conversation ON runtime_usage(conversation_id);
CREATE INDEX IF NOT EXISTS runtime_usage_agent ON runtime_usage(agent_id);

CREATE TABLE IF NOT EXISTS agent_runtime_preferences (
    agent_id TEXT PRIMARY KEY,
    runtime TEXT NOT NULL CHECK(runtime IN ('claude_sdk','deep_agents'))
);
