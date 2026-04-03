import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "nertia.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

SEED_BUCKETS = [
    (1, "Now", 0, "Urgent + Important"),
    (2, "Career", 1, "Job apps, LinkedIn, resume, GitHub portfolio"),
    (3, "Marriage & Faith", 2, "Gottman study, couples activities, theological discussions"),
    (4, "Personal Growth", 3, "Books, Duolingo, skills"),
    (5, "Health", 4, "Exercise, nutrition, caffeine reduction"),
    (6, "Projects", 5, "Dev projects - revenue + portfolio ranked"),
    (7, "Theology & Philosophy", 6, "Research queue"),
    (8, "Admin", 7, "One-off errands and tasks"),
]

SEED_USERS = [
    (1, "User 1", "primary"),
    (2, "User 2", "member"),
]

SEED_NOTIFICATION_PREFS = [
    # (user_id, type, enabled)
    (1, "morning_briefing", 1),
    (1, "transition", 1),
    (1, "exercise", 1),
    (1, "meal", 1),
    (1, "weekly_review", 1),
]

SEED_FEATURES = [
    # Primary user
    (1, "workout_logging", 1),
    (1, "meal_logging", 1),
    (1, "bible_reading", 1),
    (1, "schedule", 1),
    (1, "tasks", 1),
    (1, "nutrition_insights", 1),
    (1, "cycle_tracking", 0),   # off by default; enable per user in Settings → Features
    (1, "partner_health_awareness", 0),
    (1, "recipe_planning", 0),
    # Member user
    (2, "workout_logging", 1),
    (2, "meal_logging", 1),
    (2, "bible_reading", 1),
    (2, "schedule", 1),
    (2, "tasks", 1),
    (2, "nutrition_insights", 1),
    (2, "cycle_tracking", 0),   # off by default; enable per user in Settings → Features
    (2, "partner_health_awareness", 0),
    (2, "recipe_planning", 0),
]

SEED_SHARING = [
    # All categories default to private (0) — rows created on first GET /sharing
]

SEED_PROFILE = {
    "wake_time": "06:15",
    "sleep_time": "22:00",
    "focus_peak_am_start": "09:00",
    "focus_peak_am_end": "11:30",
    "energy_dip_start": "13:00",
    "energy_dip_end": "14:30",
    "focus_peak_pm_start": "15:00",
    "focus_peak_pm_end": "17:00",
    "wind_down_start": "20:30",
    "exercise_preference": "morning or transition periods",
    "morning_routine": "prayer + Bible study (30 min, first thing)",
    "evening_routine": "Bible study with partner after dinner (~19:00)",
    "weekly_activity": "piano practice",
    "coffee_max": "2",
    "coffee_cutoff": "13:00",
}


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    try:
        schema = SCHEMA_PATH.read_text()
        await db.executescript(schema)

        # Seed buckets if empty
        cursor = await db.execute("SELECT COUNT(*) FROM buckets")
        count = (await cursor.fetchone())[0]
        if count == 0:
            await db.executemany(
                "INSERT INTO buckets (id, name, sort_order, description) VALUES (?, ?, ?, ?)",
                SEED_BUCKETS,
            )

        # Seed users if empty
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        count = (await cursor.fetchone())[0]
        if count == 0:
            await db.executemany(
                "INSERT INTO users (id, name, role) VALUES (?, ?, ?)",
                SEED_USERS,
            )
            await db.executemany(
                "INSERT INTO notification_prefs (user_id, notification_type, enabled) VALUES (?, ?, ?)",
                SEED_NOTIFICATION_PREFS,
            )

        # Seed user features if empty
        cursor = await db.execute("SELECT COUNT(*) FROM user_features")
        count = (await cursor.fetchone())[0]
        if count == 0:
            await db.executemany(
                "INSERT OR IGNORE INTO user_features (user_id, feature, enabled) VALUES (?, ?, ?)",
                SEED_FEATURES,
            )

        # Seed sharing permissions
        cursor = await db.execute("SELECT COUNT(*) FROM sharing_permissions")
        count = (await cursor.fetchone())[0]
        if count == 0:
            await db.executemany(
                "INSERT OR IGNORE INTO sharing_permissions (owner_user_id, target_user_id, data_category, shared) VALUES (?, ?, ?, ?)",
                SEED_SHARING,
            )

        # Seed profile if empty
        cursor = await db.execute("SELECT COUNT(*) FROM profile")
        count = (await cursor.fetchone())[0]
        if count == 0:
            await db.executemany(
                "INSERT INTO profile (key, value) VALUES (?, ?)",
                SEED_PROFILE.items(),
            )

        await db.commit()
    finally:
        await db.close()


async def execute(sql: str, params: tuple = ()) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        await db.commit()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def execute_insert(sql: str, params: tuple = ()) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(sql, params)
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()
