"""
Notification preference tools — enable/disable specific notification types.
The periodic_nudge script reads these before sending.

Types: morning_briefing, transition, exercise, meal, weekly_review
"""
from typing import Any
from claude_agent_sdk import tool
from db.database import execute, execute_insert


VALID_TYPES = ("morning_briefing", "transition", "exercise", "meal", "weekly_review")


@tool(
    "set_notification_pref",
    "Enable or disable a specific notification type. The agent calls this when you say things like "
    "'stop sending exercise reminders' or 're-enable meal notifications'.",
    {
        "type": "object",
        "properties": {
            "notification_type": {
                "type": "string",
                "enum": list(VALID_TYPES),
                "description": "morning_briefing | transition | exercise | meal | weekly_review",
            },
            "enabled": {"type": "boolean"},
            "reason": {"type": "string", "description": "Why it's being changed (stored for context)"},
            "user_id": {"type": "integer", "default": 1},
        },
        "required": ["notification_type", "enabled"],
    },
)
async def set_notification_pref(args: dict[str, Any]) -> dict[str, Any]:
    ntype = args["notification_type"]
    enabled = int(args["enabled"])
    user_id = args.get("user_id", 1)
    reason = args.get("reason", "")

    await execute(
        """INSERT INTO notification_prefs (user_id, notification_type, enabled, disabled_reason, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(user_id, notification_type)
           DO UPDATE SET enabled=excluded.enabled, disabled_reason=excluded.disabled_reason, updated_at=excluded.updated_at""",
        (user_id, ntype, enabled, reason),
    )
    state = "enabled" if enabled else "disabled"
    return {"content": [{"type": "text", "text": f"{ntype} notifications {state}" + (f" ({reason})" if reason else "") + "."}]}


@tool(
    "get_notification_prefs",
    "Show current notification preferences for a user.",
    {
        "type": "object",
        "properties": {"user_id": {"type": "integer", "default": 1}},
        "required": [],
    },
)
async def get_notification_prefs(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)
    rows = await execute(
        "SELECT notification_type, enabled, disabled_reason, updated_at FROM notification_prefs WHERE user_id = ? ORDER BY notification_type",
        (user_id,),
    )
    if not rows:
        return {"content": [{"type": "text", "text": "No preferences set — all notifications enabled by default."}]}

    lines = ["Notification preferences:"]
    for r in rows:
        state = "✅ on" if r["enabled"] else "🔕 off"
        reason = f"  — {r['disabled_reason']}" if r["disabled_reason"] and not r["enabled"] else ""
        lines.append(f"  {r['notification_type']}: {state}{reason}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


ALL_NOTIF_PREF_TOOLS = [set_notification_pref, get_notification_prefs]


# ── Helper for scripts ─────────────────────────────────────────────────────────

async def is_enabled(notification_type: str, user_id: int = 1) -> bool:
    """Used by cron scripts to check before sending."""
    rows = await execute(
        "SELECT enabled FROM notification_prefs WHERE user_id = ? AND notification_type = ?",
        (user_id, notification_type),
    )
    if not rows:
        return True  # default on
    return bool(rows[0]["enabled"])
