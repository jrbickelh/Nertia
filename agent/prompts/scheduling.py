SCHEDULING_RULES = """\
## Schedule Generation Rules

You are generating an optimized daily schedule grounded in circadian science.

### Non-negotiables (always include, in order)
1. Morning faith routine — first thing after waking (check user profile for details)
2. Evening routine — after dinner (check user profile for evening_routine preference)
3. Existing calendar events — must be honoured as hard blocks

### Circadian time-of-day rules
- 06:15–07:00  Morning routine (prayer, Bible study, breakfast)
- 09:00–11:30  AM peak: deep work only — Career tasks, coding, writing
- 11:30–13:00  Transition: meetings, calls, shallow Career/Projects work
- 13:00–14:30  Energy dip: email, admin, errands, light reading
- 14:30–15:00  Short break or brief walk
- 15:00–17:00  PM second wind: moderate-complexity tasks (Projects, Personal Growth)
- 17:00–19:00  Transition: exercise window, meal prep, personal admin
- 19:00–19:30  Evening routine (per user profile)
- 19:30–20:30  Family time / personal
- 20:30–22:00  Wind-down: reading, reflection, tomorrow prep

### Block structure
- Max 90-minute focus block, then 15-min break
- Leave ~30 min per 4-hour window as unscheduled buffer
- Never stack two demanding blocks back-to-back without a break

### Task assignment rules
- energy_level=high  → AM or PM peak only
- energy_level=medium → any non-dip window
- energy_level=low   → energy dip (13:00–14:30) or wind-down
- Career bucket: priority weighting — schedule best slots during active job search
- Ensure at least one "health" block (exercise) and one "faith" block per day

### Output format
Return ONLY a JSON array of blocks — no surrounding text. Each block:
{
  "start": "HH:MM",
  "end": "HH:MM",
  "activity": "description",
  "type": "deep_work|shallow_work|exercise|meal|faith|rest|personal|admin",
  "task_id": null or integer
}
The array must cover 06:15 to 22:00 with no gaps.
"""
