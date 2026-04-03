# Nertia: Full Project Plan

> An agentic personal scheduling and task management system running on a
> Raspberry Pi, powered by the Claude Agent SDK.

---

## Table of Contents

1. [Vision & Goals](#1-vision--goals)
2. [Architecture](#2-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Hardware & Infrastructure](#4-hardware--infrastructure)
5. [Directory Structure](#5-directory-structure)
6. [Database Schema](#6-database-schema)
7. [Agent Tools (MCP)](#7-agent-tools-mcp)
8. [Scheduling Engine Design](#8-scheduling-engine-design)
9. [Build Phases](#9-build-phases)
10. [API Endpoints (PWA Backend)](#10-api-endpoints-pwa-backend)
11. [Cost Projections](#11-cost-projections)
12. [Risk Register](#12-risk-register)
13. [Future / Stretch Goals](#13-future--stretch-goals)

---

## 1. Vision & Goals

A personal AI assistant that lives on a Raspberry Pi and:

- Manages tasks across life domains (career, marriage, faith, health, projects, admin)
- Generates optimized daily schedules based on circadian science and personal patterns
- Proactively nudges via push notifications at the right moments
- Learns from feedback — adapts to what actually works for you
- Is fully self-hosted, private, and accessible from any device via Tailscale

**Design principles:**
- Agent-first: Claude is the core, not a bolt-on
- Lean: every byte matters on 1GB RAM
- Pragmatic: ship a working CLI agent in days, not weeks
- Iterative: each phase delivers standalone value

---

## 2. Architecture

```
+--------------------------------------------------+
|                   Your Devices                    |
|  (Phone / Laptop / Desktop via Tailscale)         |
+--------------------------------------------------+
        |                          |
        | HTTPS (PWA)             | Push (ntfy)
        v                          v
+----------------+          +----------------+
|  FastAPI       |          |  ntfy          |
|  (PWA backend) |          |  (notifications)|
|  port 8000     |          |  port 8080      |
+----------------+          +----------------+
        |                          ^
        v                          |
+----------------------------------------------+
|           Nertia Agent               |
|          (Claude Agent SDK + Python)         |
|                                              |
|  +----------+  +----------+  +------------+ |
|  | Task     |  | Calendar |  | Schedule   | |
|  | Tools    |  | Tools    |  | Tools      | |
|  +----------+  +----------+  +------------+ |
|  +----------+  +----------+  +------------+ |
|  | Notify   |  | Profile  |  | Feedback   | |
|  | Tools    |  | Tools    |  | Tools      | |
|  +----------+  +----------+  +------------+ |
+----------------------------------------------+
        |                |
        v                v
+----------------+  +----------------+
|  SQLite        |  |  Radicale      |
|  (tasks, logs, |  |  (CalDAV)      |
|   preferences) |  |  port 5232     |
+----------------+  +----------------+
```

**Key architectural decision:** The Claude Agent SDK is the core runtime.
Custom MCP tools (in-process, no separate servers) handle all domain logic.
FastAPI exists only to serve the PWA and proxy chat to the agent. This
eliminates the need for a large custom backend.

---

## 3. Tech Stack

| Layer           | Technology              | Version   | Notes                                    |
|-----------------|-------------------------|-----------|------------------------------------------|
| OS              | Raspberry Pi OS 64-bit  | Bookworm  | Lite (no desktop) to save RAM            |
| Runtime         | Python                  | 3.11+     | Agent SDK requires 3.10+                 |
| Agent framework | claude-agent-sdk        | latest    | pip install claude-agent-sdk             |
| AI model (fast) | claude-haiku-4-5        | -         | Routine queries: $1/$5 per MTok          |
| AI model (deep) | claude-sonnet-4-6       | -         | Planning/reasoning: $3/$15 per MTok      |
| Database        | SQLite                  | 3.x       | Via aiosqlite for async                  |
| CalDAV server   | Radicale                | 3.x       | pip install radicale                     |
| CalDAV client   | caldav (Python lib)     | 1.x       | Programmatic access to Radicale          |
| Notifications   | ntfy                    | latest    | Self-hosted, has iOS app                 |
| Web framework   | FastAPI + Uvicorn       | latest    | Minimal: PWA serving + chat proxy        |
| Frontend        | PWA (vanilla JS)        | -         | Lightweight, no build step               |
| VPN             | Tailscale               | latest    | Already configured across devices        |
| Process mgmt    | systemd                 | -         | Native services, no Docker overhead      |
| Scheduler       | cron + systemd timers   | -         | Triggers proactive agent runs            |

**Why no Docker:** The RPi 3 has 1GB RAM. Docker daemon + overlay filesystem
adds ~150-200MB overhead. Running services natively via systemd reclaims that
memory for actual workloads.

### Python Dependencies (requirements.txt)

```
claude-agent-sdk
fastapi
uvicorn[standard]
aiosqlite
caldav
httpx
python-dotenv
pydantic
```

---

## 4. Hardware & Infrastructure

### Raspberry Pi 3 Model B
- CPU: Quad-core ARM Cortex-A53 @ 1.2GHz
- RAM: 1GB LPDDR2
- Storage: 32GB+ microSD (Class 10 / A1 minimum)
- Network: Tailscale mesh VPN

### Memory Budget (target)

| Service             | Estimated RAM |
|---------------------|---------------|
| OS + systemd        | ~200MB        |
| Python agent process| ~80MB         |
| FastAPI + Uvicorn   | ~60MB         |
| Radicale            | ~30MB         |
| ntfy                | ~30MB         |
| SQLite (in-process) | ~10MB         |
| **Headroom**        | **~590MB**    |

Note: These are estimates. The agent process will spike during API calls
(JSON parsing, response handling). Monitor with `htop` and adjust.

### Swap

Configure 512MB-1GB swap on the SD card as a safety net:
```bash
sudo dphys-swapfile swapoff
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=1024/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

---

## 5. Directory Structure

```
/path/to/nertia/
|
|-- agent/
|   |-- __init__.py
|   |-- main.py              # Agent entry point (CLI + programmatic)
|   |-- config.py             # Settings, model selection, paths
|   |-- tools/
|   |   |-- __init__.py
|   |   |-- tasks.py          # Task CRUD tools
|   |   |-- calendar.py       # CalDAV tools (via caldav library)
|   |   |-- schedule.py       # Schedule generation tools
|   |   |-- notifications.py  # ntfy tools
|   |   |-- profile.py        # User profile/preference tools
|   |   |-- feedback.py       # Completion tracking, adaptation tools
|   |-- prompts/
|   |   |-- system.py         # System prompt with user context
|   |   |-- scheduling.py     # Scheduling rules and constraints
|   |
|-- db/
|   |-- __init__.py
|   |-- schema.sql            # SQLite schema
|   |-- migrations/           # Manual migration scripts
|   |-- database.py           # DB connection + helpers
|   |
|-- web/
|   |-- app.py                # FastAPI app
|   |-- routers/
|   |   |-- chat.py           # POST /chat -> agent interaction
|   |   |-- schedule.py       # GET /schedule/today, etc.
|   |   |-- tasks.py          # GET /tasks (read-only, for PWA display)
|   |-- static/               # PWA files
|   |   |-- index.html
|   |   |-- app.js
|   |   |-- style.css
|   |   |-- manifest.json
|   |   |-- sw.js             # Service worker
|   |
|-- scripts/
|   |-- morning_briefing.py   # Cron: generate daily schedule + notify
|   |-- periodic_nudge.py     # Cron: check schedule, send reminders
|   |-- weekly_review.py      # Cron: weekly summary + adaptation
|   |
|-- systemd/
|   |-- nertia-web.service
|   |-- radicale.service
|   |-- ntfy.service
|   |
|-- .env                      # ANTHROPIC_API_KEY, NTFY_TOKEN, etc.
|-- requirements.txt
|-- README.md
```

---

## 6. Database Schema

```sql
-- User profile and preferences
CREATE TABLE profile (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Seeded with: wake_time, sleep_time, exercise_preference, focus_peak_am,
-- focus_peak_pm, energy_dip_start, energy_dip_end, etc.

-- Task buckets
CREATE TABLE buckets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    description TEXT
);
-- Seeded with: Now, Career, Marriage & Faith, Personal Growth,
-- Health, Projects, Theology & Philosophy, Admin

-- Tasks
CREATE TABLE tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bucket_id   INTEGER NOT NULL REFERENCES buckets(id),
    title       TEXT NOT NULL,
    description TEXT,
    priority    INTEGER NOT NULL DEFAULT 3,  -- 1=highest, 5=lowest
    status      TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','in_progress','done','deferred')),
    due_date    TEXT,                         -- ISO 8601 date
    est_minutes INTEGER,                     -- estimated duration
    energy_level TEXT CHECK(energy_level IN ('high','medium','low')),  -- required energy
    recurring   TEXT,                         -- cron expression or null
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    tags        TEXT                          -- comma-separated
);

-- Daily schedules (generated by agent)
CREATE TABLE schedules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,               -- ISO 8601 date
    generated_at TEXT NOT NULL DEFAULT (datetime('now')),
    schedule_json TEXT NOT NULL,             -- JSON array of time blocks
    model_used  TEXT NOT NULL,               -- which Claude model generated it
    accepted    INTEGER DEFAULT 0            -- did user accept/use this schedule?
);

-- Schedule blocks (denormalized from schedule_json for querying)
CREATE TABLE schedule_blocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id INTEGER NOT NULL REFERENCES schedules(id),
    start_time  TEXT NOT NULL,               -- HH:MM
    end_time    TEXT NOT NULL,               -- HH:MM
    task_id     INTEGER REFERENCES tasks(id),
    activity    TEXT NOT NULL,               -- description if not a task
    block_type  TEXT NOT NULL CHECK(block_type IN (
        'deep_work','shallow_work','exercise','meal','faith','rest','personal','admin'
    )),
    completed   INTEGER DEFAULT 0,
    skipped     INTEGER DEFAULT 0,
    notes       TEXT
);

-- Agent conversation log (for context persistence)
CREATE TABLE conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    role        TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content     TEXT NOT NULL,
    model_used  TEXT,
    tokens_in   INTEGER,
    tokens_out  INTEGER
);

-- Feedback / adaptation data
CREATE TABLE feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,
    block_id        INTEGER REFERENCES schedule_blocks(id),
    actual_start    TEXT,
    actual_end      TEXT,
    energy_rating   INTEGER CHECK(energy_rating BETWEEN 1 AND 5),
    focus_rating    INTEGER CHECK(focus_rating BETWEEN 1 AND 5),
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- API usage tracking
CREATE TABLE api_usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    model       TEXT NOT NULL,
    tokens_in   INTEGER NOT NULL,
    tokens_out  INTEGER NOT NULL,
    cost_usd    REAL NOT NULL,
    trigger     TEXT NOT NULL  -- 'chat', 'morning_briefing', 'nudge', 'weekly_review'
);

-- Indexes
CREATE INDEX idx_tasks_bucket ON tasks(bucket_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_due ON tasks(due_date);
CREATE INDEX idx_schedules_date ON schedules(date);
CREATE INDEX idx_blocks_schedule ON schedule_blocks(schedule_id);
CREATE INDEX idx_blocks_date ON schedule_blocks(schedule_id, start_time);
CREATE INDEX idx_api_usage_date ON api_usage(timestamp);
CREATE INDEX idx_conversations_date ON conversations(timestamp);
```

---

## 7. Agent Tools (MCP)

All tools are defined as in-process MCP tools via `@tool` decorator from
`claude-agent-sdk`. They run inside the agent Python process -- no separate
servers or subprocesses.

### Task Tools (`agent/tools/tasks.py`)

| Tool Name         | Description                              | Parameters                                      |
|-------------------|------------------------------------------|------------------------------------------------|
| `list_tasks`      | List tasks, filterable by bucket/status  | bucket?, status?, limit?                        |
| `add_task`        | Create a new task                        | title, bucket, priority?, description?, due_date?, est_minutes?, energy_level?, tags? |
| `update_task`     | Update task fields                       | task_id, fields to update (any column)          |
| `complete_task`   | Mark a task as done                      | task_id, notes?                                 |
| `defer_task`      | Defer a task to a new date               | task_id, new_due_date, reason?                  |
| `search_tasks`    | Full-text search across tasks            | query                                           |
| `get_buckets`     | List all buckets with task counts        | -                                               |

### Calendar Tools (`agent/tools/calendar.py`)

| Tool Name         | Description                              | Parameters                                      |
|-------------------|------------------------------------------|------------------------------------------------|
| `add_event`       | Create a calendar event in Radicale      | title, start_datetime, end_datetime, description? |
| `list_events`     | List events for a date range             | start_date, end_date                            |
| `delete_event`    | Remove a calendar event                  | event_uid                                       |
| `find_free_slots` | Find available time blocks for a date    | date, min_duration_minutes?                     |

### Schedule Tools (`agent/tools/schedule.py`)

| Tool Name               | Description                                    | Parameters                  |
|-------------------------|------------------------------------------------|-----------------------------|
| `generate_daily_schedule`| Create an optimized schedule for a given date  | date, preferences?          |
| `get_todays_schedule`   | Retrieve today's active schedule               | -                           |
| `get_next_block`        | What should I be doing right now?              | -                           |
| `adjust_schedule`       | Re-optimize remaining day after disruption     | reason, current_time        |

### Notification Tools (`agent/tools/notifications.py`)

| Tool Name         | Description                              | Parameters                          |
|-------------------|------------------------------------------|-------------------------------------|
| `send_notification`| Send a push notification via ntfy       | title, message, priority?, tags?    |
| `schedule_reminder`| Queue a notification for a future time  | title, message, send_at             |

### Profile Tools (`agent/tools/profile.py`)

| Tool Name            | Description                           | Parameters           |
|----------------------|---------------------------------------|----------------------|
| `get_profile`        | Get all user preferences              | -                    |
| `update_preference`  | Update a single preference            | key, value           |
| `get_user_context`   | Full context string for scheduling    | -                    |

### Feedback Tools (`agent/tools/feedback.py`)

| Tool Name             | Description                                  | Parameters                              |
|-----------------------|----------------------------------------------|-----------------------------------------|
| `log_block_feedback`  | Record how a schedule block actually went    | block_id, completed?, energy?, focus?, notes? |
| `get_completion_stats`| Completion rates by bucket/block_type/day    | period (week/month), group_by?          |
| `get_adaptation_insights` | Analyze patterns for schedule improvement | -                                       |

---

## 8. Scheduling Engine Design

The scheduling engine is NOT a deterministic algorithm. It's Claude with
structured context and constraints. This is the key insight: Claude IS the
scheduling engine. We provide it with data and rules; it reasons about the
optimal schedule.

### Input Context (assembled by `get_user_context` tool)

```
User Profile:
- Wake: 6:15 AM, Sleep target: 10:00 PM
- Morning routine: prayer + Bible study (30 min, non-negotiable, first thing)
- Exercise preference: short runs, bike, weights (flexible timing)
- Evening routine: after dinner (~7:00 PM)
- Weekly activity (piano, etc.)
- Coffee reduction goal: max 2 cups, none after 1 PM

Circadian Model:
- Peak focus AM: 9:00-11:30 (deep work — career tasks, coding)
- Energy dip: 1:00-2:30 PM (shallow work, admin, or rest)
- Peak focus PM: 3:00-5:00 (second wind — moderate complexity)
- Wind-down: 8:30 PM+ (reading, reflection, prep for tomorrow)

Ultradian rhythm: 90-min work blocks with 15-min breaks

Today's Tasks (from DB, ranked by priority and bucket):
[... dynamic ...]

Today's Calendar Events (from Radicale):
[... dynamic ...]

Recent Feedback Patterns:
- Completion rate this week: X%
- Consistently skipped: [...]
- Energy mismatches: [...]
```

### Output Format

The agent generates a JSON schedule:
```json
[
    {"start": "06:15", "end": "06:45", "activity": "Prayer & Bible Study", "type": "faith", "task_id": null},
    {"start": "06:45", "end": "07:15", "activity": "Morning run", "type": "exercise", "task_id": 42},
    {"start": "07:15", "end": "07:45", "activity": "Shower + breakfast", "type": "meal", "task_id": null},
    {"start": "07:45", "end": "09:15", "activity": "Resume optimization for quick apply", "type": "deep_work", "task_id": 12},
    {"start": "09:15", "end": "09:30", "activity": "Break", "type": "rest", "task_id": null},
    ...
]
```

### Scheduling Rules (in system prompt)

1. Non-negotiables go first: prayer/Bible study at wake, evening routine after dinner
2. High-energy tasks during AM peak (9:00-11:30): career work, deep coding
3. Low-energy tasks during afternoon dip (1:00-2:30): email, admin, errands
4. Exercise: schedule during energy transitions, not during peaks
5. 90-minute focus blocks max, then 15-min break
6. No meetings/commitments stacked back-to-back without buffer
7. Leave 30 min unscheduled per 4 hours for overflow
8. Career bucket gets priority weighting during active job search
9. At least one "marriage/faith" and one "health" block per day
10. Adapt based on feedback: if user consistently skips a slot type, suggest alternative times

---

## 9. Build Phases

### Phase 1: Foundation — CLI Agent + Task Management
**Goal:** Chat with your AI assistant from the terminal, manage tasks.
**Duration estimate:** Weekend project

**Tasks:**
- [ ] Set up project directory and virtualenv on RPi
- [ ] Install Python 3.11+, pip, create venv
- [ ] `pip install claude-agent-sdk aiosqlite python-dotenv`
- [ ] Create `.env` with `ANTHROPIC_API_KEY`
- [ ] Write `db/schema.sql` and `db/database.py` (async SQLite helpers)
- [ ] Run schema, seed buckets and initial profile data
- [ ] Implement task tools: `add_task`, `list_tasks`, `complete_task`, `update_task`, `get_buckets`
- [ ] Implement profile tools: `get_profile`, `get_user_context`
- [ ] Write `agent/main.py` — interactive CLI loop using `ClaudeSDKClient`
- [ ] Write system prompt in `agent/prompts/system.py`
- [ ] Configure model selection: Haiku for task CRUD, Sonnet for planning
- [ ] Test: add tasks, list by bucket, complete tasks, all via natural language

**Deliverable:** Working CLI agent that manages your task buckets.

```bash
$ python -m agent.main
You: Add "update resume for data science roles" to Career bucket, high priority
Agent: Added task #1 "Update resume for data science roles" to Career (priority 1).
You: What's in my Career bucket?
Agent: You have 1 task in Career:
  1. [TODO] Update resume for data science roles (priority 1)
```

---

### Phase 2: Calendar + Schedule Generation
**Goal:** Agent generates optimized daily schedules using circadian science.

**Tasks:**
- [ ] Install Radicale: `pip install radicale`
- [ ] Configure Radicale: auth, storage path, port 5232
- [ ] Create systemd service for Radicale
- [ ] Install caldav library: `pip install caldav`
- [ ] Implement calendar tools: `add_event`, `list_events`, `find_free_slots`
- [ ] Implement schedule tools: `generate_daily_schedule`, `get_todays_schedule`, `get_next_block`
- [ ] Write scheduling prompt with circadian rules in `agent/prompts/scheduling.py`
- [ ] Add `schedules` and `schedule_blocks` tables
- [ ] Test: generate a full day schedule, view it, modify it via chat
- [ ] Sync generated schedule blocks to Radicale as calendar events

**Deliverable:** Agent produces a science-based daily schedule. Calendar
events visible in any CalDAV client (iOS Calendar app via Tailscale).

```bash
You: Generate my schedule for tomorrow
Agent: Here's your optimized schedule for March 8:

  06:15-06:45  Prayer & Bible Study [faith]
  06:45-07:15  Morning run [exercise]
  07:15-07:45  Breakfast [meal]
  07:45-09:15  Update resume for data science roles [deep_work]
  09:15-09:30  Break [rest]
  09:30-11:00  LinkedIn networking — draft messages [deep_work]
  ...

  I've added these as events to your calendar. Want me to adjust anything?
```

---

### Phase 3: Notifications + Proactive Agent
**Goal:** Agent reaches out to YOU, not just responds.

**Tasks:**
- [ ] Install ntfy server on RPi (binary or from package)
- [ ] Configure ntfy: auth tokens, topic for nertia
- [ ] Create systemd service for ntfy
- [ ] Install ntfy iOS app, configure with Tailscale IP
- [ ] Implement notification tools: `send_notification`
- [ ] Write `scripts/morning_briefing.py`:
  - Runs via cron at 6:00 AM
  - Agent generates today's schedule
  - Sends summary notification to phone
- [ ] Write `scripts/periodic_nudge.py`:
  - Runs every 30 min during waking hours
  - Checks current schedule block
  - Sends reminder if transition upcoming
  - Uses Haiku (cheap, fast)
- [ ] Write `scripts/weekly_review.py`:
  - Runs Sunday evening
  - Agent (Sonnet) analyzes the week's completion data
  - Generates insights and next week's priorities
  - Sends summary notification
- [ ] Set up cron jobs / systemd timers for all scripts
- [ ] Add `api_usage` tracking to monitor costs

**Deliverable:** Wake up to a daily briefing on your phone. Get nudged
throughout the day. Weekly review auto-generated.

---

### Phase 4: PWA Frontend
**Goal:** Chat with the agent and view schedules from your phone browser.

**Tasks:**
- [ ] Set up FastAPI app in `web/app.py`
- [ ] Create systemd service for FastAPI + Uvicorn
- [ ] Implement routes:
  - `POST /api/chat` — send message, stream agent response
  - `GET /api/schedule/today` — today's schedule blocks
  - `GET /api/schedule/{date}` — schedule for any date
  - `GET /api/tasks` — all tasks (filterable)
  - `GET /api/tasks/buckets` — bucket summary
  - `GET /api/stats` — completion rates, API costs
- [ ] Build PWA frontend (vanilla JS, no framework):
  - Chat interface (primary view)
  - Schedule timeline view (today's blocks as a visual timeline)
  - Task board (kanban-style by bucket or simple list)
  - Stats dashboard (completion rates, streaks)
- [ ] PWA manifest + service worker for offline shell
- [ ] Mobile-first responsive design
- [ ] Test via Tailscale from phone and laptop

**Deliverable:** Full mobile-friendly web app accessible from any device
on your Tailscale network.

---

### Phase 5: Feedback Loop + Adaptation
**Goal:** The system learns what works for YOU specifically.

**Tasks:**
- [ ] Implement feedback tools: `log_block_feedback`, `get_completion_stats`, `get_adaptation_insights`
- [ ] Add quick-feedback buttons in PWA: "Done" / "Skipped" / "Modified" per block
- [ ] Add optional energy + focus rating (1-5) per block
- [ ] Build `get_adaptation_insights` tool:
  - Queries feedback table for patterns
  - Returns structured insights like:
    - "Exercise blocks after 5 PM are skipped 80% of the time"
    - "Deep work blocks before 9 AM have highest focus ratings"
    - "Career tasks get deferred most on Fridays"
- [ ] Inject adaptation insights into scheduling prompt
- [ ] Agent uses insights when generating new schedules
- [ ] Add conversation memory: agent recalls prior discussions via `conversations` table
- [ ] Weekly review script now includes trend analysis

**Deliverable:** Schedules that improve over time. The agent says things like
"I notice you've been skipping afternoon workouts — want me to move exercise
to your morning slot?"

---

### Phase 6: Integrations (Stretch)
**Goal:** Connect to external services for richer automation.

**Potential integrations:**
- [ ] GitHub API tool — track portfolio repos, issues, PRs
- [ ] LinkedIn tracking — log applications, follow-ups (manual entry via agent)
- [ ] Bible reading plan tool — track progress through a reading plan
- [ ] Weather API tool — agent considers weather for outdoor exercise scheduling
- [ ] Fitness tracking — manual logging or integration with Apple Health (export)
- [ ] Grocery/meal planning tools
- [ ] Check for existing MCP servers before building custom tools

---

## 10. API Endpoints (PWA Backend)

### Chat
```
POST /api/chat
Body: { "message": "string" }
Response: Server-Sent Events stream of agent response chunks
```

### Schedule
```
GET /api/schedule/today
GET /api/schedule/{date}      # YYYY-MM-DD
POST /api/schedule/generate   # Trigger schedule generation for a date
POST /api/schedule/feedback   # Submit block feedback
```

### Tasks
```
GET  /api/tasks                # ?bucket=&status=&limit=
GET  /api/tasks/buckets        # Summary with counts
```

### Stats
```
GET /api/stats/completion      # ?period=week|month
GET /api/stats/api-usage       # ?period=week|month
```

All endpoints return JSON. Auth is not needed — Tailscale provides the
network boundary. Optionally add a simple bearer token if desired.

---

## 11. Cost Projections

### Claude API Costs (estimated monthly)

| Trigger            | Frequency        | Model       | Tokens/call (est.) | Monthly cost |
|--------------------|------------------|-------------|---------------------|-------------|
| Morning briefing   | 1x/day           | Sonnet 4.6  | 2K in, 1K out       | ~$0.63      |
| Periodic nudges    | 16x/day          | Haiku 4.5   | 500 in, 200 out     | ~$0.72      |
| Chat interactions  | ~10x/day         | Haiku 4.5   | 1K in, 500 out      | ~$1.05      |
| Weekly review      | 1x/week          | Sonnet 4.6  | 5K in, 2K out       | ~$0.19      |
| Schedule regen     | 2x/day           | Sonnet 4.6  | 3K in, 1K out       | ~$0.81      |
| **Total**          |                  |             |                     | **~$3.40**  |

These are rough estimates. Actual costs depend on conversation length and
context size. The `api_usage` table tracks real costs.

**Cost controls:**
- Haiku for all routine/simple queries (task CRUD, nudges, quick questions)
- Sonnet only for planning tasks (schedule generation, weekly review, complex reasoning)
- Cache user profile and scheduling rules in the system prompt (sent once per conversation)
- Set a monthly budget alert at $10 in the agent config
- Track cumulative spend in `api_usage` table; agent can refuse non-essential calls if over budget

---

## 12. Risk Register

| Risk                                    | Impact | Likelihood | Mitigation                                              |
|-----------------------------------------|--------|------------|---------------------------------------------------------|
| RPi 3 runs out of memory               | High   | Medium     | No Docker, monitor with htop, swap file, upgrade to Pi 4/5 |
| SD card corruption from frequent writes | Medium | Medium     | SQLite WAL mode, minimize writes, consider USB SSD boot  |
| Claude API costs exceed budget          | Medium | Low        | Tiered model usage, budget tracking, hard cap            |
| API latency makes agent feel slow       | Medium | Medium     | Haiku for interactive use (faster), cache common queries |
| Radicale CalDAV sync issues with iOS    | Low    | Medium     | Test early in Phase 2, fallback to direct schedule display|
| Anthropic API outage                    | Medium | Low        | Graceful degradation: show cached schedule, queue tasks  |
| Scope creep                             | High   | High       | Stick to phases, resist adding features mid-phase        |

---

## 13. Future / Stretch Goals

- **Voice interface** — Whisper on RPi 5 or API-based STT for hands-free interaction
- **Multi-user** — Members get their own agent/calendar (shared Radicale instance)
- **Local LLM fallback** — Small model on RPi 5 for offline basic queries
- **Home automation** — Agent controls smart home devices via Home Assistant MCP
- **Migrate to Pi 5** — 8GB RAM enables Docker, more services, local models
- **Email integration** — Agent drafts and sends follow-up emails
- **Revenue tracking** — For dev projects with revenue potential

---

## Quick Start (Phase 1)

```bash
# On the Raspberry Pi
cd /path/to/nertia
mkdir -p nertia/{agent/{tools,prompts},db/migrations,web/{routers,static},scripts,systemd}
cd nertia

python -m venv venv
source venv/bin/activate
pip install claude-agent-sdk aiosqlite python-dotenv

# Create .env
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Initialize database
sqlite3 nertia.db < db/schema.sql

# Run the agent
python -m agent.main
```

---

*Plan created: 2026-03-07*
*Last updated: 2026-03-07*
