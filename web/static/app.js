'use strict';

// ── Settings (localStorage) ───────────────────────────────────────────────────
const S = {
  get: (k, d) => { const v = localStorage.getItem('lo_' + k); return v === null ? d : JSON.parse(v); },
  set: (k, v) => localStorage.setItem('lo_' + k, JSON.stringify(v)),
  del: (k)    => localStorage.removeItem('lo_' + k),
};

// ── Authenticated fetch ───────────────────────────────────────────────────────
async function apiFetch(url, options = {}) {
  const token = S.get('sessionToken', null);
  const headers = { ...(options.headers || {}) };
  if (token) headers['X-Session-Token'] = token;
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    S.del('sessionToken');
    S.del('userId');
    currentUserId = null;
    showLoginScreen();
    throw new Error('Session expired — please log in again');
  }
  return res;
}

// ── Theme ─────────────────────────────────────────────────────────────────────
function applyTheme() {
  const dark = S.get('darkMode', false);
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.getElementById('theme-color-meta').content = dark ? '#000000' : '#ffffff';
  document.getElementById('status-bar-meta').content  = dark ? 'black-translucent' : 'default';
}
applyTheme();

// ── Time formatting ───────────────────────────────────────────────────────────
const fmt12h = t => { const [h, m] = t.split(':').map(Number); return `${h % 12 || 12}:${String(m).padStart(2,'0')} ${h>=12?'PM':'AM'}`; };
const fmtTime = t => S.get('use12h', true) ? fmt12h(t) : t;

// ── Auth ──────────────────────────────────────────────────────────────────────
let currentUserId = null;

function isAuthValid() {
  return !!(S.get('sessionToken', null) && S.get('userId', null));
}

let _loginScreenShowing = false;
async function showLoginScreen() {
  if (_loginScreenShowing) return;
  _loginScreenShowing = true;
  const screen = document.getElementById('login-screen');
  screen.classList.remove('hidden');
  const list = document.getElementById('login-user-list');
  list.innerHTML = '';
  try {
    // Use plain fetch — no auth token needed for user list, avoids re-entrant 401 loop
    const data = await fetch('/api/users').then(r => r.json());
    data.users.forEach(u => addLoginUserBtn(list, u.id, u.name));
  } catch {
    [{id:1, name:'User 1'}, {id:2, name:'User 2'}].forEach(u => addLoginUserBtn(list, u.id, u.name));
  }
}

function addLoginUserBtn(list, uid, name) {
  const btn = document.createElement('button');
  btn.className = 'login-user-btn';
  btn.innerHTML = `<span class="login-user-avatar">${name[0].toUpperCase()}</span><span>${name}</span>`;
  btn.addEventListener('click', () => loginAs(uid));
  list.appendChild(btn);
}

async function loginAs(uid) {
  const rememberMe = document.getElementById('login-remember-me').checked;
  try {
    const data = await apiFetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: uid, remember_me: rememberMe }),
    }).then(r => r.json());
    S.set('sessionToken', data.token);
    S.set('userId', uid);
    currentUserId = uid;
    _loginScreenShowing = false;
    document.getElementById('login-screen').classList.add('hidden');
    document.getElementById('user-switcher').value = uid;
    checkMidayCheckin();
  } catch (e) {
    console.error('Login failed:', e);
  }
}

// Initialise auth on load
if (isAuthValid()) {
  currentUserId = S.get('userId', 1);
} else {
  S.del('userId');
  S.del('sessionToken');
  // Show after DOM ready
  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', showLoginScreen, { once: true });
  } else {
    showLoginScreen();
  }
}

// ── TTS ───────────────────────────────────────────────────────────────────────
let ttsEnabled = S.get('ttsEnabled', true);
let _ttsVoice  = null;
let _ttsUnlocked = false;

function _loadBestVoice() {
  // If user has a saved preference, that takes priority (handled by restore block above)
  if (S.get('ttsVoiceName', null)) return;
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return;
  // Priority: Premium > Enhanced > known warm voices > local en-US > any en
  // On iOS: download Siri voices via Settings → Accessibility → Spoken Content → Voices → English
  _ttsVoice = voices.find(v => /premium/i.test(v.name) && v.lang.startsWith('en'))
           || voices.find(v => /enhanced/i.test(v.name) && v.lang.startsWith('en'))
           || voices.find(v => ['Ava', 'Evan', 'Tom', 'Allison', 'Samantha'].some(n => v.name.startsWith(n)) && v.localService)
           || voices.find(v => v.localService && v.lang === 'en-US')
           || voices.find(v => v.lang === 'en-US' && !/google/i.test(v.name))
           || voices.find(v => v.lang.startsWith('en'))
           || null;
  console.log('TTS voice selected:', _ttsVoice?.name, '— all en voices:', voices.filter(v=>v.lang.startsWith('en')).map(v=>`${v.name}(${v.localService?'local':'net'})`).join(', '));
}
if ('speechSynthesis' in window) {
  window.speechSynthesis.addEventListener('voiceschanged', _loadBestVoice);
  _loadBestVoice();
}

// iOS requires a user gesture to unlock speechSynthesis
document.addEventListener('touchend', () => {
  if (_ttsUnlocked || !('speechSynthesis' in window)) return;
  const u = new SpeechSynthesisUtterance('');
  u.volume = 0;
  window.speechSynthesis.speak(u);
  _ttsUnlocked = true;
}, { once: true });
// Also unlock on click (desktop + iOS fallback)
document.addEventListener('click', () => {
  if (_ttsUnlocked || !('speechSynthesis' in window)) return;
  const u = new SpeechSynthesisUtterance('');
  u.volume = 0;
  window.speechSynthesis.speak(u);
  _ttsUnlocked = true;
}, { once: true });

// Restore saved voice on load
(function() {
  const restoreVoice = () => {
    const saved = S.get('ttsVoiceName', null);
    if (saved) {
      const v = window.speechSynthesis?.getVoices().find(v => v.name === saved);
      if (v) _ttsVoice = v;
    }
  };
  if ('speechSynthesis' in window) {
    window.speechSynthesis.addEventListener('voiceschanged', restoreVoice);
    restoreVoice();
  }
})();

function speak(text) {
  if (!ttsEnabled || !('speechSynthesis' in window)) return Promise.resolve();
  return new Promise(resolve => {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const rate = parseFloat(S.get('ttsRate', '0.90'));
    u.rate = rate; u.pitch = 1.05; u.lang = 'en-US'; u.volume = 1.0;
    if (_ttsVoice) u.voice = _ttsVoice;
    // iOS pauses speech after ~15s; keep-alive with periodic resume()
    const keepAlive = setInterval(() => {
      if ('speechSynthesis' in window) window.speechSynthesis.resume();
    }, 10000);
    const safetyMs = Math.max(text.length * 80, 6000);
    const timer = setTimeout(() => { clearInterval(keepAlive); resolve(); }, safetyMs);
    u.onend  = () => { clearInterval(keepAlive); clearTimeout(timer); resolve(); };
    u.onerror = () => { clearInterval(keepAlive); clearTimeout(timer); resolve(); };
    window.speechSynthesis.speak(u);
  });
}
function stopSpeaking() { window.speechSynthesis?.cancel(); }

// ── Router ────────────────────────────────────────────────────────────────────
let activeView = 'home';
const ALL_VIEWS = ['home', 'history', 'current', 'upcoming', 'settings', 'checkin'];

function showView(name) {
  // Clean up checkin conversation when navigating away
  if (activeView === 'checkin' && name !== 'checkin') {
    stopSpeaking(); stopRecognition();
    if (checkinConversation) { checkinConversation.destroy(); checkinConversation = null; }
  }
  ALL_VIEWS.forEach(v => document.getElementById('view-' + v)?.classList.toggle('active', v === name));
  activeView = name;
  closeMenu();
  if (name === 'upcoming') {
    if (activeSchedTab === 'day') loadSchedule(schedDate);
    else if (activeSchedTab === 'week') loadWeekView();
    else if (activeSchedTab === 'month') loadMonthView();
    ensureWeekSchedules();
  }
  if (name === 'home')     { initHomeForUser(); }
  if (name === 'current')  loadCurrent();
  if (name === 'history')  loadHistoryTab(activeHistTab);
  if (name === 'settings') { initSettingsUI(); loadFeatureToggles(); loadSharingSettings(); loadStats(); loadSupplements(); renderQuickCmdEditor(); loadWeatherSettings(); }
  if (name === 'checkin')  { startCheckinView(); }
}
document.querySelectorAll('.back-btn').forEach(b => b.addEventListener('click', () => showView('home')));

// ── Menu ──────────────────────────────────────────────────────────────────────
function openMenu() { document.getElementById('menu-overlay').classList.remove('hidden'); }
function closeMenu() { document.getElementById('menu-overlay').classList.add('hidden'); }
document.getElementById('menu-btn').addEventListener('click', openMenu);
document.getElementById('menu-backdrop').addEventListener('click', closeMenu);
document.querySelectorAll('.menu-item[data-view]').forEach(b => b.addEventListener('click', () => showView(b.dataset.view)));

// ── Speech recognition ────────────────────────────────────────────────────────
let recognition = null;
let _recogCallback = null;
let _recogInterim  = null;
let _listeningFor  = null;

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SR();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = 'en-US';
  recognition.onresult = e => {
    const t = Array.from(e.results).map(r => r[0].transcript).join('');
    _recogInterim?.(t);
    if (e.results[e.results.length - 1].isFinal) {
      const cb = _recogCallback;
      _recogCallback = null;
      cb?.(t);
    }
  };
  recognition.onend = () => setMicListeningUI(false);
  recognition.onerror = () => { setMicListeningUI(false); _recogCallback?.(''); };
}

function setMicListeningUI(active) {
  if (_listeningFor === 'home') {
    // handled by homeMicState
  } else if (_listeningFor === 'overlay') {
    document.getElementById('voice-mic-btn').classList.toggle('listening', active);
  } else if (_listeningFor === 'checkin') {
    document.getElementById('checkin-mic-btn')?.classList.toggle('listening', active);
  }
}

function startRecognition(forCtx, onInterim, onFinal) {
  if (!recognition) { onFinal?.(''); return; }
  try { recognition.abort(); } catch {}
  _listeningFor = forCtx;
  _recogInterim  = onInterim;
  _recogCallback = onFinal;
  setTimeout(() => { try { recognition.start(); } catch {} }, 120);
}

function stopRecognition() {
  try { recognition?.abort(); } catch {}
  _recogCallback = null; _recogInterim = null;
  setMicListeningUI(false);
}

// ── Midday check-in detection ─────────────────────────────────────────────────
let midayCheckinPending = false;
async function checkMidayCheckin() {
  if (!currentUserId || new Date().getHours() < 12) return;
  try {
    const d = await apiFetch(`/api/today/summary`).then(r => r.json());
    midayCheckinPending = !d.has_logs;
  } catch {}
}

// ── Inline home mic state machine ─────────────────────────────────────────────
let homeMicState = 'idle'; // idle | listening | processing | speaking
let inlineQuestionnaire = null;

function setHomeMicState(state) {
  homeMicState = state;
  const btn = document.getElementById('home-mic-btn');
  const inp = document.getElementById('home-text-input');
  btn?.classList.toggle('listening',  state === 'listening');
  btn?.classList.toggle('processing', state === 'processing');
  btn?.classList.toggle('speaking',   state === 'speaking');
  if (inp) {
    inp.placeholder = state === 'idle'       ? 'Ask anything…'
                    : state === 'listening'  ? 'Listening…'
                    : state === 'processing' ? 'Thinking…'
                    : 'Speaking…';
    inp.disabled = state !== 'idle';
  }
}

// ── Home chat window (last exchange) ─────────────────────────────────────────
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Store full conversation history for expanded view
let homeChatHistory = [];

function updateHomeChatWindow(userText, agentText) {
  homeChatHistory.push({ user: userText, agent: agentText });
  if (homeChatHistory.length > 50) homeChatHistory = homeChatHistory.slice(-50);
  const el = document.getElementById('home-chat');
  if (!el) return;
  el.innerHTML =
    `<div class="hc-row"><span class="hc-who">You</span><span class="hc-text">${escHtml(userText||'')}</span></div>` +
    `<div class="hc-row"><span class="hc-who">Agent</span><span class="hc-text">${escHtml(agentText||'')}</span></div>`;
  el.classList.remove('empty');
}

// Tap home-chat to expand into full overlay
document.getElementById('home-chat').addEventListener('click', () => {
  if (document.getElementById('home-chat').classList.contains('empty')) return;
  openChatOverlay();
});

let _respTimer = null;
function showMicResponse(text, ms = 9000) {
  const el = document.getElementById('mic-response');
  clearTimeout(_respTimer);
  el.textContent = text;
  el.classList.remove('fading');
  el.classList.add('visible');
  if (ms > 0) {
    _respTimer = setTimeout(() => {
      el.classList.add('fading');
      setTimeout(() => { el.classList.remove('visible', 'fading'); el.textContent = ''; }, 600);
    }, ms);
  }
}
function clearMicResponse() {
  clearTimeout(_respTimer);
  const el = document.getElementById('mic-response');
  el.classList.remove('visible', 'fading');
  el.textContent = '';
}

document.getElementById('home-mic-btn')?.addEventListener('click', async () => {
  if (homeMicState !== 'idle') {
    stopRecognition(); stopSpeaking();
    if (inlineQuestionnaire) { inlineQuestionnaire._cancelled = true; inlineQuestionnaire = null; }
    setHomeMicState('idle'); clearMicResponse(); return;
  }
  await inlineVoiceCommand();
});

// Home text input — opens chat overlay and sends through it
async function sendHomeText() {
  const inp = document.getElementById('home-text-input');
  const text = inp.value.trim();
  if (!text || homeMicState !== 'idle') return;
  inp.value = '';
  openChatOverlay();
  chatTextIn.value = text;
  await sendChatMessage();
}
document.getElementById('home-text-send').addEventListener('click', sendHomeText);
document.getElementById('home-text-input').addEventListener('keydown', e => { if (e.key === 'Enter') sendHomeText(); });

// Check-in menu item — opens dedicated check-in page

async function inlineVoiceCommand() {
  setHomeMicState('listening');
  clearMicResponse();

  const transcript = await new Promise(resolve => {
    startRecognition('home',
      interim => { document.getElementById('mic-response').textContent = interim; },
      final   => resolve(final)
    );
    setTimeout(() => resolve(null), 10000);
  });

  if (!transcript?.trim()) { setHomeMicState('idle'); clearMicResponse(); return; }

  clearMicResponse();
  setHomeMicState('idle');
  // Open overlay and send through it (keeps conversation history + full streaming UI)
  openChatOverlay();
  chatTextIn.value = transcript;
  await sendChatMessage();
}

async function inlineTextCommand(text) {
  setHomeMicState('processing');
  showMicResponse('Thinking…', 0);
  let full = '';
  try {
    const res = await apiFetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, history: homeChatHistory.slice(-6) }),
    });
    const reader = res.body.getReader();
    const dec = new TextDecoder(); let buf = '';
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop();
      for (const l of lines) {
        if (!l.startsWith('data: ')) continue;
        const raw = l.slice(6).trim(); if (raw === '[DONE]') break;
        try { const o = JSON.parse(raw); if (o.text) full += o.text; } catch {}
      }
    }
  } catch { full = 'Sorry, something went wrong.'; }
  clearMicResponse();
  updateHomeChatWindow(text, full);
  setHomeMicState('speaking');
  await speak(full);
  setHomeMicState('idle');
}

async function inlineOfferCheckin(context) {
  const offer = 'Would you like a quick mood check-in? Say yes, or no to skip.';
  showMicResponse(offer, 0);
  setHomeMicState('speaking');
  await speak(offer);
  setHomeMicState('listening');

  const answer = await new Promise(resolve => {
    startRecognition('home', null, t => resolve(t));
    setTimeout(() => resolve(null), 7000);
  });

  setHomeMicState('idle');
  if (answer && /yes|yeah|sure|okay|ok|go ahead/i.test(answer)) {
    inlineQuestionnaire = new InlineQuestionnaire(context);
    await inlineQuestionnaire.start();
  } else {
    const bye = 'No problem. Have a great rest of your day!';
    showMicResponse(bye);
    await speak(bye);
  }
}

// ── Inline Questionnaire ──────────────────────────────────────────────────────
class InlineQuestionnaire {
  constructor(context = 'general') {
    this.context = context;
    this.answers = {};
    this.idx = 0;
    this._cancelled = false;
    this.questions = this._buildQuestions();
  }

  _buildQuestions() {
    const qs = [];
    if (this.context === 'meal')    qs.push({ id: 'meal_rating',    ask: 'How satisfying was that meal? Say great, good, okay, or not great.' });
    if (this.context === 'workout') qs.push({ id: 'workout_feel',   ask: 'How did that workout feel? Excellent, good, tough, or exhausting?' });
    qs.push({ id: 'mood',     ask: 'On a scale of 1 to 10, how would you rate your mood right now?' });
    qs.push({ id: 'energy',   ask: 'How are your energy levels? Say high, medium, or low.' });
    qs.push({ id: 'emotions', ask: 'Any emotions to note — happy, grateful, tired, anxious? Say skip to move on.' });
    qs.push({ id: 'notes',    ask: 'Any final thoughts? Say skip to finish.' });
    return qs;
  }

  get total() { return this.questions.length; }

  async start() {
    setHomeMicState('speaking');
    showMicResponse(`Starting check-in…`, 0);
    await speak('Great! Let me ask you a few quick questions.');
    if (!this._cancelled) await this._askCurrent();
  }

  async _askCurrent() {
    if (this._cancelled) return;
    if (this.idx >= this.questions.length) { await this._finish(); return; }
    const q = this.questions[this.idx];
    showMicResponse(`${this.idx + 1} / ${this.total} — ${q.ask}`, 0);
    setHomeMicState('speaking');
    await speak(q.ask);
    if (this._cancelled) return;
    setHomeMicState('listening');

    const answer = await new Promise(resolve => {
      startRecognition('home',
        t => showMicResponse(t, 0),
        t => resolve(t)
      );
      setTimeout(() => resolve(null), 12000);
    });

    if (this._cancelled) return;
    if (answer) await this._receiveAnswer(answer);
    else { this.idx++; await this._askCurrent(); }
  }

  async _receiveAnswer(text) {
    const lower = text.toLowerCase().trim();
    const q = this.questions[this.idx];

    if (q.id === 'mood') {
      const m = lower.match(/\b(10|[1-9])\b/);
      if (m) {
        this.answers.mood_score = parseInt(m[1]);
      } else {
        await speak('Please give me a number from 1 to 10.');
        await this._askCurrent(); return;
      }
    } else if (q.id === 'energy') {
      this.answers.energy = lower.includes('high') ? 'high' : lower.includes('low') ? 'low' : 'medium';
    } else {
      if (!/skip|no|nothing|none|nope/i.test(lower)) this.answers[q.id] = text;
    }
    this.idx++;
    await this._askCurrent();
  }

  async _finish() {
    const EMOTION_WORDS = ['happy','grateful','motivated','calm','content','tired','anxious','stressed','sad','frustrated'];
    const emoText = (this.answers.emotions || '').toLowerCase();
    const emotions = EMOTION_WORDS.filter(e => emoText.includes(e));
    const notes = [this.answers.notes, this.answers.meal_rating, this.answers.workout_feel].filter(Boolean).join('; ');
    const score = this.answers.mood_score;

    try {
      await apiFetch('/api/mood', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: currentUserId, mood_score: score ?? null, energy: this.answers.energy ?? null, emotions, context: this.context, notes: notes || null }),
      });
    } catch {}

    const closing = score >= 8 ? 'Glad to hear you\'re feeling great!'
                  : score >= 5 ? 'Thanks for checking in — keep going!'
                  : score ? 'Thank you for sharing. Take good care of yourself.'
                  : 'Check-in complete. Have a great rest of your day!';

    showMicResponse(`Check-in saved. ${closing}`);
    setHomeMicState('speaking');
    await speak(`Check-in saved. ${closing}`);
    setHomeMicState('idle');
    midayCheckinPending = false;
    // mic-label removed from home view — no-op
    inlineQuestionnaire = null;
    if (activeView === 'history' && activeHistTab === 'mood') loadMoodHistory();
  }
}

// ── Check-in view ──────────────────────────────────────────────────────────────
let checkinConversation = null;
let _checkinMicState = 'idle';

function setCheckinMicState(state) {
  _checkinMicState = state;
  const btn   = document.getElementById('checkin-mic-btn');
  const label = document.getElementById('checkin-mic-label');
  if (!btn) return;
  btn.classList.toggle('listening',   state === 'listening');
  btn.classList.toggle('processing',  state === 'processing');
  btn.classList.toggle('speaking',    state === 'speaking');
  if (label) {
    if (state === 'idle')       label.textContent = 'Tap to speak';
    if (state === 'listening')  label.textContent = 'Listening…';
    if (state === 'processing') label.textContent = 'Thinking…';
    if (state === 'speaking')   label.textContent = 'Speaking…';
  }
}

class CheckinConversation {
  constructor() { this._active = true; }

  destroy() {
    this._active = false;
    setCheckinMicState('idle');
  }

  appendMsg(role, text) {
    const el = document.getElementById('checkin-messages');
    if (!el) return null;
    const div = document.createElement('div');
    div.className = `ci-msg ci-${role}`;
    div.textContent = text;
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
    return div;
  }

  async _streamToDiv(message, agentDiv) {
    let full = '';
    try {
      const res = await apiFetch('/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      });
      const reader = res.body.getReader();
      const dec = new TextDecoder(); let buf = '';
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n'); buf = lines.pop();
        for (const l of lines) {
          if (!l.startsWith('data: ')) continue;
          const raw = l.slice(6).trim(); if (raw === '[DONE]') break;
          try { const o = JSON.parse(raw); if (o.text) { full += o.text; agentDiv.textContent = full; document.getElementById('checkin-messages')?.scrollTo({ top: 9999 }); } } catch {}
        }
      }
    } catch { full = full || 'Something went wrong.'; agentDiv.textContent = full; }
    agentDiv.classList.remove('streaming');
    return full;
  }

  async start() {
    if (!this._active) return;
    setCheckinMicState('processing');
    const agentDiv = this.appendMsg('agent', '');
    agentDiv?.classList.add('streaming');
    const greeting = await this._streamToDiv(
      'Begin my daily check-in. Greet me and ask how I\'m doing. Keep it brief and conversational.',
      agentDiv,
    );
    if (!this._active) return;
    setCheckinMicState('speaking');
    await speak(greeting);
    if (!this._active) return;
    setCheckinMicState('idle');
  }

  async sendMessage(text) {
    if (!this._active || !text?.trim()) return;
    this.appendMsg('user', text);
    setCheckinMicState('processing');
    const agentDiv = this.appendMsg('agent', '');
    agentDiv?.classList.add('streaming');
    const reply = await this._streamToDiv(text, agentDiv);
    if (!this._active) return;
    setCheckinMicState('speaking');
    await speak(reply);
    if (!this._active) return;
    setCheckinMicState('idle');
  }

  async listenAndSend() {
    if (_checkinMicState !== 'idle') {
      stopRecognition(); stopSpeaking();
      setCheckinMicState('idle'); return;
    }
    if (!this._active) return;
    setCheckinMicState('listening');
    const transcript = await new Promise(resolve => {
      startRecognition('checkin', null, t => resolve(t));
      setTimeout(() => resolve(null), 12000);
    });
    if (!this._active) return;
    if (!transcript?.trim()) { setCheckinMicState('idle'); return; }
    await this.sendMessage(transcript);
  }
}

function startCheckinView() {
  document.getElementById('checkin-messages').innerHTML = '';
  checkinConversation = new CheckinConversation();
  setTimeout(() => checkinConversation.start(), 300);
}

document.getElementById('checkin-mic-btn').addEventListener('click', () => {
  checkinConversation?.listenAndSend();
});

// Check-in text input
function sendCheckinText() {
  const inp = document.getElementById('checkin-text-input');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  checkinConversation?.sendMessage(text);
}
document.getElementById('checkin-text-send').addEventListener('click', sendCheckinText);
document.getElementById('checkin-text-input').addEventListener('keydown', e => { if (e.key === 'Enter') sendCheckinText(); });

// Helper: detect log confirmation in agent response
const isLogConfirmation = t => /i('ve| have) (added|logged|recorded|noted)|successfully (added|logged|recorded)/i.test(t);
const getLogContext = m => {
  const s = m.toLowerCase();
  if (/meal|food|eat|lunch|breakfast|dinner|snack|drink/.test(s)) return 'meal';
  if (/workout|exercise|run|walk|gym|lift|swim|bike|yoga/.test(s)) return 'workout';
  return 'general';
};

// ── Voice overlay (section mic buttons) ───────────────────────────────────────
const voiceOverlay  = document.getElementById('voice-overlay');
const voiceMessages = document.getElementById('voice-messages');
const voiceStatus   = document.getElementById('voice-status');
const voiceTextIn   = document.getElementById('voice-text-input');

function openVoiceOverlay(autoListen = false) {
  voiceOverlay.classList.remove('hidden');
  if (autoListen) {
    setTimeout(() => startRecognition('overlay',
      t => { voiceTextIn.value = t; },
      t => { voiceTextIn.value = t; sendVoiceMessage(); }
    ), 300);
  }
}

function closeVoiceOverlay() {
  stopRecognition(); stopSpeaking();
  voiceOverlay.classList.add('hidden');
  voiceMessages.innerHTML = '';
  voiceTextIn.value = '';
  voiceStatus.textContent = '';
}

document.getElementById('voice-backdrop').addEventListener('click', closeVoiceOverlay);
document.getElementById('voice-close-btn').addEventListener('click', closeVoiceOverlay);

document.getElementById('voice-mic-btn').addEventListener('click', () => {
  if (document.getElementById('voice-mic-btn').classList.contains('listening')) stopRecognition();
  else startRecognition('overlay', t => { voiceTextIn.value = t; }, t => { voiceTextIn.value = t; sendVoiceMessage(); });
});

voiceTextIn.addEventListener('input', () => { voiceTextIn.style.height = 'auto'; voiceTextIn.style.height = Math.min(voiceTextIn.scrollHeight, 100) + 'px'; });
voiceTextIn.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendVoiceMessage(); } });
document.getElementById('voice-send-btn').addEventListener('click', sendVoiceMessage);

function appendVMsg(role, text) {
  const div = document.createElement('div');
  div.className = `vmsg ${role}`; div.textContent = text;
  voiceMessages.appendChild(div);
  voiceMessages.scrollTop = voiceMessages.scrollHeight;
  return div;
}

async function sendVoiceMessage() {
  const text = voiceTextIn.value.trim();
  if (!text) return;
  voiceTextIn.value = ''; voiceTextIn.style.height = 'auto';
  document.getElementById('voice-send-btn').disabled = true;
  stopRecognition(); stopSpeaking();
  appendVMsg('user', text);
  const agentDiv = appendVMsg('agent', '');
  agentDiv.classList.add('streaming');
  voiceStatus.textContent = 'Thinking…';

  let full = '';
  try {
    const res = await apiFetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text }) });
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop();
      for (const l of lines) {
        if (!l.startsWith('data: ')) continue;
        const raw = l.slice(6).trim(); if (raw === '[DONE]') break;
        try { const o = JSON.parse(raw); if (o.text) { full += o.text; agentDiv.textContent = full; voiceMessages.scrollTop = voiceMessages.scrollHeight; } } catch {}
      }
    }
  } catch (err) { full = 'Connection error.'; }

  agentDiv.classList.remove('streaming');
  agentDiv.textContent = full;
  document.getElementById('voice-send-btn').disabled = false;
  voiceStatus.textContent = '';
  await speak(full);
}

// Section mic buttons open the overlay
document.querySelectorAll('.view-mic-btn').forEach(b => b.addEventListener('click', () => openVoiceOverlay(true)));

// ── Schedule ──────────────────────────────────────────────────────────────────
let schedDate = todayStr();
function localDateStr(d) { const dd = d || new Date(); return `${dd.getFullYear()}-${String(dd.getMonth()+1).padStart(2,'0')}-${String(dd.getDate()).padStart(2,'0')}`; }
function todayStr() { return localDateStr(); }
function fmtSchedDate(d) {
  const [y, m, dy] = d.split('-');
  const dt = new Date(y, m-1, dy);
  if (d === todayStr()) return 'Today';
  const tom = new Date(); tom.setDate(tom.getDate()+1);
  if (dt.toDateString() === tom.toDateString()) return 'Tomorrow';
  return dt.toLocaleDateString('en-US', { weekday:'short', month:'short', day:'numeric' });
}
function nowHM() { const n = new Date(); return String(n.getHours()).padStart(2,'0') + ':' + String(n.getMinutes()).padStart(2,'0'); }

document.getElementById('sched-prev').addEventListener('click', () => { const d = new Date(schedDate+'T00:00:00'); d.setDate(d.getDate()-1); schedDate = localDateStr(d); loadSchedule(schedDate); });
document.getElementById('sched-next').addEventListener('click', () => { const d = new Date(schedDate+'T00:00:00'); d.setDate(d.getDate()+1); schedDate = localDateStr(d); loadSchedule(schedDate); });

async function fetchCalendarEvents(start, end) {
  try {
    const res = await apiFetch(`/api/calendar/events?start=${start}&end=${end}`);
    if (!res.ok) return [];
    return (await res.json()).events || [];
  } catch { return []; }
}

async function loadSchedule(d) {
  document.getElementById('sched-date').textContent = fmtSchedDate(d);
  const el = document.getElementById('schedule-list');
  el.innerHTML = '<div class="no-sched"><div class="spinner"></div></div>';
  try {
    const [res, calEvents] = await Promise.all([
      apiFetch(`/api/schedule/${d}`),
      fetchCalendarEvents(d, d),
    ]);
    if (res.status === 404) {
      el.innerHTML = `<div class="no-sched"><div class="spinner"></div><p style="margin-top:14px;font-size:13px;color:var(--muted)">Building schedule…</p></div>`;
      await generateScheduleFor(d);
      const res2 = await apiFetch(`/api/schedule/${d}`);
      if (res2.ok) renderSchedule((await res2.json()).blocks, el, calEvents);
      else el.innerHTML = '<div class="no-sched">Could not generate schedule.</div>';
      return;
    }
    renderSchedule((await res.json()).blocks, el, calEvents);
  } catch { el.innerHTML = '<div class="no-sched">Error loading schedule.</div>'; }
}

async function generateScheduleFor(d) {
  try {
    const r = await apiFetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: `Generate my schedule for ${d}` }),
    });
    const reader = r.body.getReader();
    while (true) { const { done } = await reader.read(); if (done) break; }
  } catch {}
}

function ensureWeekSchedules() {
  // Fire-and-forget: generate any missing days in the next 7 days (except today, already handled by loadSchedule)
  (async () => {
    const today = new Date();
    for (let i = 1; i < 7; i++) {
      const d = new Date(today);
      d.setDate(d.getDate() + i);
      const dateStr = localDateStr(d);
      try {
        const res = await apiFetch(`/api/schedule/${dateStr}`);
        if (res.status === 404) await generateScheduleFor(dateStr);
      } catch {}
      await new Promise(r => setTimeout(r, 1200)); // stagger calls
    }
  })();
}

function renderSchedule(blocks, el, calEvents = []) {
  const now = nowHM(); el.innerHTML = '';
  // Merge calendar events as read-only blocks
  // Separate all-day events and render as banners
  const allDayEvents = calEvents.filter(e => e.all_day);
  const timedCalEvents = calEvents.filter(e => !e.all_day);

  allDayEvents.forEach(e => {
    const banner = document.createElement('div');
    banner.className = 'all-day-banner';
    banner.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg> ${escHtml(e.title)}${e.recurring ? ' <span class="recur-badge">↻</span>' : ''}`;
    el.appendChild(banner);
  });

  const calBlocks = timedCalEvents.map(e => ({
    id: null, start: e.start, end: e.end, activity: e.title,
    type: 'calendar', completed: false, skipped: false,
    _calEvent: true, _uid: e.uid, _date: e.date, _recurring: e.recurring,
  }));
  const allBlocks = [...blocks, ...calBlocks].sort((a, b) => a.start.localeCompare(b.start));

  // Build conflict set: any block whose time overlaps another
  const conflictIds = new Set();
  for (let i = 0; i < allBlocks.length; i++) {
    for (let j = i + 1; j < allBlocks.length; j++) {
      if (allBlocks[i].start < allBlocks[j].end && allBlocks[j].start < allBlocks[i].end) {
        conflictIds.add(i); conflictIds.add(j);
      }
    }
  }

  if (!allBlocks.length && !allDayEvents.length) { showGhostSchedule(el); return;
  } else if (!allBlocks.length) return;
  allBlocks.forEach((b, idx) => {
    const isConflict = conflictIds.has(idx);
    if (b._calEvent) {
      const isCur = b.start <= now && now < b.end;
      const container = document.createElement('div');
      container.className = 'swipe-container';
      container.innerHTML = `
        <div class="swipe-actions" style="grid-template-columns:repeat(4,1fr)">
          <button class="swipe-action sa-complete cal-action" data-uid="${escHtml(b._uid)}" data-action="edit"
            data-title="${escHtml(b.activity)}" data-date="${b._date}" data-start="${b.start}" data-end="${b.end}"
            style="background:var(--accent)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            Edit
          </button>
          <button class="swipe-action sa-push cal-action" data-uid="${escHtml(b._uid)}"
            data-date="${b._date}" data-start="${b.start}" data-end="${b.end}" data-title="${escHtml(b.activity)}" data-action="push30">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
            +30m
          </button>
          <button class="swipe-action cal-action" data-uid="${escHtml(b._uid)}"
            data-date="${b._date}" data-start="${b.start}" data-end="${b.end}" data-title="${escHtml(b.activity)}" data-action="tomorrow"
            style="background:#6b7280">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/><polyline points="15 18 21 12 15 6"/></svg>
            +1 day
          </button>
          <button class="swipe-action sa-remove cal-action" data-uid="${escHtml(b._uid)}" data-action="delete">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            Delete
          </button>
        </div>
        <div class="swipe-content">
          <div class="block-row type-calendar${isCur ? ' current' : ''}${isConflict ? ' conflict' : ''}">
            <div class="block-time">${fmtTime(b.start)}<br>${fmtTime(b.end)}</div>
            <div class="block-info">
              <div class="block-activity">${escHtml(b.activity)}${b._recurring ? ' <span class="recur-badge">↻</span>' : ''}</div>
              <div class="block-type">calendar</div>
            </div>
          </div>
        </div>`;
      el.appendChild(container);
      const swipe = new SwipeHandler(container);
      container._swipe = swipe;
      return;
    }
    const isCur = b.start <= now && now < b.end;
    if (!b.completed && !b.skipped) {
      // Swipeable block
      const container = document.createElement('div');
      container.className = 'swipe-container';
      container.innerHTML = `
        <div class="swipe-actions">
          <button class="swipe-action sa-complete" data-id="${b.id}" data-action="complete">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            Done
          </button>
          <button class="swipe-action sa-skip" data-id="${b.id}" data-action="skip" style="background:#6B7280">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            Skip
          </button>
          <button class="swipe-action sa-push" data-id="${b.id}" data-action="push">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
            Later
          </button>
          <button class="swipe-action sa-remove" data-id="${b.id}" data-action="remove">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            Remove
          </button>
        </div>
        <div class="swipe-content">
          <div class="block-row type-${b.type}${isCur?' current':''}">
            <div class="block-time">${fmtTime(b.start)}<br>${fmtTime(b.end)}</div>
            <div class="block-info">
              <div class="block-activity">${escHtml(b.activity)}</div>
              <div class="block-type">${b.type.replace('_',' ')}</div>
              ${b.notes ? `<div class="block-expand">${escHtml(b.notes)}</div>` : `<div class="block-expand">${fmtTime(b.start)} – ${fmtTime(b.end)} · ${b.type.replace('_',' ')}</div>`}
            </div>
          </div>
        </div>`;
      el.appendChild(container);
      const swipe = new SwipeHandler(container);
      container._swipe = swipe;
    } else {
      // Completed/skipped — swipeable with undo
      const container = document.createElement('div');
      container.className = 'swipe-container';
      container.innerHTML = `
        <div class="swipe-actions" style="grid-template-columns:1fr">
          <button class="swipe-action sa-complete" data-id="${b.id}" data-action="undo"
            style="background:var(--accent)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.54"/></svg>
            Undo
          </button>
        </div>
        <div class="swipe-content">
          <div class="block-row type-${b.type} completed${isCur?' current':''}">
            <div class="block-time">${fmtTime(b.start)}<br>${fmtTime(b.end)}</div>
            <div class="block-info">
              <div class="block-activity">${escHtml(b.activity)}</div>
              <div class="block-type">${b.type.replace('_',' ')} · ${b.completed?'done':'skipped'}</div>
            </div>
          </div>
        </div>`;
      el.appendChild(container);
      const swipe = new SwipeHandler(container);
      container._swipe = swipe;
    }
  });

  // Swipe affordance hint (shown once)
  if (!S.get('swipeHintSeen') && el.children.length > 0) {
    const hint = document.createElement('div');
    hint.className = 'swipe-hint';
    hint.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14"><path d="M5 12h14M12 5l7 7-7 7"/></svg> Swipe left on any block for options`;
    el.appendChild(hint);
    setTimeout(() => { S.set('swipeHintSeen', true); hint.style.transition='opacity 0.5s'; hint.style.opacity='0'; setTimeout(()=>hint.remove(),500); }, 4000);
  }

  // Swipe action handlers — schedule blocks
  el.querySelectorAll('.swipe-action:not(.cal-action)').forEach(btn => btn.addEventListener('click', async () => {
    const id = btn.dataset.id, action = btn.dataset.action;
    if (action === 'complete') {
      await submitFeedback(id, true, false, null);
    } else if (action === 'skip') {
      showSkipReasonDialog(id);
    } else if (action === 'undo') {
      await apiFetch(`/api/schedule/block/${id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ completed: false, skipped: false }),
      });
      loadSchedule(schedDate);
    } else if (action === 'remove') {
      await apiFetch(`/api/schedule/block/${id}`, { method: 'DELETE' });
      loadSchedule(schedDate);
    }
    else if (action === 'push') {
      await apiFetch('/api/schedule/push-block', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ block_id: parseInt(id), minutes: 30 }) });
      loadSchedule(schedDate);
    }
  }));

  // Swipe action handlers — calendar events
  el.querySelectorAll('.cal-action').forEach(btn => btn.addEventListener('click', async () => {
    const uid = btn.dataset.uid, action = btn.dataset.action;
    if (action === 'edit') {
      openCalEventOverlay({ uid, title: btn.dataset.title, date: btn.dataset.date, start: btn.dataset.start, end: btn.dataset.end });
    } else if (action === 'push30') {
      const [sh, sm] = btn.dataset.start.split(':').map(Number);
      const [eh, em] = btn.dataset.end.split(':').map(Number);
      const addMin = (h, m, n) => { const t = h*60+m+n; return `${String(Math.min(Math.floor(t/60),23)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}`; };
      const newStart = addMin(sh, sm, 30), newEnd = addMin(eh, em, 30);
      await apiFetch(`/api/calendar/events/${encodeURIComponent(uid)}`, {
        method: 'PUT', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ title: btn.dataset.title, date: btn.dataset.date || schedDate, start_time: newStart, end_time: newEnd }),
      });
      loadSchedule(schedDate);
    } else if (action === 'delete') {
      if (!confirm('Delete this calendar event?')) return;
      await apiFetch(`/api/calendar/events/${encodeURIComponent(uid)}`, { method: 'DELETE' });
      loadSchedule(schedDate);
    }
  }));

  // Insert current-time line and peek animation
  insertNowLine();
  peekFirstSwipe();

  el.querySelector('.current')?.scrollIntoView({ behavior:'smooth', block:'center' });
}

async function submitFeedback(id, completed, skipped, energy) {
  const p = { block_id: parseInt(id), completed, skipped };
  if (energy) p.energy_rating = energy;
  try { await apiFetch('/api/schedule/feedback', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(p) }); loadSchedule(schedDate); } catch {}
}

const SKIP_REASONS = ['Got interrupted','Ran out of time','Too tired','Changed priorities','Already done','Doesn\'t apply today'];

function showSkipReasonDialog(blockId) {
  const existing = document.getElementById('skip-reason-dialog');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.id = 'skip-reason-dialog';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:200;display:flex;flex-direction:column;justify-content:flex-end';
  overlay.innerHTML = `
    <div style="position:absolute;inset:0;background:rgba(0,0,0,0.4)" id="srd-backdrop"></div>
    <div style="background:var(--bg);border-radius:20px 20px 0 0;padding:20px;position:relative">
      <div style="font-weight:700;font-size:15px;margin-bottom:12px">Why are you skipping?</div>
      <div style="display:flex;flex-direction:column;gap:8px" id="srd-reasons">
        ${SKIP_REASONS.map(r => `<button class="srd-btn" style="padding:10px 14px;border-radius:10px;background:var(--surface2);border:none;text-align:left;font-size:14px;cursor:pointer;color:var(--text)">${r}</button>`).join('')}
      </div>
      <button id="srd-cancel" style="margin-top:12px;width:100%;padding:11px;border-radius:12px;background:none;border:1px solid var(--border);font-size:14px;cursor:pointer;color:var(--muted)">Cancel</button>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#srd-backdrop').addEventListener('click', () => overlay.remove());
  overlay.querySelector('#srd-cancel').addEventListener('click', () => overlay.remove());
  overlay.querySelectorAll('.srd-btn').forEach(btn => btn.addEventListener('click', async () => {
    const reason = btn.textContent;
    overlay.remove();
    try {
      await apiFetch(`/api/schedule/block/${blockId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skipped: true, skip_reason: reason })
      });
      await apiFetch('/api/schedule/feedback', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ block_id: parseInt(blockId), completed: false, skipped: true })
      });
    } catch {}
    loadSchedule(schedDate);
  }));
}

// Show timing prompt before marking a block complete
function showTimingPrompt(blockId, blockStart, onDone) {
  const existing = document.getElementById('timing-prompt-' + blockId);
  if (existing) { existing.remove(); return; }
  const now = nowHM();
  const wrap = document.createElement('div');
  wrap.id = 'timing-prompt-' + blockId;
  wrap.className = 'timing-prompt';
  wrap.innerHTML = `
    <div class="timing-prompt-label">How'd it go?</div>
    <div class="timing-prompt-row">
      <label>Actual start <input type="time" class="tp-start add-task-select" value="${blockStart || now}"></label>
      <label>Actual end <input type="time" class="tp-end add-task-select" value="${now}"></label>
    </div>
    <div class="timing-prompt-btns">
      <button class="tp-done add-task-btn">Done</button>
      <button class="tp-skip add-task-btn-cancel">Skip</button>
    </div>`;
  wrap.querySelector('.tp-done').addEventListener('click', async () => {
    const actual_start = wrap.querySelector('.tp-start').value;
    const actual_end = wrap.querySelector('.tp-end').value;
    // POST feedback with timing, then PATCH block complete
    try {
      await apiFetch('/api/schedule/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ block_id: parseInt(blockId), completed: true, skipped: false }) });
      await apiFetch(`/api/schedule/block/${blockId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ completed: true, actual_start, actual_end }) });
    } catch {}
    wrap.remove();
    if (onDone) onDone();
    else loadSchedule(schedDate);
  });
  wrap.querySelector('.tp-skip').addEventListener('click', async () => {
    wrap.remove();
    await submitFeedback(blockId, true, false, null);
  });
  return wrap;
}


// ── Calendar Event Overlay ─────────────────────────────────────────────────

let _calEventUID = null; // null = create, string = update

function openCalEventOverlay(ev = null) {
  _calEventUID = ev ? ev.uid : null;
  document.getElementById('cal-event-overlay-title').textContent = ev ? 'Edit Event' : 'New Event';
  document.getElementById('cal-event-title').value = ev ? ev.title : '';
  document.getElementById('cal-event-date').value = ev ? (ev.date || schedDate) : schedDate;
  document.getElementById('cal-event-start').value = ev ? (ev.start || '09:00') : '09:00';
  document.getElementById('cal-event-end').value = ev ? (ev.end || '10:00') : '10:00';
  document.getElementById('cal-event-overlay').classList.remove('hidden');
}

function closeCalEventOverlay() {
  document.getElementById('cal-event-overlay').classList.add('hidden');
}

document.getElementById('cal-event-backdrop').addEventListener('click', closeCalEventOverlay);
document.getElementById('cal-event-cancel').addEventListener('click', closeCalEventOverlay);

document.getElementById('cal-event-save').addEventListener('click', async () => {
  const title = document.getElementById('cal-event-title').value.trim();
  const date = document.getElementById('cal-event-date').value;
  const start_time = document.getElementById('cal-event-start').value;
  const end_time = document.getElementById('cal-event-end').value;
  if (!title || !date || !start_time || !end_time) return;

  const btn = document.getElementById('cal-event-save');
  btn.disabled = true; btn.textContent = 'Saving…';

  try {
    const body = JSON.stringify({ title, date, start_time, end_time });
    if (_calEventUID) {
      await apiFetch(`/api/calendar/events/${encodeURIComponent(_calEventUID)}`, {
        method: 'PUT', headers: {'Content-Type':'application/json'}, body,
      });
    } else {
      await apiFetch('/api/calendar/events', {
        method: 'POST', headers: {'Content-Type':'application/json'}, body,
      });
    }
    closeCalEventOverlay();
    loadSchedule(schedDate);
  } catch (e) {
    alert('Error saving event: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Save';
  }
});

document.getElementById('add-cal-event-btn').addEventListener('click', () => openCalEventOverlay());


// ── Current ───────────────────────────────────────────────────────────────────
let activeCurrTab = 'tasks';
document.querySelectorAll('#view-current .sub-tab').forEach(b => b.addEventListener('click', () => {
  activeCurrTab = b.dataset.tab;
  document.querySelectorAll('#view-current .sub-tab').forEach(x => x.classList.toggle('active', x.dataset.tab===b.dataset.tab));
  document.querySelectorAll('.curr-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('curr-tab-'+b.dataset.tab)?.classList.add('active');
  if (b.dataset.tab==='tasks') loadTasks(); else if (b.dataset.tab==='goals') loadGoals(); else loadRecurringTab();
}));
function loadCurrent() {
  if (activeCurrTab === 'tasks') loadTasks();
  else if (activeCurrTab === 'goals') loadGoals();
  else loadRecurringTab();
}

let _taskViewUser = 'mine'; // 'mine' or 'all'

document.querySelectorAll('.user-filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    _taskViewUser = btn.dataset.viewUser;
    document.querySelectorAll('.user-filter-btn').forEach(b => b.classList.toggle('active', b === btn));
    loadTasks();
  });
});

async function loadTasks() {
  const el = document.getElementById('tasks-list');
  el.innerHTML = '<div class="no-sched"><div class="spinner"></div></div>';
  const bucket = document.getElementById('bucket-filter').value;
  const status = document.getElementById('status-filter').value;
  const fe = document.getElementById('bucket-filter');
  if (fe.options.length <= 1) {
    try {
      const GOAL_BUCKET_NAMES = ['Read More', 'Music', 'Health & Wellness', 'AI Engineering'];
      (await apiFetch('/api/tasks/buckets').then(r=>r.json())).buckets
        .filter(b => !GOAL_BUCKET_NAMES.includes(b.name))
        .forEach(b => {
          const o = document.createElement('option'); o.value=b.name; o.textContent=`${b.name} (${b.todo+b.in_progress})`; fe.appendChild(o);
        });
    } catch {}
  }
  const p = new URLSearchParams({ limit:100 });
  if (bucket) p.set('bucket', bucket);
  if (status) p.set('status', status);
  if (_taskViewUser === 'all') p.set('view_user', 'all');
  try {
    const GOAL_BUCKET_NAMES = ['Read More', 'Music', 'Health & Wellness', 'AI Engineering'];
    const allTasks = (await apiFetch('/api/tasks?'+p).then(r=>r.json())).tasks;
    // Hide goal-statement tasks from task view — they belong in Goals tab only
    const filtered = bucket ? allTasks : allTasks.filter(t => !GOAL_BUCKET_NAMES.includes(t.bucket));
    if (!filtered.length) {
      el.innerHTML = '<div class="empty-state"><p>No tasks found.</p><button class="inline-btn" id="empty-add-task-btn" style="margin-top:8px">+ Add a task</button></div>';
      document.getElementById('empty-add-task-btn')?.addEventListener('click', () => document.getElementById('current-add-btn').click());
    } else {
      renderTasks(filtered, el);
    }
  } catch { el.innerHTML='<div class="no-sched">Error loading tasks.</div>'; }
}
document.getElementById('bucket-filter').addEventListener('change', loadTasks);
document.getElementById('status-filter').addEventListener('change', loadTasks);

function renderTasks(tasks, el) {
  el.innerHTML = '';
  if (!tasks.length) { el.innerHTML='<div class="empty-state">No tasks found.</div>'; return; }
  const today = new Date().toISOString().slice(0,10);
  tasks.forEach(t => {
    if (t.status === 'done') {
      const div = document.createElement('div');
      div.className = `task-row p${t.priority} done`;
      div.innerHTML = `<div class="task-title">${escHtml(t.title)}</div>
        <div class="task-meta"><span class="badge">${t.bucket}</span><span class="badge">done</span></div>`;
      el.appendChild(div);
      return;
    }
    const isOverdue = t.due_date && t.due_date < today;
    const ownerBadge = (_taskViewUser === 'all' && t.user_name) ? `<span class="badge" style="background:var(--accent);color:#fff">${escHtml(t.user_name)}</span>` : '';
    const dueBadge = t.due_date ? `<span class="badge${isOverdue?' overdue':''}">due ${t.due_date}</span>` : '';
    const container = document.createElement('div');
    container.className = 'swipe-container';
    container.innerHTML = `
      <div class="swipe-actions">
        <button class="swipe-action sa-complete" data-id="${t.id}" data-action="complete">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          Done
        </button>
        <button class="swipe-action sa-defer" data-id="${t.id}" data-action="defer">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
          Defer
        </button>
        <button class="swipe-action sa-edit" data-action="edit" data-task='${JSON.stringify(t).replace(/'/g,"&#39;")}'>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          Edit
        </button>
        <button class="swipe-action sa-delete" data-id="${t.id}" data-action="delete">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          Delete
        </button>
      </div>
      <div class="swipe-content">
        <div class="task-row p${t.priority}" data-task-id="${t.id}">
          <div class="task-header">
            <div class="task-title">${escHtml(t.title)}</div>
            <div class="task-chevron">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="6 9 12 15 18 9"/></svg>
            </div>
          </div>
          ${t.bucket ? `<div><span class="task-goal-badge">Goal: ${escHtml(t.bucket)}</span></div>` : ''}
          <div class="task-meta">
            ${ownerBadge}<span class="badge">P${t.priority}</span><span class="badge">${t.status}</span>${dueBadge}
          </div>
          <div class="task-expand">
            ${t.description ? `<div class="task-expand-desc">${escHtml(t.description)}</div>` : ''}
            <div class="task-expand-meta">
              ${t.est_minutes?`<span>⏱ ${t.est_minutes} min</span>`:''}
              ${t.energy_level?`<span>⚡ ${t.energy_level} energy</span>`:''}
              ${t.notes?`<div class="task-expand-notes">${escHtml(t.notes)}</div>`:''}
            </div>
          </div>
        </div>
      </div>`;
    el.appendChild(container);
    container._taskData = t;
    const swipe = new SwipeHandler(container);
    container._swipe = swipe;
  });

  peekFirstSwipe();

  // Task swipe action handlers
  el.querySelectorAll('.swipe-action').forEach(btn => btn.addEventListener('click', async () => {
    const id = btn.dataset.id, action = btn.dataset.action;
    try {
      if (action === 'complete') await apiFetch(`/api/tasks/${id}/complete`, { method: 'POST' });
      else if (action === 'defer') await apiFetch(`/api/tasks/${id}/defer`, { method: 'POST' });
      else if (action === 'delete') await apiFetch(`/api/tasks/${id}`, { method: 'DELETE' });
      else if (action === 'edit') { const t = JSON.parse(btn.dataset.task); openTaskEditOverlay(t); return; }
      loadTasks();
    } catch {}
  }));
}

// ── Task edit overlay ─────────────────────────────────────────────────────
let _editingTaskId = null;

async function openTaskEditOverlay(t) {
  _editingTaskId = t.id;
  document.getElementById('te-title').value = t.title || '';
  document.getElementById('te-priority').value = t.priority || 2;
  document.getElementById('te-due').value = t.due_date || '';
  document.getElementById('te-energy').value = t.energy_level || '';
  document.getElementById('te-description').value = t.description || '';

  // Populate bucket select
  const bucketSel = document.getElementById('te-bucket');
  if (bucketSel.options.length <= 1) {
    try {
      (await apiFetch('/api/tasks/buckets').then(r=>r.json())).buckets.forEach(b => {
        const o = document.createElement('option'); o.value=b.name; o.textContent=b.name; bucketSel.appendChild(o);
      });
    } catch {}
  }
  bucketSel.value = t.bucket || '';

  document.getElementById('task-edit-overlay').classList.remove('hidden');
}

document.getElementById('te-cancel')?.addEventListener('click', () => {
  document.getElementById('task-edit-overlay').classList.add('hidden');
  _editingTaskId = null;
});

document.getElementById('te-save')?.addEventListener('click', async () => {
  if (!_editingTaskId) return;
  const body = {
    title: document.getElementById('te-title').value.trim(),
    bucket: document.getElementById('te-bucket').value,
    priority: parseInt(document.getElementById('te-priority').value),
    energy_level: document.getElementById('te-energy').value || null,
    description: document.getElementById('te-description').value.trim() || null,
  };
  const due = document.getElementById('te-due').value;
  if (due) body.due_date = due;
  const btn = document.getElementById('te-save');
  btn.textContent = 'Saving…'; btn.disabled = true;
  try {
    await apiFetch(`/api/tasks/${_editingTaskId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    document.getElementById('task-edit-overlay').classList.add('hidden');
    _editingTaskId = null;
    loadTasks();
  } catch (e) { console.error('Save task failed:', e); }
  btn.textContent = 'Save'; btn.disabled = false;
});

// ── Add Task form (Current view) ───────────────────────────────────────────
const addTaskForm = document.getElementById('add-task-form');

// Populate all bucket selects from API
async function populateBucketSelects() {
  try {
    const data = await apiFetch('/api/tasks/buckets').then(r => r.json());
    // new-task-bucket: keep placeholder, add goal options
    const ntb = document.getElementById('new-task-bucket');
    if (ntb) {
      ntb.innerHTML = '<option value="" disabled selected>— Select a goal —</option>';
      data.buckets.forEach(b => {
        const o = document.createElement('option'); o.value = b.name; o.textContent = b.name;
        ntb.appendChild(o);
      });
    }
    // bulk-task-bucket: no placeholder needed
    const btb = document.getElementById('bulk-task-bucket');
    if (btb) {
      btb.innerHTML = '';
      data.buckets.forEach(b => {
        const o = document.createElement('option'); o.value = b.name; o.textContent = b.name;
        btb.appendChild(o);
      });
    }
  } catch {}
}

// Mode tab switching (single/bulk) - works for both in-view and overlay
document.querySelectorAll('.add-task-mode-tabs').forEach(tabs => {
  tabs.querySelectorAll('.add-mode-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const container = tabs.parentElement;
      container.querySelectorAll('.add-mode-tab').forEach(t => t.classList.toggle('active', t === tab));
      container.querySelectorAll('.add-mode').forEach(m => m.classList.toggle('active', m.id.includes(tab.dataset.mode)));
    });
  });
});

// addTaskToggle is now the + button in view-bar (current-add-btn), handled below

document.getElementById('add-task-cancel')?.addEventListener('click', () => addTaskForm.classList.add('hidden'));
document.getElementById('bulk-task-cancel')?.addEventListener('click', () => addTaskForm.classList.add('hidden'));

// Single add (Current view)
document.getElementById('add-task-submit').addEventListener('click', async () => {
  const title = document.getElementById('new-task-title').value.trim();
  if (!title) return;
  const btn = document.getElementById('add-task-submit');
  btn.disabled = true; btn.textContent = 'Adding…';
  try {
    const body = { title, bucket: document.getElementById('new-task-bucket').value, priority: parseInt(document.getElementById('new-task-priority').value) };
    const due = document.getElementById('new-task-due').value;
    if (due) body.due_date = due;
    const desc = document.getElementById('new-task-description').value.trim();
    if (desc) body.description = desc;
    const est = document.getElementById('new-task-est-minutes').value;
    if (est) body.est_minutes = parseInt(est);
    const energy = document.getElementById('new-task-energy').value;
    if (energy) body.energy_level = energy;
    const tags = document.getElementById('new-task-tags').value.trim();
    if (tags) body.tags = tags;
    await apiFetch('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    document.getElementById('new-task-title').value = '';
    document.getElementById('new-task-due').value = '';
    document.getElementById('new-task-description').value = '';
    document.getElementById('new-task-est-minutes').value = '';
    document.getElementById('new-task-energy').value = '';
    document.getElementById('new-task-tags').value = '';
    loadTasks();
  } catch (e) { console.error('Add task failed:', e); }
  btn.disabled = false; btn.textContent = 'Add';
});

document.getElementById('new-task-title').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('add-task-submit').click();
});

// Bulk add (Current view)
document.getElementById('bulk-task-submit').addEventListener('click', () => bulkAddTasks('bulk-task-text', 'bulk-task-bucket', 'bulk-task-priority', 'bulk-task-submit', 'bulk-task-status'));

// ── Bulk add helper ───────────────────────────────────────────────────────
async function bulkAddTasks(textId, bucketId, priorityId, btnId, statusId) {
  const raw = document.getElementById(textId).value.trim();
  if (!raw) return;
  const lines = raw.split('\n').map(l => l.replace(/^[-•*\d.)\s]+/, '').trim()).filter(l => l.length > 0);
  if (!lines.length) return;
  const btn = document.getElementById(btnId);
  const status = document.getElementById(statusId);
  btn.disabled = true; btn.textContent = `Adding ${lines.length}…`;
  status.textContent = '';
  try {
    const res = await apiFetch('/api/tasks/bulk', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tasks: lines, bucket: document.getElementById(bucketId).value, priority: parseInt(document.getElementById(priorityId).value) }),
    });
    const data = await res.json();
    status.textContent = `${data.added} task(s) added`;
    document.getElementById(textId).value = '';
    loadTasks();
  } catch (e) { status.textContent = 'Error adding tasks'; console.error(e); }
  btn.disabled = false; btn.textContent = 'Add All';
}

// ── Current view "+" button → toggle add-task form or add-goal form ──────────
const addGoalForm = document.getElementById('add-goal-form');
document.getElementById('current-add-btn').addEventListener('click', async () => {
  if (activeCurrTab === 'goals') {
    addGoalForm.classList.toggle('hidden');
    if (!addGoalForm.classList.contains('hidden')) {
      document.getElementById('new-goal-name').focus();
    }
  } else {
    addTaskForm.classList.toggle('hidden');
    if (!addTaskForm.classList.contains('hidden')) {
      await populateBucketSelects();
      document.getElementById('new-task-title').focus();
    }
  }
});

document.getElementById('add-goal-cancel')?.addEventListener('click', () => addGoalForm.classList.add('hidden'));
document.getElementById('add-goal-submit')?.addEventListener('click', async () => {
  const name = document.getElementById('new-goal-name').value.trim();
  if (!name) return;
  const btn = document.getElementById('add-goal-submit');
  btn.disabled = true; btn.textContent = 'Creating…';
  try {
    const desc = document.getElementById('new-goal-desc').value.trim();
    await apiFetch('/api/tasks/buckets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, description: desc || undefined }) });
    document.getElementById('new-goal-name').value = '';
    document.getElementById('new-goal-desc').value = '';
    addGoalForm.classList.add('hidden');
    loadGoals();
  } catch (e) { console.error('Create goal failed:', e); }
  btn.disabled = false; btn.textContent = 'Create';
});

// Task tap-to-expand (event delegation on tasks-list)
document.getElementById('tasks-list').addEventListener('click', e => {
  const row = e.target.closest('.task-row');
  if (!row || e.target.closest('.swipe-actions')) return;
  const container = row.closest('.swipe-container');
  if (container?._swipe?.open) return;
  // Close all others, toggle this one
  document.querySelectorAll('#tasks-list .task-row.expanded').forEach(r => { if (r !== row) r.classList.remove('expanded'); });
  row.classList.toggle('expanded');
});

// Colors matched to the 4 goal buckets in display order
const GOAL_PALETTE_MAP = {
  'Read More':         '#8B5CF6', // violet
  'Music':             '#EC4899', // pink
  'Health & Wellness': '#10B981', // emerald
  'AI Engineering':    '#3B82F6', // blue
};
// Fallback palette for any unexpected buckets
const GOAL_PALETTE = ['#8B5CF6','#10B981','#3B82F6','#F59E0B','#EF4444','#EC4899','#06B6D4','#F97316'];

async function loadGoals() {
  const el = document.getElementById('goals-list');
  el.innerHTML = '<div class="no-sched"><div class="spinner"></div></div>';
  try {
    // Load buckets + all non-done tasks together
    const [bucketsData, tasksData] = await Promise.all([
      apiFetch('/api/tasks/buckets').then(r => r.json()),
      apiFetch('/api/tasks?limit=200').then(r => r.json()),
    ]);
    const buckets = bucketsData.buckets;
    const allTasks = tasksData.tasks;

    // Build a map: bucket name → tasks
    const tasksByBucket = {};
    allTasks.forEach(t => {
      if (!tasksByBucket[t.bucket]) tasksByBucket[t.bucket] = [];
      tasksByBucket[t.bucket].push(t);
    });

    // Show only the 4 goal-area buckets — everything else is a task bucket
    const GOAL_BUCKETS = ['Read More', 'Music', 'Health & Wellness', 'AI Engineering'];
    const goalBuckets = buckets.filter(b => GOAL_BUCKETS.includes(b.name));
    el.innerHTML = '';
    goalBuckets.forEach((b, i) => {
      const color = GOAL_PALETTE_MAP[b.name] || GOAL_PALETTE[i % GOAL_PALETTE.length];
      const tasks = (tasksByBucket[b.name] || []).filter(t => t.status !== 'done' && t.status !== 'deferred');

      const section = document.createElement('div');
      section.className = 'goal-section';

      // Goal area header
      const header = document.createElement('div');
      header.className = 'goal-section-header';
      const taskCount = tasks.length;
      header.innerHTML = `
        <div class="goal-section-bar" style="background:${color}"></div>
        <div class="goal-section-name" style="color:${color}">${escHtml(b.name)}</div>
        ${taskCount > 0 ? `<span style="margin-left:6px;font-size:10px;font-weight:600;color:${color};opacity:0.7;padding:2px 7px;border-radius:10px;background:${color}22">${taskCount}</span>` : ''}
        <div style="margin-left:auto;display:flex;gap:4px;">
          <button class="goal-edit-btn icon-btn" data-id="${b.id}" data-name="${escHtml(b.name)}" data-desc="${escHtml(b.description||'')}" style="padding:4px;opacity:0.55;" title="Rename">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
          <button class="goal-delete-btn icon-btn" data-id="${b.id}" data-name="${escHtml(b.name)}" style="padding:4px;opacity:0.55;color:#ef4444;" title="Remove">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
          </button>
        </div>`;
      // Edit goal name
      header.querySelector('.goal-edit-btn').addEventListener('click', e => {
        e.stopPropagation();
        const id = e.currentTarget.dataset.id;
        const oldName = e.currentTarget.dataset.name;
        const newName = prompt('Rename goal:', oldName);
        if (!newName || newName.trim() === oldName) return;
        apiFetch(`/api/tasks/buckets/${id}`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ name: newName.trim() }) })
          .then(() => loadGoals()).catch(err => alert('Rename failed: ' + err));
      });
      // Delete goal category
      header.querySelector('.goal-delete-btn').addEventListener('click', e => {
        e.stopPropagation();
        const id = e.currentTarget.dataset.id;
        const name = e.currentTarget.dataset.name;
        if (!confirm(`Remove goal "${name}"? Tasks in this category will be moved to Now.`)) return;
        apiFetch(`/api/tasks/buckets/${id}`, { method: 'DELETE' })
          .then(() => loadGoals()).catch(err => alert('Delete failed: ' + err));
      });
      section.appendChild(header);

      // Individual tasks under this goal
      if (tasks.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'goal-task-empty';
        empty.textContent = 'No active tasks';
        section.appendChild(empty);
      } else {
        tasks.forEach(t => {
          const row = document.createElement('div');
          row.className = 'goal-task-row';
          row.innerHTML = `
            <div class="goal-task-dot" style="background:${color}"></div>
            <div class="goal-task-text">
              <div class="goal-task-title">${escHtml(t.title)}</div>
              ${t.status === 'in_progress' ? `<span class="goal-task-active">Active</span>` : ''}
            </div>`;
          row.addEventListener('click', () => {
            document.querySelector('#view-current .sub-tab[data-tab="tasks"]').click();
            const filter = document.getElementById('bucket-filter');
            filter.value = b.name; filter.dispatchEvent(new Event('change'));
          });
          section.appendChild(row);
        });
      }

      el.appendChild(section);
    });

    if (!el.children.length) el.innerHTML = '<div class="empty-state">No goals yet. Add your first goal with the + button.</div>';
  } catch (e) { el.innerHTML = '<div class="no-sched">Error loading goals.</div>'; }
}

// ── History Search ────────────────────────────────────────────────────────────
document.getElementById('history-search-btn')?.addEventListener('click', () => showHistorySearchOverlay());

function showHistorySearchOverlay() {
  const existing = document.getElementById('hist-search-overlay');
  if (existing) { existing.remove(); return; }
  const overlay = document.createElement('div');
  overlay.id = 'hist-search-overlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:9999;background:var(--bg);display:flex;flex-direction:column;';
  overlay.innerHTML = `
    <div class="view-bar">
      <button id="hist-search-close" class="back-btn" aria-label="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><polyline points="15 18 9 12 15 6"/></svg>
      </button>
      <span class="view-title">Search History</span>
      <span></span>
    </div>
    <div id="hist-search-results" style="flex:1;overflow-y:auto;padding:12px 16px;">
      <p style="color:var(--muted);font-size:13px;text-align:center;margin-top:24px">Ask anything about your past meals, workouts, mood, or habits.</p>
    </div>
    <div style="padding:12px 16px;border-top:1px solid var(--border);display:flex;gap:8px;">
      <input id="hist-search-input" type="text" placeholder="e.g. What did I eat last week?" style="flex:1;padding:10px 14px;border-radius:12px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:15px;">
      <button id="hist-search-send" style="padding:10px 16px;border-radius:12px;background:var(--accent);color:#fff;border:none;font-size:15px;cursor:pointer;">→</button>
    </div>`;
  document.body.appendChild(overlay);

  overlay.querySelector('#hist-search-close').addEventListener('click', () => overlay.remove());
  const input = overlay.querySelector('#hist-search-input');
  const sendBtn = overlay.querySelector('#hist-search-send');
  const results = overlay.querySelector('#hist-search-results');

  async function doSearch() {
    const q = input.value.trim(); if (!q) return;
    const userBubble = document.createElement('div');
    userBubble.style.cssText = 'margin-bottom:12px;text-align:right;';
    userBubble.innerHTML = `<span style="background:var(--accent);color:#fff;padding:8px 12px;border-radius:16px 16px 4px 16px;display:inline-block;max-width:80%;font-size:14px">${escHtml(q)}</span>`;
    results.appendChild(userBubble);
    input.value = ''; sendBtn.disabled = true; sendBtn.textContent = '...';
    results.scrollTop = results.scrollHeight;
    try {
      const resp = await apiFetch('/api/chat', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ message: `[History search] ${q}`, user_id: currentUserId }) });
      const data = await resp.json();
      const agentBubble = document.createElement('div');
      agentBubble.style.cssText = 'margin-bottom:16px;';
      agentBubble.innerHTML = `<div style="background:var(--surface2);padding:10px 14px;border-radius:16px 16px 16px 4px;font-size:14px;line-height:1.5;white-space:pre-wrap">${escHtml(data.reply || 'No response')}</div>`;
      results.appendChild(agentBubble);
    } catch {
      const errBubble = document.createElement('div');
      errBubble.innerHTML = `<div style="color:var(--muted);font-size:13px">Error — try again.</div>`;
      results.appendChild(errBubble);
    }
    sendBtn.disabled = false; sendBtn.textContent = '→';
    results.scrollTop = results.scrollHeight;
  }

  sendBtn.addEventListener('click', doSearch);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
  setTimeout(() => input.focus(), 100);
}

// ── History ───────────────────────────────────────────────────────────────────
let activeHistTab = 'meal';
document.querySelectorAll('#view-history .sub-tab').forEach(b => b.addEventListener('click', () => {
  activeHistTab = b.dataset.tab;
  document.querySelectorAll('#view-history .sub-tab').forEach(x => x.classList.toggle('active', x.dataset.tab===b.dataset.tab));
  document.querySelectorAll('.hist-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('hist-tab-'+b.dataset.tab)?.classList.add('active');
  loadHistoryTab(b.dataset.tab);
}));
function loadHistoryTab(tab) {
  if (tab==='fitness') loadFitnessHistory();
  if (tab==='meal')    loadMealHistory();
  if (tab==='mood')    loadMoodHistory();
  if (tab==='bible')   loadBibleProgress();
}

// Mood UI
const MOOD_EMOJIS = ['','😔','😔','😕','😕','😐','😐','🙂','🙂','😊','😊'];
document.getElementById('mood-score').addEventListener('input', function() {
  document.getElementById('mood-score-label').textContent = this.value;
  document.getElementById('mood-emoji').textContent = MOOD_EMOJIS[this.value] || '🙂';
});
document.querySelectorAll('.energy-btn').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.energy-btn').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
}));
document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => c.classList.toggle('active')));

document.getElementById('mood-submit').addEventListener('click', async () => {
  const btn = document.getElementById('mood-submit');
  const score = parseInt(document.getElementById('mood-score').value);
  const energy = document.querySelector('.energy-btn.active')?.dataset.energy || 'medium';
  const emotions = Array.from(document.querySelectorAll('.chip.active')).map(c => c.dataset.emotion);
  const notes = document.getElementById('mood-notes').value.trim();
  btn.disabled=true; btn.textContent='Saving…';
  try {
    await apiFetch('/api/mood', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ user_id:currentUserId, mood_score:score, energy, emotions, notes:notes||null, context:'manual' }) });
    document.querySelectorAll('.chip.active').forEach(c=>c.classList.remove('active'));
    document.getElementById('mood-notes').value='';
    loadMoodHistory();
  } catch {}
  btn.disabled=false; btn.textContent='Log Mood';
});

async function loadMoodHistory() {
  const el = document.getElementById('mood-history');
  try {
    const data = await apiFetch(`/api/mood?user_id=${currentUserId}&period=week`).then(r=>r.json());
    if (!data.entries.length) { el.innerHTML='<div class="empty-state">No mood entries this week.</div>'; return; }
    el.innerHTML='';
    data.entries.forEach(e => {
      const emo = JSON.parse(e.emotions||'[]').join(', ');
      const dt = new Date(e.logged_at);
      const ts = dt.toLocaleString('en-US', { weekday:'short', hour:'numeric', minute:'2-digit', hour12:true });
      const div = document.createElement('div'); div.className='mood-entry';
      div.innerHTML=`<div style="display:flex;align-items:center;gap:8px"><span class="mood-score-big">${MOOD_EMOJIS[e.mood_score]||'·'} ${e.mood_score??'—'}/10</span>${e.energy?`<span class="badge">${e.energy} energy</span>`:''}</div>
        <div class="mood-meta">${ts}${e.context&&e.context!=='manual'?` · ${e.context}`:''}${emo?`<br>${emo}`:''}${e.notes?`<br><em>${e.notes}</em>`:''}</div>`;
      el.appendChild(div);
    });
  } catch { el.innerHTML=''; }
}

// Photo upload
async function uploadPhoto(input, ctx) {
  const file = input.files[0]; if (!file) return null;
  const fd = new FormData(); fd.append('file', file); fd.append('context', ctx);
  try { return await apiFetch('/api/upload/photo', { method:'POST', body:fd }).then(r=>r.json()); } catch { return null; }
}

function showNutritionPreview(n) {
  const el = document.getElementById('meal-nutrition-preview');
  if (!el || !n) return;
  const calEl = document.getElementById('meal-cal');
  if (calEl && !calEl.value && n.calories != null) calEl.value = n.calories;
  el.innerHTML = `
    ${n.description ? `<div style="font-size:13px;color:var(--muted);margin-bottom:6px">${escHtml(n.description)}</div>` : ''}
    <div class="nutrition-row">
      ${n.calories  != null ? `<div class="nutrition-item"><span class="nutrition-val">${n.calories}</span><span class="nutrition-lbl">cal</span></div>` : ''}
      ${n.protein_g != null ? `<div class="nutrition-item"><span class="nutrition-val">${n.protein_g}g</span><span class="nutrition-lbl">protein</span></div>` : ''}
      ${n.carbs_g   != null ? `<div class="nutrition-item"><span class="nutrition-val">${n.carbs_g}g</span><span class="nutrition-lbl">carbs</span></div>` : ''}
      ${n.fat_g     != null ? `<div class="nutrition-item"><span class="nutrition-val">${n.fat_g}g</span><span class="nutrition-lbl">fat</span></div>` : ''}
    </div>
    ${n.confidence ? `<div class="nutrition-conf">Confidence: ${escHtml(n.confidence)}</div>` : ''}
  `;
  el.classList.remove('hidden');
}

// Workout
document.getElementById('workout-photo').addEventListener('change', function() { document.getElementById('workout-photo-label').textContent = this.files[0]?.name||''; });
document.getElementById('workout-submit').addEventListener('click', async () => {
  const btn=document.getElementById('workout-submit'), text=document.getElementById('workout-text').value.trim();
  if (!text) return; btn.disabled=true; btn.textContent='Logging…';
  const pi=document.getElementById('workout-photo'); let photoDesc=null;
  if (pi.files[0]) { btn.textContent='Analyzing…'; const r=await uploadPhoto(pi,'workout'); if(r) photoDesc=r.description; }
  const dur=document.getElementById('workout-duration').value, dist=document.getElementById('workout-distance').value, cal=document.getElementById('workout-cal').value;
  const msg=`Log workout: "${text}"${dur?` duration=${dur}min`:''}${dist?` distance=${dist}km`:''}${cal?` calories=${cal}`:''}${photoDesc?`. Photo: ${photoDesc}`:''} Call log_workout with user_id=${currentUserId}.`;
  await apiFetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})}).then(r=>r.body.getReader().read());
  ['workout-text','workout-duration','workout-distance','workout-cal'].forEach(id=>document.getElementById(id).value='');
  pi.value=''; document.getElementById('workout-photo-label').textContent='';
  btn.disabled=false; btn.textContent='Log Workout';
  loadFitnessHistory();
});

// Meal
document.getElementById('meal-photo').addEventListener('change', function() { document.getElementById('meal-photo-label').textContent = this.files[0]?.name||''; });
// Default meal date/time to now
(function initMealDateTime() {
  const now = new Date();
  document.getElementById('meal-date').value = localDateStr(now);
  document.getElementById('meal-time').value = now.toTimeString().slice(0, 5);
})();

document.getElementById('meal-submit').addEventListener('click', async () => {
  const btn=document.getElementById('meal-submit'); let text=document.getElementById('meal-text').value.trim();
  btn.disabled=true; btn.textContent='Logging…';
  const pi=document.getElementById('meal-photo'); let photoPath=null, photoDesc=null;
  if (pi.files[0]) { btn.textContent='Analyzing…'; const r=await uploadPhoto(pi,'meal'); if(r){photoDesc=r.description; photoPath=r.path||null; if(!text)text=photoDesc; if(r.nutrition)showNutritionPreview(r.nutrition);} }
  if (!text) { btn.disabled=false; btn.textContent='Log Meal'; return; }
  try {
    const body = { activity: text };
    const mealDate = document.getElementById('meal-date').value;
    const mealTime = document.getElementById('meal-time').value;
    if (mealDate) body.date = mealDate;
    if (mealTime) body.time = mealTime;
    if (photoDesc) body.notes = photoDesc;
    if (photoPath) body.photo_path = photoPath;
    await apiFetch('/api/meals', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
  } catch (e) { console.error('Meal log failed:', e); }
  document.getElementById('meal-text').value='';
  pi.value=''; document.getElementById('meal-photo-label').textContent='';
  document.getElementById('meal-nutrition-preview')?.classList.add('hidden');
  // Reset time to now
  const now = new Date();
  document.getElementById('meal-date').value = localDateStr(now);
  document.getElementById('meal-time').value = now.toTimeString().slice(0, 5);
  btn.disabled=false; btn.textContent='Log Meal';
  loadMealHistory();
});

// ── Meal Insights ─────────────────────────────────────────────────────────
document.getElementById('meal-insights-btn').addEventListener('click', () => {
  const panel = document.getElementById('meal-insights-panel');
  if (!panel.classList.contains('hidden')) { panel.classList.add('hidden'); return; }
  panel.classList.remove('hidden');
  const today = todayStr();
  const weekAgo = localDateStr(new Date(Date.now() - 7 * 86400000));
  panel.innerHTML = `
    <div class="insights-range-row">
      <select id="insights-preset">
        <option value="today">Today</option>
        <option value="week" selected>Last 7 days</option>
        <option value="month">Last 30 days</option>
        <option value="custom">Custom</option>
      </select>
      <input id="insights-start" type="date" value="${weekAgo}" style="display:none">
      <input id="insights-end" type="date" value="${today}" style="display:none">
      <button id="insights-load">Load</button>
    </div>
    <div id="insights-content"><div class="spinner" style="margin:12px auto"></div></div>`;
  document.getElementById('insights-preset').addEventListener('change', (e) => {
    const custom = e.target.value === 'custom';
    document.getElementById('insights-start').style.display = custom ? '' : 'none';
    document.getElementById('insights-end').style.display = custom ? '' : 'none';
  });
  document.getElementById('insights-load').addEventListener('click', loadInsights);
  loadInsights();
});

async function loadInsights() {
  const el = document.getElementById('insights-content');
  el.innerHTML = '<div class="spinner" style="margin:12px auto"></div>';
  const preset = document.getElementById('insights-preset').value;
  const today = todayStr();
  let start, end = today;
  if (preset === 'today') start = today;
  else if (preset === 'week') start = localDateStr(new Date(Date.now() - 7 * 86400000));
  else if (preset === 'month') start = localDateStr(new Date(Date.now() - 30 * 86400000));
  else { start = document.getElementById('insights-start').value; end = document.getElementById('insights-end').value; }
  try {
    const data = await apiFetch(`/api/meals/insights?start=${start}&end=${end}`).then(r => r.json());
    el.innerHTML = `<div style="font-size:11px;color:var(--muted);margin-bottom:6px">${data.meals_count} meals · ${data.period}</div>${data.insights}`;
  } catch { el.textContent = 'Error loading insights.'; }
}

// Bible (tab removed — handler kept as no-op to avoid null crash)
document.getElementById('bible-submit')?.addEventListener('click', async () => {});

// Health / cycle
document.getElementById('cycle-submit').addEventListener('click', async () => {
  const type=document.getElementById('cycle-event-type').value, notes=document.getElementById('cycle-notes').value.trim();
  const btn=document.getElementById('cycle-submit'); btn.disabled=true; btn.textContent='Logging…';
  await apiFetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:`Log health event: type="${type}"${notes?`, notes="${notes}"`:''} for user_id=${currentUserId}.`})}).then(r=>r.body.getReader().read());
  document.getElementById('cycle-notes').value=''; btn.disabled=false; btn.textContent='Log';
});

// History loaders
async function loadFitnessHistory() {
  const el=document.getElementById('fitness-history');
  try { const d=await apiFetch(`/api/users/${currentUserId}/fitness?period=week`).then(r=>r.json()); el.innerHTML=`<div class="log-entry"><div class="log-entry-title">This week</div><div class="log-entry-meta" style="white-space:pre-line">${d.summary}</div></div>`; } catch { el.innerHTML=''; }
}
async function loadCalorieBar() {
  try {
    const [summary, targetsData] = await Promise.all([
      apiFetch('/api/meals/today-summary').then(r => r.json()),
      apiFetch(`/api/users/${currentUserId}/calorie-targets`).then(r => r.json()).catch(() => ({ targets: {} })),
    ]);
    const t = targetsData.targets || {};
    const calGoal = t.calorie_target;
    const protGoal = t.protein_target_g;
    const carbGoal = t.carbs_target_g;
    const fatGoal  = t.fat_target_g;
    const cal  = summary.total_cal     || 0;
    const prot = summary.total_protein || 0;
    const carb = summary.total_carbs   || 0;
    const fat  = summary.total_fat     || 0;
    const fmt = (v, g) => g ? `${v}<span style="color:var(--muted);font-size:10px"> / ${g}</span>` : `${v}`;
    document.getElementById('cal-bar-total').innerHTML = calGoal
      ? `${cal}<span style="font-size:12px;font-weight:400;color:var(--muted)"> / ${calGoal} kcal</span>`
      : `${cal} <span style="font-size:12px;font-weight:400;color:var(--muted)">kcal</span>`;
    document.getElementById('cal-bar-protein').innerHTML = fmt(prot + 'g', protGoal ? protGoal + 'g' : null);
    document.getElementById('cal-bar-carbs').innerHTML   = fmt(carb + 'g', carbGoal ? carbGoal + 'g' : null);
    document.getElementById('cal-bar-fat').innerHTML     = fmt(fat  + 'g', fatGoal  ? fatGoal  + 'g' : null);
    document.getElementById('cal-bar-count').textContent = `${summary.meal_count} meal${summary.meal_count !== 1 ? 's' : ''}`;
  } catch {}
}

async function loadMealHistory() {
  loadCalorieBar();
  const el = document.getElementById('meal-history');
  el.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';
  try {
    const data = await apiFetch('/api/meals?days=14').then(r => r.json());
    if (!data.meals.length) { el.innerHTML = '<div class="empty-state">No meals logged yet.</div>'; return; }
    el.innerHTML = '';
    data.meals.forEach(m => {
      const time = m.created_at?.split(' ')[1]?.slice(0,5) || '';
      const details = m.details || '';
      const macros = [
        m.protein_g != null ? `${m.protein_g}g P` : null,
        m.carbs_g   != null ? `${m.carbs_g}g C`   : null,
        m.fat_g     != null ? `${m.fat_g}g F`     : null,
      ].filter(Boolean);
      const macroBadges = macros.map(s => `<span class="meal-macro-tag">${s}</span>`).join('');
      const div = document.createElement('div'); div.className = 'log-entry meal-entry';
      div.dataset.id = m.id;
      div.innerHTML = `
        <div class="meal-entry-header">
          <div class="log-entry-title">${escHtml(m.activity)}</div>
          <div class="meal-entry-actions">
            <button class="meal-action-btn meal-relog-btn" data-id="${m.id}" data-activity="${escHtml(m.activity)}" data-calories="${m.calories||''}" data-details="${escHtml(details)}" title="Log again">↩</button>
            <button class="meal-action-btn meal-delete-btn" data-id="${m.id}" aria-label="Delete">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
        </div>
        <div class="log-entry-meta">${m.date} · ${time}${m.calories?` · ${m.calories} kcal`:''}${macroBadges?' · '+macroBadges:''}${details ? '<br><span style="font-size:11px">' + escHtml(details) + '</span>' : ''}</div>
        <div class="meal-detail">
          <div class="meal-detail-row">
            <span class="meal-detail-label">Meal</span>
            <input class="meal-detail-input" data-field="activity" value="${escHtml(m.activity)}">
          </div>
          <div class="meal-detail-row">
            <span class="meal-detail-label">Calories</span>
            <input class="meal-detail-input" data-field="calories" type="number" value="${m.calories || ''}" placeholder="e.g. 450">
          </div>
          <div class="meal-detail-row">
            <span class="meal-detail-label">Protein (g)</span>
            <input class="meal-detail-input" data-field="protein_g" type="number" value="${m.protein_g ?? ''}" placeholder="e.g. 30">
          </div>
          <div class="meal-detail-row">
            <span class="meal-detail-label">Carbs (g)</span>
            <input class="meal-detail-input" data-field="carbs_g" type="number" value="${m.carbs_g ?? ''}" placeholder="e.g. 45">
          </div>
          <div class="meal-detail-row">
            <span class="meal-detail-label">Fat (g)</span>
            <input class="meal-detail-input" data-field="fat_g" type="number" value="${m.fat_g ?? ''}" placeholder="e.g. 12">
          </div>
          <div class="meal-detail-row">
            <span class="meal-detail-label">Details</span>
            <input class="meal-detail-input" data-field="notes" value="${escHtml(details)}" placeholder="Category, notes…">
          </div>
          <button class="meal-save-btn" data-id="${m.id}">Save Changes</button>
        </div>`;
      div.querySelector('.meal-entry-header').addEventListener('click', () => {
        el.querySelectorAll('.meal-entry.expanded').forEach(e => { if (e !== div) e.classList.remove('expanded'); });
        div.classList.toggle('expanded');
      });
      el.appendChild(div);
    });

    // Re-log handlers
    el.querySelectorAll('.meal-relog-btn').forEach(btn => btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const activity = btn.dataset.activity;
      const calories = btn.dataset.calories;
      const details = btn.dataset.details;
      btn.textContent = '…'; btn.disabled = true;
      try {
        await apiFetch('/api/meals', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ activity, calories: calories ? parseInt(calories) : undefined, notes: details || undefined }),
        });
        loadMealHistory();
      } catch { btn.textContent = '↩'; btn.disabled = false; }
    }));

    // Delete handlers
    el.querySelectorAll('.meal-delete-btn').forEach(btn => btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm('Delete this meal?')) return;
      await apiFetch(`/api/meals/${btn.dataset.id}`, { method: 'DELETE' });
      loadMealHistory();
    }));

    // Save handlers
    el.querySelectorAll('.meal-save-btn').forEach(btn => btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const entry = btn.closest('.meal-entry');
      const id = btn.dataset.id;
      const body = {};
      entry.querySelectorAll('.meal-detail-input').forEach(inp => {
        const field = inp.dataset.field;
        const val = inp.value.trim();
        if (['calories','protein_g','carbs_g','fat_g'].includes(field)) { if (val) body[field] = parseInt(val); }
        else if (val) body[field] = val;
      });
      btn.textContent = 'Saving…'; btn.disabled = true;
      await apiFetch(`/api/meals/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      loadMealHistory();
    }));
  } catch { el.innerHTML = '<div class="empty-state">Error loading meals.</div>'; }
}
async function loadBibleProgress() {
  const el=document.getElementById('bible-progress');
  try { const d=await apiFetch(`/api/users/${currentUserId}/bible`).then(r=>r.json()); el.innerHTML=`<div class="log-entry"><div class="log-entry-meta" style="white-space:pre-line">${d.progress}</div></div>`; } catch { el.innerHTML=''; }
}

// Offer check-in via voice overlay (called from form-based log buttons)
async function offerVoiceCheckin(context) {
  const vm = appendVMsg('system', 'Would you like a quick mood check-in? Say yes or no.');
  await speak('Would you like a quick mood check-in? Say yes or no.');
  const answer = await new Promise(resolve => {
    startRecognition('overlay', t => { voiceStatus.textContent = t; }, t => resolve(t));
    setTimeout(() => resolve(null), 7000);
  });
  voiceStatus.textContent = '';
  if (answer && /yes|yeah|sure|okay|ok/i.test(answer)) {
    // Run questionnaire inline on home (switch to home view for cleaner UX)
    closeVoiceOverlay();
    showView('home');
    await new Promise(r => setTimeout(r, 400));
    inlineQuestionnaire = new InlineQuestionnaire(context);
    await inlineQuestionnaire.start();
  } else {
    await speak('No problem!');
    closeVoiceOverlay();
  }
}

document.getElementById('history-search-btn')?.addEventListener('click', () => {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:200;display:flex;flex-direction:column;justify-content:flex-end';
  overlay.innerHTML = `
    <div style="position:absolute;inset:0;background:rgba(0,0,0,0.4)" id="hs-backdrop"></div>
    <div style="background:var(--bg);border-radius:20px 20px 0 0;padding:20px;position:relative;max-height:85vh;overflow-y:auto">
      <div style="font-weight:700;font-size:15px;margin-bottom:12px">Search Your History</div>
      <div style="display:flex;gap:8px;margin-bottom:16px">
        <input id="hs-input" type="text" class="add-task-input" placeholder="e.g. 'workouts last week', 'what I ate Monday'" style="flex:1">
        <button id="hs-search" class="add-task-btn" style="flex-shrink:0">Search</button>
      </div>
      <div id="hs-results" style="font-size:13px;line-height:1.6;color:var(--text);min-height:60px"></div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#hs-backdrop').addEventListener('click', () => overlay.remove());
  const input = overlay.querySelector('#hs-input');
  const results = overlay.querySelector('#hs-results');
  const doSearch = async () => {
    const q = input.value.trim(); if (!q) return;
    results.innerHTML = '<div class="spinner"></div>';
    try {
      let full = '';
      const res = await apiFetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: `Search my history and logs: ${q}` }) });
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n'); buf = lines.pop();
        for (const l of lines) {
          if (!l.startsWith('data: ')) continue;
          const raw = l.slice(6).trim(); if (raw === '[DONE]') break;
          try { const o = JSON.parse(raw); if (o.text) full += o.text; } catch {}
        }
      }
      results.style.whiteSpace = 'pre-wrap';
      results.textContent = full || 'No results found.';
    } catch { results.textContent = 'Error searching. Please try again.'; }
  };
  overlay.querySelector('#hs-search').addEventListener('click', doSearch);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
  setTimeout(() => input.focus(), 100);
});

// ── Settings ──────────────────────────────────────────────────────────────────
// ── Weather location settings ─────────────────────────────────────────────────
async function loadWeatherSettings() {
  const inp = document.getElementById('weather-city-input');
  const status = document.getElementById('weather-city-status');
  if (!inp) return;
  try {
    const data = await apiFetch('/api/profile').then(r => r.json());
    const p = data.profile || {};
    if (p.weather_city) inp.value = p.weather_city;
    else if (p.weather_lat) inp.value = `${p.weather_lat}, ${p.weather_lon}`;
    else inp.placeholder = 'Chicago, IL (default)';
  } catch {}
  status.textContent = '';
}

document.getElementById('weather-city-save')?.addEventListener('click', async () => {
  const inp = document.getElementById('weather-city-input');
  const status = document.getElementById('weather-city-status');
  const city = inp.value.trim();
  if (!city) return;
  status.textContent = 'Looking up…';
  try {
    const geoRes = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(city)}&count=1&language=en&format=json`);
    const geo = await geoRes.json();
    if (!geo.results?.length) { status.textContent = 'City not found. Try a different name.'; return; }
    const { latitude, longitude, name, admin1, country } = geo.results[0];
    const label = [name, admin1, country].filter(Boolean).join(', ');
    await apiFetch('/api/profile', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ weather_lat: String(latitude), weather_lon: String(longitude), weather_city: label }),
    });
    inp.value = label;
    status.textContent = `✓ Saved (${latitude.toFixed(2)}, ${longitude.toFixed(2)})`;
  } catch { status.textContent = 'Error saving location.'; }
});

function initSettingsUI() {
  const darkT      = document.getElementById('setting-darkmode');
  const timeT      = document.getElementById('setting-12h');
  const ttsT       = document.getElementById('setting-tts');
  const checkinT   = document.getElementById('setting-checkin');
  const schedHomeT = document.getElementById('setting-show-schedule');
  const userSel    = document.getElementById('user-switcher');

  darkT.checked      = S.get('darkMode', false);
  timeT.checked      = S.get('use12h', true);
  ttsT.checked       = S.get('ttsEnabled', true);
  checkinT.checked   = S.get('autoCheckin', true);
  schedHomeT.checked = S.get(`showScheduleHome_${currentUserId}`, true);
  // Populate user switcher dynamically
  apiFetch('/api/users').then(r => r.json()).then(data => {
    userSel.innerHTML = '';
    (data.users || []).forEach(u => {
      const o = document.createElement('option');
      o.value = u.id; o.textContent = u.name;
      if (u.id === currentUserId) o.selected = true;
      userSel.appendChild(o);
    });
  }).catch(() => { userSel.innerHTML = `<option value="${currentUserId}">User ${currentUserId}</option>`; });
  userSel.value      = currentUserId;

  darkT.onchange      = () => { S.set('darkMode', darkT.checked); applyTheme(); };
  timeT.onchange      = () => { S.set('use12h', timeT.checked); if (activeView==='upcoming') loadSchedule(schedDate); };
  ttsT.onchange       = () => { S.set('ttsEnabled', ttsT.checked); ttsEnabled = ttsT.checked; };
  checkinT.onchange   = () => S.set('autoCheckin', checkinT.checked);
  schedHomeT.onchange = () => { S.set(`showScheduleHome_${currentUserId}`, schedHomeT.checked); initHomeForUser(); };

  // Voice selector — populate once voices load
  const voiceSel  = document.getElementById('setting-voice');
  const speedSel  = document.getElementById('setting-tts-speed');
  function populateVoiceList() {
    const voices = window.speechSynthesis?.getVoices() || [];
    const enVoices = voices.filter(v => v.lang.startsWith('en'));
    if (!enVoices.length) return;
    voiceSel.innerHTML = '';
    enVoices.forEach(v => {
      const o = document.createElement('option');
      o.value = v.name; o.textContent = v.name.replace(' (Premium)', '★ ').replace(' (Enhanced)', '+ ');
      if (_ttsVoice && v.name === _ttsVoice.name) o.selected = true;
      voiceSel.appendChild(o);
    });
    const saved = S.get('ttsVoiceName', null);
    if (saved) voiceSel.value = saved;
  }
  populateVoiceList();
  if ('speechSynthesis' in window) window.speechSynthesis.addEventListener('voiceschanged', populateVoiceList);

  voiceSel.onchange = () => {
    const name = voiceSel.value;
    S.set('ttsVoiceName', name);
    const v = window.speechSynthesis?.getVoices().find(v => v.name === name);
    if (v) { _ttsVoice = v; speak('Hello, I sound like this.'); }
  };

  speedSel.value = S.get('ttsRate', '0.90');
  speedSel.onchange = () => S.set('ttsRate', speedSel.value);

  // User switcher is display-only; switching requires re-authentication
  userSel.disabled = true;
  document.getElementById('switch-profile-btn').onclick = async () => {
    const token = S.get('sessionToken', null);
    if (token) {
      await apiFetch('/api/auth/logout', { method: 'POST', headers: { 'X-Session-Token': token } }).catch(() => {});
    }
    S.del('sessionToken');
    S.del('userId');
    currentUserId = null;
    showLoginScreen();
  };
}

async function loadFeatureToggles() {
  const el = document.getElementById('feature-toggles');
  el.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';
  try {
    const data = await apiFetch(`/api/users/${currentUserId}/features`).then(r=>r.json());
    el.innerHTML='';
    data.features.forEach(f => {
      const row = document.createElement('div'); row.className='feature-row';
      row.innerHTML=`<span>${f.label}</span><label class="toggle-switch"><input type="checkbox" ${f.enabled?'checked':''} data-feature="${f.feature}"><span class="toggle-track"><span class="toggle-thumb"></span></span></label>`;
      el.appendChild(row);
    });
    el.querySelectorAll('input').forEach(chk => chk.addEventListener('change', async () => {
      await apiFetch(`/api/users/${currentUserId}/features`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({feature:chk.dataset.feature, enabled:chk.checked}) });
      applyFeatureVisibility(data.features.map(f => f.feature===chk.dataset.feature?{...f,enabled:chk.checked}:f));
    }));
    applyFeatureVisibility(data.features);
  } catch { el.innerHTML='<div class="empty-state">Error loading features.</div>'; }
}

function applyFeatureVisibility(features) {
  const map = Object.fromEntries(features.map(f=>[f.feature,f.enabled]));
  const h = document.getElementById('tab-health');
  if (h) h.style.display = map.cycle_tracking ? '' : 'none';
}

async function loadSharingSettings() {
  const el = document.getElementById('sharing-content');
  el.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';
  try {
    const data = await apiFetch(`/api/users/${currentUserId}/sharing`).then(r=>r.json());
    el.innerHTML = '';
    if (!data.sharing.length) { el.innerHTML='<div class="empty-state">No other profiles to share with.</div>'; return; }
    data.sharing.forEach(target => {
      const section = document.createElement('div'); section.className='sharing-target';
      section.innerHTML = `<div class="sharing-target-label">Share with ${target.user_name}</div>`;
      target.categories.forEach((cat, i) => {
        const row = document.createElement('div'); row.className='feature-row';
        if (i===0) row.style.cssText='border-radius:14px 14px 0 0;border-top:none';
        if (i===target.categories.length-1) row.style.cssText='border-radius:0 0 14px 14px';
        if (target.categories.length===1) row.style.cssText='border-radius:14px;border-top:none';
        row.innerHTML=`<span>${cat.label}</span><label class="toggle-switch"><input type="checkbox" ${cat.shared?'checked':''} data-owner="${currentUserId}" data-target="${target.user_id}" data-cat="${cat.category}"><span class="toggle-track"><span class="toggle-thumb"></span></span></label>`;
        section.appendChild(row);
      });
      el.appendChild(section);
    });
    el.querySelectorAll('input[data-cat]').forEach(chk => chk.addEventListener('change', async () => {
      await apiFetch(`/api/users/${chk.dataset.owner}/sharing`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({target_user_id:parseInt(chk.dataset.target),data_category:chk.dataset.cat,shared:chk.checked}) });
    }));
  } catch { el.innerHTML='<div class="empty-state">Error loading privacy settings.</div>'; }
}

// ── Routine (Daily Routine settings) ──────────────────────────────────────────
const BLOCK_TYPES = ['deep_work','shallow_work','exercise','meal','faith','rest','personal','admin'];
const DOW_LABELS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

// ── Supplements ───────────────────────────────────────────────────────────────
const SUPP_TIMING_LABELS = {
  morning: 'Morning (with breakfast)',
  with_meal: 'With a meal',
  afternoon: 'Afternoon',
  evening: 'Evening',
  bedtime: 'At bedtime',
};

async function loadSupplements() {
  const el = document.getElementById('supplements-list');
  if (!el) return;
  el.innerHTML = '<div style="padding:8px 0;font-size:13px;color:var(--muted)">Loading…</div>';
  try {
    const { supplements } = await apiFetch('/api/supplements').then(r => r.json());
    el.innerHTML = '';
    if (!supplements.length) {
      el.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:8px 0">No supplements added yet.</div>';
      return;
    }
    supplements.forEach(s => {
      const card = document.createElement('div');
      card.className = 'routine-card';
      card.innerHTML = `
        <div class="routine-card-header">
          <div>
            <div class="routine-title">${escHtml(s.name)}${s.dose ? ` <span style="font-weight:400;color:var(--muted)">${escHtml(s.dose)}</span>` : ''}</div>
            <div class="routine-meta">${SUPP_TIMING_LABELS[s.timing] || s.timing}${s.notes ? ' · ' + escHtml(s.notes) : ''}${!s.enabled ? ' · <em>disabled</em>' : ''}</div>
          </div>
          <div style="display:flex;gap:6px;flex-shrink:0">
            <button class="inline-btn" style="font-size:11px" data-supp-edit="${s.id}">Edit</button>
            <button class="inline-btn" style="font-size:11px;background:var(--surface2);color:var(--muted)" data-supp-del="${s.id}">Delete</button>
          </div>
        </div>`;
      card.querySelector('[data-supp-edit]').addEventListener('click', () => showSupplementForm(s));
      card.querySelector('[data-supp-del]').addEventListener('click', async () => {
        await apiFetch(`/api/supplements/${s.id}`, { method: 'DELETE' });
        loadSupplements();
      });
      el.appendChild(card);
    });
  } catch { el.innerHTML = '<div style="color:var(--muted);font-size:13px">Error loading supplements.</div>'; }
}

function showSupplementForm(supp = null) {
  const existing = document.getElementById('supp-form-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'supp-form-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:900;display:flex;align-items:flex-end';
  overlay.innerHTML = `
    <div style="background:var(--surface);border-radius:20px 20px 0 0;padding:20px 20px max(var(--safe-bot),20px);width:100%;max-height:85vh;overflow-y:auto">
      <div style="font-size:15px;font-weight:700;margin-bottom:14px">${supp ? 'Edit' : 'Add'} Supplement</div>
      <input id="sf-name" class="add-task-input" placeholder="Name (e.g. Vitamin D3)" value="${supp ? escHtml(supp.name) : ''}" style="margin-bottom:8px">
      <input id="sf-dose" class="add-task-input" placeholder="Dose (e.g. 2000 IU, 500mg) — optional" value="${supp ? escHtml(supp.dose || '') : ''}" style="margin-bottom:8px">
      <select id="sf-timing" class="add-task-select" style="width:100%;margin-bottom:8px">
        ${Object.entries(SUPP_TIMING_LABELS).map(([v, l]) => `<option value="${v}"${supp?.timing === v ? ' selected' : ''}>${l}</option>`).join('')}
      </select>
      <input id="sf-notes" class="add-task-input" placeholder="Notes (e.g. take with food, avoid with calcium) — optional" value="${supp ? escHtml(supp.notes || '') : ''}" style="margin-bottom:8px">
      <label style="display:flex;align-items:center;gap:8px;font-size:13px;margin-bottom:14px">
        <input type="checkbox" id="sf-enabled"${!supp || supp.enabled ? ' checked' : ''}> Enabled
      </label>
      <div style="display:flex;gap:8px">
        <button id="sf-save" class="add-task-btn">Save</button>
        <button id="sf-cancel" class="add-task-btn-cancel">Cancel</button>
      </div>
    </div>`;

  overlay.querySelector('#sf-cancel').addEventListener('click', () => overlay.remove());
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  overlay.querySelector('#sf-save').addEventListener('click', async () => {
    const name = overlay.querySelector('#sf-name').value.trim();
    if (!name) return;
    const body = {
      name,
      dose: overlay.querySelector('#sf-dose').value.trim() || null,
      timing: overlay.querySelector('#sf-timing').value,
      notes: overlay.querySelector('#sf-notes').value.trim() || null,
      enabled: overlay.querySelector('#sf-enabled').checked,
    };
    if (supp) await apiFetch(`/api/supplements/${supp.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    else await apiFetch('/api/supplements', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    overlay.remove();
    loadSupplements();
  });
  document.body.appendChild(overlay);
  setTimeout(() => overlay.querySelector('#sf-name').focus(), 50);
}

document.getElementById('add-supplement-btn')?.addEventListener('click', () => showSupplementForm());

async function loadRoutine() {
  const el = document.getElementById('routine-list');
  if (!el) return;
  el.innerHTML = '<div style="padding:8px 0"><div class="spinner"></div></div>';
  try {
    const data = await apiFetch('/api/routine').then(r => r.json());
    el.innerHTML = '';
    if (!data.items.length) { el.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:8px 0">No routine items yet.</div>'; return; }
    data.items.forEach(item => {
      const card = document.createElement('div');
      card.className = 'routine-card';
      const timeStr = item.start_time ? (item.end_time ? `${item.start_time}–${item.end_time}` : item.start_time) : '';
      const dowParts = (item.days_of_week || '').split(',').map(Number).filter(d => d >= 1 && d <= 7);
      const dowStr = dowParts.length === 7 ? 'Every day' : dowParts.map(d => DOW_LABELS[d-1]).join(', ');
      card.innerHTML = `
        <div class="routine-card-header">
          <div>
            <div class="routine-title">${escHtml(item.title)}${item.enabled ? '' : ' <span style="color:var(--muted)">(off)</span>'}</div>
            <div class="routine-meta">${timeStr ? escHtml(timeStr) + ' · ' : ''}${escHtml(dowStr)} · ${escHtml(item.block_type)}</div>
          </div>
          <div style="display:flex;gap:6px">
            <button class="inline-btn" data-routine-edit="${item.id}" style="font-size:11px">Edit</button>
            <button class="inline-btn" data-routine-delete="${item.id}" style="font-size:11px;background:var(--surface2)">Del</button>
          </div>
        </div>`;
      el.appendChild(card);
      card.querySelector('[data-routine-edit]').addEventListener('click', () => showRoutineForm(item));
      card.querySelector('[data-routine-delete]').addEventListener('click', async () => {
        if (!confirm(`Delete "${item.title}"?`)) return;
        await apiFetch(`/api/routine/${item.id}`, { method: 'DELETE' });
        loadRoutine();
      });
    });
  } catch { el.innerHTML = '<div style="color:var(--muted);font-size:13px">Error loading routine.</div>'; }
}

let _routineFormEl = null;

function showRoutineForm(item = null) {
  if (_routineFormEl) _routineFormEl.remove();
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:200;display:flex;flex-direction:column;justify-content:flex-end';
  const dow = item ? (item.days_of_week || '1,2,3,4,5,6,7').split(',').map(Number) : [1,2,3,4,5,6,7];
  overlay.innerHTML = `
    <div style="position:absolute;inset:0;background:rgba(0,0,0,0.45)" id="routine-backdrop"></div>
    <div style="background:var(--bg);border-radius:20px 20px 0 0;padding:20px;max-height:85vh;overflow-y:auto;position:relative">
      <div style="font-weight:700;font-size:15px;margin-bottom:14px">${item ? 'Edit Routine Item' : 'Add Routine Item'}</div>
      <label style="font-size:12px;color:var(--muted)">Title</label>
      <input id="rf-title" type="text" value="${escHtml(item?.title || '')}" class="add-task-input" style="margin-bottom:10px">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
        <div>
          <label style="font-size:12px;color:var(--muted)">Start time</label>
          <input id="rf-start" type="time" value="${item?.start_time || ''}" class="add-task-input">
        </div>
        <div>
          <label style="font-size:12px;color:var(--muted)">End time</label>
          <input id="rf-end" type="time" value="${item?.end_time || ''}" class="add-task-input">
        </div>
      </div>
      <label style="font-size:12px;color:var(--muted)">Duration (min, optional)</label>
      <input id="rf-dur" type="number" min="1" value="${item?.duration_minutes || ''}" class="add-task-input" style="margin-bottom:10px">
      <label style="font-size:12px;color:var(--muted)">Block type</label>
      <select id="rf-type" class="add-task-select" style="width:100%;margin-bottom:10px">
        ${BLOCK_TYPES.map(t => `<option value="${t}"${item?.block_type===t?' selected':''}>${t.replace('_',' ')}</option>`).join('')}
      </select>
      <label style="font-size:12px;color:var(--muted)">Days of week</label>
      <div id="rf-dow" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">
        ${DOW_LABELS.map((l,i) => `<label style="display:flex;align-items:center;gap:3px;font-size:12px"><input type="checkbox" value="${i+1}" ${dow.includes(i+1)?'checked':''}>${l}</label>`).join('')}
      </div>
      <label style="font-size:12px;color:var(--muted)">Notes</label>
      <textarea id="rf-notes" class="add-task-input" rows="2" style="margin-bottom:10px">${escHtml(item?.notes || '')}</textarea>
      <label style="display:flex;align-items:center;gap:8px;margin-bottom:14px;font-size:14px">
        <input type="checkbox" id="rf-enabled" ${(!item || item.enabled) ? 'checked' : ''}> Enabled
      </label>
      <div style="display:flex;gap:8px">
        <button id="rf-save" style="flex:1;padding:12px;border-radius:12px;background:var(--accent);color:#fff;border:none;font-size:14px;font-weight:600;cursor:pointer">${item ? 'Save' : 'Add'}</button>
        <button id="rf-cancel" style="flex:1;padding:12px;border-radius:12px;background:var(--surface2);color:var(--text);border:none;font-size:14px;cursor:pointer">Cancel</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  _routineFormEl = overlay;
  overlay.querySelector('#routine-backdrop').addEventListener('click', () => { overlay.remove(); _routineFormEl = null; });
  overlay.querySelector('#rf-cancel').addEventListener('click', () => { overlay.remove(); _routineFormEl = null; });
  overlay.querySelector('#rf-save').addEventListener('click', async () => {
    const title = overlay.querySelector('#rf-title').value.trim();
    if (!title) return;
    const dowChecked = Array.from(overlay.querySelectorAll('#rf-dow input:checked')).map(i => i.value).join(',') || '1,2,3,4,5,6,7';
    const body = {
      title,
      start_time: overlay.querySelector('#rf-start').value || null,
      end_time: overlay.querySelector('#rf-end').value || null,
      duration_minutes: overlay.querySelector('#rf-dur').value ? parseInt(overlay.querySelector('#rf-dur').value) : null,
      block_type: overlay.querySelector('#rf-type').value,
      days_of_week: dowChecked,
      notes: overlay.querySelector('#rf-notes').value.trim() || null,
      enabled: overlay.querySelector('#rf-enabled').checked,
    };
    const btn = overlay.querySelector('#rf-save');
    btn.disabled = true; btn.textContent = 'Saving…';
    try {
      if (item) await apiFetch(`/api/routine/${item.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      else await apiFetch('/api/routine', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      overlay.remove(); _routineFormEl = null;
      loadRoutine();
    } catch (e) { console.error('Routine save failed:', e); btn.disabled = false; btn.textContent = item ? 'Save' : 'Add'; }
  });
}

document.getElementById('add-routine-btn')?.addEventListener('click', () => showRoutineForm());

// ── Recurring Tasks (Settings) ─────────────────────────────────────────────
async function loadRecurringTasks() {
  const el = document.getElementById('recurring-tasks-list');
  if (!el) return;
  el.innerHTML = '<div style="font-size:12px;color:var(--muted)">Loading…</div>';
  try {
    const data = await apiFetch('/api/tasks?recurring=true&limit=50').then(r => r.json());
    const tasks = data.tasks || [];
    if (!tasks.length) {
      el.innerHTML = '<div style="font-size:12px;color:var(--muted)">No recurring tasks yet.</div>';
      return;
    }
    el.innerHTML = '';
    tasks.forEach(t => {
      const row = document.createElement('div');
      row.className = 'supplement-row';
      row.innerHTML = `
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escHtml(t.title)}</div>
          <div style="font-size:11px;color:var(--muted)">${escHtml(t.recurring)} · ${escHtml(t.bucket)} · ${t.status}</div>
        </div>
        <button class="icon-btn" data-id="${t.id}" aria-label="Delete">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
        </button>
      `;
      row.querySelector('.icon-btn').addEventListener('click', async () => {
        if (!confirm(`Delete "${t.title}"?`)) return;
        await apiFetch(`/api/tasks/${t.id}`, { method: 'DELETE' });
        loadRecurringTasks();
      });
      el.appendChild(row);
    });
  } catch { el.innerHTML = '<div style="font-size:12px;color:var(--muted)">Error loading.</div>'; }
}

document.getElementById('add-recurring-btn')?.addEventListener('click', async () => {
  const bucketsData = await apiFetch('/api/tasks/buckets').then(r => r.json()).catch(() => ({ buckets: [] }));
  const bucketNames = (bucketsData.buckets || []).map(b => b.name);
  const FREQS = ['daily', 'weekdays', 'weekends', 'weekly', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:200;display:flex;flex-direction:column;justify-content:flex-end';
  overlay.innerHTML = `
    <div style="position:absolute;inset:0;background:rgba(0,0,0,0.45)" id="rec-backdrop"></div>
    <div style="background:var(--bg);border-radius:20px 20px 0 0;padding:20px;position:relative">
      <div style="font-weight:700;font-size:15px;margin-bottom:14px">Add Recurring Task</div>
      <label style="font-size:12px;color:var(--muted)">Task name</label>
      <input id="rec-title" type="text" class="add-task-input" placeholder="e.g. Review weekly goals" style="margin-bottom:10px">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px">
        <div>
          <label style="font-size:12px;color:var(--muted)">Frequency</label>
          <select id="rec-freq" class="add-task-select" style="width:100%">
            ${FREQS.map(f => `<option value="${f}">${f.charAt(0).toUpperCase()+f.slice(1)}</option>`).join('')}
          </select>
        </div>
        <div>
          <label style="font-size:12px;color:var(--muted)">Bucket</label>
          <select id="rec-bucket" class="add-task-select" style="width:100%">
            ${bucketNames.map(b => `<option value="${b}">${b}</option>`).join('')}
          </select>
        </div>
      </div>
      <div style="display:flex;gap:8px">
        <button id="rec-save" style="flex:1;padding:12px;border-radius:12px;background:var(--accent);color:#fff;border:none;font-size:14px;font-weight:600;cursor:pointer">Add</button>
        <button id="rec-cancel" style="flex:1;padding:12px;border-radius:12px;background:var(--surface2);color:var(--text);border:none;font-size:14px;cursor:pointer">Cancel</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#rec-backdrop').addEventListener('click', () => overlay.remove());
  overlay.querySelector('#rec-cancel').addEventListener('click', () => overlay.remove());
  overlay.querySelector('#rec-save').addEventListener('click', async () => {
    const title = overlay.querySelector('#rec-title').value.trim();
    if (!title) { overlay.querySelector('#rec-title').focus(); return; }
    const freq = overlay.querySelector('#rec-freq').value;
    const bucket = overlay.querySelector('#rec-bucket').value;
    const btn = overlay.querySelector('#rec-save');
    btn.disabled = true; btn.textContent = 'Saving…';
    try {
      await apiFetch('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, bucket, recurring: freq }) });
      overlay.remove();
      loadRecurringTasks();
    } catch { btn.disabled = false; btn.textContent = 'Add'; }
  });
});

// ── Recurring Tab (Current view) ───────────────────────────────────────────
async function loadRecurringTab() {
  await Promise.all([_loadCurrRoutine(), _loadCurrRecurring()]);
}

async function _loadCurrRoutine() {
  const el = document.getElementById('curr-routine-list');
  if (!el) return;
  el.innerHTML = '<div style="padding:6px 0"><div class="spinner"></div></div>';
  try {
    const [routineData, completionData] = await Promise.all([
      apiFetch('/api/routine').then(r => r.json()),
      apiFetch('/api/routine/completions').then(r => r.json()).catch(() => ({ completions: [] })),
    ]);
    el.innerHTML = '';
    if (!routineData.items.length) { el.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:8px 0">No routine items yet.</div>'; return; }
    const compMap = {};
    (completionData.completions || []).forEach(c => { compMap[c.id] = c; });
    routineData.items.forEach(item => {
      const comp = compMap[item.id] || {};
      const done = comp.done_today || false;
      const streak = comp.streak || 0;
      const card = document.createElement('div');
      card.className = 'routine-card';
      const timeStr = item.start_time ? (item.end_time ? `${item.start_time}–${item.end_time}` : item.start_time) : '';
      const dowParts = (item.days_of_week || '').split(',').map(Number).filter(d => d >= 1 && d <= 7);
      const dowStr = dowParts.length === 7 ? 'Every day' : dowParts.map(d => DOW_LABELS[d-1]).join(', ');
      card.innerHTML = `
        <div class="routine-card-header">
          <label class="routine-check-wrap" style="display:flex;align-items:center;gap:10px;flex:1;cursor:pointer">
            <input type="checkbox" class="routine-check" data-id="${item.id}" ${done ? 'checked' : ''} style="width:18px;height:18px;accent-color:var(--accent);cursor:pointer;flex-shrink:0">
            <div style="flex:1">
              <div class="routine-title" style="${done ? 'text-decoration:line-through;opacity:0.5' : ''}">${escHtml(item.title)}${item.enabled ? '' : ' <span style="color:var(--muted)">(off)</span>'}</div>
              <div class="routine-meta">${timeStr ? escHtml(timeStr) + ' · ' : ''}${escHtml(dowStr)}${streak > 1 ? ` · 🔥 ${streak} day streak` : ''}</div>
            </div>
          </label>
          <div style="display:flex;gap:6px">
            <button class="inline-btn" data-routine-edit style="font-size:11px">Edit</button>
            <button class="inline-btn" data-routine-delete style="font-size:11px;background:var(--surface2)">Del</button>
          </div>
        </div>`;
      card.querySelector('.routine-check').addEventListener('change', async (e) => {
        await apiFetch(`/api/routine/completions/${item.id}`, { method: 'POST' });
        _loadCurrRoutine();
      });
      card.querySelector('[data-routine-edit]').addEventListener('click', () => showRoutineForm(item));
      card.querySelector('[data-routine-delete]').addEventListener('click', async () => {
        if (!confirm(`Delete "${item.title}"?`)) return;
        await apiFetch(`/api/routine/${item.id}`, { method: 'DELETE' });
        _loadCurrRoutine();
      });
      el.appendChild(card);
    });
  } catch { el.innerHTML = '<div style="color:var(--muted);font-size:13px">Error loading.</div>'; }
}

async function _loadCurrRecurring() {
  const el = document.getElementById('curr-recurring-list');
  if (!el) return;
  el.innerHTML = '<div style="padding:6px 0"><div class="spinner"></div></div>';
  try {
    const data = await apiFetch('/api/tasks?recurring=true&limit=50').then(r => r.json());
    const tasks = data.tasks || [];
    if (!tasks.length) { el.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:8px 0">No recurring tasks yet.</div>'; return; }
    el.innerHTML = '';
    tasks.forEach(t => {
      const row = document.createElement('div');
      row.className = 'supplement-row';
      row.innerHTML = `
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escHtml(t.title)}</div>
          <div style="font-size:11px;color:var(--muted)">${escHtml(t.recurring)} · ${escHtml(t.bucket)}</div>
        </div>
        <button class="icon-btn" aria-label="Delete">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
        </button>`;
      row.querySelector('.icon-btn').addEventListener('click', async () => {
        if (!confirm(`Delete "${t.title}"?`)) return;
        await apiFetch(`/api/tasks/${t.id}`, { method: 'DELETE' });
        _loadCurrRecurring();
      });
      el.appendChild(row);
    });
  } catch { el.innerHTML = '<div style="color:var(--muted);font-size:13px">Error loading.</div>'; }
}

document.getElementById('curr-add-routine-btn')?.addEventListener('click', () => showRoutineForm());
document.getElementById('curr-add-recurring-btn')?.addEventListener('click', async () => {
  // Reuse the existing add-recurring overlay logic but refresh Recurring tab after save
  const bucketsData = await apiFetch('/api/tasks/buckets').then(r => r.json()).catch(() => ({ buckets: [] }));
  const bucketNames = (bucketsData.buckets || []).map(b => b.name);
  const FREQS = ['daily', 'weekdays', 'weekends', 'weekly', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:200;display:flex;flex-direction:column;justify-content:flex-end';
  overlay.innerHTML = `
    <div style="position:absolute;inset:0;background:rgba(0,0,0,0.45)" id="crec-backdrop"></div>
    <div style="background:var(--bg);border-radius:20px 20px 0 0;padding:20px;position:relative">
      <div style="font-weight:700;font-size:15px;margin-bottom:14px">Add Recurring Task</div>
      <label style="font-size:12px;color:var(--muted)">Task name</label>
      <input id="crec-title" type="text" class="add-task-input" placeholder="e.g. Review weekly goals" style="margin-bottom:10px">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px">
        <div><label style="font-size:12px;color:var(--muted)">Frequency</label>
          <select id="crec-freq" class="add-task-select" style="width:100%">${FREQS.map(f => `<option value="${f}">${f.charAt(0).toUpperCase()+f.slice(1)}</option>`).join('')}</select></div>
        <div><label style="font-size:12px;color:var(--muted)">Bucket</label>
          <select id="crec-bucket" class="add-task-select" style="width:100%">${bucketNames.map(b => `<option value="${b}">${b}</option>`).join('')}</select></div>
      </div>
      <div style="display:flex;gap:8px">
        <button id="crec-save" style="flex:1;padding:12px;border-radius:12px;background:var(--accent);color:#fff;border:none;font-size:14px;font-weight:600;cursor:pointer">Add</button>
        <button id="crec-cancel" style="flex:1;padding:12px;border-radius:12px;background:var(--surface2);color:var(--text);border:none;font-size:14px;cursor:pointer">Cancel</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#crec-backdrop').addEventListener('click', () => overlay.remove());
  overlay.querySelector('#crec-cancel').addEventListener('click', () => overlay.remove());
  overlay.querySelector('#crec-save').addEventListener('click', async () => {
    const title = overlay.querySelector('#crec-title').value.trim();
    if (!title) { overlay.querySelector('#crec-title').focus(); return; }
    const freq = overlay.querySelector('#crec-freq').value;
    const bucket = overlay.querySelector('#crec-bucket').value;
    const btn = overlay.querySelector('#crec-save');
    btn.disabled = true; btn.textContent = 'Saving…';
    try {
      await apiFetch('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, bucket, recurring: freq }) });
      overlay.remove(); _loadCurrRecurring();
    } catch { btn.disabled = false; btn.textContent = 'Add'; }
  });
});

document.getElementById('goto-recurring-btn')?.addEventListener('click', () => {
  showView('current');
  document.querySelector('#view-current .sub-tab[data-tab="recurring"]')?.click();
});

// ── Diet Settings overlay ──────────────────────────────────────────────────
document.getElementById('diet-settings-btn')?.addEventListener('click', async () => {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;z-index:200;display:flex;flex-direction:column;justify-content:flex-end';
  overlay.innerHTML = `
    <div style="position:absolute;inset:0;background:rgba(0,0,0,0.45)" id="ds-backdrop"></div>
    <div style="background:var(--bg);border-radius:20px 20px 0 0;padding:20px;max-height:80vh;overflow-y:auto;position:relative">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
        <div style="font-weight:700;font-size:15px">Diet Settings</div>
        <button id="ds-close" style="background:none;border:none;font-size:20px;cursor:pointer;color:var(--muted)">✕</button>
      </div>
      <div style="font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px;margin-top:4px">Daily Targets</div>
      <div id="ds-targets-form" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px">
        <div><label style="font-size:11px;color:var(--muted)">Calories (kcal)</label><input id="dst-cal" type="number" class="add-task-input" placeholder="e.g. 2000" style="margin-top:3px"></div>
        <div><label style="font-size:11px;color:var(--muted)">Protein (g)</label><input id="dst-pro" type="number" class="add-task-input" placeholder="e.g. 150" style="margin-top:3px"></div>
        <div><label style="font-size:11px;color:var(--muted)">Carbs (g)</label><input id="dst-carb" type="number" class="add-task-input" placeholder="e.g. 200" style="margin-top:3px"></div>
        <div><label style="font-size:11px;color:var(--muted)">Fat (g)</label><input id="dst-fat" type="number" class="add-task-input" placeholder="e.g. 65" style="margin-top:3px"></div>
      </div>
      <button id="dst-save" class="add-task-btn" style="width:100%;margin-bottom:16px">Save Targets</button>
      <div style="font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px">Vitamins &amp; Supplements</div>
      <div id="ds-supp-list"><div class="spinner"></div></div>
      <button id="ds-add-supp" class="inline-btn" style="margin-top:8px;width:100%">+ Add supplement</button>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#ds-backdrop').addEventListener('click', () => overlay.remove());
  overlay.querySelector('#ds-close').addEventListener('click', () => overlay.remove());
  overlay.querySelector('#ds-add-supp').addEventListener('click', () => { overlay.remove(); showSupplementForm(); });

  // Load supplements into this overlay
  try {
    const { supplements } = await apiFetch('/api/supplements').then(r => r.json());
    const listEl = overlay.querySelector('#ds-supp-list');
    // Load and pre-fill calorie targets
    try {
      const td = await apiFetch(`/api/users/${currentUserId}/calorie-targets`).then(r => r.json());
      const tgt = td.targets || {};
      if (tgt.calorie_target) overlay.querySelector('#dst-cal').value = tgt.calorie_target;
      if (tgt.protein_target_g) overlay.querySelector('#dst-pro').value = tgt.protein_target_g;
      if (tgt.carbs_target_g) overlay.querySelector('#dst-carb').value = tgt.carbs_target_g;
      if (tgt.fat_target_g) overlay.querySelector('#dst-fat').value = tgt.fat_target_g;
    } catch {}
    overlay.querySelector('#dst-save').addEventListener('click', async () => {
      const body = {};
      const cal = overlay.querySelector('#dst-cal').value; if (cal) body.calorie_target = parseInt(cal);
      const pro = overlay.querySelector('#dst-pro').value; if (pro) body.protein_target_g = parseInt(pro);
      const carb = overlay.querySelector('#dst-carb').value; if (carb) body.carbs_target_g = parseInt(carb);
      const fat = overlay.querySelector('#dst-fat').value; if (fat) body.fat_target_g = parseInt(fat);
      const btn = overlay.querySelector('#dst-save');
      btn.textContent = 'Saving…'; btn.disabled = true;
      await apiFetch(`/api/users/${currentUserId}/calorie-targets`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      btn.textContent = 'Saved ✓'; loadCalorieBar();
      setTimeout(() => { btn.textContent = 'Save Targets'; btn.disabled = false; }, 1500);
    });
    if (!supplements.length) { listEl.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:4px 0">No supplements added yet.</div>'; return; }
    listEl.innerHTML = '';
    supplements.forEach(s => {
      const row = document.createElement('div');
      row.className = 'supplement-row';
      row.innerHTML = `
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:500">${escHtml(s.name)}${s.enabled ? '' : ' <span style="color:var(--muted)">(off)</span>'}</div>
          <div style="font-size:11px;color:var(--muted)">${escHtml(s.dose || '')}${s.dose && s.timing ? ' · ' : ''}${escHtml(s.timing || '')}</div>
        </div>
        <button class="inline-btn" style="font-size:11px" data-edit>Edit</button>`;
      row.querySelector('[data-edit]').addEventListener('click', () => { overlay.remove(); showSupplementForm(s); });
      listEl.appendChild(row);
    });
  } catch { overlay.querySelector('#ds-supp-list').innerHTML = '<div style="color:var(--muted);font-size:13px">Error loading.</div>'; }
});

async function loadStats() {
  const period=document.getElementById('period-select').value;
  const el=document.getElementById('stats-content');
  el.innerHTML='<div class="no-sched"><div class="spinner"></div></div>';
  try {
    const d=await apiFetch(`/api/stats?period=${period}`).then(r=>r.json());
    const done=d.completion.completed_blocks||0, total=d.completion.total_blocks||0;
    const pct=total?Math.round(100*done/total):0;
    const rows=(d.by_type||[]).map(bt=>{const p=bt.total?Math.round(100*bt.completed/bt.total):0;return`<div class="progress-item"><label><span>${bt.block_type.replace('_',' ')}</span><span>${bt.completed}/${bt.total}</span></label><div class="progress-bar"><div class="progress-fill" style="width:${p}%"></div></div></div>`;}).join('');
    el.innerHTML=`<div class="stat-card"><h3>Completion · ${d.period}</h3><div class="big-num">${pct}%</div><div class="big-label">${done} of ${total} blocks · ${d.tasks_completed} tasks done</div></div>
      <div class="stat-card"><h3>By block type</h3><div class="progress-row">${rows||'<div style="color:var(--muted)">No data yet</div>'}</div></div>
      <div class="stat-card"><h3>API cost · ${d.period}</h3><div class="cost-row"><div><div class="cost-usd">$${d.api_cost_usd.toFixed(4)}</div><div class="big-label">${(d.api_tokens||0).toLocaleString()} tokens</div></div></div></div>`;
  } catch { el.innerHTML='<div class="no-sched">Error loading stats.</div>'; }
}
document.getElementById('period-select').addEventListener('change', loadStats);

// ── Chat Overlay (expanded home chat) ────────────────────────────────────────
const chatOverlay = document.getElementById('chat-overlay');
const chatMessages = document.getElementById('chat-messages');
const chatTextIn = document.getElementById('chat-text-input');

function openChatOverlay() {
  chatOverlay.classList.remove('hidden');
  chatMessages.innerHTML = '';
  homeChatHistory.forEach(h => {
    _appendChatMsg('user', h.user);
    _appendChatMsg('agent', h.agent);
  });
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function closeChatOverlay() {
  stopRecognition(); stopSpeaking();
  chatOverlay.classList.add('hidden');
  chatTextIn.value = '';
}

function _appendChatMsg(role, text) {
  const div = document.createElement('div');
  div.className = `cm-msg ${role}`;
  div.textContent = text;
  chatMessages.appendChild(div);
  return div;
}

document.getElementById('chat-backdrop').addEventListener('click', closeChatOverlay);

document.getElementById('chat-mic-btn').addEventListener('click', () => {
  const btn = document.getElementById('chat-mic-btn');
  if (btn.classList.contains('listening')) { stopRecognition(); return; }
  startRecognition('overlay',
    t => { chatTextIn.value = t; },
    t => { chatTextIn.value = t; sendChatMessage(); }
  );
  btn.classList.add('listening');
});

chatTextIn.addEventListener('input', () => { chatTextIn.style.height = 'auto'; chatTextIn.style.height = Math.min(chatTextIn.scrollHeight, 100) + 'px'; });
chatTextIn.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); } });
document.getElementById('chat-send-btn').addEventListener('click', sendChatMessage);

async function sendChatMessage() {
  const text = chatTextIn.value.trim();
  if (!text) return;
  chatTextIn.value = ''; chatTextIn.style.height = 'auto';
  stopRecognition();
  document.getElementById('chat-mic-btn').classList.remove('listening');
  _appendChatMsg('user', text);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  // Show typing indicator with small delay
  const typingTimer = setTimeout(() => showTypingIndicator(chatMessages), 300);

  let full = '', agentDiv = null;
  try {
    const res = await apiFetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text, history: homeChatHistory.slice(-6) }) });
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop();
      for (const l of lines) {
        if (!l.startsWith('data: ')) continue;
        const raw = l.slice(6).trim(); if (raw === '[DONE]') break;
        try {
          const o = JSON.parse(raw);
          if (o.text) {
            if (!agentDiv) { clearTimeout(typingTimer); removeTypingIndicator(); agentDiv = _appendChatMsg('agent', ''); agentDiv.classList.add('streaming'); }
            full += o.text; agentDiv.textContent = full; chatMessages.scrollTop = chatMessages.scrollHeight;
          }
        } catch {}
      }
    }
  } catch { full = 'Connection error.'; }
  clearTimeout(typingTimer); removeTypingIndicator();
  if (!agentDiv) agentDiv = _appendChatMsg('agent', '');
  agentDiv.classList.remove('streaming');
  agentDiv.textContent = full;
  updateHomeChatWindow(text, full);  // also pushes to homeChatHistory
  await speak(full);
}

// ── Swipe Handler ────────────────────────────────────────────────────────────
class SwipeHandler {
  constructor(el) {
    this.el = el;
    this.content = el.querySelector('.swipe-content');
    this.actions = el.querySelector('.swipe-actions');
    this.startX = 0; this.currentX = 0; this.swiping = false; this.open = false;
    const actionsW = this.actions ? this.actions.scrollWidth : 216;
    this.threshold = actionsW;

    el.addEventListener('touchstart', e => this._start(e), { passive: true });
    el.addEventListener('touchmove', e => this._move(e), { passive: false });
    el.addEventListener('touchend', e => this._end(e));
    // Close on tap when open
    this.content.addEventListener('click', e => {
      if (this.open) { e.preventDefault(); e.stopPropagation(); this.close(); }
    }, true);
  }

  _start(e) {
    this.startX = e.touches[0].clientX;
    this.startY = e.touches[0].clientY;
    this.swiping = false;
    this.content.style.transition = 'none';
  }

  _move(e) {
    const dx = e.touches[0].clientX - this.startX;
    const dy = e.touches[0].clientY - this.startY;
    if (!this.swiping && Math.abs(dy) > Math.abs(dx)) return; // vertical scroll
    if (Math.abs(dx) > 10) this.swiping = true;
    if (!this.swiping) return;
    e.preventDefault();
    const offset = this.open ? -this.threshold + dx : dx;
    const clamped = Math.max(-this.threshold, Math.min(0, offset));
    this.content.style.transform = `translateX(${clamped}px)`;
  }

  _end(e) {
    if (!this.swiping) return;
    this.content.style.transition = 'transform .25s ease';
    const dx = e.changedTouches[0].clientX - this.startX;
    const moved = this.open ? -this.threshold + dx : dx;
    if (moved < -this.threshold / 3) this._open();
    else this.close();
  }

  _open() {
    this.content.style.transform = `translateX(-${this.threshold}px)`;
    this.open = true;
    // Close other open swipes
    document.querySelectorAll('.swipe-container').forEach(sc => {
      if (sc !== this.el && sc._swipe?.open) sc._swipe.close();
    });
  }

  close() {
    this.content.style.transition = 'transform .25s ease';
    this.content.style.transform = 'translateX(0)';
    this.open = false;
  }
}

// ── Schedule: Week/Month views ──────────────────────────────────────────────
let activeSchedTab = 'day';
let weekStart = getMonday(new Date());
let monthDate = new Date();

function getMonday(d) {
  const dt = new Date(d); dt.setDate(dt.getDate() - ((dt.getDay() + 6) % 7));
  return dt;
}

function dateStr(d) { return localDateStr(d); }

document.querySelectorAll('#sched-tabs .sub-tab').forEach(b => b.addEventListener('click', () => {
  activeSchedTab = b.dataset.tab;
  document.querySelectorAll('#sched-tabs .sub-tab').forEach(x => x.classList.toggle('active', x.dataset.tab === b.dataset.tab));
  document.querySelectorAll('.sched-view').forEach(v => v.classList.remove('active'));
  document.getElementById('sched-' + b.dataset.tab)?.classList.add('active');
  if (b.dataset.tab === 'day') loadSchedule(schedDate);
  if (b.dataset.tab === 'week') loadWeekView();
  if (b.dataset.tab === 'month') loadMonthView();
}));

// Week navigation
document.getElementById('week-prev')?.addEventListener('click', () => { weekStart.setDate(weekStart.getDate() - 7); loadWeekView(); });
document.getElementById('week-next')?.addEventListener('click', () => { weekStart.setDate(weekStart.getDate() + 7); loadWeekView(); });

async function loadWeekView() {
  const start = dateStr(weekStart);
  const end7 = new Date(weekStart); end7.setDate(end7.getDate() + 6);
  const end = dateStr(end7);
  const label = document.getElementById('week-label');
  label.textContent = `${weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${end7.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;

  const grid = document.getElementById('week-grid');
  grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px"><div class="spinner"></div></div>';

  try {
    const [data, calEvents] = await Promise.all([
      apiFetch(`/api/schedule/range?start=${start}&end=${end}`).then(r => r.json()),
      fetchCalendarEvents(start, end),
    ]);
    // Group cal events by date
    const calByDate = {};
    calEvents.forEach(e => { (calByDate[e.date] = calByDate[e.date] || []).push(e); });

    grid.innerHTML = '';
    const today = todayStr();
    for (let i = 0; i < 7; i++) {
      const d = new Date(weekStart); d.setDate(d.getDate() + i);
      const ds = dateStr(d);
      const col = document.createElement('div'); col.className = 'week-col';
      const hdr = document.createElement('div');
      hdr.className = `week-col-header${ds === today ? ' today' : ''}`;
      hdr.textContent = d.toLocaleDateString('en-US', { weekday: 'narrow', day: 'numeric' });
      hdr.addEventListener('click', () => { schedDate = ds; activeSchedTab = 'day'; document.querySelector('#sched-tabs .sub-tab[data-tab="day"]').click(); });
      col.appendChild(hdr);

      const blocks = data.schedules[ds] || [];
      const dayCalEvents = calByDate[ds] || [];
      const allItems = [
        ...blocks.map(b => ({ ...b, _cal: false })),
        ...dayCalEvents.map(e => ({ start: e.start, end: e.end, activity: e.title, type: 'calendar', completed: false, _cal: true })),
      ].sort((a, b) => a.start.localeCompare(b.start));

      allItems.forEach(b => {
        const bl = document.createElement('div');
        bl.className = `week-block${b._cal ? ' cal-event' : ` type-${b.type}${b.completed ? ' completed' : ''}`}`;
        bl.textContent = `${b.start.slice(0,5)} ${b.activity}`;
        bl.title = `${fmtTime(b.start)}–${fmtTime(b.end)} ${b.activity}${b._cal ? ' (calendar)' : ''}`;
        bl.addEventListener('click', () => { schedDate = ds; activeSchedTab = 'day'; document.querySelector('#sched-tabs .sub-tab[data-tab="day"]').click(); });
        col.appendChild(bl);
      });

      if (!allItems.length) {
        const empty = document.createElement('div');
        empty.style.cssText = 'padding:8px 4px;font-size:10px;color:var(--muted);text-align:center';
        empty.textContent = '—';
        col.appendChild(empty);
      }
      grid.appendChild(col);
    }
  } catch { grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted)">Error loading week</div>'; }
}

// Month navigation
document.getElementById('month-prev')?.addEventListener('click', () => { monthDate.setMonth(monthDate.getMonth() - 1); loadMonthView(); });
document.getElementById('month-next')?.addEventListener('click', () => { monthDate.setMonth(monthDate.getMonth() + 1); loadMonthView(); });

async function loadMonthView() {
  const label = document.getElementById('month-label');
  label.textContent = monthDate.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

  const grid = document.getElementById('month-grid');
  grid.innerHTML = '';

  // Day labels
  ['M', 'T', 'W', 'T', 'F', 'S', 'S'].forEach(d => {
    const lbl = document.createElement('div'); lbl.className = 'month-day-label'; lbl.textContent = d;
    grid.appendChild(lbl);
  });

  const year = monthDate.getFullYear(), month = monthDate.getMonth();
  const first = new Date(year, month, 1);
  const startDay = (first.getDay() + 6) % 7; // Monday = 0
  const last = new Date(year, month + 1, 0);
  const totalDays = last.getDate();
  const today = todayStr();

  // Fetch schedule data and calendar events for the month
  const monthStart = dateStr(first);
  const monthEnd = dateStr(last);
  let schedData = {};
  let calByDate = {};
  try {
    const [data, calEvents] = await Promise.all([
      apiFetch(`/api/schedule/range?start=${monthStart}&end=${monthEnd}`).then(r => r.json()),
      fetchCalendarEvents(monthStart, monthEnd),
    ]);
    schedData = data.schedules || {};
    calEvents.forEach(e => { (calByDate[e.date] = calByDate[e.date] || []).push(e); });
  } catch {}

  // Previous month padding
  const prevLast = new Date(year, month, 0);
  for (let i = startDay - 1; i >= 0; i--) {
    const d = prevLast.getDate() - i;
    const cell = document.createElement('div'); cell.className = 'month-day other-month';
    cell.innerHTML = `<span class="day-num">${d}</span>`;
    grid.appendChild(cell);
  }

  // Current month days
  for (let d = 1; d <= totalDays; d++) {
    const ds = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    const cell = document.createElement('div');
    cell.className = `month-day${ds === today ? ' today' : ''}`;
    cell.innerHTML = `<span class="day-num">${d}</span>`;

    const blocks = schedData[ds] || [];
    const dayCal = calByDate[ds] || [];
    if (blocks.length || dayCal.length) {
      const dots = document.createElement('div'); dots.className = 'month-dots';
      if (blocks.length) {
        const completed = blocks.filter(b => b.completed).length;
        const total = blocks.length;
        const dot = document.createElement('span');
        dot.className = `month-dot${total > 0 ? ' has-schedule' : ''}${completed === total && total > 0 ? ' completed' : ''}`;
        dots.appendChild(dot);
      }
      if (dayCal.length) {
        const calDot = document.createElement('span');
        calDot.className = 'month-dot has-cal-event';
        calDot.title = dayCal.map(e => e.title).join(', ');
        dots.appendChild(calDot);
      }
      cell.appendChild(dots);
    }

    cell.addEventListener('click', () => {
      schedDate = ds;
      activeSchedTab = 'day';
      document.querySelector('#sched-tabs .sub-tab[data-tab="day"]').click();
    });
    grid.appendChild(cell);
  }

  // Next month padding
  const totalCells = startDay + totalDays;
  const remaining = (7 - (totalCells % 7)) % 7;
  for (let d = 1; d <= remaining; d++) {
    const cell = document.createElement('div'); cell.className = 'month-day other-month';
    cell.innerHTML = `<span class="day-num">${d}</span>`;
    grid.appendChild(cell);
  }
}

// ── Item 1: Swipe peek animation on first load ──────────────────────────────
function peekFirstSwipe() {
  if (S.get('swipePeekDone', false)) return;
  setTimeout(() => {
    const first = document.querySelector('.swipe-content');
    if (first) { first.classList.add('peek'); first.addEventListener('animationend', () => first.classList.remove('peek'), { once: true }); }
    S.set('swipePeekDone', true);
  }, 800);
}

// ── Item 2: Suggestion chips ─────────────────────────────────────────────────
const DEFAULT_CHIPS = {
  morning:   ['Plan my day', "What's next?", 'Log a workout'],
  midday:    ["What's next?", 'Add a task', 'Show my schedule'],
  afternoon: ['How am I doing?', "What's left today?", 'Log a meal'],
  evening:   ['Log mood', 'Review my day', 'Bible reading'],
};

function getCustomChips() {
  try { return JSON.parse(localStorage.getItem('customChips') || 'null'); } catch { return null; }
}

function saveCustomChips(data) {
  localStorage.setItem('customChips', JSON.stringify(data));
}

function currentSlot() {
  const h = new Date().getHours();
  if (h < 10) return 'morning';
  if (h < 14) return 'midday';
  if (h < 18) return 'afternoon';
  return 'evening';
}

function updateSuggestionChips() {
  const el = document.getElementById('suggestion-chips');
  if (!el) return;
  const custom = getCustomChips();
  const slot = currentSlot();
  const chips = (custom && custom[slot] && custom[slot].length) ? custom[slot] : DEFAULT_CHIPS[slot];
  el.innerHTML = '';
  chips.forEach(label => {
    const btn = document.createElement('button');
    btn.className = 'suggestion-chip';
    btn.textContent = label;
    btn.addEventListener('click', () => {
      openChatOverlay();
      chatTextIn.value = label;
      sendChatMessage();
    });
    el.appendChild(btn);
  });
}
updateSuggestionChips();

// ── Quick command editor (Settings) ──────────────────────────────────────────
function renderQuickCmdEditor() {
  const custom = getCustomChips() || JSON.parse(JSON.stringify(DEFAULT_CHIPS));
  document.querySelectorAll('.quick-cmd-slot').forEach(slot => {
    const key = slot.dataset.slot;
    const container = slot.querySelector('.quick-cmd-chips-edit');
    container.innerHTML = '';
    (custom[key] || []).forEach((label, idx) => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:6px';
      const inp = document.createElement('input');
      inp.type = 'text'; inp.value = label;
      inp.className = 'add-task-input';
      inp.style.cssText = 'flex:1;padding:6px 10px;font-size:13px';
      inp.addEventListener('change', () => {
        const c = getCustomChips() || JSON.parse(JSON.stringify(DEFAULT_CHIPS));
        c[key][idx] = inp.value.trim();
        saveCustomChips(c);
        updateSuggestionChips();
      });
      const del = document.createElement('button');
      del.textContent = '✕'; del.className = 'add-task-btn-cancel';
      del.style.cssText = 'padding:4px 8px;font-size:12px;flex-shrink:0';
      del.addEventListener('click', () => {
        const c = getCustomChips() || JSON.parse(JSON.stringify(DEFAULT_CHIPS));
        c[key].splice(idx, 1);
        saveCustomChips(c);
        renderQuickCmdEditor();
        updateSuggestionChips();
      });
      row.appendChild(inp); row.appendChild(del);
      container.appendChild(row);
    });
  });
}

document.querySelectorAll('.quick-cmd-add').forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.closest('.quick-cmd-slot').dataset.slot;
    const c = getCustomChips() || JSON.parse(JSON.stringify(DEFAULT_CHIPS));
    if ((c[key] || []).length >= 4) return;
    if (!c[key]) c[key] = [];
    c[key].push('');
    saveCustomChips(c);
    renderQuickCmdEditor();
    // Focus the new input
    const inputs = btn.closest('.quick-cmd-slot').querySelectorAll('input');
    if (inputs.length) inputs[inputs.length - 1].focus();
  });
});

document.getElementById('quick-cmd-reset')?.addEventListener('click', () => {
  localStorage.removeItem('customChips');
  renderQuickCmdEditor();
  updateSuggestionChips();
});

// ── Item 3: Current-time indicator on schedule day view ──────────────────────
function insertNowLine() {
  const el = document.getElementById('schedule-list');
  if (!el) return;
  el.querySelectorAll('.now-line').forEach(n => n.remove());
  const now = nowHM();
  const blocks = el.querySelectorAll('.block-row, .swipe-container');
  let inserted = false;
  for (const node of blocks) {
    const row = node.classList.contains('block-row') ? node : node.querySelector('.block-row');
    if (!row) continue;
    const timeEl = row.querySelector('.block-time');
    if (!timeEl) continue;
    const startTime = timeEl.textContent.split('\n')[0].trim();
    // Convert displayed time back to HH:MM for comparison
    let cmp = startTime;
    if (startTime.includes('AM') || startTime.includes('PM')) {
      const m = startTime.match(/(\d+):(\d+)\s*(AM|PM)/i);
      if (m) { let h = parseInt(m[1]); if (m[3].toUpperCase()==='PM' && h!==12) h+=12; if (m[3].toUpperCase()==='AM' && h===12) h=0; cmp = String(h).padStart(2,'0')+':'+m[2]; }
    }
    if (cmp > now && !inserted) {
      const line = document.createElement('div');
      line.className = 'now-line';
      line.innerHTML = `<span class="now-time-label">${fmtTime(now)}</span>`;
      node.parentNode.insertBefore(line, node);
      inserted = true;
      break;
    }
  }
}

// ── Item 4: Home greeting + schedule panel ────────────────────────────────────
function updateHomeGreeting() {
  const el = document.getElementById('home-greeting');
  if (!el) return;
  const hour = new Date().getHours();
  let greet = 'Good evening';
  if (hour < 12) greet = 'Good morning';
  else if (hour < 17) greet = 'Good afternoon';
  el.textContent = greet;
}

async function loadHomeSchedule() {
  const list = document.getElementById('home-sched-list');
  if (!list) return;
  list.innerHTML = '<div style="padding:12px 8px;font-size:12px;color:var(--muted)">Loading…</div>';
  try {
    const res = await apiFetch(`/api/schedule/${todayStr()}`);
    if (!res.ok) { list.innerHTML = '<div style="padding:12px 8px;font-size:12px;color:var(--muted)">No schedule yet — ask me to generate one.</div>'; return; }
    const { blocks } = await res.json();
    list.innerHTML = '';
    const now = nowHM();
    let nowInserted = false, scrollTarget = null;

    blocks.forEach((b, i) => {
      // Insert "now" line before the first future block
      if (!nowInserted && b.start > now) {
        nowInserted = true;
        const nl = document.createElement('div');
        nl.className = 'hs-block hs-now-marker';
        nl.innerHTML = `<span class="hs-now-label">NOW</span><span class="hs-now-line"></span>`;
        list.appendChild(nl);
        scrollTarget = nl;
      }

      const isCurrent = b.start <= now && now < b.end;
      const isDone = b.completed || b.skipped;
      const row = document.createElement('div');
      row.className = `hs-block${isCurrent ? ' hs-current' : ''}${isDone ? ' hs-completed' : ''}`;
      row.innerHTML = `
        <div class="hs-time">${fmtTime(b.start)}</div>
        <div class="hs-dot"></div>
        <div>
          <div class="hs-activity">${escHtml(b.activity)}${isDone ? ' ✓' : ''}</div>
          <div class="hs-type">${b.type.replace('_', ' ')} · ${fmtTime(b.start)}–${fmtTime(b.end)}</div>
        </div>`;
      row.addEventListener('click', () => showView('upcoming'));
      list.appendChild(row);
      if (isCurrent && !scrollTarget) scrollTarget = row;
    });

    // Scroll so the now-line / current block is near the top with a bit of context
    if (scrollTarget) {
      setTimeout(() => {
        const offset = scrollTarget.offsetTop - 24;
        list.scrollTop = Math.max(0, offset);
      }, 80);
    }
  } catch {
    list.innerHTML = '<div style="padding:12px 8px;font-size:12px;color:var(--muted)">Could not load schedule.</div>';
  }
}

document.getElementById('home-sched-expand')?.addEventListener('click', () => showView('upcoming'));

// keep for compat — greeting-card is now hidden
async function updateGreetingCard() {}

// ── Home layout per user ───────────────────────────────────────────────────────
function initHomeForUser() {
  const el = document.getElementById('home-greeting');
  if (!el) return;
  const hour = new Date().getHours();
  const greet = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  apiFetch('/api/users').then(r => r.json()).then(data => {
    const user = (data.users || []).find(u => u.id === currentUserId);
    el.textContent = `${greet}, ${user ? user.name : 'there'}`;
  }).catch(() => { el.textContent = greet; });
}

async function loadHomeTasks() {
  const el = document.getElementById('home-tasks-list');
  if (!el) return;
  el.innerHTML = '<div style="padding:8px;font-size:12px;color:var(--muted)">Loading…</div>';
  try {
    const data = await apiFetch('/api/tasks?status=todo&limit=3').then(r => r.json());
    const tasks = (data.tasks || []).filter(t => t.status === 'todo' || t.status === 'in_progress').slice(0, 3);
    el.innerHTML = '';
    if (!tasks.length) {
      el.innerHTML = '<div style="padding:10px 4px;font-size:12px;color:var(--muted)">No pending tasks.</div>';
      return;
    }
    tasks.forEach(t => {
      const row = document.createElement('div');
      row.className = 'ht-row';
      row.innerHTML = `
        <button class="ht-circle" data-id="${t.id}" aria-label="Complete"></button>
        <span class="ht-title">${escHtml(t.title)}</span>
        <span class="ht-badge">${escHtml(t.bucket || '')}</span>`;
      const circle = row.querySelector('.ht-circle');
      circle.addEventListener('click', async (e) => {
        e.stopPropagation();
        circle.classList.add('completing');
        circle.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" width="12" height="12"><polyline points="20 6 9 17 4 12"/></svg>';
        try {
          await apiFetch(`/api/tasks/${t.id}/complete`, { method: 'POST' });
          row.style.opacity = '0.3';
          setTimeout(() => row.remove(), 600);
        } catch { circle.classList.remove('completing'); circle.innerHTML = ''; }
      });
      row.addEventListener('click', (e) => {
        if (e.target.closest('.ht-circle')) return;
        showView('current');
      });
      el.appendChild(row);
    });
  } catch {
    el.innerHTML = '<div style="padding:8px 4px;font-size:12px;color:var(--muted)">Could not load tasks.</div>';
  }
}

function loadAlexHome() {} // no-op — calorie bar moved to food insights

// ── Member user "How can I help?" input ───────────────────────────────────────
async function sendAlexHelp() {
  const inp = document.getElementById('alex-help-input');
  const status = document.getElementById('alex-help-status');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = ''; inp.disabled = true;
  status.textContent = 'Thinking…';
  let full = '';
  try {
    const res = await apiFetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop();
      for (const l of lines) {
        if (!l.startsWith('data: ')) continue;
        const raw = l.slice(6).trim(); if (raw === '[DONE]') break;
        try { const o = JSON.parse(raw); if (o.text) full += o.text; } catch {}
      }
    }
    status.textContent = full;
  } catch { status.textContent = 'Something went wrong.'; }
  inp.disabled = false;
}
document.getElementById('alex-help-send')?.addEventListener('click', sendAlexHelp);
document.getElementById('alex-help-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') sendAlexHelp(); });

// startup
initHomeForUser();

// ── Item 5: Tap-to-expand on schedule blocks ─────────────────────────────────
// (Added via event delegation on schedule-list)
document.getElementById('schedule-list')?.addEventListener('click', e => {
  const row = e.target.closest('.block-row');
  if (!row || row.closest('.swipe-actions')) return;
  if (e.target.closest('.timing-prompt')) return;
  // Don't toggle if swipe is open
  const container = row.closest('.swipe-container');
  if (container?._swipe?.open) return;
  row.classList.toggle('expanded');
  // Add "Adjust time" button to expand area when expanded
  if (row.classList.contains('expanded')) {
    const blockId = container?.querySelector('.swipe-action[data-id]')?.dataset.id;
    if (blockId && !row.querySelector('.block-adjust-btn')) {
      const expandArea = row.querySelector('.block-expand');
      if (expandArea) {
        const adjBtn = document.createElement('button');
        adjBtn.className = 'block-adjust-btn';
        adjBtn.textContent = 'Adjust time';
        adjBtn.style.cssText = 'margin-top:6px;padding:4px 10px;border-radius:8px;background:var(--surface2);border:1px solid var(--border);color:var(--text);font-size:11px;cursor:pointer';
        adjBtn.addEventListener('click', e => {
          e.stopPropagation();
          const blockStart = row.querySelector('.block-time')?.textContent.split('\n')[0].trim();
          let startHM = blockStart || '';
          if (startHM.includes('AM') || startHM.includes('PM')) {
            const m = startHM.match(/(\d+):(\d+)\s*(AM|PM)/i);
            if (m) { let h = parseInt(m[1]); if (m[3].toUpperCase()==='PM'&&h!==12) h+=12; if (m[3].toUpperCase()==='AM'&&h===12) h=0; startHM = String(h).padStart(2,'0')+':'+m[2]; }
          }
          // Toggle timing prompt below this block
          const existing = document.getElementById('timing-prompt-' + blockId);
          if (existing) { existing.remove(); return; }
          const prompt = showTimingPrompt(blockId, startHM, null);
          if (prompt && container) container.parentNode.insertBefore(prompt, container.nextSibling);
        });
        expandArea.appendChild(adjBtn);
      }
    }
  }
});

// ── Item 9: Typing indicator helper ──────────────────────────────────────────
function showTypingIndicator(container) {
  const div = document.createElement('div');
  div.className = 'typing-indicator';
  div.id = 'typing-indicator';
  div.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}
function removeTypingIndicator() {
  document.getElementById('typing-indicator')?.remove();
}

// ── Item 10: Empty schedule ghost blocks ─────────────────────────────────────
function showGhostSchedule(el) {
  el.innerHTML = '';
  for (let i = 0; i < 5; i++) {
    const g = document.createElement('div');
    g.className = 'ghost-block';
    g.innerHTML = '<div class="ghost-time"></div><div style="flex:1"><div class="ghost-title"></div><div class="ghost-type"></div></div>';
    el.appendChild(g);
  }
  const cta = document.createElement('div');
  cta.className = 'empty-sched-cta';
  cta.innerHTML = '<p>No schedule for this day.</p><button class="inline-btn" id="gen-sched-btn" style="margin-top:8px">✦ Generate Schedule</button>';
  el.appendChild(cta);
  document.getElementById('gen-sched-btn')?.addEventListener('click', async () => {
    document.getElementById('gen-sched-btn').textContent = 'Generating…';
    document.getElementById('gen-sched-btn').disabled = true;
    try {
      await apiFetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: `Generate my daily schedule for ${schedDate}` }) }).then(r => r.body.getReader().read());
    } catch {}
    loadSchedule(schedDate);
  });
}

// ── Refresh now-line every minute ─────────────────────────────────────────────
setInterval(insertNowLine, 60000);

// ── Service Worker ────────────────────────────────────────────────────────────
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/static/sw.js').catch(()=>{});
