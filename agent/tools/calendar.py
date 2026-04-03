"""
CalDAV tools — talk to Radicale running on localhost:5232.

All datetimes are stored as local time (no TZ offset) because Radicale is
self-hosted and the RPi is in JR's timezone. The caldav library handles
the iCalendar serialisation.
"""
import uuid
from datetime import datetime, timedelta, date, timezone
from typing import Any

import caldav
from claude_agent_sdk import tool

RADICALE_URL = "http://127.0.0.1:5232"

# Map user_id → Radicale calendar path slug
_USER_CAL_SLUG: dict[int, str] = {1: "jr", 2: "alex"}


def _get_calendar(user_id: int = 1) -> caldav.Calendar:
    slug = _USER_CAL_SLUG.get(user_id, "jr")
    client = caldav.DAVClient(url=RADICALE_URL)
    return client.calendar(url=f"{RADICALE_URL}/{slug}/calendar/")


def _as_utc(dt: datetime) -> datetime:
    """Make a naive datetime timezone-aware (assume UTC/local equivalence for caldav search)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_dt(s: str) -> datetime:
    """Parse ISO datetime string (YYYY-MM-DDTHH:MM or YYYY-MM-DD HH:MM)."""
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s!r}")


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


@tool(
    "add_event",
    "Create a calendar event in Radicale. Returns the event UID.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start_datetime": {"type": "string", "description": "YYYY-MM-DDTHH:MM"},
            "end_datetime": {"type": "string", "description": "YYYY-MM-DDTHH:MM"},
            "description": {"type": "string"},
            "uid": {"type": "string", "description": "Optional: reuse an existing UID to update an event"},
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": ["title", "start_datetime", "end_datetime"],
    },
)
async def add_event(args: dict[str, Any]) -> dict[str, Any]:
    try:
        cal = _get_calendar(args.get("user_id", 1))
        start = _parse_dt(args["start_datetime"])
        end = _parse_dt(args["end_datetime"])
        event_uid = args.get("uid") or str(uuid.uuid4())

        ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//nertia//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{event_uid}\r\n"
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"SUMMARY:{args['title']}\r\n"
        )
        if desc := args.get("description"):
            ical += f"DESCRIPTION:{desc}\r\n"
        ical += "END:VEVENT\r\nEND:VCALENDAR\r\n"

        cal.add_event(ical)
        return {"content": [{"type": "text", "text": f"Event created (UID: {event_uid}): {args['title']} {start.strftime('%Y-%m-%d %H:%M')}–{end.strftime('%H:%M')}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error creating event: {e}"}]}


@tool(
    "list_events",
    "List calendar events for a date range.",
    {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD (inclusive)"},
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": ["start_date", "end_date"],
    },
)
async def list_events(args: dict[str, Any]) -> dict[str, Any]:
    try:
        cal = _get_calendar(args.get("user_id", 1))
        start = datetime.combine(_parse_date(args["start_date"]), datetime.min.time())
        end = datetime.combine(_parse_date(args["end_date"]), datetime.max.time().replace(microsecond=0))

        events = cal.search(start=_as_utc(start), end=_as_utc(end), event=True)

        if not events:
            return {"content": [{"type": "text", "text": f"No events from {args['start_date']} to {args['end_date']}."}]}

        lines = []
        def _sort_key(ev):
            val = ev.vobject_instance.vevent.dtstart.value
            if isinstance(val, datetime):
                return val.replace(tzinfo=None)
            return datetime.combine(val, datetime.min.time())

        for ev in sorted(events, key=_sort_key):
            v = ev.vobject_instance.vevent
            dt_start = v.dtstart.value
            dt_end = v.dtend.value
            if isinstance(dt_start, datetime):
                dt_start = dt_start.replace(tzinfo=None)
                dt_end = dt_end.replace(tzinfo=None)
            uid = v.uid.value if hasattr(v, "uid") else "?"
            summary = v.summary.value if hasattr(v, "summary") else "(no title)"
            if isinstance(dt_start, datetime):
                lines.append(f"{dt_start.strftime('%Y-%m-%d %H:%M')}–{dt_end.strftime('%H:%M')}  {summary}  [uid:{uid}]")
            else:
                lines.append(f"{dt_start}  {summary} (all-day)  [uid:{uid}]")

        return {"content": [{"type": "text", "text": "\n".join(lines)}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error listing events: {e}"}]}


@tool(
    "delete_event",
    "Delete a calendar event by its UID.",
    {
        "type": "object",
        "properties": {
            "event_uid": {"type": "string"},
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": ["event_uid"],
    },
)
async def delete_event(args: dict[str, Any]) -> dict[str, Any]:
    try:
        cal = _get_calendar(args.get("user_id", 1))
        # Search recent 6-month window to find the event
        now = datetime.now()
        events = cal.search(
            start=_as_utc(now - timedelta(days=30)),
            end=_as_utc(now + timedelta(days=180)),
            event=True,
        )
        for ev in events:
            v = ev.vobject_instance.vevent
            if hasattr(v, "uid") and v.uid.value == args["event_uid"]:
                ev.delete()
                return {"content": [{"type": "text", "text": f"Deleted event {args['event_uid']}."}]}
        return {"content": [{"type": "text", "text": f"Event UID {args['event_uid']} not found."}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error deleting event: {e}"}]}


@tool(
    "find_free_slots",
    "Find free time slots on a given date not occupied by calendar events.",
    {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "min_duration_minutes": {"type": "integer", "default": 30, "description": "Minimum slot length to report"},
            "day_start": {"type": "string", "default": "06:15", "description": "HH:MM start of day"},
            "day_end": {"type": "string", "default": "22:00", "description": "HH:MM end of day"},
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": ["date"],
    },
)
async def find_free_slots(args: dict[str, Any]) -> dict[str, Any]:
    try:
        target = _parse_date(args["date"])
        day_start_str = args.get("day_start", "06:15")
        day_end_str = args.get("day_end", "22:00")
        min_dur = args.get("min_duration_minutes", 30)

        def hm(s: str) -> datetime:
            h, m = map(int, s.split(":"))
            return datetime(target.year, target.month, target.day, h, m)

        day_start = hm(day_start_str)
        day_end = hm(day_end_str)

        cal = _get_calendar(args.get("user_id", 1))
        events = cal.search(start=_as_utc(day_start), end=_as_utc(day_end), event=True)

        # Build sorted list of (start, end) for events that overlap the day
        busy: list[tuple[datetime, datetime]] = []
        for ev in events:
            v = ev.vobject_instance.vevent
            s = v.dtstart.value
            e = v.dtend.value
            if not isinstance(s, datetime):
                continue
            # Strip tzinfo so we can compare with naive day_start/day_end
            s = s.replace(tzinfo=None)
            e = e.replace(tzinfo=None)
            busy.append((max(s, day_start), min(e, day_end)))
        busy.sort()

        # Find gaps
        free_slots = []
        cursor = day_start
        for b_start, b_end in busy:
            if b_start > cursor:
                gap = int((b_start - cursor).total_seconds() / 60)
                if gap >= min_dur:
                    free_slots.append((cursor, b_start, gap))
            cursor = max(cursor, b_end)
        if cursor < day_end:
            gap = int((day_end - cursor).total_seconds() / 60)
            if gap >= min_dur:
                free_slots.append((cursor, day_end, gap))

        if not free_slots:
            return {"content": [{"type": "text", "text": f"No free slots >= {min_dur} min on {args['date']}."}]}

        lines = [f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')}  ({dur} min)" for s, e, dur in free_slots]
        return {"content": [{"type": "text", "text": f"Free slots on {args['date']}:\n" + "\n".join(lines)}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error finding free slots: {e}"}]}


ALL_CALENDAR_TOOLS = [add_event, list_events, delete_event, find_free_slots]
