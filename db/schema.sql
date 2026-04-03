-- Life Optimizer Schema

-- User profile and preferences (per-user)
CREATE TABLE IF NOT EXISTS profile (
    user_id INTEGER NOT NULL DEFAULT 1,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

-- Task buckets
CREATE TABLE IF NOT EXISTS buckets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    description TEXT
);

-- Tasks
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL DEFAULT 1,
    bucket_id    INTEGER NOT NULL REFERENCES buckets(id),
    title        TEXT NOT NULL,
    description  TEXT,
    priority     INTEGER NOT NULL DEFAULT 3,
    status       TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','in_progress','done','deferred')),
    due_date     TEXT,
    est_minutes  INTEGER,
    energy_level TEXT CHECK(energy_level IN ('high','medium','low')),
    recurring    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    tags         TEXT
);

-- Daily schedules
CREATE TABLE IF NOT EXISTS schedules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL DEFAULT 1,
    date          TEXT NOT NULL,
    generated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    schedule_json TEXT NOT NULL,
    model_used    TEXT NOT NULL,
    accepted      INTEGER DEFAULT 0
);

-- Schedule blocks
CREATE TABLE IF NOT EXISTS schedule_blocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id INTEGER NOT NULL REFERENCES schedules(id),
    start_time  TEXT NOT NULL,
    end_time    TEXT NOT NULL,
    task_id     INTEGER REFERENCES tasks(id),
    activity    TEXT NOT NULL,
    block_type  TEXT NOT NULL CHECK(block_type IN (
        'deep_work','shallow_work','exercise','meal','faith','rest','personal','admin'
    )),
    completed   INTEGER DEFAULT 0,
    skipped     INTEGER DEFAULT 0,
    notes       TEXT
);

-- Agent conversation log
CREATE TABLE IF NOT EXISTS conversations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    role      TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content   TEXT NOT NULL,
    model_used TEXT,
    tokens_in  INTEGER,
    tokens_out INTEGER
);

-- Feedback / adaptation data
CREATE TABLE IF NOT EXISTS feedback (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,
    block_id      INTEGER REFERENCES schedule_blocks(id),
    actual_start  TEXT,
    actual_end    TEXT,
    energy_rating INTEGER CHECK(energy_rating BETWEEN 1 AND 5),
    focus_rating  INTEGER CHECK(focus_rating BETWEEN 1 AND 5),
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- API usage tracking
CREATE TABLE IF NOT EXISTS api_usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT NOT NULL DEFAULT (datetime('now')),
    model      TEXT NOT NULL,
    tokens_in  INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    cost_usd   REAL NOT NULL,
    trigger    TEXT NOT NULL
);

-- Users (id=1 primary, id=2 member)
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT 'member',  -- 'primary', 'member'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Notification preferences (per user, per type)
CREATE TABLE IF NOT EXISTS notification_prefs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL DEFAULT 1,
    notification_type TEXT NOT NULL,
    enabled           INTEGER NOT NULL DEFAULT 1,
    disabled_reason   TEXT,
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, notification_type)
);

-- Bible reading log
CREATE TABLE IF NOT EXISTS bible_reading (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL DEFAULT 1,
    date          TEXT NOT NULL,
    book          TEXT NOT NULL,
    chapter_start INTEGER NOT NULL,
    chapter_end   INTEGER,
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Fitness & meal log
CREATE TABLE IF NOT EXISTS fitness_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL DEFAULT 1,
    date             TEXT NOT NULL,
    log_type         TEXT NOT NULL CHECK(log_type IN ('workout','meal','weight','steps','water')),
    activity         TEXT,
    duration_minutes INTEGER,
    distance_km      REAL,
    calories         INTEGER,
    details          TEXT,
    photo_path       TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-user feature flags (enable/disable UI sections)
CREATE TABLE IF NOT EXISTS user_features (
    user_id INTEGER NOT NULL,
    feature  TEXT    NOT NULL,
    enabled  INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, feature)
);

-- Insight dismissals (adaptive feedback learning)
CREATE TABLE IF NOT EXISTS insight_dismissals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    insight_type TEXT    NOT NULL,
    dismissed_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Mood & emotion log
CREATE TABLE IF NOT EXISTS mood_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL DEFAULT 1,
    logged_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    mood_score INTEGER CHECK(mood_score BETWEEN 1 AND 10),
    energy     TEXT    CHECK(energy IN ('high', 'medium', 'low')),
    emotions   TEXT,   -- JSON array string
    context    TEXT,   -- 'morning','midday','evening','post_workout','post_meal','general'
    notes      TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tasks_bucket ON tasks(bucket_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_schedules_date ON schedules(date);
CREATE INDEX IF NOT EXISTS idx_schedules_user ON schedules(user_id);
CREATE INDEX IF NOT EXISTS idx_profile_user ON profile(user_id);
CREATE INDEX IF NOT EXISTS idx_blocks_schedule ON schedule_blocks(schedule_id);
CREATE INDEX IF NOT EXISTS idx_api_usage_date ON api_usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_conversations_date ON conversations(timestamp);
CREATE INDEX IF NOT EXISTS idx_bible_user_date ON bible_reading(user_id, date);
CREATE INDEX IF NOT EXISTS idx_fitness_user_date ON fitness_log(user_id, date);
CREATE INDEX IF NOT EXISTS idx_mood_user_date ON mood_log(user_id, logged_at);

-- Privacy: what data each user shares with other household members
CREATE TABLE IF NOT EXISTS sharing_permissions (
    owner_user_id  INTEGER NOT NULL REFERENCES users(id),
    target_user_id INTEGER NOT NULL REFERENCES users(id),
    data_category  TEXT    NOT NULL,
    shared         INTEGER NOT NULL DEFAULT 0 CHECK(shared IN (0,1)),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(owner_user_id, target_user_id, data_category)
);
CREATE INDEX IF NOT EXISTS idx_sharing_owner ON sharing_permissions(owner_user_id);

-- Server-side auth sessions
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
