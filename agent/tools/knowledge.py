"""RAG knowledge base tool — semantic search over personal data."""

from typing import Any
from claude_agent_sdk import tool


@tool(
    "query_knowledge_base",
    "Search the user's personal knowledge base using semantic similarity. "
    "Returns relevant tasks, schedule blocks, fitness logs, mood entries, Bible readings, "
    "and feedback. Use this to answer questions about past activities, patterns, and history.",
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query, e.g. 'What workouts did I do last week?' or 'When was I most productive?'",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default 5, max 20)",
                "default": 5,
            },
            "source": {
                "type": "string",
                "description": "Optional: filter by data source (tasks, schedule, fitness, mood, bible, feedback)",
                "enum": ["tasks", "schedule", "fitness", "mood", "bible", "feedback"],
            },
        },
        "required": ["query"],
    },
)
async def query_knowledge_base(args: dict[str, Any]) -> dict[str, Any]:
    from agent.rag.store import query, count

    if count() == 0:
        return {
            "content": [{"type": "text", "text": "Knowledge base is empty. Run ingestion first."}]
        }

    query_text = args["query"]
    top_k = min(args.get("top_k", 5), 20)
    where = None
    if source := args.get("source"):
        where = {"source": source}

    results = query(query_text, n_results=top_k, where=where)

    if not results["documents"] or not results["documents"][0]:
        return {"content": [{"type": "text", "text": "No relevant results found."}]}

    lines = []
    for i, (doc, meta, dist) in enumerate(
        zip(results["documents"][0], results["metadatas"][0], results["distances"][0])
    ):
        relevance = max(0, round((1 - dist) * 100))
        source_label = meta.get("source", "unknown")
        date_label = meta.get("date", "")
        lines.append(f"[{i+1}] ({source_label}{' · ' + date_label if date_label else ''} · {relevance}% match)\n{doc}")

    return {"content": [{"type": "text", "text": "\n\n".join(lines)}]}


ALL_KNOWLEDGE_TOOLS = [query_knowledge_base]
