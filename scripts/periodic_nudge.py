#!/usr/bin/env python3
"""
Periodic nudge — runs every 30 min via cron during waking hours (6:00–22:00).

Checks the current schedule block and sends a reminder when:
  - A new block has just started (within first 5 min)
  - A block is ending soon (within 10 min)
  - We're between blocks (gap in schedule)

Uses Haiku for speed and cost efficiency.
"""
import asyncio
import os
import sys
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from db.database import init_db, execute
from agent.usage import log_usage
from agent.tools.notification_prefs import is_enabled

# Map block types to notification pref types
_BLOCK_TO_PREF = {
    "meal": "meal",
    "exercise": "exercise",
    "faith": "transition",
    "deep_work": "transition",
    "shallow_work": "transition",
    "rest": "transition",
    "personal": "transition",
    "admin": "transition",
}

NTFY_URL = os.environ.get("NTFY_URL", "http://localhost:8080")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nertia")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")

_BLOCK_TYPE_EMOJI = {
    "deep_work":    "brain",
    "shallow_work": "pencil",
    "exercise":     "muscle",
    "meal":         "fork_and_knife",
    "faith":        "pray",
    "rest":         "zzz",
    "personal":     "person",
    "admin":        "memo",
}


async def send_ntfy(title: str, message: str, priority: int = 3, tags: list[str] | None = None):
    import httpx
    headers: dict[str, str] = {"Title": title, "Priority": str(priority)}
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    if tags:
        headers["Tags"] = ",".join(tags)
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{NTFY_URL}/{NTFY_TOPIC}", content=message.encode(), headers=headers)


def _hm_to_minutes(hm: str) -> int:
    h, m = map(int, hm.split(":"))
    return h * 60 + m


async def main():
    await init_db()
    today = date.today().isoformat()
    now = datetime.now()
    now_minutes = now.hour * 60 + now.minute
    now_hm = now.strftime("%H:%M")

    # Get today's schedule
    sched = await execute(
        "SELECT id FROM schedules WHERE date = ? ORDER BY generated_at DESC LIMIT 1",
        (today,),
    )
    if not sched:
        print("No schedule for today — skipping nudge.")
        return

    schedule_id = sched[0]["id"]
    blocks = await execute(
        """
        SELECT id, start_time, end_time, activity, block_type, completed, skipped
        FROM schedule_blocks WHERE schedule_id = ?
        ORDER BY start_time
        """,
        (schedule_id,),
    )

    if not blocks:
        return

    current = None
    upcoming = None

    for i, b in enumerate(blocks):
        b_start = _hm_to_minutes(b["start_time"])
        b_end = _hm_to_minutes(b["end_time"])

        if b_start <= now_minutes < b_end:
            current = b
            if i + 1 < len(blocks):
                upcoming = blocks[i + 1]
            break
        elif b_start > now_minutes and not b["completed"]:
            upcoming = b
            break

    if not current and not upcoming:
        print("No active or upcoming blocks.")
        return

    # Decide whether to nudge
    should_nudge = False
    title = ""
    message = ""
    tags = []

    if current:
        b_start = _hm_to_minutes(current["start_time"])
        b_end = _hm_to_minutes(current["end_time"])
        mins_in = now_minutes - b_start
        mins_left = b_end - now_minutes
        emoji = _BLOCK_TYPE_EMOJI.get(current["block_type"], "bell")

        if current["completed"] or current["skipped"]:
            pass  # already done
        elif mins_in <= 5:
            # Block just started
            should_nudge = True
            title = f"Starting now: {current['activity']}"
            message = f"{current['start_time']}–{current['end_time']} ({b_end - b_start} min)"
            if upcoming:
                message += f"\nUp next at {upcoming['start_time']}: {upcoming['activity']}"
            tags = [emoji, "alarm_clock"]
        elif mins_left <= 10 and upcoming:
            # Wrap-up warning
            should_nudge = True
            title = f"Wrapping up in {mins_left} min"
            message = f"Current: {current['activity']}\nNext at {upcoming['start_time']}: {upcoming['activity']}"
            tags = [emoji, "hourglass"]
    elif upcoming:
        b_start = _hm_to_minutes(upcoming["start_time"])
        mins_until = b_start - now_minutes
        if mins_until <= 5:
            should_nudge = True
            emoji = _BLOCK_TYPE_EMOJI.get(upcoming["block_type"], "bell")
            title = f"Up next: {upcoming['activity']}"
            message = f"Starting at {upcoming['start_time']} ({upcoming['block_type']})"
            tags = [emoji, "alarm_clock"]

    if should_nudge:
        # Check notification prefs before sending
        block_type = (current or upcoming or {}).get("block_type", "transition")
        pref_type = _BLOCK_TO_PREF.get(block_type, "transition")
        if not await is_enabled(pref_type):
            print(f"Nudge suppressed — {pref_type} notifications disabled.")
            return
        await send_ntfy(title, message, priority=3, tags=tags)
        print(f"Nudge sent: {title}")
    else:
        print(f"No nudge needed at {now_hm}.")


if __name__ == "__main__":
    asyncio.run(main())
