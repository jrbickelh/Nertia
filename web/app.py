"""
Nertia — FastAPI PWA backend.

Routes:
  POST /api/chat                — stream agent response
  GET  /api/schedule/today      — today's schedule blocks
  GET  /api/schedule/{date}     — schedule for any date (YYYY-MM-DD)
  GET  /api/tasks               — tasks (filterable)
  GET  /api/tasks/buckets       — bucket summary
  GET  /api/stats               — completion rates + API cost
  GET  /                        — serve PWA index.html
"""
import asyncio
import json
import os
import secrets
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import base64
import uuid as uuid_mod
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from db.database import init_db, execute, execute_insert
from agent.main import build_options
from agent.config import MCP_SERVER_NAME
from agent.prompts.system import SYSTEM_PROMPT
from agent.tools.tasks import ALL_TASK_TOOLS
from agent.tools.profile import ALL_PROFILE_TOOLS
from agent.tools.calendar import ALL_CALENDAR_TOOLS
from agent.tools.schedule import ALL_SCHEDULE_TOOLS
from agent.tools.notifications import ALL_NOTIFICATION_TOOLS

UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# Radicale CalDAV — configure URL and calendar slugs via environment or .env
# Each user needs a matching Radicale account; slug defaults to lowercase user name.
RADICALE_URL = os.getenv("RADICALE_URL", "http://127.0.0.1:5232")


async def _get_cal_slug(user_id: int) -> str:
    """Return the Radicale calendar slug for a user (lowercase name)."""
    rows = await execute("SELECT name FROM users WHERE id = ?", (user_id,))
    if rows:
        return rows[0]["name"].lower().replace(" ", "_")
    return f"user{user_id}"


limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Nertia", docs_url=None, redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
async def startup():
    await init_db()
    await execute("DELETE FROM sessions WHERE expires_at < datetime('now')")
    # Add macro columns if they don't exist yet (idempotent migration)
    for col, typ in [("protein_g", "INTEGER"), ("carbs_g", "INTEGER"), ("fat_g", "INTEGER")]:
        try:
            await execute(f"ALTER TABLE fitness_log ADD COLUMN {col} {typ}")
        except Exception:
            pass  # column already exists
    # Supplements table migration
    await execute("""
        CREATE TABLE IF NOT EXISTS supplements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            dose TEXT,
            timing TEXT NOT NULL DEFAULT 'morning',
            notes TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Routine items table migration
    await execute("""
        CREATE TABLE IF NOT EXISTS routine_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            title TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            duration_minutes INTEGER,
            block_type TEXT NOT NULL DEFAULT 'personal',
            days_of_week TEXT NOT NULL DEFAULT '1,2,3,4,5,6,7',
            notes TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Skip reason column migration
    try:
        await execute("ALTER TABLE schedule_blocks ADD COLUMN skip_reason TEXT")
    except Exception:
        pass  # column already exists
    # Routine completions table
    await execute("""
        CREATE TABLE IF NOT EXISTS routine_completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            routine_item_id INTEGER NOT NULL REFERENCES routine_items(id) ON DELETE CASCADE,
            date TEXT NOT NULL DEFAULT (date('now')),
            completed_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, routine_item_id, date)
        )
    """)


# ── Rate limiting (simple in-memory sliding window) ───────────────────────────

_rate_windows: dict[str, list[float]] = defaultdict(list)

def _check_rate(client_ip: str, limit: int = 20, window: int = 60) -> bool:
    now = time.time()
    _rate_windows[client_ip] = [t for t in _rate_windows[client_ip] if now - t < window]
    if len(_rate_windows[client_ip]) >= limit:
        return False
    _rate_windows[client_ip].append(now)
    return True


# ── MIME validation (no external deps) ────────────────────────────────────────

def _detect_image_mime(data: bytes) -> str | None:
    if data[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if data[:4] == b'\x89PNG':
        return 'image/png'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


# ── Auth dependency ───────────────────────────────────────────────────────────

async def get_current_user(x_session_token: str | None = Header(None)) -> int:
    if not x_session_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    rows = await execute(
        "SELECT user_id, expires_at FROM sessions WHERE token = ?",
        (x_session_token,),
    )
    if not rows:
        raise HTTPException(status_code=401, detail="Invalid session token")
    session = rows[0]
    if datetime.fromisoformat(session["expires_at"]) < datetime.utcnow():
        await execute("DELETE FROM sessions WHERE token = ?", (x_session_token,))
        raise HTTPException(status_code=401, detail="Session expired")
    return session["user_id"]


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ── Auth endpoints ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    user_id: int
    remember_me: bool = True


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    users = await execute("SELECT id FROM users WHERE id = ?", (req.user_id,))
    if not users:
        raise HTTPException(status_code=404, detail="User not found")
    token = secrets.token_urlsafe(32)
    days = 30 if req.remember_me else 1
    expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat()
    await execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, req.user_id, expires_at),
    )
    return {"token": token, "user_id": req.user_id, "expires_at": expires_at}


@app.post("/api/auth/logout")
async def logout(x_session_token: str | None = Header(None)):
    if x_session_token:
        await execute("DELETE FROM sessions WHERE token = ?", (x_session_token,))
    return {"ok": True}


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


@app.post("/api/chat")
@limiter.limit("30/minute")
async def chat(req: ChatRequest, request: Request, user_id: int = Depends(get_current_user)):
    """Stream agent response as Server-Sent Events."""
    from claude_agent_sdk import query, AssistantMessage, TextBlock

    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")

    # Build user-specific system prompt
    user_rows = await execute("SELECT name FROM users WHERE id = ?", (user_id,))
    user_name = user_rows[0]["name"] if user_rows else "User"
    feature_rows = await execute(
        "SELECT feature FROM user_features WHERE user_id = ? AND enabled = 1", (user_id,)
    )
    enabled_features = [r["feature"] for r in feature_rows]
    user_context = (
        f"\n\n## Active user\n"
        f"You are speaking with {user_name} (user_id={user_id}). "
        f"Refer to them by name. Their enabled features: {', '.join(enabled_features) or 'all standard features'}.\n"
        f"IMPORTANT: Always pass user_id={user_id} as a parameter when calling any tool "
        f"(list_tasks, add_task, complete_task, update_task, defer_task, search_tasks, get_buckets, "
        f"get_profile, update_preference, get_user_context, generate_daily_schedule, get_todays_schedule, "
        f"get_next_block, adjust_schedule, add_event, list_events, delete_event, find_free_slots, "
        f"get_completion_stats, get_adaptation_insights, log_bible_reading, get_reading_progress, "
        f"log_workout, log_meal, log_body_metric, get_fitness_summary, "
        f"set_notification_pref, get_notification_prefs). "
        f"Never omit user_id or use a different user's ID."
    )
    options = build_options(system_prompt=SYSTEM_PROMPT + user_context)

    # Prepend conversation history so the agent has context
    if req.history:
        ctx_parts = []
        for h in req.history[-6:]:
            if h.get("user"):
                ctx_parts.append(f"User: {h['user']}")
            if h.get("agent"):
                ctx_parts.append(f"Assistant: {h['agent']}")
        full_message = f"[Previous conversation for context:\n{chr(10).join(ctx_parts)}\n]\n\n{req.message}"
    else:
        full_message = req.message

    async def event_stream():
        try:
            async for message in query(prompt=full_message, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text:
                            payload = json.dumps({"text": block.text})
                            yield f"data: {payload}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Schedule ──────────────────────────────────────────────────────────────────

def _format_schedule(schedule_row: dict, block_rows: list[dict]) -> dict:
    return {
        "id": schedule_row["id"],
        "date": schedule_row["date"],
        "generated_at": schedule_row["generated_at"],
        "blocks": [
            {
                "id": b["id"],
                "start": b["start_time"],
                "end": b["end_time"],
                "activity": b["activity"],
                "type": b["block_type"],
                "task_id": b["task_id"],
                "completed": bool(b["completed"]),
                "skipped": bool(b["skipped"]),
            }
            for b in block_rows
        ],
    }


@app.get("/api/schedule/today")
async def schedule_today(user_id: int = Depends(get_current_user)):
    target = date.today().isoformat()
    return await _get_schedule(target, user_id)


@app.get("/api/schedule/range")
async def schedule_range(
    start: str = Query(...), end: str = Query(...),
    user_id: int = Depends(get_current_user),
):
    rows = await execute(
        "SELECT id, date, generated_at FROM schedules "
        "WHERE user_id = ? AND date >= ? AND date <= ? ORDER BY date, generated_at DESC",
        (user_id, start, end),
    )
    seen = {}
    for r in rows:
        if r["date"] not in seen:
            seen[r["date"]] = r
    result = {}
    for d, sched in seen.items():
        blocks = await execute(
            "SELECT id, start_time, end_time, activity, block_type, task_id, completed, skipped "
            "FROM schedule_blocks WHERE schedule_id = ? ORDER BY start_time",
            (sched["id"],),
        )
        result[d] = [
            {"id": b["id"], "start": b["start_time"], "end": b["end_time"],
             "activity": b["activity"], "type": b["block_type"],
             "completed": bool(b["completed"]), "skipped": bool(b["skipped"])}
            for b in blocks
        ]
    return {"schedules": result}


@app.get("/api/schedule/{target_date}")
async def schedule_for_date(target_date: str, user_id: int = Depends(get_current_user)):
    return await _get_schedule(target_date, user_id)


async def _get_schedule(target_date: str, user_id: int = 1):
    rows = await execute(
        "SELECT id, date, generated_at FROM schedules WHERE user_id = ? AND date = ? ORDER BY generated_at DESC LIMIT 1",
        (user_id, target_date),
    )
    if not rows:
        return JSONResponse({"error": f"No schedule for {target_date}"}, status_code=404)

    sched = rows[0]
    blocks = await execute(
        "SELECT id, start_time, end_time, activity, block_type, task_id, completed, skipped "
        "FROM schedule_blocks WHERE schedule_id = ? ORDER BY start_time",
        (sched["id"],),
    )
    return _format_schedule(sched, blocks)


# ── Tasks ─────────────────────────────────────────────────────────────────────

@app.get("/api/tasks")
async def list_tasks(
    bucket: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50),
    recurring: str | None = Query(None),  # "true" → only recurring tasks
    view_user: str | None = Query(None),  # "all" → show all users; omit → current user only
    user_id: int = Depends(get_current_user),
):
    if view_user == "all":
        conditions = ["1=1"]
        params: list = []
    else:
        conditions = ["t.user_id = ?"]
        params: list = [user_id]
    if bucket:
        conditions.append("b.name = ?")
        params.append(bucket)
    if status:
        conditions.append("t.status = ?")
        params.append(status)
    if recurring == "true":
        conditions.append("t.recurring IS NOT NULL")

    where = f"WHERE {' AND '.join(conditions)}"
    rows = await execute(
        f"""
        SELECT t.id, t.title, t.description, t.priority, t.status,
               t.due_date, t.est_minutes, t.energy_level, t.tags, t.recurring,
               t.created_at, t.completed_at, b.name as bucket,
               t.user_id, u.name as user_name
        FROM tasks t JOIN buckets b ON t.bucket_id = b.id
             JOIN users u ON t.user_id = u.id
        {where}
        ORDER BY t.priority ASC, t.created_at ASC
        LIMIT ?
        """,
        (*params, limit),
    )
    return {"tasks": [dict(r) for r in rows]}


@app.get("/api/tasks/buckets")
async def task_buckets(user_id: int = Depends(get_current_user)):
    rows = await execute(
        """
        SELECT b.name, b.description,
               COUNT(CASE WHEN t.status = 'todo' AND t.user_id = ? THEN 1 END) as todo,
               COUNT(CASE WHEN t.status = 'in_progress' AND t.user_id = ? THEN 1 END) as in_progress,
               COUNT(CASE WHEN t.status = 'done' AND t.user_id = ? THEN 1 END) as done,
               COUNT(CASE WHEN t.status = 'deferred' AND t.user_id = ? THEN 1 END) as deferred
        FROM buckets b LEFT JOIN tasks t ON b.id = t.bucket_id
        GROUP BY b.id ORDER BY b.sort_order
        """,
        (user_id, user_id, user_id, user_id),
    )
    return {"buckets": [dict(r) for r in rows]}


class AddBucketRequest(BaseModel):
    name: str
    description: str | None = None

@app.post("/api/tasks/buckets")
async def add_bucket_api(req: AddBucketRequest, uid: int = Depends(get_current_user)):
    existing = await execute("SELECT id FROM buckets WHERE name = ?", (req.name,))
    if existing:
        raise HTTPException(status_code=409, detail="Bucket already exists")
    sort_order = await execute("SELECT COALESCE(MAX(sort_order),0)+1 as n FROM buckets")
    so = sort_order[0]["n"] if sort_order else 1
    await execute_insert(
        "INSERT INTO buckets (name, description, sort_order) VALUES (?, ?, ?)",
        (req.name, req.description or "", so),
    )
    return {"ok": True}


class PatchBucketRequest(BaseModel):
    name: str | None = None
    description: str | None = None

@app.patch("/api/tasks/buckets/{bucket_id}")
async def patch_bucket_api(bucket_id: int, req: PatchBucketRequest, uid: int = Depends(get_current_user)):
    if req.name:
        await execute("UPDATE buckets SET name = ? WHERE id = ?", (req.name, bucket_id))
    if req.description is not None:
        await execute("UPDATE buckets SET description = ? WHERE id = ?", (req.description, bucket_id))
    return {"ok": True}

@app.delete("/api/tasks/buckets/{bucket_id}")
async def delete_bucket_api(bucket_id: int, uid: int = Depends(get_current_user)):
    # Move tasks in this bucket to the first non-deleted bucket (fallback: Now)
    fallback = await execute("SELECT id FROM buckets WHERE id != ? ORDER BY sort_order LIMIT 1", (bucket_id,))
    fallback_id = fallback[0]["id"] if fallback else None
    if fallback_id:
        await execute("UPDATE tasks SET bucket_id = ? WHERE bucket_id = ?", (fallback_id, bucket_id))
    await execute("DELETE FROM buckets WHERE id = ?", (bucket_id,))
    return {"ok": True}


# ── Profile settings ──────────────────────────────────────────────────────────

@app.get("/api/profile")
async def get_profile_api(user_id: int = Depends(get_current_user)):
    rows = await execute("SELECT key, value FROM profile WHERE user_id = ?", (user_id,))
    return {"profile": {r["key"]: r["value"] for r in rows}}

@app.put("/api/profile")
async def update_profile_api(req: Request, user_id: int = Depends(get_current_user)):
    body = await req.json()
    for key, value in body.items():
        await execute(
            "INSERT OR REPLACE INTO profile (user_id, key, value) VALUES (?, ?, ?)",
            (user_id, key, str(value)),
        )
    return {"ok": True}


# ── Supplements ───────────────────────────────────────────────────────────────

class SupplementRequest(BaseModel):
    name: str
    dose: str | None = None
    timing: str = "morning"   # morning | with_meal | afternoon | evening | bedtime
    notes: str | None = None
    enabled: bool = True

@app.get("/api/supplements")
async def list_supplements(user_id: int = Depends(get_current_user)):
    rows = await execute("SELECT * FROM supplements WHERE user_id = ? ORDER BY timing, name", (user_id,))
    return {"supplements": [dict(r) for r in rows]}

@app.post("/api/supplements")
async def create_supplement(req: SupplementRequest, user_id: int = Depends(get_current_user)):
    sid = await execute_insert(
        "INSERT INTO supplements (user_id, name, dose, timing, notes, enabled) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, req.name, req.dose, req.timing, req.notes, int(req.enabled)),
    )
    return {"ok": True, "id": sid}

@app.put("/api/supplements/{sid}")
async def update_supplement(sid: int, req: SupplementRequest, user_id: int = Depends(get_current_user)):
    await execute(
        "UPDATE supplements SET name=?, dose=?, timing=?, notes=?, enabled=? WHERE id=? AND user_id=?",
        (req.name, req.dose, req.timing, req.notes, int(req.enabled), sid, user_id),
    )
    return {"ok": True}

@app.delete("/api/supplements/{sid}")
async def delete_supplement(sid: int, user_id: int = Depends(get_current_user)):
    await execute("DELETE FROM supplements WHERE id=? AND user_id=?", (sid, user_id))
    return {"ok": True}


# ── Routine items ─────────────────────────────────────────────────────────────

class RoutineItemRequest(BaseModel):
    title: str
    start_time: str | None = None
    end_time: str | None = None
    duration_minutes: int | None = None
    block_type: str = "personal"
    days_of_week: str = "1,2,3,4,5,6,7"
    notes: str | None = None
    enabled: bool = True

class RoutineItemUpdate(BaseModel):
    title: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    duration_minutes: int | None = None
    block_type: str | None = None
    days_of_week: str | None = None
    notes: str | None = None
    enabled: bool | None = None

@app.get("/api/routine")
async def list_routine(user_id: int = Depends(get_current_user)):
    rows = await execute(
        "SELECT * FROM routine_items WHERE user_id = ? ORDER BY sort_order, start_time",
        (user_id,),
    )
    return {"items": [dict(r) for r in rows]}

@app.post("/api/routine")
async def create_routine(req: RoutineItemRequest, user_id: int = Depends(get_current_user)):
    item_id = await execute_insert(
        """INSERT INTO routine_items
           (user_id, title, start_time, end_time, duration_minutes, block_type, days_of_week, notes, enabled)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, req.title, req.start_time, req.end_time, req.duration_minutes,
         req.block_type, req.days_of_week, req.notes, int(req.enabled)),
    )
    return {"ok": True, "id": item_id}

@app.put("/api/routine/{item_id}")
async def update_routine(item_id: int, req: RoutineItemUpdate, user_id: int = Depends(get_current_user)):
    updates, params = [], []
    if req.title is not None: updates.append("title = ?"); params.append(req.title)
    if req.start_time is not None: updates.append("start_time = ?"); params.append(req.start_time)
    if req.end_time is not None: updates.append("end_time = ?"); params.append(req.end_time)
    if req.duration_minutes is not None: updates.append("duration_minutes = ?"); params.append(req.duration_minutes)
    if req.block_type is not None: updates.append("block_type = ?"); params.append(req.block_type)
    if req.days_of_week is not None: updates.append("days_of_week = ?"); params.append(req.days_of_week)
    if req.notes is not None: updates.append("notes = ?"); params.append(req.notes)
    if req.enabled is not None: updates.append("enabled = ?"); params.append(int(req.enabled))
    if updates:
        params.extend([item_id, user_id])
        await execute(f"UPDATE routine_items SET {', '.join(updates)} WHERE id = ? AND user_id = ?", tuple(params))
    return {"ok": True}

@app.delete("/api/routine/{item_id}")
async def delete_routine(item_id: int, user_id: int = Depends(get_current_user)):
    await execute("DELETE FROM routine_items WHERE id = ? AND user_id = ?", (item_id, user_id))
    return {"ok": True}


@app.get("/api/routine/completions")
async def get_routine_completions(user_id: int = Depends(get_current_user)):
    today = date.today().isoformat()
    # Get all enabled routine items with today's completion status and streak
    items = await execute(
        "SELECT id, title FROM routine_items WHERE user_id = ? AND enabled = 1",
        (user_id,)
    )
    result = []
    for item in items:
        done_today = await execute(
            "SELECT id FROM routine_completions WHERE user_id = ? AND routine_item_id = ? AND date = ?",
            (user_id, item["id"], today)
        )
        # Calculate streak (consecutive days completed up to today)
        streak_rows = await execute(
            """SELECT date FROM routine_completions
               WHERE user_id = ? AND routine_item_id = ?
               ORDER BY date DESC LIMIT 30""",
            (user_id, item["id"])
        )
        streak = 0
        check_date = date.today()
        dates = {r["date"] for r in streak_rows}
        while check_date.isoformat() in dates:
            streak += 1
            check_date -= timedelta(days=1)
        result.append({"id": item["id"], "title": item["title"], "done_today": bool(done_today), "streak": streak})
    return {"completions": result}


@app.post("/api/routine/completions/{item_id}")
async def toggle_routine_completion(item_id: int, user_id: int = Depends(get_current_user)):
    today = date.today().isoformat()
    existing = await execute(
        "SELECT id FROM routine_completions WHERE user_id = ? AND routine_item_id = ? AND date = ?",
        (user_id, item_id, today)
    )
    if existing:
        await execute(
            "DELETE FROM routine_completions WHERE user_id = ? AND routine_item_id = ? AND date = ?",
            (user_id, item_id, today)
        )
        return {"done": False}
    else:
        await execute_insert(
            "INSERT OR IGNORE INTO routine_completions (user_id, routine_item_id, date) VALUES (?,?,?)",
            (user_id, item_id, today)
        )
        return {"done": True}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def stats(period: str = Query("week"), user_id: int = Depends(get_current_user)):
    days = 7 if period == "week" else 30
    since = f"datetime('now', '-{days} days')"

    completion = await execute(
        f"""
        SELECT
            COUNT(*) as total_blocks,
            SUM(completed) as completed_blocks,
            SUM(skipped) as skipped_blocks
        FROM schedule_blocks sb
        JOIN schedules s ON sb.schedule_id = s.id
        WHERE s.user_id = ? AND s.date >= date('now', '-{days} days')
        """,
        (user_id,),
    )

    by_type = await execute(
        f"""
        SELECT block_type,
               COUNT(*) as total,
               SUM(completed) as completed
        FROM schedule_blocks sb
        JOIN schedules s ON sb.schedule_id = s.id
        WHERE s.user_id = ? AND s.date >= date('now', '-{days} days')
        GROUP BY block_type ORDER BY total DESC
        """,
        (user_id,),
    )

    api_cost = await execute(
        f"SELECT COALESCE(SUM(cost_usd), 0) as total, COALESCE(SUM(tokens_in + tokens_out), 0) as tokens "
        f"FROM api_usage WHERE timestamp >= {since}"
    )

    tasks_done = await execute(
        f"SELECT COUNT(*) as count FROM tasks WHERE user_id = ? AND status = 'done' AND completed_at >= {since}",
        (user_id,),
    )

    return {
        "period": period,
        "completion": dict(completion[0]) if completion else {},
        "by_type": [dict(r) for r in by_type],
        "api_cost_usd": round(api_cost[0]["total"], 4) if api_cost else 0,
        "api_tokens": api_cost[0]["tokens"] if api_cost else 0,
        "tasks_completed": tasks_done[0]["count"] if tasks_done else 0,
    }


# ── Feedback ──────────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    block_id: int
    completed: bool = False
    skipped: bool = False
    energy_rating: int | None = None
    focus_rating: int | None = None
    notes: str | None = None


@app.post("/api/schedule/feedback")
async def submit_feedback(req: FeedbackRequest, _: int = Depends(get_current_user)):
    from agent.tools.feedback import log_block_feedback
    result = await log_block_feedback.handler(req.model_dump(exclude_none=True))
    return {"message": result["content"][0]["text"]}


class PushBlockRequest(BaseModel):
    block_id: int
    minutes: int = 30


@app.post("/api/schedule/push-block")
async def push_block(req: PushBlockRequest, _: int = Depends(get_current_user)):
    """Push a schedule block forward by N minutes, shifting subsequent blocks."""
    block = await execute(
        "SELECT id, schedule_id, start_time, end_time FROM schedule_blocks WHERE id = ?",
        (req.block_id,),
    )
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")
    b = block[0]
    # Shift this block and all subsequent blocks in same schedule
    subsequent = await execute(
        "SELECT id, start_time, end_time FROM schedule_blocks "
        "WHERE schedule_id = ? AND start_time >= ? ORDER BY start_time",
        (b["schedule_id"], b["start_time"]),
    )
    for sb in subsequent:
        def shift(t):
            h, m = map(int, t.split(":"))
            total = h * 60 + m + req.minutes
            return f"{min(total // 60, 23):02d}:{total % 60:02d}"
        await execute(
            "UPDATE schedule_blocks SET start_time = ?, end_time = ? WHERE id = ?",
            (shift(sb["start_time"]), shift(sb["end_time"]), sb["id"]),
        )
    return {"ok": True, "message": f"Pushed {len(subsequent)} block(s) forward by {req.minutes} minutes"}


@app.delete("/api/schedule/block/{block_id}")
async def delete_block(block_id: int, _: int = Depends(get_current_user)):
    await execute("DELETE FROM schedule_blocks WHERE id = ?", (block_id,))
    return {"ok": True}


class PatchBlockRequest(BaseModel):
    completed: bool | None = None
    skipped: bool | None = None
    actual_start: str | None = None
    actual_end: str | None = None
    skip_reason: str | None = None

@app.patch("/api/schedule/block/{block_id}")
async def patch_block(block_id: int, req: PatchBlockRequest, _: int = Depends(get_current_user)):
    """Update block completion status and optionally store actual timing via feedback."""
    updates, params = [], []
    if req.completed is not None: updates.append("completed = ?"); params.append(int(req.completed))
    if req.skipped is not None: updates.append("skipped = ?"); params.append(int(req.skipped))
    if req.skip_reason is not None:
        updates.append("skip_reason = ?"); params.append(req.skip_reason)
    if updates:
        params.append(block_id)
        await execute(f"UPDATE schedule_blocks SET {', '.join(updates)} WHERE id = ?", tuple(params))
    # Upsert feedback row with actual timing if provided
    if req.actual_start or req.actual_end:
        existing = await execute("SELECT id FROM feedback WHERE block_id = ?", (block_id,))
        if existing:
            fb_updates, fb_params = [], []
            if req.actual_start: fb_updates.append("actual_start = ?"); fb_params.append(req.actual_start)
            if req.actual_end: fb_updates.append("actual_end = ?"); fb_params.append(req.actual_end)
            if fb_updates:
                fb_params.append(existing[0]["id"])
                await execute(f"UPDATE feedback SET {', '.join(fb_updates)} WHERE id = ?", tuple(fb_params))
        else:
            await execute_insert(
                "INSERT INTO feedback (block_id, actual_start, actual_end) VALUES (?, ?, ?)",
                (block_id, req.actual_start, req.actual_end),
            )
    return {"ok": True}


# ── Direct task mutations ────────────────────────────────────────────────────

@app.post("/api/tasks/{task_id}/complete")
async def complete_task_api(task_id: int, _: int = Depends(get_current_user)):
    from agent.tools.tasks import complete_task
    result = await complete_task.handler({"task_id": task_id})
    return {"message": result["content"][0]["text"]}


class DeferRequest(BaseModel):
    new_due_date: str | None = None
    reason: str | None = None

@app.post("/api/tasks/{task_id}/defer")
async def defer_task_api(task_id: int, req: DeferRequest | None = None, _: int = Depends(get_current_user)):
    from agent.tools.tasks import defer_task
    due = (req.new_due_date if req and req.new_due_date else None)
    if not due:
        # Default: defer to tomorrow
        due = (date.today() + timedelta(days=1)).isoformat()
    args = {"task_id": task_id, "new_due_date": due}
    if req and req.reason:
        args["reason"] = req.reason
    result = await defer_task.handler(args)
    return {"message": result["content"][0]["text"]}


class AddTaskRequest(BaseModel):
    title: str
    bucket: str = "Now"
    priority: int = 3
    description: str | None = None
    due_date: str | None = None
    est_minutes: int | None = None
    energy_level: str | None = None
    tags: str | None = None
    recurring: str | None = None

@app.post("/api/tasks")
async def add_task_api(req: AddTaskRequest, uid: int = Depends(get_current_user)):
    import re
    from agent.tools.tasks import add_task
    args = {"title": req.title, "bucket": req.bucket, "priority": req.priority, "user_id": uid}
    if req.description: args["description"] = req.description
    if req.due_date: args["due_date"] = req.due_date
    if req.est_minutes: args["est_minutes"] = req.est_minutes
    if req.energy_level: args["energy_level"] = req.energy_level
    if req.tags: args["tags"] = req.tags
    result = await add_task.handler(args)
    if req.recurring:
        match = re.search(r'Added task #(\d+)', result["content"][0]["text"])
        if match:
            await execute("UPDATE tasks SET recurring = ? WHERE id = ?", (req.recurring, int(match.group(1))))
    return {"message": result["content"][0]["text"]}


class BulkAddTaskRequest(BaseModel):
    tasks: list[str]
    bucket: str = "Now"
    priority: int = 3

@app.post("/api/tasks/bulk")
async def bulk_add_tasks_api(req: BulkAddTaskRequest, uid: int = Depends(get_current_user)):
    from agent.tools.tasks import add_task
    added = []
    errors = []
    for title in req.tasks:
        title = title.strip()
        if not title:
            continue
        try:
            result = await add_task.handler({"title": title, "bucket": req.bucket, "priority": req.priority})
            added.append(title)
        except Exception as e:
            errors.append(f"{title}: {e}")
    return {"added": len(added), "errors": errors, "message": f"Added {len(added)} task(s)"}


@app.delete("/api/tasks/{task_id}")
async def delete_task_api(task_id: int, _: int = Depends(get_current_user)):
    await execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return {"ok": True}


class UpdateTaskRequest(BaseModel):
    title: str | None = None
    bucket: str | None = None
    priority: int | None = None
    due_date: str | None = None
    energy_level: str | None = None
    description: str | None = None
    recurring: str | None = None


@app.put("/api/tasks/{task_id}")
async def update_task_api(task_id: int, req: UpdateTaskRequest, _: int = Depends(get_current_user)):
    updates, params = [], []
    if req.title is not None:
        updates.append("title = ?"); params.append(req.title)
    if req.priority is not None:
        updates.append("priority = ?"); params.append(req.priority)
    if req.due_date is not None:
        updates.append("due_date = ?"); params.append(req.due_date or None)
    if req.energy_level is not None:
        updates.append("energy_level = ?"); params.append(req.energy_level or None)
    if req.description is not None:
        updates.append("description = ?"); params.append(req.description or None)
    if req.recurring is not None:
        updates.append("recurring = ?"); params.append(req.recurring or None)
    if req.bucket is not None:
        bucket_row = await execute("SELECT id FROM buckets WHERE name = ?", (req.bucket,))
        if bucket_row:
            updates.append("bucket_id = ?"); params.append(bucket_row[0]["id"])
    if updates:
        params.append(task_id)
        await execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", tuple(params))
    return {"ok": True}


# ── Direct meal logging ─────────────────────────────────────────────────────

class MealLogRequest(BaseModel):
    activity: str
    calories: int | None = None
    notes: str | None = None
    photo_path: str | None = None
    date: str | None = None      # YYYY-MM-DD
    time: str | None = None      # HH:MM
    protein_g: int | None = None
    carbs_g: int | None = None
    fat_g: int | None = None

@app.post("/api/meals")
async def log_meal_api(req: MealLogRequest, uid: int = Depends(get_current_user)):
    from agent.tools.fitness import log_meal
    args = {"activity": req.activity, "user_id": uid}
    if req.date: args["date"] = req.date
    if req.calories: args["calories"] = req.calories
    # Auto-analyze nutrition if no notes provided
    notes = req.notes or ""
    auto_nutrition: dict = {}
    if not notes:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic()
            analysis = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": (
                    "Analyze this meal. Return ONLY a raw JSON object with no markdown, no code fences, no explanation. "
                    'Format: {"summary":"one-line description","calories":N,"protein_g":N,"carbs_g":N,"fat_g":N} '
                    f"Meal: {req.activity}"
                )}],
            )
            raw = analysis.content[0].text.strip()
            try:
                auto_nutrition = json.loads(raw)
                notes = auto_nutrition.get("summary", raw)
            except Exception:
                notes = raw
        except Exception:
            pass
    if notes:
        args["notes"] = notes
    if req.photo_path: args["photo_path"] = req.photo_path
    result = await log_meal.handler(args)
    # Store macros — prefer explicit values from request, fall back to auto-analyzed
    meal_date = req.date or date.today().isoformat()
    last = await execute(
        "SELECT id FROM fitness_log WHERE user_id = ? AND log_type = 'meal' ORDER BY id DESC LIMIT 1",
        (uid,),
    )
    if last:
        meal_id = last[0]["id"]
        protein = req.protein_g or auto_nutrition.get("protein_g")
        carbs   = req.carbs_g   or auto_nutrition.get("carbs_g")
        fat     = req.fat_g     or auto_nutrition.get("fat_g")
        cal     = req.calories  or auto_nutrition.get("calories")
        macro_updates, macro_params = [], []
        if protein is not None: macro_updates.append("protein_g = ?"); macro_params.append(protein)
        if carbs   is not None: macro_updates.append("carbs_g = ?");   macro_params.append(carbs)
        if fat     is not None: macro_updates.append("fat_g = ?");     macro_params.append(fat)
        if cal     is not None: macro_updates.append("calories = ?");  macro_params.append(cal)
        if req.time:
            macro_updates.append("created_at = ?")
            macro_params.append(f"{meal_date} {req.time}:00")
        if macro_updates:
            macro_params.append(meal_id)
            await execute(f"UPDATE fitness_log SET {', '.join(macro_updates)} WHERE id = ?", tuple(macro_params))
    return {"message": result["content"][0]["text"]}

@app.get("/api/meals/today-summary")
async def meals_today_summary(uid: int = Depends(get_current_user)):
    today = date.today().isoformat()
    rows = await execute(
        "SELECT COALESCE(SUM(calories),0) as total_cal, "
        "COALESCE(SUM(protein_g),0) as total_protein, "
        "COALESCE(SUM(carbs_g),0) as total_carbs, "
        "COALESCE(SUM(fat_g),0) as total_fat, "
        "COUNT(*) as meal_count "
        "FROM fitness_log WHERE user_id = ? AND log_type = 'meal' AND date = ?",
        (uid, today),
    )
    r = rows[0] if rows else {}
    return {
        "date": today,
        "total_cal": r.get("total_cal", 0),
        "total_protein": r.get("total_protein", 0),
        "total_carbs": r.get("total_carbs", 0),
        "total_fat": r.get("total_fat", 0),
        "meal_count": r.get("meal_count", 0),
    }

@app.get("/api/meals")
async def get_meals_api(days: int = 7, uid: int = Depends(get_current_user)):
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = await execute(
        "SELECT id, date, activity, calories, protein_g, carbs_g, fat_g, details, photo_path, created_at "
        "FROM fitness_log WHERE user_id = ? AND log_type = 'meal' AND date >= ? "
        "ORDER BY created_at DESC",
        (uid, since),
    )
    import re as _re
    meals = []
    for r in rows:
        m = dict(r)
        raw = (m.get("details") or "").strip()
        # Strip markdown code fences (```json ... ```)
        raw = _re.sub(r'^```[a-zA-Z]*\n?', '', raw).strip()
        raw = _re.sub(r'\n?```$', '', raw).strip()
        if raw.startswith("{"):
            try:
                parsed = json.loads(raw)
                if m["calories"]  is None and parsed.get("calories")  is not None: m["calories"]  = int(parsed["calories"])
                if m["protein_g"] is None and parsed.get("protein_g") is not None: m["protein_g"] = int(parsed["protein_g"])
                if m["carbs_g"]   is None and parsed.get("carbs_g")   is not None: m["carbs_g"]   = int(parsed["carbs_g"])
                if m["fat_g"]     is None and parsed.get("fat_g")     is not None: m["fat_g"]     = int(parsed["fat_g"])
                m["details"] = parsed.get("summary") or parsed.get("description") or ""
            except Exception:
                pass
        elif raw:
            # Parse pipe-delimited nutrition strings like "Category: X | ~165 cal | P:31g C:0g F:3.6g"
            cal_m = _re.search(r'~?(\d+)\s*cal', raw, _re.I)
            pro_m = _re.search(r'P:(\d+(?:\.\d+)?)g', raw)
            carb_m = _re.search(r'C:(\d+(?:\.\d+)?)g', raw)
            fat_m  = _re.search(r'F:(\d+(?:\.\d+)?)g', raw)
            if cal_m and m["calories"] is None: m["calories"] = int(cal_m.group(1))
            if pro_m and m["protein_g"] is None: m["protein_g"] = int(float(pro_m.group(1)))
            if carb_m and m["carbs_g"] is None:  m["carbs_g"]  = int(float(carb_m.group(1)))
            if fat_m  and m["fat_g"]   is None:  m["fat_g"]    = int(float(fat_m.group(1)))
            m["details"] = raw  # keep human-readable string as-is
        meals.append(m)
    return {"meals": meals}


class MealUpdateRequest(BaseModel):
    activity: str | None = None
    calories: int | None = None
    notes: str | None = None
    protein_g: int | None = None
    carbs_g: int | None = None
    fat_g: int | None = None

@app.put("/api/meals/{meal_id}")
async def update_meal_api(meal_id: int, req: MealUpdateRequest, uid: int = Depends(get_current_user)):
    existing = await execute("SELECT id FROM fitness_log WHERE id = ? AND user_id = ? AND log_type = 'meal'", (meal_id, uid))
    if not existing:
        raise HTTPException(status_code=404, detail="Meal not found")
    updates, params = [], []
    if req.activity  is not None: updates.append("activity = ?");  params.append(req.activity)
    if req.calories  is not None: updates.append("calories = ?");  params.append(req.calories)
    if req.notes     is not None: updates.append("details = ?");   params.append(req.notes)
    if req.protein_g is not None: updates.append("protein_g = ?"); params.append(req.protein_g)
    if req.carbs_g   is not None: updates.append("carbs_g = ?");   params.append(req.carbs_g)
    if req.fat_g     is not None: updates.append("fat_g = ?");     params.append(req.fat_g)
    if updates:
        params.append(meal_id)
        await execute(f"UPDATE fitness_log SET {', '.join(updates)} WHERE id = ?", tuple(params))
    return {"ok": True}


@app.delete("/api/meals/{meal_id}")
async def delete_meal_api(meal_id: int, uid: int = Depends(get_current_user)):
    await execute("DELETE FROM fitness_log WHERE id = ? AND user_id = ? AND log_type = 'meal'", (meal_id, uid))
    return {"ok": True}


@app.get("/api/meals/insights")
async def meal_insights_api(start: str = Query(None), end: str = Query(None), uid: int = Depends(get_current_user)):
    """Generate AI-powered nutrition insights for a date range."""
    if not start:
        start = (date.today() - timedelta(days=7)).isoformat()
    if not end:
        end = date.today().isoformat()
    rows = await execute(
        "SELECT date, activity, calories, details, created_at "
        "FROM fitness_log WHERE user_id = ? AND log_type = 'meal' AND date >= ? AND date <= ? "
        "ORDER BY date, created_at",
        (uid, start, end),
    )
    meals = [dict(r) for r in rows]
    if not meals:
        return {"insights": "No meals logged in this period.", "meals_count": 0, "period": f"{start} to {end}"}

    meal_list = "\n".join(f"- {m['date']} {m.get('created_at','')[:16]}: {m['activity']}" + (f" ({m['details']})" if m.get('details') else "") for m in meals)

    import anthropic
    client = anthropic.AsyncAnthropic()
    analysis = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": f"""Analyze these meals from {start} to {end} and provide a brief nutrition summary. Include:
1. Total meals logged
2. Overall eating patterns (timing, frequency)
3. Macro balance assessment (protein/carb/fat tendency)
4. Food variety score (1-10)
5. Top 2-3 suggestions for improvement
Keep it concise, use short bullet points.

Meals:
{meal_list}"""}],
    )
    return {
        "insights": analysis.content[0].text.strip(),
        "meals_count": len(meals),
        "period": f"{start} to {end}",
    }


# ── Photo analysis ────────────────────────────────────────────────────────────

@app.post("/api/upload/photo")
async def analyze_photo(
    file: UploadFile = File(...),
    context: str = Form("general"),  # "meal" | "workout" | "general"
    _: int = Depends(get_current_user),
):
    """Receive a photo, save it, analyze with Claude vision, return description."""
    import anthropic

    content = await file.read()

    # Validate MIME type from actual file bytes, not extension
    mime = _detect_image_mime(content)
    if not mime:
        raise HTTPException(status_code=400, detail="File must be a JPEG, PNG, GIF, or WebP image")

    suffix = {
        'image/jpeg': '.jpg', 'image/png': '.png',
        'image/gif': '.gif', 'image/webp': '.webp',
    }.get(mime, '.jpg')
    fname = f"{uuid_mod.uuid4()}{suffix}"
    fpath = UPLOADS_DIR / fname
    fpath.write_bytes(content)

    prompts = {
        "meal": (
            'Analyze this meal photo. Respond ONLY with valid JSON, no markdown, no text outside the JSON object: '
            '{"description":"<1-sentence description of what you see>","calories":<integer>,'
            '"protein_g":<integer>,"carbs_g":<integer>,"fat_g":<integer>,"confidence":"<high|medium|low>"} '
            'Base estimates on typical portion sizes visible in the photo.'
        ),
        "workout": "Describe this workout or exercise photo. What activity, equipment, or results are visible? 2-3 sentences.",
        "general": "Briefly describe what you see in this photo relevant to health, fitness, or nutrition. 2-3 sentences.",
    }

    try:
        img_b64 = base64.standard_b64encode(content).decode()
        client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=250,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": img_b64}},
                {"type": "text", "text": prompts.get(context, prompts["general"])},
            ]}],
        )
        from agent.usage import log_usage
        await log_usage("claude-haiku-4-5-20251001",
                        response.usage.input_tokens, response.usage.output_tokens, "photo_analysis")
        raw_text = response.content[0].text.strip()
    except Exception as e:
        raw_text = f"Could not analyze photo: {e}"

    # For meal photos, attempt to parse structured nutrition JSON
    nutrition = None
    if context == "meal":
        try:
            nutrition = json.loads(raw_text)
            description = nutrition.get("description", raw_text)
        except (json.JSONDecodeError, ValueError):
            description = raw_text
    else:
        description = raw_text

    result: dict = {"description": description, "photo_path": str(fpath), "filename": fname}
    if nutrition:
        result["nutrition"] = nutrition
    return result


# ── Users & shared data ───────────────────────────────────────────────────────

@app.get("/api/users")
async def list_users():
    rows = await execute("SELECT id, name, role FROM users ORDER BY id")
    return {"users": [dict(r) for r in rows]}


@app.get("/api/users/{user_id}/fitness")
async def user_fitness(user_id: int, period: str = Query("week"), _: int = Depends(get_current_user)):
    from agent.tools.fitness import get_fitness_summary
    result = await get_fitness_summary.handler({"period": period, "user_id": user_id})
    return {"summary": result["content"][0]["text"]}


@app.get("/api/users/{user_id}/bible")
async def user_bible(user_id: int, _: int = Depends(get_current_user)):
    from agent.tools.bible import get_reading_progress
    result = await get_reading_progress.handler({"user_id": user_id})
    return {"progress": result["content"][0]["text"]}


# ── Notification prefs ────────────────────────────────────────────────────────

@app.get("/api/notification-prefs")
async def get_notif_prefs(user_id: int = Depends(get_current_user)):
    rows = await execute(
        "SELECT notification_type, enabled, disabled_reason FROM notification_prefs WHERE user_id = ? ORDER BY notification_type",
        (user_id,),
    )
    return {"prefs": [dict(r) for r in rows]}


class NotifPrefUpdate(BaseModel):
    notification_type: str
    enabled: bool
    reason: str | None = None
    user_id: int = 1


@app.post("/api/notification-prefs")
async def update_notif_pref(req: NotifPrefUpdate, _: int = Depends(get_current_user)):
    from agent.tools.notification_prefs import set_notification_pref
    result = await set_notification_pref.handler(req.model_dump(exclude_none=True))
    return {"message": result["content"][0]["text"]}


# ── Fitness log ───────────────────────────────────────────────────────────────

@app.get("/api/fitness")
async def fitness_log(user_id: int = Depends(get_current_user), period: str = Query("week")):
    from agent.tools.fitness import get_fitness_summary
    result = await get_fitness_summary.handler({"period": period, "user_id": user_id})
    return {"summary": result["content"][0]["text"]}


# ── Mood log ──────────────────────────────────────────────────────────────────

class MoodRequest(BaseModel):
    user_id: int = 1
    mood_score: int | None = None
    energy: str | None = None
    emotions: list[str] | None = None
    context: str = "general"
    notes: str | None = None


@app.post("/api/mood")
async def log_mood(req: MoodRequest, _: int = Depends(get_current_user)):
    emotions_json = json.dumps(req.emotions or [])
    await execute(
        "INSERT INTO mood_log (user_id, mood_score, energy, emotions, context, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (req.user_id, req.mood_score, req.energy, emotions_json, req.context, req.notes),
    )
    return {"ok": True, "message": "Mood logged."}


@app.get("/api/mood")
async def get_mood(user_id: int = Depends(get_current_user), period: str = Query("week")):
    days = 7 if period == "week" else 30
    rows = await execute(
        "SELECT id, logged_at, mood_score, energy, emotions, context, notes "
        "FROM mood_log WHERE user_id = ? AND logged_at >= datetime('now', ? || ' days') "
        "ORDER BY logged_at DESC LIMIT 50",
        (user_id, f"-{days}"),
    )
    return {"entries": [dict(r) for r in rows]}


@app.get("/api/today/summary")
async def today_summary(user_id: int = Depends(get_current_user)):
    today = date.today().isoformat()
    fitness = await execute(
        "SELECT COUNT(*) as c FROM fitness_log WHERE user_id = ? AND date = ?",
        (user_id, today),
    )
    mood = await execute(
        "SELECT COUNT(*) as c FROM mood_log WHERE user_id = ? AND DATE(logged_at) = ?",
        (user_id, today),
    )
    bible = await execute(
        "SELECT COUNT(*) as c FROM bible_reading WHERE user_id = ? AND date = ?",
        (user_id, today),
    )
    has_logs = (fitness[0]["c"] + mood[0]["c"] + bible[0]["c"]) > 0
    return {"has_logs": has_logs, "date": today}


# ── User features ────────────────────────────────────────────────────────────

FEATURE_LABELS = {
    "workout_logging": "Workout Logging",
    "meal_logging": "Meal Logging",
    "recipe_planning": "Recipe Planning",
    "bible_reading": "Bible Reading",
    "schedule": "Daily Schedule",
    "tasks": "Tasks & Goals",
    "nutrition_insights": "Nutrition Insights",
    "cycle_tracking": "Cycle Tracking",
    "partner_health_awareness": "Partner Health Awareness",
}


@app.get("/api/users/{user_id}/features")
async def get_features(user_id: int, _: int = Depends(get_current_user)):
    rows = await execute(
        "SELECT feature, enabled FROM user_features WHERE user_id = ? ORDER BY feature",
        (user_id,),
    )
    features = {r["feature"]: bool(r["enabled"]) for r in rows}
    # Ensure all known features are represented
    result = [
        {"feature": f, "label": label, "enabled": features.get(f, True)}
        for f, label in FEATURE_LABELS.items()
    ]
    return {"features": result}


class FeatureUpdate(BaseModel):
    feature: str
    enabled: bool


@app.post("/api/users/{user_id}/features")
async def update_feature(user_id: int, req: FeatureUpdate, _: int = Depends(get_current_user)):
    await execute(
        "INSERT INTO user_features (user_id, feature, enabled) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, feature) DO UPDATE SET enabled = excluded.enabled",
        (user_id, req.feature, int(req.enabled)),
    )
    return {"ok": True}


# ── Privacy / Sharing ─────────────────────────────────────────────────────────

SHARE_CATEGORIES = {
    "fitness_log":    "Workouts & Fitness",
    "meal_log":       "Meals & Nutrition",
    "mood_log":       "Mood & Emotions",
    "bible_reading":  "Bible Reading",
    "cycle_tracking": "Cycle Tracking",
    "schedule":       "Daily Schedule",
    "tasks":          "Tasks & Goals",
}


@app.get("/api/users/{owner_id}/sharing")
async def get_sharing(owner_id: int, _: int = Depends(get_current_user)):
    others = await execute(
        "SELECT id, name FROM users WHERE id != ? ORDER BY id", (owner_id,)
    )
    rows = await execute(
        "SELECT target_user_id, data_category, shared FROM sharing_permissions WHERE owner_user_id = ?",
        (owner_id,),
    )
    perm_map = {(r["target_user_id"], r["data_category"]): bool(r["shared"]) for r in rows}

    result = []
    for other in others:
        cats = [
            {"category": k, "label": v, "shared": perm_map.get((other["id"], k), False)}
            for k, v in SHARE_CATEGORIES.items()
        ]
        result.append({"user_id": other["id"], "user_name": other["name"], "categories": cats})
    return {"sharing": result}


class SharingUpdate(BaseModel):
    target_user_id: int
    data_category: str
    shared: bool


@app.post("/api/users/{owner_id}/sharing")
async def update_sharing(owner_id: int, req: SharingUpdate, _: int = Depends(get_current_user)):
    if req.data_category not in SHARE_CATEGORIES:
        return JSONResponse({"error": "Unknown category"}, status_code=400)
    await execute(
        "INSERT INTO sharing_permissions (owner_user_id, target_user_id, data_category, shared, updated_at) "
        "VALUES (?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(owner_user_id, target_user_id, data_category) "
        "DO UPDATE SET shared = excluded.shared, updated_at = excluded.updated_at",
        (owner_id, req.target_user_id, req.data_category, int(req.shared)),
    )
    return {"ok": True}


@app.get("/api/users/{user_id}/calorie-targets")
async def get_calorie_targets(user_id: int, _: int = Depends(get_current_user)):
    keys = ["calorie_target", "protein_target_g", "carbs_target_g", "fat_target_g"]
    rows = await execute(
        f"SELECT key, value FROM profile WHERE user_id = ? AND key IN ({','.join(['?']*len(keys))})",
        (user_id, *keys)
    )
    targets = {r["key"]: int(r["value"]) for r in rows if r["value"]}
    return {"targets": targets}


class CalorieTargetRequest(BaseModel):
    calorie_target: int | None = None
    protein_target_g: int | None = None
    carbs_target_g: int | None = None
    fat_target_g: int | None = None


@app.post("/api/users/{user_id}/calorie-targets")
async def set_calorie_targets(user_id: int, req: CalorieTargetRequest, _: int = Depends(get_current_user)):
    fields = {"calorie_target": req.calorie_target, "protein_target_g": req.protein_target_g,
              "carbs_target_g": req.carbs_target_g, "fat_target_g": req.fat_target_g}
    for key, val in fields.items():
        if val is not None:
            await execute(
                "INSERT INTO profile (user_id, key, value) VALUES (?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                (user_id, key, str(val))
            )
    return {"ok": True}


# ── Adaptive insights ─────────────────────────────────────────────────────────

import anthropic as _anthropic

_insights_cache: dict[int, tuple[float, list]] = {}  # user_id → (timestamp, insights)


@app.get("/api/insights")
async def get_insights(user_id: int = Depends(get_current_user)):
    import time

    # Cache for 30 minutes
    cached = _insights_cache.get(user_id)
    if cached and time.time() - cached[0] < 1800:
        return {"insights": cached[1]}

    # Check which insight types are suppressed (dismissed 3+ times in last 7 days)
    suppressed = set()
    dismissed_rows = await execute(
        "SELECT insight_type, COUNT(*) as cnt FROM insight_dismissals "
        "WHERE user_id = ? AND dismissed_at >= datetime('now', '-7 days') "
        "GROUP BY insight_type HAVING cnt >= 3",
        (user_id,),
    )
    suppressed = {r["insight_type"] for r in dismissed_rows}

    # Gather recent activity data
    recent_fitness = await execute(
        "SELECT date, log_type, activity, duration_minutes, calories, details "
        "FROM fitness_log WHERE user_id = ? AND date >= date('now', '-3 days') "
        "ORDER BY date DESC LIMIT 10",
        (user_id,),
    )
    recent_meals = await execute(
        "SELECT date, activity, calories, details FROM fitness_log "
        "WHERE user_id = ? AND log_type = 'meal' AND date >= date('now', '-2 days') "
        "ORDER BY date DESC LIMIT 8",
        (user_id,),
    )
    recent_bible = await execute(
        "SELECT date, book, chapter_start, chapter_end FROM bible_reading "
        "WHERE user_id = ? AND date >= date('now', '-3 days') ORDER BY date DESC LIMIT 5",
        (user_id,),
    )
    sched_completion = await execute(
        "SELECT SUM(completed) as done, COUNT(*) as total "
        "FROM schedule_blocks sb JOIN schedules s ON sb.schedule_id = s.id "
        "WHERE s.date = date('now', '-1 day')",
    )

    fitness_summary = "\n".join(
        f"- {r['date']}: {r['log_type']} — {r['activity'] or ''} {r['duration_minutes'] or ''}min {r['calories'] or ''}kcal {r['details'] or ''}"
        for r in recent_fitness
    ) or "No fitness activity in last 3 days."

    meal_summary = "\n".join(
        f"- {r['date']}: {r['activity'] or ''} {r['calories'] or ''}kcal {r['details'] or ''}"
        for r in recent_meals
    ) or "No meals logged in last 2 days."

    bible_summary = "\n".join(
        f"- {r['date']}: {r['book']} ch.{r['chapter_start']}–{r['chapter_end'] or r['chapter_start']}"
        for r in recent_bible
    ) or "No Bible reading logged in last 3 days."

    comp = dict(sched_completion[0]) if sched_completion else {}
    done = comp.get("done") or 0
    total = comp.get("total") or 0
    sched_pct = round(100 * done / total) if total else None

    suppressed_note = f"Do NOT generate insights of these types (user dismissed them): {', '.join(suppressed)}." if suppressed else ""

    prompt = f"""You are a supportive life coach reviewing recent activity data. Generate 1–3 short, warm, actionable insights for this user. Each insight should be a single sentence or two — concise, encouraging, not preachy.

Recent fitness & workouts:
{fitness_summary}

Recent meals:
{meal_summary}

Recent Bible reading:
{bible_summary}

Yesterday's schedule completion: {f"{sched_pct}% ({done}/{total} blocks)" if sched_pct is not None else "No schedule data."}

{suppressed_note}

Respond ONLY with a JSON array of objects, each with:
- "type": short snake_case category (e.g. "exercise", "nutrition", "bible", "schedule", "hydration")
- "message": the insight text (1-2 sentences, warm tone)
- "priority": 1 (high) to 3 (low)

Example: [{{"type":"exercise","message":"You haven't logged a workout in 2 days — even a 20-minute walk counts!","priority":2}}]

Return [] if everything looks great and there's nothing to mention."""

    try:
        client = _anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        from agent.usage import log_usage
        await log_usage("claude-haiku-4-5-20251001",
                        response.usage.input_tokens, response.usage.output_tokens, "insights")
        raw = response.content[0].text.strip()
        # Extract JSON array
        start = raw.find("[")
        end = raw.rfind("]") + 1
        insights = json.loads(raw[start:end]) if start >= 0 else []
        # Filter suppressed types
        insights = [i for i in insights if i.get("type") not in suppressed]
    except Exception:
        insights = []

    _insights_cache[user_id] = (time.time(), insights)
    return {"insights": insights}


class DismissInsight(BaseModel):
    user_id: int = 1
    insight_type: str


@app.post("/api/insights/dismiss")
async def dismiss_insight(req: DismissInsight, _: int = Depends(get_current_user)):
    await execute(
        "INSERT INTO insight_dismissals (user_id, insight_type) VALUES (?, ?)",
        (req.user_id, req.insight_type),
    )
    # Invalidate cache
    _insights_cache.pop(req.user_id, None)
    return {"ok": True}


# ── Calendar events (Radicale) ────────────────────────────────────────────────

@app.get("/api/calendar/events")
async def calendar_events(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD inclusive"),
    user_id: int = Depends(get_current_user),
):
    """Return calendar events from Radicale for the given date range."""
    import caldav

    slug = await _get_cal_slug(user_id)

    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)

    def _fetch_events():
        client = caldav.DAVClient(url=RADICALE_URL)
        cal = client.calendar(url=f"{RADICALE_URL}/{slug}/calendar/")
        # Fetch all events and filter by date in Python to avoid caldav search quirks
        return cal.events()

    try:
        import asyncio
        raw_events = await asyncio.to_thread(_fetch_events)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    events = []
    for ev in raw_events:
        try:
            v = ev.vobject_instance.vevent
            summary = v.summary.value if hasattr(v, "summary") else "(no title)"
            uid = v.uid.value if hasattr(v, "uid") else None
            dt_start = v.dtstart.value
            dt_end = v.dtend.value if hasattr(v, "dtend") else dt_start

            # Normalise to naive local time strings
            if isinstance(dt_start, datetime):
                dt_start = dt_start.replace(tzinfo=None)
                dt_end = dt_end.replace(tzinfo=None) if isinstance(dt_end, datetime) else datetime.combine(dt_end, datetime.min.time())
                event_date = dt_start.date()
                day = dt_start.strftime("%Y-%m-%d")
                start_str = dt_start.strftime("%H:%M")
                end_str = dt_end.strftime("%H:%M")
                all_day = False
            else:
                # date-only (all-day event)
                event_date = dt_start if isinstance(dt_start, date) else date.fromisoformat(str(dt_start)[:10])
                day = event_date.isoformat()
                start_str = "00:00"
                end_str = "23:59"
                all_day = True

            # Filter to requested date range
            if not (start_date <= event_date <= end_date):
                continue

            # Detect recurrence
            vcal = ev.vobject_instance
            recurring = hasattr(vcal.vevent, "rrule")

            events.append({
                "uid": uid,
                "title": summary,
                "date": day,
                "start": start_str,
                "end": end_str,
                "all_day": all_day,
                "recurring": recurring,
            })
        except Exception:
            continue

    events.sort(key=lambda e: (e["date"], e["start"]))
    return {"events": events}


class CalendarEventRequest(BaseModel):
    title: str
    date: str          # YYYY-MM-DD
    start_time: str    # HH:MM
    end_time: str      # HH:MM
    uid: str | None = None  # if provided, used as the event UID (for create)


def _build_ical(title: str, start: datetime, end: datetime, uid: str) -> str:
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//nertia//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}\r\n"
        f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}\r\n"
        f"SUMMARY:{title}\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )


def _parse_cal_dt(d: str, t: str) -> datetime:
    return datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")


@app.post("/api/calendar/events")
async def create_calendar_event(req: CalendarEventRequest, user_id: int = Depends(get_current_user)):
    import caldav, uuid as _uuid, asyncio
    slug = await _get_cal_slug(user_id)
    uid = req.uid or str(_uuid.uuid4())
    start = _parse_cal_dt(req.date, req.start_time)
    end = _parse_cal_dt(req.date, req.end_time)
    ical = _build_ical(req.title, start, end, uid)

    def _create():
        client = caldav.DAVClient(url=RADICALE_URL)
        cal = client.calendar(url=f"{RADICALE_URL}/{slug}/calendar/")
        cal.add_event(ical)

    try:
        await asyncio.to_thread(_create)
        return {"uid": uid, "title": req.title, "date": req.date,
                "start": req.start_time, "end": req.end_time}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/calendar/events/{event_uid}")
async def update_calendar_event(
    event_uid: str, req: CalendarEventRequest, user_id: int = Depends(get_current_user)
):
    import caldav, asyncio
    slug = await _get_cal_slug(user_id)
    start = _parse_cal_dt(req.date, req.start_time)
    end = _parse_cal_dt(req.date, req.end_time)
    new_ical = _build_ical(req.title, start, end, event_uid)

    def _update():
        client = caldav.DAVClient(url=RADICALE_URL)
        cal = client.calendar(url=f"{RADICALE_URL}/{slug}/calendar/")
        # Delete existing then re-add with same UID
        for ev in cal.events():
            try:
                if ev.vobject_instance.vevent.uid.value == event_uid:
                    ev.delete()
                    break
            except Exception:
                continue
        cal.add_event(new_ical)

    try:
        await asyncio.to_thread(_update)
        return {"uid": event_uid, "title": req.title, "date": req.date,
                "start": req.start_time, "end": req.end_time}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/calendar/events/{event_uid}")
async def delete_calendar_event(event_uid: str, user_id: int = Depends(get_current_user)):
    import caldav, asyncio
    slug = await _get_cal_slug(user_id)

    def _delete():
        client = caldav.DAVClient(url=RADICALE_URL)
        cal = client.calendar(url=f"{RADICALE_URL}/{slug}/calendar/")
        for ev in cal.events():
            try:
                if ev.vobject_instance.vevent.uid.value == event_uid:
                    ev.delete()
                    return True
            except Exception:
                continue
        return False

    try:
        found = await asyncio.to_thread(_delete)
        if not found:
            raise HTTPException(status_code=404, detail="Event not found")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Static / PWA ──────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    return FileResponse(STATIC_DIR / "index.html")
