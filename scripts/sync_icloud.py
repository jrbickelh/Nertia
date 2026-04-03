#!/usr/bin/env python3
"""
iCloud CalDAV sync — pulls events from iCloud into local Radicale calendar.

Runs every 30 minutes via cron (and before morning schedule generation).
Only syncs events in a rolling window: 7 days back → 60 days forward.
Uses the event UID as the idempotency key — safe to run repeatedly.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import caldav

ICLOUD_USER  = os.environ.get("ICLOUD_USER", "")
ICLOUD_TOKEN = os.environ.get("ICLOUD_APP_PASSWORD", "")  # app-specific password

ICLOUD_URL   = "https://caldav.icloud.com/.well-known/caldav"
ICLOUD_CALENDARS = os.environ.get("ICLOUD_CALENDARS", "")  # comma-sep display names to sync, empty = all

RADICALE_URL = os.environ.get("RADICALE_URL", "http://127.0.0.1:5232")
RADICALE_USER = os.environ.get("RADICALE_USER", "jr")
LOCAL_CALENDAR_URL = f"{RADICALE_URL}/{RADICALE_USER}/calendar/"

# Rolling sync window
DAYS_BACK    = 7
DAYS_FORWARD = 60


def _get_icloud_calendars() -> list[caldav.Calendar]:
    client = caldav.DAVClient(
        url=ICLOUD_URL,
        username=ICLOUD_USER,
        password=ICLOUD_TOKEN,
        auth=(ICLOUD_USER, ICLOUD_TOKEN),
    )
    principal = client.principal()
    cals = principal.calendars()

    filter_names = [n.strip().lower() for n in ICLOUD_CALENDARS.split(",") if n.strip()]
    if filter_names:
        cals = [c for c in cals if (c.get_display_name() or "").lower() in filter_names]

    return cals


def _get_local_calendar() -> caldav.Calendar:
    client = caldav.DAVClient(url=RADICALE_URL)
    return client.calendar(url=LOCAL_CALENDAR_URL)


def _existing_uids(local_cal: caldav.Calendar, start: datetime, end: datetime) -> set[str]:
    """Return set of UIDs already in local Radicale for the sync window."""
    try:
        events = local_cal.search(start=start, end=end, event=True)
    except Exception:
        return set()
    uids = set()
    for ev in events:
        try:
            v = ev.vobject_instance.vevent
            if hasattr(v, "uid"):
                uids.add(v.uid.value)
        except Exception:
            pass
    return uids


def _ical_to_local_naive(ical_str: str) -> str:
    """
    Sanitise iCloud iCal data for Radicale:
    - Strip TZID/UTC markers from DTSTART/DTEND (store as naive local time)
    - Remove VTIMEZONE blocks (Radicale doesn't need them)
    - Remove X-APPLE-* and other vendor-specific properties that cause 400s
    - Remove VALARM blocks (not needed for schedule display)
    """
    import re

    # Remove VTIMEZONE blocks entirely
    ical_str = re.sub(r'BEGIN:VTIMEZONE.*?END:VTIMEZONE\r?\n', '', ical_str, flags=re.DOTALL)
    # Remove VALARM blocks entirely
    ical_str = re.sub(r'BEGIN:VALARM.*?END:VALARM\r?\n', '', ical_str, flags=re.DOTALL)

    lines = ical_str.splitlines(keepends=True)
    out = []
    skip_continuation = False
    for line in lines:
        # Skip vendor-specific / iCloud-only properties
        prop = line.split(';')[0].split(':')[0].strip()
        if prop.startswith('X-') or prop in ('ATTENDEE', 'ORGANIZER', 'SEQUENCE', 'STATUS'):
            skip_continuation = True
            continue
        # Skip folded continuation lines of a skipped property
        if skip_continuation and line.startswith((' ', '\t')):
            continue
        skip_continuation = False

        # Strip TZID params and Z suffix from all datetime properties
        line = re.sub(r'^(DTSTART|DTEND|EXDATE|RECURRENCE-ID|DUE);[^:]+:', r'\1:', line)
        line = re.sub(r'^(DTSTART|DTEND|EXDATE|RECURRENCE-ID|DUE):(\d{8}T\d{6})Z', r'\1:\2', line)
        # Drop empty URL lines that cause parse errors
        if re.match(r'^URL[;:].{0,10}$', line.strip()):
            continue
        out.append(line)
    return "".join(out)


def sync():
    if not ICLOUD_USER or not ICLOUD_TOKEN:
        print("iCloud credentials not set — skipping sync (set ICLOUD_USER and ICLOUD_APP_PASSWORD in .env)")
        return

    now_utc = datetime.now(timezone.utc)
    start   = now_utc - timedelta(days=DAYS_BACK)
    end     = now_utc + timedelta(days=DAYS_FORWARD)

    print(f"Connecting to iCloud as {ICLOUD_USER}...")
    icloud_cals = _get_icloud_calendars()
    if not icloud_cals:
        print("No iCloud calendars found (check ICLOUD_CALENDARS filter or credentials).")
        return
    print(f"Found {len(icloud_cals)} calendar(s): {[c.get_display_name() for c in icloud_cals]}")

    local_cal = _get_local_calendar()
    existing  = _existing_uids(local_cal, start, end)

    added = skipped = errors = 0

    for ical_cal in icloud_cals:
        cal_name = ical_cal.get_display_name() or "unknown"
        try:
            events = ical_cal.search(start=start, end=end, event=True)
        except Exception as e:
            print(f"  [{cal_name}] Search error: {e}")
            continue

        for ev in events:
            try:
                v = ev.vobject_instance.vevent
                uid = v.uid.value if hasattr(v, "uid") else None
                if not uid:
                    continue

                if uid in existing:
                    skipped += 1
                    continue

                # Get raw ical and normalise datetimes to naive local
                raw_ical = ev.data
                local_ical = _ical_to_local_naive(raw_ical)

                local_cal.add_event(local_ical)
                existing.add(uid)
                summary = v.summary.value if hasattr(v, "summary") else "(no title)"
                print(f"  + [{cal_name}] {summary}")
                added += 1
            except Exception as e:
                errors += 1
                print(f"  ! Error syncing event: {e}")

    print(f"\nSync complete — added: {added}, skipped: {skipped}, errors: {errors}")


if __name__ == "__main__":
    sync()
