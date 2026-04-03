from typing import Any
from claude_agent_sdk import tool
from db.database import execute


@tool(
    "get_profile",
    "Get all user preferences and settings.",
    {
        "type": "object",
        "properties": {
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": [],
    },
)
async def get_profile(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)
    rows = await execute("SELECT key, value FROM profile WHERE user_id = ? ORDER BY key", (user_id,))
    if not rows:
        return {"content": [{"type": "text", "text": "No profile data found."}]}

    lines = [f"{r['key']}: {r['value']}" for r in rows]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "update_preference",
    "Update a single user preference.",
    {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": ["key", "value"],
    },
)
async def update_preference(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)
    await execute(
        "INSERT INTO profile (user_id, key, value) VALUES (?, ?, ?) ON CONFLICT(user_id, key) DO UPDATE SET value = ?",
        (user_id, args["key"], args["value"], args["value"]),
    )
    return {"content": [{"type": "text", "text": f"Updated {args['key']} = {args['value']}"}]}


@tool(
    "get_user_context",
    "Get a full context string about the user for scheduling decisions. Includes profile, active task counts, and recent completions.",
    {
        "type": "object",
        "properties": {
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": [],
    },
)
async def get_user_context(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)
    profile = await execute("SELECT key, value FROM profile WHERE user_id = ? ORDER BY key", (user_id,))
    profile_str = "\n".join(f"  {r['key']}: {r['value']}" for r in profile)

    bucket_stats = await execute(
        """
        SELECT b.name,
               COUNT(CASE WHEN t.status IN ('todo','in_progress') AND t.user_id = ? THEN 1 END) as active
        FROM buckets b LEFT JOIN tasks t ON b.id = t.bucket_id
        GROUP BY b.id ORDER BY b.sort_order
        """,
        (user_id,),
    )
    buckets_str = "\n".join(f"  {r['name']}: {r['active']} active tasks" for r in bucket_stats)

    recent = await execute(
        """
        SELECT t.title, t.completed_at, b.name as bucket
        FROM tasks t JOIN buckets b ON t.bucket_id = b.id
        WHERE t.status = 'done' AND t.user_id = ?
        ORDER BY t.completed_at DESC LIMIT 5
        """,
        (user_id,),
    )
    recent_str = "\n".join(
        f"  {r['title']} ({r['bucket']}) - completed {r['completed_at']}" for r in recent
    ) if recent else "  None yet"

    context = f"""User Profile:
{profile_str}

Active Tasks by Bucket:
{buckets_str}

Recently Completed:
{recent_str}"""

    return {"content": [{"type": "text", "text": context}]}


ALL_PROFILE_TOOLS = [get_profile, update_preference, get_user_context]
