#!/usr/bin/env python3
"""
Morning briefing — runs at 6:00 AM via cron.

1. Generates today's optimized schedule
2. Fetches upcoming tasks (priority 1-2)
3. Sends a concise push notification summary
4. Logs API usage
"""
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from db.database import init_db, execute
from agent.tools.schedule import generate_daily_schedule
from agent.usage import log_usage
from agent.tools.notification_prefs import is_enabled
from scripts.sync_icloud import sync as sync_icloud

NTFY_URL = os.environ.get("NTFY_URL", "http://localhost:8080")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nertia")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")


async def send_ntfy(title: str, message: str, priority: int = 3):
    import httpx
    headers = {"Title": title, "Priority": str(priority), "Tags": "calendar,sunny"}
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{NTFY_URL}/{NTFY_TOPIC}", content=message.encode(), headers=headers)


async def main():
    await init_db()

    if not await is_enabled("morning_briefing"):
        print("Morning briefing disabled — skipping.")
        return

    today = date.today().isoformat()

    # 0. Sync iCloud events into local Radicale before generating schedule
    print("Syncing iCloud calendar...")
    try:
        sync_icloud()
    except Exception as e:
        print(f"iCloud sync failed (non-fatal): {e}")

    # 1. Generate schedule (also syncs to calendar)
    print(f"Generating schedule for {today}...")
    result = await generate_daily_schedule.handler({"date": today, "sync_to_calendar": True})
    schedule_text = result["content"][0]["text"]

    # 2. Get top priority tasks
    tasks = await execute(
        """
        SELECT t.title, t.priority, b.name as bucket
        FROM tasks t JOIN buckets b ON t.bucket_id = b.id
        WHERE t.status IN ('todo', 'in_progress') AND t.priority <= 2
        ORDER BY t.priority ASC, t.created_at ASC
        LIMIT 5
        """
    )

    # 3. Build briefing with Claude (Haiku — cheap)
    model = "claude-haiku-4-5-20251001"
    task_lines = "\n".join(f"  P{r['priority']} [{r['bucket']}] {r['title']}" for r in tasks) or "  (none)"

    prompt = f"""You are a concise daily briefing assistant.

Today is {today}.

Schedule summary (first and last few blocks):
{schedule_text[:600]}

Top priority tasks:
{task_lines}

Write a 3-4 sentence morning briefing for a push notification. Be direct and energizing.
Start with the most important focus for the day. Mention 1-2 key schedule anchors.
No markdown, plain text only."""

    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = await client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    await log_usage(model, response.usage.input_tokens, response.usage.output_tokens, "morning_briefing")
    briefing = response.content[0].text.strip()

    # 4. Send notification
    user_row = await execute("SELECT name FROM users WHERE id = 1")
    user_name = user_row[0]["name"] if user_row else "there"
    await send_ntfy(f"Good morning, {user_name} — {today}", briefing, priority=4)
    print(f"Briefing sent:\n{briefing}")


if __name__ == "__main__":
    asyncio.run(main())
