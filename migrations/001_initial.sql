PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS hints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('romanian','exclude')),
    value TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 10,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(kind, value)
);

CREATE TABLE IF NOT EXISTS channel_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_key TEXT NOT NULL UNIQUE,
    label TEXT,
    rule TEXT NOT NULL CHECK(rule IN ('trusted','blocked')),
    weight REAL NOT NULL DEFAULT 25
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    youtube_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    channel_id TEXT,
    channel_name TEXT,
    duration INTEGER,
    view_count INTEGER,
    thumbnail_url TEXT,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    score REAL NOT NULL DEFAULT 0,
    score_details TEXT,
    discovered_at TEXT NOT NULL,
    downloaded_at TEXT,
    file_path TEXT,
    file_size INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id, channel_name);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    candidates_selected INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS discovery_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES discovery_runs(id) ON DELETE CASCADE,
    youtube_id TEXT NOT NULL,
    title TEXT NOT NULL,
    channel_name TEXT,
    query TEXT,
    source_type TEXT,
    source_rank INTEGER,
    final_score REAL NOT NULL DEFAULT 0,
    accepted INTEGER NOT NULL DEFAULT 0,
    reject_reason TEXT,
    score_details TEXT,
    UNIQUE(run_id, youtube_id)
);

CREATE TABLE IF NOT EXISTS download_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK(target_type IN ('local','device')),
    target_device_serial TEXT,
    target_path TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    phase TEXT NOT NULL DEFAULT 'queued',
    position INTEGER NOT NULL DEFAULT 0,
    progress REAL NOT NULL DEFAULT 0,
    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    speed REAL,
    eta INTEGER,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON download_jobs(status, position, id);

CREATE TABLE IF NOT EXISTS devices (
    serial TEXT PRIMARY KEY,
    manufacturer TEXT,
    model TEXT,
    state TEXT,
    last_seen_at TEXT NOT NULL,
    free_bytes INTEGER,
    total_bytes INTEGER
);

CREATE TABLE IF NOT EXISTS device_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    device_serial TEXT NOT NULL,
    remote_path TEXT NOT NULL,
    file_size INTEGER,
    transferred_at TEXT NOT NULL,
    verified_at TEXT,
    UNIQUE(video_id, device_serial)
);
