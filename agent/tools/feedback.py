"""
Feedback tools — log how schedule blocks actually went, query completion
patterns, and generate adaptation insights that improve future schedules.
"""
import os
from datetime import date, timedelta
from typing import Any

import anthropic
from claude_agent_sdk import tool
from agent.config import PROJECT_ROOT
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from db.database import execute, execute_insert
from agent.usage import log_usage


@tool(
    "log_block_feedback",
    "Record how a schedule block actually went. Use after completing or skipping a block.",
    {
        "type": "object",
        "properties": {
            "block_id": {"type": "integer", "description": "ID from schedule_blocks table"},
            "completed": {"type": "boolean", "description": "Did you complete it?"},
            "skipped": {"type": "boolean", "description": "Did you skip it entirely?"},
            "energy_rating": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Your energy level (1=drained, 5=great)"},
            "focus_rating": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Your focus quality (1=scattered, 5=flow state)"},
            "actual_start": {"type": "string", "description": "HH:MM when you actually started"},
            "actual_end": {"type": "string", "description": "HH:MM when you actually finished"},
            "notes": {"type": "string"},
        },
        "required": ["block_id"],
    },
)
async def log_block_feedback(args: dict[str, Any]) -> dict[str, Any]:
    block_id = args["block_id"]

    rows = await execute("SELECT id, activity FROM schedule_blocks WHERE id = ?", (block_id,))
    if not rows:
        return {"content": [{"type": "text", "text": f"Block #{block_id} not found."}]}

    completed = args.get("completed", False)
    skipped = args.get("skipped", False)

    # Update block status
    await execute(
        "UPDATE schedule_blocks SET completed = ?, skipped = ? WHERE id = ?",
        (int(completed), int(skipped), block_id),
    )

    # Insert feedback row if ratings or notes provided
    if any(k in args for k in ("energy_rating", "focus_rating", "actual_start", "actual_end", "notes")):
        await execute_insert(
            """
            INSERT INTO feedback (date, block_id, actual_start, actual_end, energy_rating, focus_rating, notes)
            VALUES (date('now'), ?, ?, ?, ?, ?, ?)
            """,
            (
                block_id,
                args.get("actual_start"),
                args.get("actual_end"),
                args.get("energy_rating"),
                args.get("focus_rating"),
                args.get("notes"),
            ),
        )

    status = "completed" if completed else ("skipped" if skipped else "updated")
    return {"content": [{"type": "text", "text": f"Block #{block_id} \"{rows[0]['activity']}\" marked as {status}."}]}


@tool(
    "get_completion_stats",
    "Get schedule completion rates, filterable by period and grouping.",
    {
        "type": "object",
        "properties": {
            "period": {"type": "string", "enum": ["week", "month", "all"], "default": "week"},
            "group_by": {"type": "string", "enum": ["block_type", "day", "bucket"], "default": "block_type"},
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": [],
    },
)
async def get_completion_stats(args: dict[str, Any]) -> dict[str, Any]:
    period = args.get("period", "week")
    group_by = args.get("group_by", "block_type")
    user_id = args.get("user_id", 1)

    days = {"week": 7, "month": 30, "all": 3650}[period]
    since = date.today() - timedelta(days=days)

    if group_by == "block_type":
        rows = await execute(
            """
            SELECT sb.block_type as label,
                   COUNT(*) as total,
                   SUM(sb.completed) as completed,
                   SUM(sb.skipped) as skipped,
                   ROUND(AVG(f.energy_rating), 1) as avg_energy,
                   ROUND(AVG(f.focus_rating), 1) as avg_focus
            FROM schedule_blocks sb
            JOIN schedules s ON sb.schedule_id = s.id
            LEFT JOIN feedback f ON f.block_id = sb.id
            WHERE s.date >= ? AND s.user_id = ?
            GROUP BY sb.block_type
            ORDER BY total DESC
            """,
            (since.isoformat(), user_id),
        )
    elif group_by == "day":
        rows = await execute(
            """
            SELECT s.date as label,
                   COUNT(*) as total,
                   SUM(sb.completed) as completed,
                   SUM(sb.skipped) as skipped,
                   NULL as avg_energy,
                   NULL as avg_focus
            FROM schedule_blocks sb
            JOIN schedules s ON sb.schedule_id = s.id
            WHERE s.date >= ? AND s.user_id = ?
            GROUP BY s.date
            ORDER BY s.date DESC
            LIMIT 14
            """,
            (since.isoformat(), user_id),
        )
    else:  # bucket
        rows = await execute(
            """
            SELECT b.name as label,
                   COUNT(sb.id) as total,
                   SUM(sb.completed) as completed,
                   SUM(sb.skipped) as skipped,
                   NULL as avg_energy,
                   NULL as avg_focus
            FROM schedule_blocks sb
            JOIN schedules s ON sb.schedule_id = s.id
            LEFT JOIN tasks t ON sb.task_id = t.id
            LEFT JOIN buckets b ON t.bucket_id = b.id
            WHERE s.date >= ? AND s.user_id = ? AND b.name IS NOT NULL
            GROUP BY b.name
            ORDER BY total DESC
            """,
            (since.isoformat(), user_id),
        )

    if not rows:
        return {"content": [{"type": "text", "text": f"No data for the past {period}."}]}

    lines = [f"Completion stats — past {period} (grouped by {group_by}):\n"]
    for r in rows:
        total = r["total"] or 0
        done = r["completed"] or 0
        skip = r["skipped"] or 0
        pct = round(100 * done / total) if total else 0
        energy = f"  energy:{r['avg_energy']}" if r["avg_energy"] else ""
        focus = f"  focus:{r['avg_focus']}" if r["avg_focus"] else ""
        lines.append(f"  {r['label']}: {pct}% done ({done}/{total}, {skip} skipped){energy}{focus}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "get_adaptation_insights",
    "Analyze completion patterns and return actionable scheduling insights. "
    "Uses Sonnet to identify what's working and what isn't.",
    {
        "type": "object",
        "properties": {
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": [],
    },
)
async def get_adaptation_insights(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)
    # Gather data
    since_4w = (date.today() - timedelta(days=28)).isoformat()

    by_type = await execute(
        """
        SELECT sb.block_type,
               COUNT(*) as total,
               SUM(sb.completed) as completed,
               SUM(sb.skipped) as skipped,
               ROUND(AVG(f.energy_rating), 1) as avg_energy,
               ROUND(AVG(f.focus_rating), 1) as avg_focus
        FROM schedule_blocks sb
        JOIN schedules s ON sb.schedule_id = s.id
        LEFT JOIN feedback f ON f.block_id = sb.id
        WHERE s.date >= ? AND s.user_id = ?
        GROUP BY sb.block_type ORDER BY total DESC
        """,
        (since_4w, user_id),
    )

    by_time = await execute(
        """
        SELECT
            CASE
                WHEN sb.start_time < '09:00' THEN 'early_morning (before 9)'
                WHEN sb.start_time < '12:00' THEN 'late_morning (9-12)'
                WHEN sb.start_time < '14:30' THEN 'afternoon_dip (12-14:30)'
                WHEN sb.start_time < '17:00' THEN 'pm_peak (14:30-17)'
                ELSE 'evening (after 17)'
            END as window,
            COUNT(*) as total,
            SUM(sb.completed) as completed,
            SUM(sb.skipped) as skipped,
            ROUND(AVG(f.focus_rating), 1) as avg_focus
        FROM schedule_blocks sb
        JOIN schedules s ON sb.schedule_id = s.id
        LEFT JOIN feedback f ON f.block_id = sb.id
        WHERE s.date >= ? AND s.user_id = ?
        GROUP BY window ORDER BY total DESC
        """,
        (since_4w, user_id),
    )

    recent_notes = await execute(
        """
        SELECT f.notes, f.energy_rating, f.focus_rating, sb.activity, sb.block_type
        FROM feedback f
        JOIN schedule_blocks sb ON f.block_id = sb.id
        JOIN schedules s ON sb.schedule_id = s.id
        WHERE f.notes IS NOT NULL AND f.created_at >= ? AND s.user_id = ?
        ORDER BY f.created_at DESC LIMIT 10
        """,
        (since_4w, user_id),
    )

    if not by_type and not by_time:
        return {"content": [{"type": "text", "text": "Not enough data yet — log some block feedback first."}]}

    # Format for Claude
    def fmt(rows):
        out = []
        for r in rows:
            total = r["total"] or 0
            done = r["completed"] or 0
            skip = r["skipped"] or 0
            pct = round(100 * done / total) if total else 0
            extra = ""
            if r.get("avg_energy"): extra += f" energy:{r['avg_energy']}"
            if r.get("avg_focus"):  extra += f" focus:{r['avg_focus']}"
            out.append(f"  {r[list(r.keys())[0]]}: {pct}% ({done}/{total}, {skip} skipped){extra}")
        return "\n".join(out)

    notes_str = "\n".join(
        f"  [{r['block_type']}] {r['activity']}: e={r['energy_rating']} f={r['focus_rating']} — {r['notes']}"
        for r in recent_notes
    ) or "  (none)"

    user_label = f"User {user_id}"
    prompt = f"""Analyze this scheduling data for {user_label} (past 4 weeks) and produce 3-5 specific,
actionable insights to improve future schedule generation.

Completion by block type:
{fmt(by_type)}

Completion by time window:
{fmt(by_time)}

Recent feedback notes:
{notes_str}

Format your response as a numbered list. Each insight should:
- Reference specific numbers from the data
- State what pattern you see
- Give a concrete scheduling recommendation

Keep it under 200 words. Plain text, no markdown."""

    model = "claude-sonnet-4-6-20250116"
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = await client.messages.create(
        model=model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    await log_usage(model, response.usage.input_tokens, response.usage.output_tokens, "adaptation_insights")
    insights = response.content[0].text.strip()

    return {"content": [{"type": "text", "text": f"Adaptation insights (last 4 weeks):\n\n{insights}"}]}


ALL_FEEDBACK_TOOLS = [log_block_feedback, get_completion_stats, get_adaptation_insights]
