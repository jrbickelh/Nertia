"""
Notification tools — send push notifications via self-hosted ntfy server.
"""
import os
from typing import Any

import httpx
from claude_agent_sdk import tool
from agent.config import PROJECT_ROOT
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

NTFY_URL = os.environ.get("NTFY_URL", "http://localhost:8080")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nertia")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")

# ntfy priority map: 1=min, 2=low, 3=default, 4=high, 5=max
_PRIORITY_MAP = {"low": 2, "default": 3, "high": 4, "urgent": 5}


def _headers(priority: int, title: str | None, tags: list[str] | None) -> dict:
    headers: dict[str, str] = {
        "Priority": str(priority),
        "Content-Type": "text/plain; charset=utf-8",
    }
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    if title:
        headers["Title"] = title
    if tags:
        headers["Tags"] = ",".join(tags)
    return headers


@tool(
    "send_notification",
    "Send a push notification via ntfy to JR's phone/devices.",
    {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Notification body text"},
            "title": {"type": "string", "description": "Notification title (optional)"},
            "priority": {
                "type": "string",
                "enum": ["low", "default", "high", "urgent"],
                "default": "default",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "ntfy emoji tags e.g. ['calendar', 'warning']",
            },
        },
        "required": ["message"],
    },
)
async def send_notification(args: dict[str, Any]) -> dict[str, Any]:
    priority = _PRIORITY_MAP.get(args.get("priority", "default"), 3)
    headers = _headers(priority, args.get("title"), args.get("tags"))
    url = f"{NTFY_URL}/{NTFY_TOPIC}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, content=args["message"].encode(), headers=headers)
            resp.raise_for_status()
        return {"content": [{"type": "text", "text": f"Notification sent: \"{args.get('title', args['message'][:50])}\""}]}
    except httpx.HTTPStatusError as e:
        return {"content": [{"type": "text", "text": f"ntfy error {e.response.status_code}: {e.response.text}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Failed to send notification: {e}"}]}


ALL_NOTIFICATION_TOOLS = [send_notification]
