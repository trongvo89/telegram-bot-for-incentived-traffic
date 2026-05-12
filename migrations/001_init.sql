CREATE TABLE IF NOT EXISTS users_campaign (
    user_id     INTEGER PRIMARY KEY,
    campaign    TEXT NOT NULL,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS uploads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    username        TEXT,
    campaign        TEXT NOT NULL,
    file_unique_id  TEXT NOT NULL,
    storage_msg_id  INTEGER,
    storage_chat_id INTEGER,
    status          TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_unique_id, campaign)
);

CREATE INDEX IF NOT EXISTS idx_uploads_user_date ON uploads(user_id, created_at);

CREATE TABLE IF NOT EXISTS dead_letter (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    payload     TEXT NOT NULL,
    reason      TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved    INTEGER DEFAULT 0
);
