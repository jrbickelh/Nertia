#!/usr/bin/env python3
"""
Weekly review — runs Sunday evening (~20:00) via cron.

Uses Claude Sonnet to:
1. Analyse the week's completion data
2. Identify patterns and energy mismatches
3. Suggest next week's priorities
4. Send a summary notification + print full report to stdout (logged by cron)
"""
import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from db.database import init_db, execute
from agent.usage import log_usage

NTFY_URL = os.environ.get("NTFY_URL", "http://localhost:8080")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nertia")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")


async def send_ntfy(title: str, message: str, priority: int = 3):
    import httpx
    headers = {"Title": title, "Priority": str(priority), "Tags": "bar_chart,calendar"}
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{NTFY_URL}/{NTFY_TOPIC}", content=message.encode(), headers=headers)


async def gather_week_data(week_start: date, week_end: date) -> dict:
    ws = week_start.isoformat()
    we = week_end.isoformat()

    # Schedule completion by day
    days = await execute(
        """
        SELECT s.date,
               COUNT(sb.id) as total_blocks,
               SUM(sb.completed) as completed_blocks,
               SUM(sb.skipped) as skipped_blocks
        FROM schedules s
        LEFT JOIN schedule_blocks sb ON sb.schedule_id = s.id
        WHERE s.date >= ? AND s.date <= ?
        GROUP BY s.date
        ORDER BY s.date
        """,
        (ws, we),
    )

    # Completion by block type
    by_type = await execute(
        """
        SELECT sb.block_type,
               COUNT(*) as total,
               SUM(sb.completed) as completed,
               SUM(sb.skipped) as skipped
        FROM schedule_blocks sb
        JOIN schedules s ON sb.schedule_id = s.id
        WHERE s.date >= ? AND s.date <= ?
        GROUP BY sb.block_type
        ORDER BY total DESC
        """,
        (ws, we),
    )

    # Tasks completed this week
    tasks_done = await execute(
        """
        SELECT t.title, b.name as bucket, t.completed_at
        FROM tasks t JOIN buckets b ON t.bucket_id = b.id
        WHERE t.status = 'done' AND t.completed_at >= ? AND t.completed_at <= ?
        ORDER BY t.completed_at
        """,
        (ws + "T00:00:00", we + "T23:59:59"),
    )

    # Overdue / deferred tasks
    overdue = await execute(
        """
        SELECT t.title, b.name as bucket, t.due_date, t.priority
        FROM tasks t JOIN buckets b ON t.bucket_id = b.id
        WHERE t.status IN ('todo', 'deferred') AND t.due_date < ?
        ORDER BY t.priority ASC, t.due_date ASC
        """,
        (date.today().isoformat(),),
    )

    # API spend this week
    spend = await execute(
        "SELECT SUM(cost_usd) as total, SUM(tokens_in + tokens_out) as tokens FROM api_usage WHERE timestamp >= ?",
        (ws,),
    )

    return {
        "days": [dict(d) for d in days],
        "by_type": [dict(b) for b in by_type],
        "tasks_done": [dict(t) for t in tasks_done],
        "overdue": [dict(o) for o in overdue],
        "api_cost": round(spend[0]["total"] or 0, 4),
        "api_tokens": spend[0]["tokens"] or 0,
    }


async def main():
    await init_db()

    today = date.today()
    # Review covers Mon–Sun of the just-completed week
    week_end = today
    week_start = today - timedelta(days=6)

    print(f"Weekly review: {week_start} → {week_end}")
    data = await gather_week_data(week_start, week_end)

    # Format data for Claude
    days_str = ""
    for d in data["days"]:
        pct = round(100 * d["completed_blocks"] / d["total_blocks"]) if d["total_blocks"] else 0
        days_str += f"  {d['date']}: {d['completed_blocks']}/{d['total_blocks']} blocks completed ({pct}%), {d['skipped_blocks']} skipped\n"
    if not days_str:
        days_str = "  (no schedule data this week)\n"

    type_str = ""
    for bt in data["by_type"]:
        pct = round(100 * bt["completed"] / bt["total"]) if bt["total"] else 0
        type_str += f"  {bt['block_type']}: {bt['completed']}/{bt['total']} ({pct}% done, {bt['skipped']} skipped)\n"

    done_str = "\n".join(f"  [{t['bucket']}] {t['title']}" for t in data["tasks_done"]) or "  (none)"
    overdue_str = "\n".join(f"  P{o['priority']} [{o['bucket']}] {o['title']} (due {o['due_date']})" for o in data["overdue"]) or "  (none)"

    # Feedback ratings from this week
    feedback_rows = await execute(
        """
        SELECT sb.block_type, sb.activity,
               f.energy_rating, f.focus_rating, f.notes
        FROM feedback f
        JOIN schedule_blocks sb ON f.block_id = sb.id
        JOIN schedules s ON sb.schedule_id = s.id
        WHERE s.date >= ? AND s.date <= ?
        ORDER BY f.created_at DESC
        """,
        (ws, we),
    )
    feedback_str = "\n".join(
        f"  [{r['block_type']}] {r['activity']}: energy={r['energy_rating']} focus={r['focus_rating']}"
        + (f" — {r['notes']}" if r['notes'] else "")
        for r in feedback_rows
    ) or "  (no ratings logged)"

    prompt = f"""You are a personal productivity coach conducting a weekly review for JR.

Week: {week_start} to {week_end}

COMPLETION BY DAY:
{days_str}
COMPLETION BY BLOCK TYPE:
{type_str}
TASKS COMPLETED THIS WEEK:
{done_str}

OVERDUE / DEFERRED TASKS:
{overdue_str}

FEEDBACK & RATINGS:
{feedback_str}

API USAGE THIS WEEK: ${data['api_cost']} ({data['api_tokens']:,} tokens)

Write a weekly review with these sections:
1. What went well (2-3 specific observations from the data)
2. Patterns to watch (block types with low completion, energy/focus mismatches)
3. Top 3 priorities for next week (based on overdue tasks and bucket balance)
4. One scheduling adjustment for next week

Be direct and specific. Use actual numbers. Under 200 words. Plain text only."""

    model = "claude-sonnet-4-6-20250116"
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = await client.messages.create(
        model=model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    await log_usage(model, response.usage.input_tokens, response.usage.output_tokens, "weekly_review")
    review = response.content[0].text.strip()

    print(f"\n=== Weekly Review ===\n{review}\n")

    # Send short version as notification (first 300 chars)
    short = review[:280] + ("…" if len(review) > 280 else "")
    await send_ntfy(f"Weekly Review — {week_start}", short, priority=3)
    print("Notification sent.")


if __name__ == "__main__":
    asyncio.run(main())
