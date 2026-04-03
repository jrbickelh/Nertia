import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
)

from agent.config import MODEL_FAST, MCP_SERVER_NAME, PROJECT_ROOT
from agent.prompts.system import SYSTEM_PROMPT
from agent.tools.tasks import ALL_TASK_TOOLS
from agent.tools.profile import ALL_PROFILE_TOOLS
from agent.tools.calendar import ALL_CALENDAR_TOOLS
from agent.tools.schedule import ALL_SCHEDULE_TOOLS
from agent.tools.notifications import ALL_NOTIFICATION_TOOLS
from agent.tools.feedback import ALL_FEEDBACK_TOOLS
from agent.tools.weather import ALL_WEATHER_TOOLS
from agent.tools.bible import ALL_BIBLE_TOOLS
from agent.tools.fitness import ALL_FITNESS_TOOLS
from agent.tools.notification_prefs import ALL_NOTIF_PREF_TOOLS
from agent.tools.knowledge import ALL_KNOWLEDGE_TOOLS
from db.database import init_db


_ALL = (ALL_TASK_TOOLS + ALL_PROFILE_TOOLS + ALL_CALENDAR_TOOLS + ALL_SCHEDULE_TOOLS
        + ALL_NOTIFICATION_TOOLS + ALL_FEEDBACK_TOOLS + ALL_WEATHER_TOOLS
        + ALL_BIBLE_TOOLS + ALL_FITNESS_TOOLS + ALL_NOTIF_PREF_TOOLS
        + ALL_KNOWLEDGE_TOOLS)


def build_server():
    all_tools = _ALL
    return create_sdk_mcp_server(
        name=MCP_SERVER_NAME,
        version="0.1.0",
        tools=all_tools,
    )


def build_allowed_tools(server_name: str, tools: list) -> list[str]:
    return [f"mcp__{server_name}__{t.name}" for t in tools]


def build_options(system_prompt: str | None = None):
    server = build_server()
    all_tools = _ALL

    return ClaudeAgentOptions(
        model=MODEL_FAST,
        system_prompt=system_prompt or SYSTEM_PROMPT,
        mcp_servers={MCP_SERVER_NAME: server},
        allowed_tools=build_allowed_tools(MCP_SERVER_NAME, all_tools),
        permission_mode="bypassPermissions",
        max_turns=10,
        cwd=str(PROJECT_ROOT),
        # CLAUDECODE="" signals the SDK to use Claude Code OAuth (no API key consumed).
        # ANTHROPIC_API_KEY="" prevents any inherited key from being forwarded to
        # the sub-agent. For API-key-only deployments, remove these two env overrides
        # and ensure ANTHROPIC_API_KEY is set in the environment or .env file.
        env={"CLAUDECODE": "", "ANTHROPIC_API_KEY": ""},
    )


async def run_interactive():
    await init_db()
    options = build_options()

    print("Nertia v0.1")
    print("Type 'quit' to exit.\n")

    async with ClaudeSDKClient(options=options) as client:
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            await client.query(user_input)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(f"Agent: {block.text}")
                elif isinstance(message, ResultMessage):
                    if message.subtype == "error":
                        print(f"Error: {getattr(message, 'error', 'unknown error')}")

            print()


async def run_oneshot(prompt: str):
    """Run a single query and exit. Used by cron scripts."""
    from claude_agent_sdk import query

    await init_db()
    options = build_options()

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)


def main():
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        asyncio.run(run_oneshot(prompt))
    else:
        asyncio.run(run_interactive())


if __name__ == "__main__":
    main()
