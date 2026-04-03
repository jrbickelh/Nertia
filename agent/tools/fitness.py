"""
Fitness & meal logging tools.
Entries can come from text, photo analysis, or voice transcription.
"""
from datetime import date, timedelta
from typing import Any
from claude_agent_sdk import tool
from db.database import execute, execute_insert


@tool(
    "log_workout",
    "Log a completed workout. Can be called after photo/voice analysis.",
    {
        "type": "object",
        "properties": {
            "activity":         {"type": "string", "description": "e.g. '5km run', 'bench press 3x10x185lb'"},
            "duration_minutes": {"type": "integer"},
            "distance_km":      {"type": "number"},
            "calories":         {"type": "integer"},
            "notes":            {"type": "string"},
            "date":             {"type": "string", "description": "YYYY-MM-DD (defaults to today)"},
            "user_id":          {"type": "integer", "default": 1},
            "photo_path":       {"type": "string"},
        },
        "required": ["activity"],
    },
)
async def log_workout(args: dict[str, Any]) -> dict[str, Any]:
    target_date = args.get("date") or date.today().isoformat()
    row_id = await execute_insert(
        """INSERT INTO fitness_log
           (user_id, date, log_type, activity, duration_minutes, distance_km, calories, details, photo_path)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            args.get("user_id", 1), target_date, "workout",
            args["activity"],
            args.get("duration_minutes"),
            args.get("distance_km"),
            args.get("calories"),
            args.get("notes"),
            args.get("photo_path"),
        ),
    )

    parts = [args["activity"]]
    if args.get("duration_minutes"): parts.append(f"{args['duration_minutes']} min")
    if args.get("distance_km"):      parts.append(f"{args['distance_km']} km")
    if args.get("calories"):         parts.append(f"{args['calories']} kcal")
    return {"content": [{"type": "text", "text": f"Logged workout #{row_id}: {', '.join(parts)} on {target_date}."}]}


@tool(
    "log_meal",
    "Log a meal or food entry. Can be called after photo analysis.",
    {
        "type": "object",
        "properties": {
            "activity":   {"type": "string", "description": "e.g. 'Grilled chicken with rice and vegetables'"},
            "calories":   {"type": "integer"},
            "notes":      {"type": "string", "description": "Macros, how you felt, etc."},
            "date":       {"type": "string", "description": "YYYY-MM-DD (defaults to today)"},
            "user_id":    {"type": "integer", "default": 1},
            "photo_path": {"type": "string"},
        },
        "required": ["activity"],
    },
)
async def log_meal(args: dict[str, Any]) -> dict[str, Any]:
    target_date = args.get("date") or date.today().isoformat()
    row_id = await execute_insert(
        """INSERT INTO fitness_log
           (user_id, date, log_type, activity, calories, details, photo_path)
           VALUES (?,?,?,?,?,?,?)""",
        (
            args.get("user_id", 1), target_date, "meal",
            args["activity"],
            args.get("calories"),
            args.get("notes"),
            args.get("photo_path"),
        ),
    )
    cal_str = f" ({args['calories']} kcal)" if args.get("calories") else ""
    return {"content": [{"type": "text", "text": f"Logged meal #{row_id}: {args['activity']}{cal_str} on {target_date}."}]}


@tool(
    "log_body_metric",
    "Log weight, steps, or water intake.",
    {
        "type": "object",
        "properties": {
            "log_type": {"type": "string", "enum": ["weight", "steps", "water"]},
            "value":    {"type": "number", "description": "lbs for weight, count for steps, oz for water"},
            "date":     {"type": "string", "description": "YYYY-MM-DD (defaults to today)"},
            "user_id":  {"type": "integer", "default": 1},
        },
        "required": ["log_type", "value"],
    },
)
async def log_body_metric(args: dict[str, Any]) -> dict[str, Any]:
    target_date = args.get("date") or date.today().isoformat()
    units = {"weight": "lbs", "steps": "steps", "water": "oz"}
    await execute_insert(
        "INSERT INTO fitness_log (user_id, date, log_type, details) VALUES (?,?,?,?)",
        (args.get("user_id", 1), target_date, args["log_type"], str(args["value"])),
    )
    return {"content": [{"type": "text", "text": f"Logged {args['log_type']}: {args['value']} {units[args['log_type']]} on {target_date}."}]}


@tool(
    "get_fitness_summary",
    "Get a summary of workouts, meals, and metrics for a given period.",
    {
        "type": "object",
        "properties": {
            "period":  {"type": "string", "enum": ["today", "week", "month"], "default": "week"},
            "user_id": {"type": "integer", "default": 1},
        },
        "required": [],
    },
)
async def get_fitness_summary(args: dict[str, Any]) -> dict[str, Any]:
    period = args.get("period", "week")
    user_id = args.get("user_id", 1)
    days = {"today": 0, "week": 6, "month": 29}[period]
    since = (date.today() - timedelta(days=days)).isoformat()

    rows = await execute(
        """SELECT log_type, activity, duration_minutes, distance_km, calories, details, date
           FROM fitness_log WHERE user_id = ? AND date >= ?
           ORDER BY date DESC, id DESC""",
        (user_id, since),
    )

    if not rows:
        return {"content": [{"type": "text", "text": f"No fitness data for the past {period}."}]}

    workouts = [r for r in rows if r["log_type"] == "workout"]
    meals = [r for r in rows if r["log_type"] == "meal"]
    metrics = [r for r in rows if r["log_type"] in ("weight", "steps", "water")]

    lines = [f"Fitness summary — {period} (user {user_id}):\n"]

    if workouts:
        total_min = sum(r["duration_minutes"] or 0 for r in workouts)
        total_km = sum(r["distance_km"] or 0 for r in workouts)
        lines.append(f"Workouts ({len(workouts)})  {total_min} min total  {round(total_km,1)} km")
        for r in workouts[:5]:
            dur = f" {r['duration_minutes']}min" if r["duration_minutes"] else ""
            dist = f" {r['distance_km']}km" if r["distance_km"] else ""
            lines.append(f"  {r['date']}  {r['activity']}{dur}{dist}")

    if meals:
        total_cal = sum(r["calories"] or 0 for r in meals)
        lines.append(f"\nMeals ({len(meals)})  ~{total_cal} kcal total")
        for r in meals[:5]:
            cal = f" {r['calories']} kcal" if r["calories"] else ""
            lines.append(f"  {r['date']}  {r['activity']}{cal}")

    if metrics:
        lines.append("\nMetrics:")
        for r in metrics:
            lines.append(f"  {r['date']}  {r['log_type']}: {r['details']}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


ALL_FITNESS_TOOLS = [log_workout, log_meal, log_body_metric, get_fitness_summary]
