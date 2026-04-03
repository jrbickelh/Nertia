import json
from typing import Any
from claude_agent_sdk import tool
from db.database import execute, execute_insert


@tool(
    "list_tasks",
    "List tasks. Filter by bucket name, status (todo/in_progress/done/deferred), or get all.",
    {
        "type": "object",
        "properties": {
            "bucket": {"type": "string", "description": "Bucket name to filter by"},
            "status": {"type": "string", "enum": ["todo", "in_progress", "done", "deferred"]},
            "limit": {"type": "integer", "default": 20},
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": [],
    },
)
async def list_tasks(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)
    conditions = ["t.user_id = ?"]
    params: list = [user_id]

    if bucket := args.get("bucket"):
        conditions.append("b.name = ?")
        params.append(bucket)
    if status := args.get("status"):
        conditions.append("t.status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}"
    limit = args.get("limit", 20)

    rows = await execute(
        f"""
        SELECT t.id, t.title, t.description, t.priority, t.status,
               t.due_date, t.est_minutes, t.energy_level, t.tags,
               b.name as bucket
        FROM tasks t JOIN buckets b ON t.bucket_id = b.id
        {where}
        ORDER BY t.priority ASC, t.created_at ASC
        LIMIT ?
        """,
        (*params, limit),
    )

    if not rows:
        return {"content": [{"type": "text", "text": "No tasks found."}]}

    lines = []
    for r in rows:
        due = f" - due {r['due_date']}" if r["due_date"] else ""
        est = f" ~{r['est_minutes']}min" if r["est_minutes"] else ""
        lines.append(
            f"[{r['status'].upper()}] #{r['id']} {r['title']} "
            f"(P{r['priority']}, {r['bucket']}){due}{est}"
        )

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "add_task",
    "Create a new task in a bucket.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "bucket": {"type": "string", "description": "Bucket name"},
            "priority": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
            "description": {"type": "string"},
            "due_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
            "est_minutes": {"type": "integer"},
            "energy_level": {"type": "string", "enum": ["high", "medium", "low"]},
            "tags": {"type": "string", "description": "Comma-separated tags"},
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": ["title", "bucket"],
    },
)
async def add_task(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)
    # Resolve bucket
    rows = await execute("SELECT id FROM buckets WHERE name = ?", (args["bucket"],))
    if not rows:
        buckets = await execute("SELECT name FROM buckets ORDER BY sort_order")
        names = ", ".join(r["name"] for r in buckets)
        return {"content": [{"type": "text", "text": f"Unknown bucket '{args['bucket']}'. Available: {names}"}]}

    bucket_id = rows[0]["id"]
    priority = args.get("priority", 3)

    task_id = await execute_insert(
        """
        INSERT INTO tasks (user_id, bucket_id, title, description, priority, due_date, est_minutes, energy_level, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            bucket_id,
            args["title"],
            args.get("description"),
            priority,
            args.get("due_date"),
            args.get("est_minutes"),
            args.get("energy_level"),
            args.get("tags"),
        ),
    )

    return {
        "content": [
            {
                "type": "text",
                "text": f"Added task #{task_id} \"{args['title']}\" to {args['bucket']} (P{priority}).",
            }
        ]
    }


@tool(
    "complete_task",
    "Mark a task as done.",
    {
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "notes": {"type": "string"},
            "user_id": {"type": "integer", "description": "User ID for ownership check.", "default": 1},
        },
        "required": ["task_id"],
    },
)
async def complete_task(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)
    rows = await execute("SELECT id, title FROM tasks WHERE id = ? AND user_id = ?", (args["task_id"], user_id))
    if not rows:
        return {"content": [{"type": "text", "text": f"Task #{args['task_id']} not found."}]}

    await execute(
        "UPDATE tasks SET status = 'done', completed_at = datetime('now') WHERE id = ?",
        (args["task_id"],),
    )

    return {"content": [{"type": "text", "text": f"Completed task #{args['task_id']} \"{rows[0]['title']}\"."}]}


@tool(
    "update_task",
    "Update fields on an existing task. Pass only the fields you want to change.",
    {
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "priority": {"type": "integer", "minimum": 1, "maximum": 5},
            "status": {"type": "string", "enum": ["todo", "in_progress", "done", "deferred"]},
            "due_date": {"type": "string"},
            "est_minutes": {"type": "integer"},
            "energy_level": {"type": "string", "enum": ["high", "medium", "low"]},
            "bucket": {"type": "string", "description": "Move to a different bucket by name"},
            "tags": {"type": "string"},
            "user_id": {"type": "integer", "description": "User ID for ownership check.", "default": 1},
        },
        "required": ["task_id"],
    },
)
async def update_task(args: dict[str, Any]) -> dict[str, Any]:
    task_id = args.pop("task_id")
    user_id = args.pop("user_id", 1)
    rows = await execute("SELECT id, title FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
    if not rows:
        return {"content": [{"type": "text", "text": f"Task #{task_id} not found."}]}

    # Handle bucket name -> id
    if "bucket" in args:
        bucket_rows = await execute("SELECT id FROM buckets WHERE name = ?", (args.pop("bucket"),))
        if not bucket_rows:
            return {"content": [{"type": "text", "text": "Unknown bucket name."}]}
        args["bucket_id"] = bucket_rows[0]["id"]

    if not args:
        return {"content": [{"type": "text", "text": "No fields to update."}]}

    sets = ", ".join(f"{k} = ?" for k in args)
    values = list(args.values()) + [task_id]
    await execute(f"UPDATE tasks SET {sets} WHERE id = ?", tuple(values))

    return {"content": [{"type": "text", "text": f"Updated task #{task_id}."}]}


@tool(
    "defer_task",
    "Defer a task to a new date.",
    {
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "new_due_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
            "reason": {"type": "string"},
            "user_id": {"type": "integer", "description": "User ID for ownership check.", "default": 1},
        },
        "required": ["task_id", "new_due_date"],
    },
)
async def defer_task(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)
    rows = await execute("SELECT id, title FROM tasks WHERE id = ? AND user_id = ?", (args["task_id"], user_id))
    if not rows:
        return {"content": [{"type": "text", "text": f"Task #{args['task_id']} not found."}]}

    await execute(
        "UPDATE tasks SET status = 'deferred', due_date = ? WHERE id = ?",
        (args["new_due_date"], args["task_id"]),
    )

    return {
        "content": [
            {
                "type": "text",
                "text": f"Deferred task #{args['task_id']} \"{rows[0]['title']}\" to {args['new_due_date']}.",
            }
        ]
    }


@tool(
    "search_tasks",
    "Search tasks by keyword in title or description.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": ["query"],
    },
)
async def search_tasks(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)
    q = f"%{args['query']}%"
    rows = await execute(
        """
        SELECT t.id, t.title, t.status, t.priority, b.name as bucket
        FROM tasks t JOIN buckets b ON t.bucket_id = b.id
        WHERE t.user_id = ? AND (t.title LIKE ? OR t.description LIKE ?)
        ORDER BY t.priority ASC
        LIMIT 20
        """,
        (user_id, q, q),
    )

    if not rows:
        return {"content": [{"type": "text", "text": f"No tasks matching '{args['query']}'."}]}

    lines = [
        f"[{r['status'].upper()}] #{r['id']} {r['title']} (P{r['priority']}, {r['bucket']})"
        for r in rows
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "get_buckets",
    "List all task buckets with their task counts for the current user.",
    {
        "type": "object",
        "properties": {
            "user_id": {"type": "integer", "description": "User ID (1=primary user, 2=member). Defaults to 1.", "default": 1},
        },
        "required": [],
    },
)
async def get_buckets(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", 1)
    rows = await execute(
        """
        SELECT b.name, b.description,
               COUNT(CASE WHEN t.status = 'todo' AND t.user_id = ? THEN 1 END) as todo,
               COUNT(CASE WHEN t.status = 'in_progress' AND t.user_id = ? THEN 1 END) as in_progress,
               COUNT(CASE WHEN t.status = 'done' AND t.user_id = ? THEN 1 END) as done
        FROM buckets b LEFT JOIN tasks t ON b.id = t.bucket_id
        GROUP BY b.id
        ORDER BY b.sort_order
        """,
        (user_id, user_id, user_id),
    )

    lines = []
    for r in rows:
        active = r["todo"] + r["in_progress"]
        lines.append(f"{r['name']}: {active} active ({r['todo']} todo, {r['in_progress']} in progress, {r['done']} done)")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


ALL_TASK_TOOLS = [list_tasks, add_task, complete_task, update_task, defer_task, search_tasks, get_buckets]
