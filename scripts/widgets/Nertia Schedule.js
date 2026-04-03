// Nertia — Daily Schedule Widget
// Scriptable.app — add as a Medium or Large widget
//
// SETUP:
//   1. Install Scriptable from the App Store
//   2. Copy this script into Scriptable
//   3. Add a Scriptable widget (Medium recommended) and select this script
//   4. Must be on the same WiFi as the Pi, OR use Tailscale

// ── Config ─────────────────────────────────────────────────────────────────
const API_BASE = "http://10.0.0.72:8000"
const USER_ID  = 1   // Jordan = 1, Alex = 2

const TYPE_COLORS = {
  deep_work:    "#4A90E2",
  shallow_work: "#50C8C6",
  exercise:     "#F5A623",
  meal:         "#7ED321",
  faith:        "#9B59B6",
  rest:         "#95A5A6",
  personal:     "#E91E8C",
  admin:        "#F39C12",
}

const BG_COLOR  = new Color("#1C1C1E")
const DIM_COLOR = new Color("#8E8E93")
const FG_COLOR  = Color.white()

// ── Auth ───────────────────────────────────────────────────────────────────
async function getToken() {
  const key = `nertia_token_${USER_ID}`
  if (Keychain.contains(key)) {
    return Keychain.get(key)
  }
  const req = new Request(`${API_BASE}/api/auth/login`)
  req.method = "POST"
  req.headers = { "Content-Type": "application/json" }
  req.body = JSON.stringify({ user_id: USER_ID, remember_me: true })
  const resp = await req.loadJSON()
  if (!resp.token) throw new Error("Login failed")
  Keychain.set(key, resp.token)
  return resp.token
}

// ── Data ───────────────────────────────────────────────────────────────────
async function fetchSchedule(token) {
  const req = new Request(`${API_BASE}/api/schedule/today`)
  req.headers = { "X-Session-Token": token }
  return await req.loadJSON()
}

// ── Helpers ────────────────────────────────────────────────────────────────
function toMinutes(t) {
  const [h, m] = t.split(":").map(Number)
  return h * 60 + m
}

function formatTime(t) {
  const [h, m] = t.split(":").map(Number)
  const period = h < 12 ? "AM" : "PM"
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h
  return `${h12}:${m.toString().padStart(2, "0")} ${period}`
}

function nowMinutes() {
  const d = new Date()
  return d.getHours() * 60 + d.getMinutes()
}

function typeColor(type) {
  return new Color(TYPE_COLORS[type] || "#8E8E93")
}

// ── Widget builder ─────────────────────────────────────────────────────────
async function buildWidget(schedule, isLarge) {
  const widget = new ListWidget()
  widget.backgroundColor = BG_COLOR
  widget.setPadding(14, 16, 14, 16)
  widget.url = API_BASE  // tap opens PWA

  // Header row
  const header = widget.addStack()
  header.layoutHorizontally()
  header.centerAlignContent()

  const titleText = header.addText("Schedule")
  titleText.font = Font.boldSystemFont(14)
  titleText.textColor = FG_COLOR

  header.addSpacer()

  const now = new Date()
  const clockStr = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  const clock = header.addText(clockStr)
  clock.font = Font.systemFont(12)
  clock.textColor = DIM_COLOR

  widget.addSpacer(10)

  if (!schedule || !schedule.blocks || schedule.blocks.length === 0) {
    const msg = widget.addText("No schedule yet — open the app to generate one.")
    msg.font = Font.systemFont(12)
    msg.textColor = DIM_COLOR
    msg.centerAlignText()
    return widget
  }

  const nowM   = nowMinutes()
  const blocks = schedule.blocks.filter(b => !b.skipped && !b.completed)

  // Split into current and upcoming
  let current  = null
  const upcoming = []
  const maxUpcoming = isLarge ? 6 : 4

  for (const b of blocks) {
    const startM = toMinutes(b.start)
    const endM   = toMinutes(b.end)
    if (startM <= nowM && nowM < endM) {
      current = b
    } else if (startM > nowM && upcoming.length < maxUpcoming) {
      upcoming.push(b)
    }
  }

  // ── Current block ────────────────────────────────────────────────────────
  if (current) {
    const card = widget.addStack()
    card.layoutHorizontally()
    card.centerAlignContent()
    card.backgroundColor = new Color("#2C2C2E")
    card.cornerRadius = 10
    card.setPadding(8, 10, 8, 10)

    // Color bar on left
    const bar = card.addStack()
    bar.layoutVertically()
    bar.size = new Size(3, 36)
    bar.backgroundColor = typeColor(current.type)
    bar.cornerRadius = 2
    card.addSpacer(8)

    const col = card.addStack()
    col.layoutVertically()

    const nowTag = col.addText("NOW")
    nowTag.font = Font.boldSystemFont(9)
    nowTag.textColor = new Color("#FF9F0A")

    col.addSpacer(2)

    const act = col.addText(current.activity)
    act.font = Font.semiboldSystemFont(13)
    act.textColor = FG_COLOR
    act.lineLimit = 1

    card.addSpacer()

    const endLabel = card.addText(`until ${formatTime(current.end)}`)
    endLabel.font = Font.systemFont(10)
    endLabel.textColor = DIM_COLOR

    widget.addSpacer(8)
  }

  // Separator label if no current block
  if (!current && upcoming.length > 0) {
    const next = widget.addText("UPCOMING")
    next.font = Font.boldSystemFont(9)
    next.textColor = DIM_COLOR
    widget.addSpacer(6)
  }

  // ── Upcoming blocks ──────────────────────────────────────────────────────
  for (const b of upcoming) {
    const row = widget.addStack()
    row.layoutHorizontally()
    row.centerAlignContent()
    row.setPadding(4, 0, 4, 0)

    const dot = row.addText("●")
    dot.font = Font.systemFont(10)
    dot.textColor = typeColor(b.type)
    row.addSpacer(8)

    const act = row.addText(b.activity)
    act.font = Font.systemFont(12)
    act.textColor = new Color("#EBEBF5")
    act.lineLimit = 1

    row.addSpacer()

    const t = row.addText(formatTime(b.start))
    t.font = Font.systemFont(11)
    t.textColor = DIM_COLOR

    widget.addSpacer(2)
  }

  if (!current && upcoming.length === 0) {
    const msg = widget.addText("All done for today!")
    msg.font = Font.systemFont(13)
    msg.textColor = DIM_COLOR
    msg.centerAlignText()
  }

  // Footer
  widget.addSpacer()
  const footer = widget.addStack()
  footer.layoutHorizontally()
  const dateStr = now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })
  const dateLabel = footer.addText(dateStr)
  dateLabel.font = Font.systemFont(10)
  dateLabel.textColor = DIM_COLOR

  return widget
}

// ── Main ───────────────────────────────────────────────────────────────────
try {
  const token   = await getToken()
  const schedule = await fetchSchedule(token)
  const isLarge = config.widgetFamily === "large"
  const widget  = await buildWidget(schedule, isLarge)

  if (config.runsInWidget) {
    Script.setWidget(widget)
  } else {
    await widget.presentMedium()
  }
} catch (e) {
  // Error widget
  const w = new ListWidget()
  w.backgroundColor = new Color("#1C1C1E")
  w.setPadding(14, 16, 14, 16)
  const title = w.addText("Nertia")
  title.font = Font.boldSystemFont(14)
  title.textColor = Color.white()
  w.addSpacer(6)
  const err = w.addText(e.message || "Connection error")
  err.font = Font.systemFont(11)
  err.textColor = new Color("#FF453A")
  err.lineLimit = 3
  w.addSpacer()
  const hint = w.addText("Check Pi connection & WiFi")
  hint.font = Font.systemFont(10)
  hint.textColor = new Color("#636366")

  if (config.runsInWidget) Script.setWidget(w)
  else await w.presentSmall()
}

Script.complete()
