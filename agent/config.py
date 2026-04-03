from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Models
MODEL_FAST = "claude-haiku-4-5-20251001"  # Routine queries, task CRUD
MODEL_DEEP = "claude-sonnet-4-6-20250116"  # Planning, scheduling, complex reasoning

# MCP server name — tools are exposed as mcp__nertia__<tool_name>
MCP_SERVER_NAME = "nertia"
