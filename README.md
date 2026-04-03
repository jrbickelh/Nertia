# Nertia

A self-hosted personal assistant running on a Raspberry Pi. Powered by the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk), it manages tasks, generates circadian-aware daily schedules, tracks fitness/nutrition/mood, and delivers proactive push notifications — all private and on your own hardware.

## Features

- **AI-powered scheduling** — Claude generates optimized daily blocks grounded in circadian science, accounting for energy levels, task priority, weather, and recent mood
- **Multi-user** — supports a primary user and household members with per-user feature flags and granular privacy controls
- **Task management** — buckets (Now, Career, Projects, Admin, etc.) with priority, energy level, and due dates
- **Fitness & nutrition tracking** — workouts, meals, body metrics; Claude Vision analyzes meal photos
- **Mood check-ins** — 1–10 score with energy/emotion tags; feeds back into schedule generation
- **Bible reading tracker** — log readings, track streaks and progress
- **Push notifications** — morning briefing, periodic nudges, and weekly reviews via [ntfy](https://ntfy.sh)
- **Calendar integration** — Radicale CalDAV; conflicts detected and shown on schedule
- **RAG knowledge base** — ChromaDB + local embeddings; semantic search over all personal history
- **PWA frontend** — offline-capable, voice-first, installable on mobile (iOS + Android)
- **Cycle tracking** — optional, off by default, per-user feature flag with granular sharing controls

## Architecture

```
PWA (Vanilla JS, Service Worker)
    └── FastAPI backend (port 8000)
            ├── Claude Agent SDK (MCP tools)
            ├── SQLite database
            ├── Radicale CalDAV (port 5232)
            ├── ChromaDB (local embeddings)
            └── ntfy push server (port 8080)
```

## Requirements

- Python 3.13+
- Raspberry Pi (or any Linux host) with 1GB+ RAM
- [Claude Code](https://claude.ai/code) (for OAuth-based agent — free tier works) **or** an `ANTHROPIC_API_KEY`
- [Radicale](https://radicale.org) CalDAV server
- [ntfy](https://ntfy.sh) push notification server

## Setup

### 1. Clone and create virtualenv

```bash
git clone <repo-url> && cd nertia
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...   # Required if not using Claude Code OAuth
NTFY_TOKEN=your-ntfy-token     # Optional; for authenticated ntfy topics
RADICALE_URL=http://127.0.0.1:5232  # Override if Radicale runs elsewhere
```

### 3. Initialize the database

```bash
python -c "import asyncio; from db.database import init_db; asyncio.run(init_db())"
```

This seeds two users, default buckets, feature flags, and profile defaults. Update user names and preferences via the Settings view in the PWA.

### 4. Start services

**FastAPI backend:**
```bash
source venv/bin/activate
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

**Or with systemd** (see `systemd/` for service files):
```bash
sudo cp systemd/nertia-web.service /etc/systemd/system/
sudo systemctl enable --now nertia-web.service
```

**Radicale** (CalDAV):
```bash
# Create a calendar for each user (slug = lowercase user name)
# e.g., http://127.0.0.1:5232/user_1/calendar/
```

**ntfy:**
```bash
# See ntfy docs for self-hosted setup
# Configure topic and token in .env
```

### 5. Cron jobs

```bash
# Morning briefing — 6:00 AM
0 6 * * * /path/to/venv/bin/python -m scripts.morning_briefing

# Periodic nudges — every 30 minutes
*/30 * * * * /path/to/venv/bin/python -m scripts.periodic_nudge

# Weekly review — Sunday 8:00 PM
0 20 * * 0 /path/to/venv/bin/python -m scripts.weekly_review

# RAG ingestion — nightly
0 2 * * * /path/to/venv/bin/python -m scripts.rag_ingest
```

## CLI Agent

Interactive:
```bash
python -m agent.main
```

One-shot (used by cron scripts):
```bash
python -m agent.main "What's on my schedule today?"
```

## Configuration Notes

**Radicale calendar slugs** are derived from user names in the database (lowercased). If you rename users, their calendar paths will update automatically.

**Claude Code OAuth vs API key:** The agent is configured to use Claude Code OAuth by default (no API key consumed for agent turns). To switch to direct API key usage, remove the `env` overrides in `agent/main.py` — see the comment there for details.

**Rate limiting:** The `/api/chat` endpoint is limited to 30 requests/minute per IP. Adjust in `web/app.py` if needed.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Agent framework | [claude-agent-sdk](https://github.com/anthropics/claude-agent-sdk) |
| Backend | FastAPI + uvicorn |
| Database | SQLite (aiosqlite) |
| Calendar | Radicale (CalDAV) |
| Embeddings | ChromaDB + all-MiniLM-L6-v2 (local ONNX) |
| Push notifications | ntfy |
| Frontend | Vanilla JS PWA |
| AI models | Claude Haiku (fast ops), Claude Sonnet (scheduling + review) |

## License

MIT
