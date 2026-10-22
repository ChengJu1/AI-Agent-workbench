-- Application ledger: jobs the user tracks; the kit is copy-ready values the user fills in by hand.
CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    position TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT 'saved',
    deadline TEXT NOT NULL DEFAULT '',
    next_event_at TEXT NOT NULL DEFAULT '',
    next_event TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    applied_at TEXT NOT NULL DEFAULT '',
    kit TEXT NOT NULL DEFAULT '{}',
    jd TEXT NOT NULL DEFAULT '',
    tailoring TEXT NOT NULL DEFAULT '{}',
    interview_prep TEXT NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    actor TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_application_events ON application_events(application_id,id);
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    latest_version INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS profile_versions (
    profile_id TEXT NOT NULL REFERENCES profiles(id),
    version INTEGER NOT NULL,
    data TEXT NOT NULL,
    review_state TEXT NOT NULL DEFAULT 'reviewed' CHECK(review_state IN ('reviewed','draft')),
    source_file_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(profile_id,version)
);
