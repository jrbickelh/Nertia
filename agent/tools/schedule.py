"""
Schedule tools — generate and query daily schedules stored in SQLite,
with schedule blocks optionally synced to Radicale as calendar events.
"""
import json
import os
from datetime import datetime, date, timedelta
from typing import Any

import anthropic
import caldav
from claude_agent_sdk import tool
from agent.config import PROJECT_ROOT
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from db.database import execute, execute_insert
from agent.prompts.scheduling import SCHEDULING_RULES
from agent.usage import log_usage


def _today() -> str:
    return date.today().isoformat()


def _now_hm() -> str:
    return datetime.now().strftime("%H:%M")


async def _get_context_for_date(target_date: str, user_id: int = 1) -> str:
    """Build the scheduling context string for a given date."""
    # Profile
    profile_rows = await execute("SELECT key, value FROM profile WHERE user_id = ? ORDER BY key", (user_id,))
    profile_str = "\n".join(f"  {r['key']}: {r['value']}" for r in profile_rows)

    # Active tasks by bucket, ordered by priority
    task_rows = await execute(
        """
        SELECT t.id, t.title, t.priority, t.est_minutes, t.energy_level,
               t.due_date, t.tags, b.name as bucket
        FROM tasks t JOIN buckets b ON t.bucket_id = b.id
        WHERE t.user_id = ? AND t.status IN ('todo', 'in_progress')
        ORDER BY t.priority ASC, t.created_at ASC
        LIMIT 30
        """,
        (user_id,),
    )
    task_lines = []
    for r in task_rows:
        due = f" due:{r['due_date']}" if r["due_date"] else ""
        est = f" ~{r['est_minutes']}min" if r["est_minutes"] else ""
        energy = f" [{r['energy_level']}]" if r["energy_level"] else ""
        task_lines.append(f"  #{r['id']} P{r['priority']} [{r['bucket']}] {r['title']}{energy}{due}{est}")
    tasks_str = "\n".join(task_lines) if task_lines else "  (no active tasks)"

    # Adaptation insights from recent feedback (last 4 weeks)
    since_4w = (date.today() - timedelta(days=28)).isoformat()
    insights_rows = await execute(
        """
        SELECT sb.block_type,
               COUNT(*) as total,
               SUM(sb.completed) as completed,
               SUM(sb.skipped) as skipped,
               ROUND(AVG(f.focus_rating), 1) as avg_focus
        FROM schedule_blocks sb
        JOIN schedules s ON sb.schedule_id = s.id
        LEFT JOIN feedback f ON f.block_id = sb.id
        WHERE s.date >= ? AND s.user_id = ?
        GROUP BY sb.block_type
        HAVING total >= 3
        ORDER BY (1.0 * completed / total) ASC
        """,
        (since_4w, user_id),
    )
    if insights_rows:
        insight_lines = []
        for r in insights_rows:
            pct = round(100 * (r["completed"] or 0) / r["total"]) if r["total"] else 0
            focus = f", avg focus {r['avg_focus']}/5" if r["avg_focus"] else ""
            insight_lines.append(f"  {r['block_type']}: {pct}% completion ({r['skipped']} skipped{focus})")
        insights_str = "\n".join(insight_lines)
    else:
        insights_str = "  (no feedback data yet)"

    # Routine items for this day
    try:
        _target_dow = date.fromisoformat(target_date).isoweekday()  # 1=Mon...7=Sun
        routine_rows = await execute(
            "SELECT title, start_time, end_time, block_type, days_of_week FROM routine_items "
            "WHERE user_id = ? AND enabled = 1 ORDER BY sort_order, start_time",
            (user_id,),
        )
        routine_lines = []
        for r in routine_rows:
            dow_list = [int(d) for d in r["days_of_week"].split(",") if d.strip().isdigit()]
            if _target_dow not in dow_list:
                continue
            time_range = ""
            if r["start_time"] and r["end_time"]:
                time_range = f"{r['start_time']}–{r['end_time']}  "
            elif r["start_time"]:
                time_range = f"{r['start_time']}  "
            routine_lines.append(f"  {time_range}{r['title']}  [{r['block_type']}]")
        routine_str = "\n".join(routine_lines) if routine_lines else "  (none)"
    except Exception:
        routine_str = "  (unavailable)"

    # Weather for the day
    try:
        import httpx as _httpx
        from db.database import execute as _exec2
        _profile = await _exec2("SELECT key, value FROM profile WHERE user_id = ? AND key IN ('weather_lat','weather_lon')", (user_id,))
        _pm = {r["key"]: float(r["value"]) for r in _profile}
        _lat = _pm.get("weather_lat", 41.8781)
        _lon = _pm.get("weather_lon", -87.6298)
        _url = (f"https://api.open-meteo.com/v1/forecast?latitude={_lat}&longitude={_lon}"
                f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
                f"&temperature_unit=fahrenheit&forecast_days=1&timezone=auto")
        async with _httpx.AsyncClient(timeout=5) as _c:
            _wr = (await _c.get(_url)).json()
        _d = _wr["daily"]
        from agent.tools.weather import _WMO
        weather_str = (f"  {_WMO.get(_d['weathercode'][0], '?')}, "
                       f"high {_d['temperature_2m_max'][0]}°F / low {_d['temperature_2m_min'][0]}°F, "
                       f"precip {_d['precipitation_sum'][0]} in")
    except Exception:
        weather_str = "  (unavailable)"

    # Calendar events for the target date (Apple Calendar / Radicale)
    try:
        from agent.tools.calendar import _USER_CAL_SLUG
        from datetime import timezone
        import caldav as _caldav
        _slug = _USER_CAL_SLUG.get(user_id, "jr")
        _client = _caldav.DAVClient(url="http://127.0.0.1:5232")
        _cal = _client.calendar(url=f"http://127.0.0.1:5232/{_slug}/calendar/")
        _year, _month, _day = map(int, target_date.split("-"))
        _start = datetime(_year, _month, _day, 0, 0, tzinfo=timezone.utc)
        _end = datetime(_year, _month, _day, 23, 59, tzinfo=timezone.utc)
        _events = _cal.search(start=_start, end=_end, event=True, expand=True)
        cal_lines = []
        for _ev in _events:
            _comp = _ev.icalendar_component
            _summary = str(_comp.get("SUMMARY", ""))
            # Skip blocks that were auto-generated by this app
            if _summary.endswith("]") and any(
                _summary.endswith(f"[{t}]") for t in
                ["faith","meal","rest","deep_work","shallow_work","admin","exercise","personal","calendar"]
            ):
                continue
            _dtstart = _comp.get("DTSTART")
            _dtend = _comp.get("DTEND")
            if _dtstart and _dtend:
                _s = _dtstart.dt
                _e = _dtend.dt
                if hasattr(_s, "hour"):
                    cal_lines.append(f"  {_s.strftime('%H:%M')}–{_e.strftime('%H:%M')}  {_summary}")
                else:
                    cal_lines.append(f"  (all-day)  {_summary}")
        calendar_str = "\n".join(cal_lines) if cal_lines else "  (no events)"
    except Exception as _exc:
        calendar_str = f"  (unavailable: {_exc})"

    # Supplements
    try:
        supp_rows = await execute(
            "SELECT name, dose, timing, notes FROM supplements WHERE user_id = ? AND enabled = 1 ORDER BY timing, name",
            (user_id,),
        )
        timing_labels = {
            "morning": "morning (with breakfast)",
            "with_meal": "with a meal",
            "afternoon": "afternoon",
            "evening": "evening",
            "bedtime": "at bedtime",
        }
        supp_lines = [
            f"  {r['name']}{' ' + r['dose'] if r['dose'] else ''} — {timing_labels.get(r['timing'], r['timing'])}"
            + (f" ({r['notes']})" if r["notes"] else "")
            for r in supp_rows
        ]
        supplements_str = "\n".join(supp_lines) if supp_lines else "  (none configured)"
    except Exception:
        supplements_str = "  (unavailable)"

    # Most recent mood entry (last 24h)
    try:
        mood_rows = await execute(
            "SELECT mood_score, energy, emotions, notes, logged_at FROM mood_log "
            "WHERE user_id = ? ORDER BY logged_at DESC LIMIT 1",
            (user_id,)
        )
        if mood_rows and mood_rows[0]["mood_score"]:
            mr = mood_rows[0]
            age_note = ""
            try:
                from datetime import datetime as _dt
                logged = _dt.fromisoformat(mr["logged_at"])
                hours_ago = (datetime.now() - logged).total_seconds() / 3600
                age_note = f" (logged {int(hours_ago)}h ago)"
            except Exception:
                pass
            mood_parts = [f"mood {mr['mood_score']}/10", f"energy: {mr['energy'] or '?'}"]
            if mr["emotions"]:
                try:
                    import json as _j
                    emotions = _j.loads(mr["emotions"]) if mr["emotions"].startswith("[") else [mr["emotions"]]
                    mood_parts.append(f"emotions: {', '.join(emotions)}")
                except Exception:
                    mood_parts.append(f"emotions: {mr['emotions']}")
            mood_str = "  " + ", ".join(mood_parts) + age_note
            if mr["mood_score"] <= 4 or mr["energy"] == "low":
                mood_str += "\n  NOTE: User reported low mood/energy — soften schedule, add rest blocks, reduce deep work demands"
        else:
            mood_str = "  (no recent mood logged)"
    except Exception:
        mood_str = "  (unavailable)"

    return f"""Date: {target_date}

User Profile:
{profile_str}

Recurring Routine Items (always include these at their set times):
{routine_str}

Supplements (suggest optimal reminder times within the schedule):
{supplements_str}

Weather:
{weather_str}

Existing Calendar Events (schedule AROUND these — do not duplicate them):
{calendar_str}

Active Tasks (P1=highest priority):
{tasks_str}

Recent completion patterns (adapt schedule accordingly):
{insights_str}

Recent Mood/Energy (use to calibrate schedule intensity):
{mood_str}
"""


@tool(
    "generate_daily_schedule",
    "Generate an optimized daily schedule for a given date using Claude. "
    "Saves it to the database and syncs blocks to the calendar.",
    {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD (defaults to today)"},
            "sync_to_calendar": {
                "type": "boolean",
                "default": False,
                "description": "Also push blocks as calendar events to Radicale (off by default — calendar events are read as input, not written as output)",
            },
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": [],
    },
)
async def generate_daily_schedule(args: dict[str, Any]) -> dict[str, Any]:
    target_date = args.get("date") or _today()
    sync = args.get("sync_to_calendar", False)
    user_id = args.get("user_id", 1)

    context = await _get_context_for_date(target_date, user_id)
    model = "claude-haiku-4-5-20251001"

    prompt = (
        f"{SCHEDULING_RULES}\n\n"
        f"Context:\n{context}\n\n"
        "Generate the schedule now. Return ONLY the JSON array."
    )

    aclient = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = await aclient.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    await log_usage(model, response.usage.input_tokens, response.usage.output_tokens, "schedule_generate")
    raw = response.content[0].text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        blocks = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"content": [{"type": "text", "text": f"Failed to parse schedule JSON: {e}\n\nRaw output:\n{raw}"}]}

    # Persist schedule
    schedule_id = await execute_insert(
        "INSERT INTO schedules (user_id, date, schedule_json, model_used) VALUES (?, ?, ?, ?)",
        (user_id, target_date, json.dumps(blocks), model),
    )

    # Persist blocks
    for block in blocks:
        await execute_insert(
            """
            INSERT INTO schedule_blocks
              (schedule_id, start_time, end_time, task_id, activity, block_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                schedule_id,
                block["start"],
                block["end"],
                block.get("task_id"),
                block["activity"],
                block["type"],
            ),
        )

    # Sync to Radicale calendar
    if sync:
        try:
            import uuid as uuid_mod
            from agent.tools.calendar import _USER_CAL_SLUG
            _slug = _USER_CAL_SLUG.get(user_id, "jr")
            client_cal = caldav.DAVClient(url="http://127.0.0.1:5232")
            cal = client_cal.calendar(url=f"http://127.0.0.1:5232/{_slug}/calendar/")

            year, month, day = map(int, target_date.split("-"))

            for block in blocks:
                sh, sm = map(int, block["start"].split(":"))
                eh, em = map(int, block["end"].split(":"))
                start_dt = datetime(year, month, day, sh, sm)
                end_dt = datetime(year, month, day, eh, em)
                uid = str(uuid_mod.uuid4())

                ical = (
                    "BEGIN:VCALENDAR\r\n"
                    "VERSION:2.0\r\n"
                    "PRODID:-//nertia//EN\r\n"
                    "BEGIN:VEVENT\r\n"
                    f"UID:{uid}\r\n"
                    f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}\r\n"
                    f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}\r\n"
                    f"SUMMARY:{block['activity']} [{block['type']}]\r\n"
                    "END:VEVENT\r\n"
                    "END:VCALENDAR\r\n"
                )
                cal.add_event(ical)
            cal_note = " Events synced to calendar."
        except Exception as e:
            cal_note = f" (Calendar sync failed: {e})"
    else:
        cal_note = ""

    # Format for display
    lines = [f"Schedule for {target_date}:\n"]
    for block in blocks:
        lines.append(f"  {block['start']}–{block['end']}  {block['activity']}  [{block['type']}]")

    return {"content": [{"type": "text", "text": "\n".join(lines) + f"\n\nSaved as schedule #{schedule_id}.{cal_note}"}]}


@tool(
    "get_todays_schedule",
    "Retrieve today's most recently generated schedule.",
    {
        "type": "object",
        "properties": {
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": [],
    },
)
async def get_todays_schedule(args: dict[str, Any]) -> dict[str, Any]:
    today = _today()
    user_id = args.get("user_id", 1)
    rows = await execute(
        "SELECT id, generated_at, schedule_json FROM schedules WHERE user_id = ? AND date = ? ORDER BY generated_at DESC LIMIT 1",
        (user_id, today),
    )
    if not rows:
        return {"content": [{"type": "text", "text": f"No schedule found for today ({today}). Use generate_daily_schedule to create one."}]}

    schedule = rows[0]
    blocks = json.loads(schedule["schedule_json"])

    # Get block completion status from DB
    block_rows = await execute(
        "SELECT start_time, end_time, activity, block_type, completed, skipped FROM schedule_blocks WHERE schedule_id = ? ORDER BY start_time",
        (schedule["id"],),
    )

    if block_rows:
        lines = [f"Today's schedule (generated {schedule['generated_at']}):\n"]
        for b in block_rows:
            status = " ✓" if b["completed"] else (" ✗" if b["skipped"] else "")
            lines.append(f"  {b['start_time']}–{b['end_time']}  {b['activity']}  [{b['block_type']}]{status}")
    else:
        lines = [f"Today's schedule (generated {schedule['generated_at']}):\n"]
        for block in blocks:
            lines.append(f"  {block['start']}–{block['end']}  {block['activity']}  [{block['type']}]")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "get_next_block",
    "What should I be doing right now? Returns the current or next schedule block.",
    {
        "type": "object",
        "properties": {
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": [],
    },
)
async def get_next_block(args: dict[str, Any]) -> dict[str, Any]:
    today = _today()
    now = _now_hm()
    user_id = args.get("user_id", 1)

    rows = await execute(
        "SELECT id FROM schedules WHERE user_id = ? AND date = ? ORDER BY generated_at DESC LIMIT 1",
        (user_id, today),
    )
    if not rows:
        return {"content": [{"type": "text", "text": "No schedule for today. Run generate_daily_schedule first."}]}

    schedule_id = rows[0]["id"]
    blocks = await execute(
        "SELECT id, start_time, end_time, activity, block_type, completed, skipped FROM schedule_blocks WHERE schedule_id = ? ORDER BY start_time",
        (schedule_id,),
    )

    # Find current block (now falls within start–end)
    for b in blocks:
        if b["start_time"] <= now <= b["end_time"]:
            status = "COMPLETED" if b["completed"] else ("SKIPPED" if b["skipped"] else "ACTIVE")
            return {"content": [{"type": "text", "text": f"Current block ({now}): {b['start_time']}–{b['end_time']}  {b['activity']}  [{b['block_type']}]  [{status}]"}]}

    # Find next upcoming block
    for b in blocks:
        if b["start_time"] > now and not b["completed"]:
            mins = int((datetime.strptime(b["start_time"], "%H:%M") - datetime.strptime(now, "%H:%M")).total_seconds() / 60)
            return {"content": [{"type": "text", "text": f"Next block in {mins} min: {b['start_time']}–{b['end_time']}  {b['activity']}  [{b['block_type']}]"}]}

    return {"content": [{"type": "text", "text": f"No upcoming blocks for today ({now}). Day is complete or schedule not generated."}]}


@tool(
    "adjust_schedule",
    "Re-generate remaining schedule blocks after a disruption.",
    {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "What changed or went wrong"},
            "current_time": {"type": "string", "description": "HH:MM (defaults to now)"},
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": ["reason"],
    },
)
async def adjust_schedule(args: dict[str, Any]) -> dict[str, Any]:
    today = _today()
    now = args.get("current_time") or _now_hm()
    reason = args["reason"]
    user_id = args.get("user_id", 1)

    rows = await execute(
        "SELECT id, schedule_json FROM schedules WHERE user_id = ? AND date = ? ORDER BY generated_at DESC LIMIT 1",
        (user_id, today),
    )
    if not rows:
        return {"content": [{"type": "text", "text": "No schedule for today to adjust."}]}

    schedule_id = rows[0]["id"]
    orig_blocks = json.loads(rows[0]["schedule_json"])

    # Completed blocks
    done_blocks = await execute(
        "SELECT activity, block_type FROM schedule_blocks WHERE schedule_id = ? AND (completed = 1 OR start_time < ?) ORDER BY start_time",
        (schedule_id, now),
    )
    done_str = "\n".join(f"  {b['activity']} [{b['block_type']}]" for b in done_blocks) or "  (none)"

    context = await _get_context_for_date(today, user_id)
    model = "claude-haiku-4-5-20251001"

    prompt = (
        f"{SCHEDULING_RULES}\n\n"
        f"Context:\n{context}\n\n"
        f"ADJUSTMENT NEEDED:\n"
        f"Current time: {now}\n"
        f"Reason for adjustment: {reason}\n"
        f"Already completed or past:\n{done_str}\n\n"
        f"Generate ONLY the remaining blocks from {now} to 22:00. Return ONLY the JSON array."
    )

    aclient = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = await aclient.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    await log_usage(model, response.usage.input_tokens, response.usage.output_tokens, "schedule_adjust")
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        new_blocks = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"content": [{"type": "text", "text": f"Failed to parse adjusted schedule: {e}\n\n{raw}"}]}

    # Remove old future blocks from DB and add new ones
    await execute(
        "DELETE FROM schedule_blocks WHERE schedule_id = ? AND start_time >= ? AND completed = 0 AND skipped = 0",
        (schedule_id, now),
    )
    for block in new_blocks:
        await execute_insert(
            "INSERT INTO schedule_blocks (schedule_id, start_time, end_time, task_id, activity, block_type) VALUES (?, ?, ?, ?, ?, ?)",
            (schedule_id, block["start"], block["end"], block.get("task_id"), block["activity"], block["type"]),
        )

    lines = [f"Adjusted schedule from {now} (reason: {reason}):\n"]
    for block in new_blocks:
        lines.append(f"  {block['start']}–{block['end']}  {block['activity']}  [{block['type']}]")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


ALL_SCHEDULE_TOOLS = [generate_daily_schedule, get_todays_schedule, get_next_block, adjust_schedule]
