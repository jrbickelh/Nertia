"""
Bible reading tracker — log readings, track streak, show progress.
"""
from datetime import date, timedelta
from typing import Any
from claude_agent_sdk import tool
from db.database import execute, execute_insert

# Canonical book order + chapter counts (Protestant canon)
BIBLE_BOOKS = [
    ("Genesis",50),("Exodus",40),("Leviticus",27),("Numbers",36),("Deuteronomy",34),
    ("Joshua",24),("Judges",21),("Ruth",4),("1 Samuel",31),("2 Samuel",24),
    ("1 Kings",22),("2 Kings",25),("1 Chronicles",29),("2 Chronicles",36),
    ("Ezra",10),("Nehemiah",13),("Esther",10),("Job",42),("Psalms",150),
    ("Proverbs",31),("Ecclesiastes",12),("Song of Solomon",8),("Isaiah",66),
    ("Jeremiah",52),("Lamentations",5),("Ezekiel",48),("Daniel",12),("Hosea",14),
    ("Joel",3),("Amos",9),("Obadiah",1),("Jonah",4),("Micah",7),("Nahum",3),
    ("Habakkuk",3),("Zephaniah",3),("Haggai",2),("Zechariah",14),("Malachi",4),
    ("Matthew",28),("Mark",16),("Luke",24),("John",21),("Acts",28),
    ("Romans",16),("1 Corinthians",16),("2 Corinthians",13),("Galatians",6),
    ("Ephesians",6),("Philippians",4),("Colossians",4),("1 Thessalonians",5),
    ("2 Thessalonians",3),("1 Timothy",6),("2 Timothy",4),("Titus",3),("Philemon",1),
    ("Hebrews",13),("James",5),("1 Peter",5),("2 Peter",3),("1 John",5),
    ("2 John",1),("3 John",1),("Jude",1),("Revelation",22),
]
TOTAL_CHAPTERS = sum(c for _, c in BIBLE_BOOKS)


@tool(
    "log_bible_reading",
    "Log a completed Bible reading session.",
    {
        "type": "object",
        "properties": {
            "book": {"type": "string", "description": "Bible book name"},
            "chapter_start": {"type": "integer"},
            "chapter_end": {"type": "integer", "description": "Defaults to chapter_start"},
            "date": {"type": "string", "description": "YYYY-MM-DD (defaults to today)"},
            "notes": {"type": "string"},
            "user_id": {"type": "integer", "default": 1},
        },
        "required": ["book", "chapter_start"],
    },
)
async def log_bible_reading(args: dict[str, Any]) -> dict[str, Any]:
    target_date = args.get("date") or date.today().isoformat()
    chapter_end = args.get("chapter_end") or args["chapter_start"]
    user_id = args.get("user_id", 1)

    await execute_insert(
        "INSERT INTO bible_reading (user_id, date, book, chapter_start, chapter_end, notes) VALUES (?,?,?,?,?,?)",
        (user_id, target_date, args["book"], args["chapter_start"], chapter_end, args.get("notes")),
    )
    chapters = chapter_end - args["chapter_start"] + 1
    return {"content": [{"type": "text", "text": f"Logged: {args['book']} {args['chapter_start']}–{chapter_end} ({chapters} chapter{'s' if chapters > 1 else ''}) on {target_date}."}]}


@tool(
    "get_reading_progress",
    "Show Bible reading progress, streak, and recent readings.",
    {
        "type": "object",
        "properties": {
            "user_id": {"type": "integer", "default": 1},
        },
        "required": [],
    },
)
async def get_reading_progress(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)

    rows = await execute(
        "SELECT book, chapter_start, chapter_end, date FROM bible_reading WHERE user_id = ? ORDER BY date DESC, id DESC",
        (user_id,),
    )
    if not rows:
        return {"content": [{"type": "text", "text": "No readings logged yet."}]}

    # Total chapters read (may have overlaps but that's fine)
    total_read = sum((r["chapter_end"] - r["chapter_start"] + 1) for r in rows)
    pct = round(100 * total_read / TOTAL_CHAPTERS, 1)

    # Current streak
    streak = 0
    check = date.today()
    dates_read = {r["date"] for r in rows}
    while check.isoformat() in dates_read:
        streak += 1
        check -= timedelta(days=1)

    # Recent (last 7)
    recent = rows[:7]
    recent_str = "\n".join(
        f"  {r['date']}  {r['book']} {r['chapter_start']}"
        + (f"–{r['chapter_end']}" if r["chapter_end"] != r["chapter_start"] else "")
        for r in recent
    )

    lines = [
        f"Bible reading progress (user {user_id}):",
        f"  Chapters logged: {total_read} / {TOTAL_CHAPTERS} ({pct}%)",
        f"  Current streak: {streak} day{'s' if streak != 1 else ''}",
        "",
        "Recent readings:",
        recent_str,
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "get_users",
    "List all users. Useful for shared data queries.",
    {"type": "object", "properties": {}, "required": []},
)
async def get_users(args: dict[str, Any]) -> dict[str, Any]:
    rows = await execute("SELECT id, name, role FROM users ORDER BY id")
    lines = [f"  {r['id']}. {r['name']} ({r['role']})" for r in rows]
    return {"content": [{"type": "text", "text": "Users:\n" + "\n".join(lines)}]}


ALL_BIBLE_TOOLS = [log_bible_reading, get_reading_progress, get_users]
