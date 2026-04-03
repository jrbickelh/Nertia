// Nertia — Quick Log Widget (Alex)
// Scriptable.app — add as a Small or Medium widget
//
// SETUP:
//   1. Install Scriptable from the App Store
//   2. Copy this script into Scriptable — name it exactly: "Nertia Quick Log"
//   3. Add a Scriptable widget (Small works), select this script
//   4. Tap the widget → Scriptable opens → shows input prompt
//   5. Must be on the same WiFi as the Pi

// ── Config ─────────────────────────────────────────────────────────────────
const API_BASE = "http://10.0.0.72:8000"
const USER_ID  = 2   // Alex = 2

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
  if (!resp.token) throw new Error("Login failed — check Pi connection")
  Keychain.set(key, resp.token)
  return resp.token
}

// ── Send log to agent ──────────────────────────────────────────────────────
async function sendLog(token, message) {
  const req = new Request(`${API_BASE}/api/chat`)
  req.method = "POST"
  req.headers = {
    "Content-Type":   "application/json",
    "X-Session-Token": token,
  }
  req.body = JSON.stringify({ message })

  // API streams SSE; loadString() waits for full response then we parse chunks
  const raw = await req.loadString()

  let result = ""
  for (const line of raw.split("\n")) {
    if (line.startsWith("data: ") && !line.includes("[DONE]")) {
      try {
        const d = JSON.parse(line.slice(6))
        if (d.text) result += d.text
      } catch {}
    }
  }
  return result.trim() || "Logged!"
}

// ── Widget UI (shown on home screen) ──────────────────────────────────────
function buildWidget() {
  const widget = new ListWidget()
  widget.backgroundColor = new Color("#1C1C1E")
  widget.setPadding(16, 18, 16, 18)

  // Tapping opens Scriptable and runs this script to show the input prompt
  widget.url = `scriptable:///run?scriptName=${encodeURIComponent("Nertia Quick Log")}`

  // Icon
  const iconRow = widget.addStack()
  iconRow.centerAlignContent()
  const icon = iconRow.addText("🌿")
  icon.font = Font.systemFont(32)
  iconRow.addSpacer()

  widget.addSpacer(8)

  // Title
  const title = widget.addText("Quick Log")
  title.font = Font.boldSystemFont(16)
  title.textColor = Color.white()

  widget.addSpacer(4)

  // Subtitle
  const sub = widget.addText("Tap to log food, mood & more")
  sub.font = Font.systemFont(12)
  sub.textColor = new Color("#8E8E93")

  widget.addSpacer()

  // Footer hint
  const hint = widget.addText("Nertia ·  Alex")
  hint.font = Font.systemFont(10)
  hint.textColor = new Color("#48484A")

  return widget
}

// ── Quick-log presets shown in action sheet ────────────────────────────────
const PRESETS = [
  "Log breakfast",
  "Log lunch",
  "Log dinner",
  "Log a snack",
  "Log mood",
  "Log water intake",
  "Something else...",
]

// ── In-app flow (runs when widget is tapped) ───────────────────────────────
async function runInApp() {
  // Step 1: pick a preset or go custom
  const picker = new Alert()
  picker.title = "What would you like to log?"
  for (const p of PRESETS) {
    picker.addAction(p)
  }
  picker.addCancelAction("Cancel")

  const choice = await picker.present()
  if (choice === -1) {
    Script.complete()
    return
  }

  let message
  if (PRESETS[choice] === "Something else...") {
    // Custom text input
    const custom = new Alert()
    custom.title = "Quick Log"
    custom.message = "Describe what you'd like to log:"
    custom.addTextField("e.g. 2 eggs scrambled, coffee with oat milk")
    custom.addAction("Send")
    custom.addCancelAction("Cancel")
    const confirmed = await custom.present()
    if (confirmed === -1) { Script.complete(); return }
    message = custom.textFieldValue(0)
  } else {
    // Use preset as prompt, then ask for details
    const detail = new Alert()
    detail.title = PRESETS[choice]
    detail.message = "Add details (or just tap Send):"
    detail.addTextField("e.g. chicken salad, 450 cal")
    detail.addAction("Send")
    detail.addCancelAction("Cancel")
    const confirmed = await detail.present()
    if (confirmed === -1) { Script.complete(); return }
    const extras = detail.textFieldValue(0)
    message = extras ? `${PRESETS[choice]}: ${extras}` : PRESETS[choice]
  }

  if (!message || !message.trim()) {
    Script.complete()
    return
  }

  // Step 2: send to agent
  try {
    const token   = await getToken()
    const response = await sendLog(token, message)

    const done = new Alert()
    done.title = "Logged!"
    // Trim long agent responses for the dialog
    done.message = response.length > 250 ? response.substring(0, 247) + "…" : response
    done.addAction("Done")
    await done.present()
  } catch (e) {
    const err = new Alert()
    err.title = "Error"
    err.message = e.message || "Could not connect to Nertia"
    err.addAction("OK")
    await err.present()
  }
}

// ── Main ───────────────────────────────────────────────────────────────────
if (config.runsInWidget) {
  Script.setWidget(buildWidget())
} else {
  await runInApp()
}

Script.complete()
