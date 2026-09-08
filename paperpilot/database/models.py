SCHEMA_SCRIPT = """
-- Papers table
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT, 
    abstract TEXT,
    published_date TEXT, -- Maps to arxiv_published_date
    url TEXT, -- Maps to arxiv_url
    arxiv_id TEXT,
    category TEXT, -- Maps to subject
    download_date TEXT, -- Maps to upload_date
    file_path TEXT,
    thumbnail_path TEXT,
    starred INTEGER DEFAULT 0,
    read_time INTEGER DEFAULT 0,
    translation_status TEXT,
    analysis_status TEXT,
    is_daily INTEGER DEFAULT 0,
    daily_date TEXT,
    metadata TEXT -- Stores other fields from Paper dataclass
);

-- Categories table
CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id TEXT,
    display_name TEXT,
    FOREIGN KEY(parent_id) REFERENCES categories(id)
);

-- User Settings table (Key-Value store)
CREATE TABLE IF NOT EXISTS user_settings (
    key TEXT PRIMARY KEY,
    value TEXT -- JSON string
);

-- Reading History
CREATE TABLE IF NOT EXISTS reading_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT, -- YYYY-MM-DD
    paper_id TEXT,
    duration INTEGER,
    timestamp INTEGER, -- Unix timestamp
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

-- Chat History
CREATE TABLE IF NOT EXISTS chats (
    session_id TEXT PRIMARY KEY,
    paper_id TEXT,
    history TEXT, -- JSON array of messages
    created_at TEXT,
    updated_at TEXT,
    title TEXT,
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

-- Reading List
CREATE TABLE IF NOT EXISTS reading_list (
    paper_id TEXT PRIMARY KEY,
    added_at TEXT,
    status TEXT, -- 'unread', 'reading', 'read'
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

-- Daily Arxiv Task Status
CREATE TABLE IF NOT EXISTS daily_arxiv_tasks (
    date TEXT,
    category TEXT,
    status TEXT,
    metadata TEXT, -- JSON
    PRIMARY KEY (date, category)
);

-- Institution Mapping
CREATE TABLE IF NOT EXISTS institution_map (
    original_name TEXT PRIMARY KEY,
    normalized_name TEXT
);

-- Daily arXiv Read Status
CREATE TABLE IF NOT EXISTS daily_arxiv_reads (
    arxiv_id TEXT PRIMARY KEY,
    read_at INTEGER
);

-- Isolated translation worker jobs. Credentials are deliberately never stored.
CREATE TABLE IF NOT EXISTS translation_jobs (
    job_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    error TEXT,
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_translation_jobs_paper_status
    ON translation_jobs(paper_id, status);

-- Isolated document validation/import jobs. No file paths or secrets are stored.
CREATE TABLE IF NOT EXISTS document_jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    paper_id TEXT,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    error TEXT,
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_document_jobs_status
    ON document_jobs(status, created_at);

-- API credentials encrypted with the deployment-only settings key.
CREATE TABLE IF NOT EXISTS agentic_secrets (
    name TEXT PRIMARY KEY,
    ciphertext TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (name IN ('translate', 'interpret', 'dailyArxiv', 'mineru'))
);
"""
