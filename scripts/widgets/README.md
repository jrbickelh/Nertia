# Nertia iPhone Widgets (Scriptable)

## Requirements
- [Scriptable](https://apps.apple.com/us/app/scriptable/id1405459188) (free) installed on iPhone
- iPhone on the same WiFi as the Pi, OR Tailscale set up

## Scripts

| Script | Widget size | Default user |
|--------|-------------|--------------|
| `Nertia Schedule.js` | Medium or Large | Primary (user 1) |
| `Nertia Quick Log.js` | Small or Medium | Member (user 2) |

---

## Setup — Nertia Schedule

1. Open Scriptable → tap **+** → paste contents of `Nertia Schedule.js`
2. Name it **Nertia Schedule**
3. Long-press home screen → add widget → Scriptable → pick **Medium**
4. Tap the widget to configure → select **Nertia Schedule**

Shows: current block (highlighted) + next 4 upcoming blocks.
Tap widget → opens PWA in browser.

---

## Setup — Nertia Quick Log

1. Open Scriptable → tap **+** → paste contents of `Nertia Quick Log.js`
2. Name it exactly **Nertia Quick Log** (the tap-to-open URL uses this name)
3. Add a Small Scriptable widget → select **Nertia Quick Log**
4. Tap the widget → Scriptable opens → shows preset picker (Breakfast, Lunch, Dinner, Snack, Mood, Water, Custom)
5. Pick one → optionally add details → tap Send → response shows in a dialog

---

## Configuration

Open each `.js` file and set:
- `API_BASE` — your Pi's local IP and port, e.g. `http://192.168.1.x:8000`
- `USER_ID` — `1` for the primary user, `2` for the member user

---

## Troubleshooting

- **"Connection error"** — Make sure Pi is on and iPhone is on same WiFi. Check `API_BASE` IP matches Pi's IP (`hostname -I` on Pi).
- **"Login failed"** — Open Scriptable, run the script manually (play button) to see the full error.
- **Token refresh** — If the session expires (30 days), delete the Keychain entry by adding `Keychain.remove("nertia_token_1")` temporarily and running once.
- **Tailscale** — For widgets to work away from home, install Tailscale on both Pi and iPhone, then change `API_BASE` to your Tailscale Pi IP (e.g. `http://100.x.x.x:8000`)
