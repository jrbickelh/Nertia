"""Ingest existing SQLite data into ChromaDB for RAG retrieval.

Run this periodically (e.g. nightly) to keep the knowledge base up to date.
Can also be called on-demand after significant data changes.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from db.database import execute, init_db
from agent.rag.store import upsert_documents, count


async def ingest_tasks():
    """Ingest all tasks into the knowledge base."""
    rows = await execute(
        """SELECT t.id, t.title, t.description, t.priority, t.status,
                  t.due_date, t.est_minutes, t.energy_level, t.tags,
                  t.created_at, t.completed_at, b.name as bucket
           FROM tasks t JOIN buckets b ON t.bucket_id = b.id"""
    )
    if not rows:
        return 0

    ids, docs, metas = [], [], []
    for r in rows:
        doc = f"Task: {r['title']}"
        if r['description']:
            doc += f"\nDescription: {r['description']}"
        doc += f"\nBucket: {r['bucket']}, Priority: P{r['priority']}, Status: {r['status']}"
        if r['due_date']:
            doc += f", Due: {r['due_date']}"
        if r['tags']:
            doc += f", Tags: {r['tags']}"

        ids.append(f"task-{r['id']}")
        docs.append(doc)
        metas.append({
            "source": "tasks",
            "task_id": r['id'],
            "bucket": r['bucket'],
            "status": r['status'],
            "priority": r['priority'],
        })

    upsert_documents(ids, docs, metas)
    return len(ids)


async def ingest_schedule_blocks():
    """Ingest recent schedule blocks (last 30 days)."""
    rows = await execute(
        """SELECT sb.id, sb.start_time, sb.end_time, sb.activity, sb.block_type,
                  sb.completed, sb.skipped, s.date
           FROM schedule_blocks sb
           JOIN schedules s ON sb.schedule_id = s.id
           WHERE s.date >= date('now', '-30 days')
           ORDER BY s.date, sb.start_time"""
    )
    if not rows:
        return 0

    ids, docs, metas = [], [], []
    for r in rows:
        status = "completed" if r['completed'] else ("skipped" if r['skipped'] else "scheduled")
        doc = f"Schedule block on {r['date']}: {r['activity']} ({r['block_type']}) from {r['start_time']} to {r['end_time']}. Status: {status}"
        ids.append(f"block-{r['id']}")
        docs.append(doc)
        metas.append({
            "source": "schedule",
            "date": r['date'],
            "block_type": r['block_type'],
            "completed": bool(r['completed']),
        })

    upsert_documents(ids, docs, metas)
    return len(ids)


async def ingest_fitness():
    """Ingest fitness logs (last 60 days)."""
    rows = await execute(
        """SELECT id, user_id, date, log_type, activity, duration_minutes,
                  calories, distance_km, details
           FROM fitness_log
           WHERE date >= date('now', '-60 days')
           ORDER BY date DESC"""
    )
    if not rows:
        return 0

    ids, docs, metas = [], [], []
    for r in rows:
        doc = f"{r['log_type'].capitalize()} on {r['date']}: {r['activity'] or 'unspecified'}"
        if r['duration_minutes']:
            doc += f", {r['duration_minutes']} minutes"
        if r['calories']:
            doc += f", {r['calories']} kcal"
        if r['distance_km']:
            doc += f", {r['distance_km']} km"
        if r['details']:
            doc += f". Details: {r['details']}"

        ids.append(f"fitness-{r['id']}")
        docs.append(doc)
        metas.append({
            "source": "fitness",
            "user_id": r['user_id'],
            "date": r['date'],
            "log_type": r['log_type'],
        })

    upsert_documents(ids, docs, metas)
    return len(ids)


async def ingest_mood():
    """Ingest mood logs (last 60 days)."""
    rows = await execute(
        """SELECT id, user_id, logged_at, mood_score, energy, emotions, context, notes
           FROM mood_log
           WHERE logged_at >= datetime('now', '-60 days')
           ORDER BY logged_at DESC"""
    )
    if not rows:
        return 0

    ids, docs, metas = [], [], []
    for r in rows:
        doc = f"Mood log ({r['logged_at'][:10]}): score {r['mood_score']}/10, energy {r['energy'] or 'unknown'}"
        if r['emotions']:
            doc += f", feeling {r['emotions']}"
        if r['context'] and r['context'] != 'general':
            doc += f", context: {r['context']}"
        if r['notes']:
            doc += f". Notes: {r['notes']}"

        ids.append(f"mood-{r['id']}")
        docs.append(doc)
        metas.append({
            "source": "mood",
            "user_id": r['user_id'],
            "date": r['logged_at'][:10],
            "mood_score": r['mood_score'] or 0,
        })

    upsert_documents(ids, docs, metas)
    return len(ids)


async def ingest_bible():
    """Ingest Bible reading logs."""
    rows = await execute(
        """SELECT id, user_id, date, book, chapter_start, chapter_end, notes
           FROM bible_reading
           ORDER BY date DESC"""
    )
    if not rows:
        return 0

    ids, docs, metas = [], [], []
    for r in rows:
        end = r['chapter_end'] or r['chapter_start']
        doc = f"Bible reading on {r['date']}: {r['book']} chapters {r['chapter_start']}–{end}"
        if r['notes']:
            doc += f". Notes: {r['notes']}"

        ids.append(f"bible-{r['id']}")
        docs.append(doc)
        metas.append({
            "source": "bible",
            "user_id": r['user_id'],
            "date": r['date'],
            "book": r['book'],
        })

    upsert_documents(ids, docs, metas)
    return len(ids)


async def ingest_feedback():
    """Ingest schedule feedback (last 60 days)."""
    rows = await execute(
        """SELECT f.id, f.block_id, f.energy_rating, f.focus_rating,
                  f.notes, f.created_at,
                  sb.activity, sb.block_type, s.date
           FROM feedback f
           JOIN schedule_blocks sb ON f.block_id = sb.id
           JOIN schedules s ON sb.schedule_id = s.id
           WHERE f.created_at >= datetime('now', '-60 days')
           ORDER BY f.created_at DESC"""
    )
    if not rows:
        return 0

    ids, docs, metas = [], [], []
    for r in rows:
        doc = f"Feedback for '{r['activity']}' ({r['block_type']}) on {r['date']}"
        if r['energy_rating']:
            doc += f", energy: {r['energy_rating']}/5"
        if r['focus_rating']:
            doc += f", focus: {r['focus_rating']}/5"
        if r['notes']:
            doc += f". Notes: {r['notes']}"

        ids.append(f"feedback-{r['id']}")
        docs.append(doc)
        metas.append({
            "source": "feedback",
            "date": r['date'],
            "block_type": r['block_type'],
            "energy_rating": r['energy_rating'] or 0,
        })

    upsert_documents(ids, docs, metas)
    return len(ids)


async def run_full_ingest():
    """Run full ingestion of all data sources."""
    await init_db()

    results = {}
    results['tasks'] = await ingest_tasks()
    results['schedule'] = await ingest_schedule_blocks()
    results['fitness'] = await ingest_fitness()
    results['mood'] = await ingest_mood()
    results['bible'] = await ingest_bible()
    results['feedback'] = await ingest_feedback()

    total = sum(results.values())
    print(f"RAG ingest complete: {total} documents total")
    for source, n in results.items():
        print(f"  {source}: {n} documents")
    print(f"Collection size: {count()}")
    return results


if __name__ == "__main__":
    asyncio.run(run_full_ingest())
