"""
Robot Posture & Emotion AI
Pi runs all AI. Laptop browser streams camera frames to Pi via SocketIO.
Dashboard and UI shown on laptop browser.
"""
import threading
import time
import json
import os
from datetime import datetime

print("APP STARTING...")

# ── GPIO ─────────────────────────────────────────────────────────────────────
try:
    import lgpio
    chip = lgpio.gpiochip_open(0)
    TOUCH_PIN_1 = 11
    TOUCH_PIN_2 = 13
    lgpio.gpio_claim_input(chip, TOUCH_PIN_1, lgpio.SET_PULL_UP)
    lgpio.gpio_claim_input(chip, TOUCH_PIN_2, lgpio.SET_PULL_UP)
    GPIO_AVAILABLE = True
    print("GPIO ready. Touch pins: 11 (confirm), 13 (complete)")
except Exception as e:
    GPIO_AVAILABLE = False
    print(f"GPIO not available: {e}")

from flask import Flask, render_template_string, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'robot-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading',
                    max_http_buffer_size=5 * 1024 * 1024)  # 5MB for frame data

# ── Global engine refs ────────────────────────────────────────────────────────
vision_engine    = None
suggestion_engine = None
data_logger      = None
analysis_engine  = None
engines_ready    = False
engines_lock     = threading.Lock()

CURRENT_MODE = 'supporter'
CURRENT_USER = 'user1'
LOG_INTERVAL = 10
_last_log_time = 0

# ── Engine init ───────────────────────────────────────────────────────────────
def init_engines(mode='supporter', user_id='user1'):
    global vision_engine, suggestion_engine, data_logger, analysis_engine, engines_ready
    global CURRENT_MODE, CURRENT_USER
    CURRENT_MODE = mode
    CURRENT_USER = user_id

    try:
        from vision_engine import VisionEngine
        from suggestion_engine import SuggestionEngine
        from data_logger import DataLogger
        from analysis_engine import AnalysisEngine

        suggestion_engine = SuggestionEngine(mode=mode, observation_period=15, cooldown=20)
        data_logger       = DataLogger(user_id=user_id, mode=mode)
        analysis_engine   = AnalysisEngine()

        vision_engine = VisionEngine(on_result=_handle_vision_result)
        vision_engine.start()

        with engines_lock:
            engines_ready = True

        print(f"[App] All engines ready. Mode={mode}, User={user_id}")
        socketio.emit('status', {'type': 'ready', 'message': 'Robot AI is ready!', 'mode': mode})
    except Exception as e:
        print(f"[App] Engine init failed: {e}")
        import traceback; traceback.print_exc()
        socketio.emit('status', {'type': 'error', 'message': str(e)})


def _handle_vision_result(result):
    """Called from VisionEngine inference thread on every processed frame."""
    global _last_log_time
    if not engines_ready:
        return

    posture_data = result.get('posture', {})
    emotion_data = result.get('emotion', [])
    posture      = posture_data.get('posture') if posture_data else None
    progress     = suggestion_engine.get_progress() if suggestion_engine else 0

    socketio.emit('vision_result', {
        'posture':       posture,
        'emotion':       emotion_data,
        'progress':      progress,
        'posture_score': int(posture_data.get('score', 0) or 0) if posture_data else 0,
        'focus_active':  suggestion_engine.focus_active if suggestion_engine else False,
        'focus_time_left': max(0, round(suggestion_engine.focus_end_time - time.time()))
                           if suggestion_engine and suggestion_engine.focus_active else 0,
    })

    now = time.time()
    if now - _last_log_time >= LOG_INTERVAL:
        _last_log_time = now
        if data_logger:
            data_logger.log_frame(posture_data, emotion_data)
        if analysis_engine and posture and emotion_data:
            elapsed = now - (data_logger.session_start if data_logger else now)
            analysis_engine.ingest(
                elapsed,
                posture.get('score', 0),
                emotion_data[0].get('valence', 0.0) if emotion_data else 0.0
            )

    if suggestion_engine and suggestion_engine.is_focus_expired():
        focus_result = suggestion_engine.end_focus()
        if focus_result:
            socketio.emit('focus_complete', focus_result)
        return

    if suggestion_engine:
        suggestion = suggestion_engine.evaluate(posture_data, emotion_data)
        if suggestion:
            if data_logger:
                data_logger.log_suggestion(suggestion.get('key', ''))
            socketio.emit('suggestion', suggestion)


# ── Touch sensor loop ─────────────────────────────────────────────────────────
def touch_sensor_loop():
    if not GPIO_AVAILABLE:
        return
    pin1_last = pin2_last = 1
    debounce = 0.3
    while True:
        try:
            p1 = lgpio.gpio_read(chip, TOUCH_PIN_1)
            p2 = lgpio.gpio_read(chip, TOUCH_PIN_2)
            if p1 == 0 and pin1_last == 1:
                if engines_ready and suggestion_engine:
                    if suggestion_engine.focus_active:
                        focus_result = suggestion_engine.end_focus()
                        if focus_result:
                            socketio.emit('focus_complete', focus_result)
                    else:
                        result = suggestion_engine.confirm_task()
                        if result:
                            if data_logger:
                                data_logger.log_confirm(result.get('key', ''))
                            socketio.emit('task_confirmed', {
                                'suggestion': result,
                                'message': f"Now complete: {result['task']}"
                            })
                time.sleep(debounce)
            if p2 == 0 and pin2_last == 1:
                if engines_ready and suggestion_engine:
                    result = suggestion_engine.complete_task()
                    if result:
                        gap = result.get('intention_action_gap_s')
                        if data_logger:
                            data_logger.log_complete(result.get('key', ''))
                        score = suggestion_engine.get_score()
                        socketio.emit('task_completed', {
                            'suggestion': result, 'score': score,
                            'intention_action_gap_s': gap,
                            'message': f"Well done! Score: {score}%",
                            'xp': suggestion_engine.get_xp_info(),
                        })
                time.sleep(debounce)
            pin1_last = p1
            pin2_last = p2
            time.sleep(0.05)
        except Exception as e:
            print(f"[Touch] Error: {e}")
            time.sleep(1)


# ══════════════════════════════════════════════════════════════════════════════
# HTML — Main UI (phone/laptop)
# ══════════════════════════════════════════════════════════════════════════════
PHONE_UI = """
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
  <title>Posture AI</title>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family:-apple-system,sans-serif; background:#0a0a0a; color:#fff; height:100vh; overflow:hidden; }

    /* ── Camera preview (hidden, used for capture only) ── */
    #cam-video { position:fixed; top:0; left:0; width:100%; height:100%;
      object-fit:cover; opacity:0.18; z-index:1; transform:scaleX(-1); }
    #cam-canvas { display:none; }
    #cam-status { position:fixed; top:50px; left:50%; transform:translateX(-50%);
      background:rgba(255,80,80,.15); border:1px solid #ff5050; color:#ff7070;
      padding:6px 16px; border-radius:20px; font-size:12px; z-index:22;
      display:none; }

    /* ── Status bar ── */
    #status-bar { position:fixed; top:0; left:0; right:0; z-index:20;
      background:rgba(0,0,0,0.82); backdrop-filter:blur(8px);
      padding:10px 16px; display:flex; justify-content:space-between; align-items:center; }
    #status-dot { width:9px; height:9px; border-radius:50%; background:#ff4444; transition:background .3s; }
    #status-dot.ready { background:#44ff88; }
    #status-text { font-size:12px; color:#aaa; margin-left:8px; }
    .badge { border-radius:20px; padding:4px 12px; font-size:12px; font-weight:700; border:1px solid; }
    #score-badge { border-color:#444; color:#44ff88; background:#111; }
    #xp-badge    { border-color:#888; color:#ffd700; background:#111; margin-left:6px; }
    #cam-badge   { border-color:#4488ff; color:#4488ff; background:#111; margin-left:6px; font-size:11px; }

    /* ── Screens ── */
    .screen { position:fixed; inset:0; z-index:50; display:flex; flex-direction:column;
      align-items:center; justify-content:center; padding:28px; }
    #mode-screen { background:#0a0a0a; }
    .mode-title { font-size:22px; font-weight:700; text-align:center; margin-bottom:6px; }
    .mode-sub   { font-size:14px; color:#888; text-align:center; margin-bottom:28px; }
    .mode-cards { display:flex; flex-direction:column; gap:12px; width:100%; max-width:360px; }
    .mode-card  { background:#1a1a2e; border:1px solid #333; border-radius:16px;
      padding:16px 20px; cursor:pointer; transition:border-color .2s,background .2s; }
    .mode-card:hover,.mode-card.selected { border-color:#44ff88; background:#0d1f1a; }
    .mode-card h3 { font-size:16px; font-weight:600; margin-bottom:4px; }
    .mode-card p  { font-size:13px; color:#777; line-height:1.5; }
    .user-row { display:flex; gap:8px; margin-top:16px; width:100%; max-width:360px; }
    .user-row input { flex:1; background:#1a1a2e; border:1px solid #333; color:#fff;
      border-radius:10px; padding:10px 14px; font-size:14px; outline:none; }
    .user-row input:focus { border-color:#44ff88; }
    #btn-start { background:#44ff88; color:#000; border:none; border-radius:14px;
      padding:14px 28px; font-size:15px; font-weight:700; cursor:pointer;
      margin-top:16px; width:100%; max-width:360px; }

    /* ── Observe panel ── */
    #observe-panel { position:fixed; bottom:0; left:0; right:0; z-index:25;
      background:linear-gradient(180deg,rgba(10,10,10,0) 0%,rgba(10,10,10,0.97) 30%);
      padding:30px 24px 44px; display:flex; flex-direction:column; align-items:center; gap:14px; }
    .observe-title { font-size:15px; font-weight:600; color:#eee; text-align:center; }
    .observe-sub   { font-size:13px; color:#666; text-align:center; }
    .rings { position:relative; width:110px; height:110px; margin:4px auto; }
    .ring  { position:absolute; border-radius:50%; border:2px solid transparent; animation:spin-ring linear infinite; }
    .ring-1 { inset:0;    border-top-color:#44ff88;   animation-duration:3s; }
    .ring-2 { inset:11px; border-right-color:#4488ff;  animation-duration:2s; animation-direction:reverse; }
    .ring-3 { inset:22px; border-bottom-color:#ff6b6b; animation-duration:1.5s; }
    .ring-center { position:absolute; inset:35px; border-radius:50%;
      background:rgba(68,255,136,.08); display:flex; align-items:center; justify-content:center;
      font-size:12px; font-weight:700; color:#44ff88; }
    @keyframes spin-ring { to { transform:rotate(360deg); } }
    .progress-wrap { width:100%; background:rgba(255,255,255,.08); border-radius:99px; height:5px; overflow:hidden; }
    .progress-fill { height:100%; border-radius:99px; background:linear-gradient(90deg,#44ff88,#4488ff);
      transition:width 1s linear; width:0%; }
    #info-bar { display:flex; gap:10px; justify-content:center; flex-wrap:wrap; }
    .info-chip  { background:rgba(255,255,255,.07); border-radius:20px; padding:6px 14px;
      font-size:13px; border:1px solid rgba(255,255,255,.1); }
    .info-chip.alert { border-color:#ff6b6b; color:#ff6b6b; }
    .info-chip.good  { border-color:#44ff88; color:#44ff88; }
    .info-chip.pos   { border-color:#ffd700; color:#ffd700; }
    .info-chip.neg   { border-color:#ff6b6b; color:#ff6b6b; }
    .score-chip { border-color:#4488ff; color:#4488ff; }

    /* ── Suggestion card ── */
    #suggestion-card { position:fixed; bottom:0; left:0; right:0; z-index:30;
      background:linear-gradient(135deg,#1a1a2e,#16213e);
      border-top:1px solid rgba(255,255,255,.1); border-radius:24px 24px 0 0;
      padding:20px 20px 44px;
      transform:translateY(100%); transition:transform .4s cubic-bezier(.34,1.56,.64,1); }
    #suggestion-card.visible { transform:translateY(0); }
    #sug-category { font-size:11px; text-transform:uppercase; letter-spacing:2px; color:#888; margin-bottom:4px; }
    #sug-hapa  { font-size:11px; color:#4488ff; margin-bottom:6px; }
    #sug-title { font-size:20px; font-weight:700; margin-bottom:8px; }
    #sug-instr { font-size:14px; color:#bbb; line-height:1.5; margin-bottom:12px; }
    #sug-task  { background:rgba(255,255,255,.07); border-radius:12px;
      padding:12px; font-size:14px; color:#eee; line-height:1.5; margin-bottom:16px; }
    #sug-task strong { color:#44ff88; }
    .btn-row { display:flex; gap:10px; }
    .btn { flex:1; padding:14px; border-radius:14px; border:none; font-size:15px; font-weight:600; cursor:pointer; }
    #btn-confirm  { background:#44ff88; color:#000; }
    #btn-complete { background:#4488ff; color:#fff; display:none; }
    #btn-dismiss  { background:rgba(255,255,255,.1); color:#aaa; }

    /* ── Focus overlay ── */
    #focus-overlay { position:fixed; inset:0; background:rgba(0,0,0,.92); z-index:40;
      display:none; flex-direction:column; align-items:center; justify-content:center; gap:16px; padding:24px; }
    #focus-overlay.active { display:flex; }
    #focus-task-name { font-size:22px; font-weight:700; text-align:center; }
    #focus-timer { font-size:56px; font-weight:800; color:#44ff88; font-variant-numeric:tabular-nums; }
    #focus-posture-bar-wrap { width:100%; max-width:300px; background:rgba(255,255,255,.1); border-radius:99px; height:8px; }
    #focus-posture-bar { height:100%; border-radius:99px; background:#44ff88; width:50%; transition:width .5s; }
    .focus-label { font-size:13px; color:#888; }
    #btn-end-focus { background:#ff6b6b; color:#fff; border:none; border-radius:14px;
      padding:12px 28px; font-size:14px; font-weight:600; cursor:pointer; margin-top:8px; }

    /* ── Focus setup ── */
    #focus-setup { position:fixed; inset:0; background:#0a0a0a; z-index:60;
      display:none; flex-direction:column; align-items:center; justify-content:center; gap:16px; padding:28px; }
    #focus-setup.active { display:flex; }
    #focus-setup input { width:100%; max-width:340px; background:#1a1a2e; border:1px solid #333;
      color:#fff; border-radius:12px; padding:12px 16px; font-size:15px; outline:none; }
    #focus-setup input:focus { border-color:#44ff88; }
    .timer-presets { display:flex; gap:10px; flex-wrap:wrap; justify-content:center; }
    .timer-btn { background:#1a1a2e; border:1px solid #333; color:#eee; border-radius:10px;
      padding:10px 18px; font-size:14px; cursor:pointer; transition:all .2s; }
    .timer-btn.selected,.timer-btn:hover { border-color:#44ff88; color:#44ff88; background:#0d1f1a; }
    #btn-start-focus { background:#44ff88; color:#000; border:none; border-radius:14px;
      padding:14px; font-size:15px; font-weight:700; cursor:pointer; width:100%; max-width:340px; }
    #btn-cancel-focus { background:transparent; color:#888; border:none; font-size:14px; cursor:pointer; margin-top:4px; }

    /* ── Reward screen ── */
    #reward-screen { position:fixed; inset:0; z-index:70; display:none;
      flex-direction:column; align-items:center; justify-content:center; padding:28px; gap:12px;
      background:linear-gradient(135deg,#0a0a0a,#0d1f1a); }
    #reward-screen.active { display:flex; }
    #reward-grade { font-size:88px; font-weight:900; line-height:1; }
    .grade-S{color:#ffd700} .grade-A{color:#44ff88} .grade-B{color:#4488ff}
    .grade-C{color:#ff9f43} .grade-D{color:#ff6b6b}
    #reward-task  { font-size:16px; color:#aaa; text-align:center; }
    #reward-score { font-size:32px; font-weight:700; }
    #xp-bar-wrap { width:100%; max-width:300px; background:rgba(255,255,255,.1); border-radius:99px; height:10px; }
    #xp-bar { height:100%; border-radius:99px; background:#ffd700; transition:width 1s ease; width:0%; }
    .xp-label { font-size:13px; color:#ffd700; }
    .stat-row { display:flex; gap:24px; justify-content:center; }
    .stat-box { background:#1a1a2e; border-radius:12px; padding:14px 20px; text-align:center; }
    .stat-val { font-size:22px; font-weight:700; color:#44ff88; }
    .stat-lbl { font-size:11px; color:#888; margin-top:2px; }
    #btn-done-reward { background:#44ff88; color:#000; border:none; border-radius:14px;
      padding:14px 32px; font-size:15px; font-weight:700; cursor:pointer; margin-top:8px; }

    /* ── Toast ── */
    #toast { position:fixed; top:68px; left:50%; transform:translateX(-50%);
      background:rgba(68,255,136,.15); border:1px solid #44ff88;
      color:#44ff88; padding:10px 20px; border-radius:20px;
      font-size:14px; z-index:80; opacity:0; transition:opacity .3s; white-space:nowrap; }
    #toast.show { opacity:1; }

    /* ── Loading ── */
    #loading { position:fixed; inset:0; background:#0a0a0a; z-index:100;
      display:flex; flex-direction:column; align-items:center; justify-content:center; gap:16px; }
    .spinner { width:40px; height:40px; border:3px solid #333;
      border-top-color:#44ff88; border-radius:50%; animation:spin-ring .8s linear infinite; }

    /* ── Side menu ── */
    #menu-btn { font-size:20px; cursor:pointer; background:none; border:none; color:#aaa; padding:4px; }
    #side-menu { position:fixed; top:0; right:-240px; width:240px; height:100%; background:#111;
      z-index:90; transition:right .3s; padding:60px 16px 24px; display:flex; flex-direction:column; gap:8px; }
    #side-menu.open { right:0; }
    .menu-item { padding:14px 16px; border-radius:12px; cursor:pointer; font-size:14px;
      color:#ccc; background:#1a1a1a; }
    .menu-item:hover { background:#1a1a2e; color:#44ff88; }
  </style>
</head>
<body>

<!-- Hidden camera elements -->
<video id="cam-video" autoplay playsinline muted></video>
<canvas id="cam-canvas"></canvas>
<div id="cam-status">📷 Camera not active</div>

<!-- Loading -->
<div id="loading">
  <div class="spinner"></div>
  <div style="color:#888;font-size:14px" id="loading-text">Starting AI on Pi...</div>
</div>

<!-- Mode picker -->
<div id="mode-screen" class="screen" style="display:none">
  <div class="mode-title">Choose Your Mode</div>
  <div class="mode-sub">This shapes how suggestions are delivered</div>
  <div class="mode-cards">
    <div class="mode-card selected" data-mode="motivator" onclick="selectMode(this)">
      <h3>⚡ Motivator</h3>
      <p>Competitive, energetic challenges. Beat your record. Score-driven.</p>
    </div>
    <div class="mode-card" data-mode="supporter" onclick="selectMode(this)">
      <h3>💛 Supporter</h3>
      <p>Gentle, non-pressuring nudges. Acknowledging tone. No score shown.</p>
    </div>
    <div class="mode-card" data-mode="tracker" onclick="selectMode(this)">
      <h3>📊 Tracker</h3>
      <p>Silent data logging only. No cards. Session summary at the end.</p>
    </div>
  </div>
  <div class="user-row">
    <input id="user-id-input" type="text" placeholder="User ID (e.g. user1)" value="user1">
  </div>
  <button id="btn-start" onclick="startSession()">Start Session →</button>
</div>

<!-- Status bar -->
<div id="status-bar" style="display:none">
  <div style="display:flex;align-items:center">
    <div id="status-dot"></div>
    <span id="status-text" style="margin-left:8px">Connecting...</span>
  </div>
  <div style="display:flex;align-items:center">
    <div class="badge" id="score-badge">Score: 0%</div>
    <div class="badge" id="xp-badge">Lv1 · 0XP</div>
    <div class="badge" id="cam-badge">📷 —</div>
    <button id="menu-btn" onclick="toggleMenu()">☰</button>
  </div>
</div>

<!-- Observe panel -->
<div id="observe-panel" style="display:none">
  <div class="observe-title">Analyzing your posture & emotion</div>
  <div class="rings">
    <div class="ring ring-1"></div>
    <div class="ring ring-2"></div>
    <div class="ring ring-3"></div>
    <div class="ring-center" id="progress-pct">0%</div>
  </div>
  <div class="progress-wrap"><div class="progress-fill" id="progress-fill"></div></div>
  <div class="observe-sub" id="observe-sub">Suggestion will appear shortly</div>
  <div id="info-bar">
    <div class="info-chip" id="chip-posture">Posture: detecting...</div>
    <div class="info-chip" id="chip-emotion">Emotion: detecting...</div>
    <div class="info-chip score-chip" id="chip-score">Score: —</div>
  </div>
</div>

<!-- Suggestion card -->
<div id="suggestion-card">
  <div id="sug-category">Suggestion</div>
  <div id="sug-hapa">Stage: Motivation</div>
  <div id="sug-title">-</div>
  <div id="sug-instr">-</div>
  <div id="sug-task"><strong>Task:</strong> <span id="task-text">-</span></div>
  <div class="btn-row">
    <button class="btn" id="btn-confirm"  onclick="confirmTask()">✓ Got it</button>
    <button class="btn" id="btn-complete" onclick="completeTask()">✓ Done!</button>
    <button class="btn" id="btn-dismiss"  onclick="dismissTask()">✕ Dismiss</button>
  </div>
</div>

<!-- Focus setup -->
<div id="focus-setup">
  <div class="mode-title">Start Focus Session</div>
  <input id="focus-task-input" type="text" placeholder="What are you working on?">
  <div class="timer-presets">
    <div class="timer-btn selected" data-mins="25" onclick="selectTimer(this)">25 min</div>
    <div class="timer-btn" data-mins="45" onclick="selectTimer(this)">45 min</div>
    <div class="timer-btn" data-mins="90" onclick="selectTimer(this)">90 min</div>
    <div class="timer-btn" data-mins="custom" onclick="selectTimer(this)">Custom</div>
  </div>
  <input id="custom-mins" type="number" placeholder="Minutes" min="1" max="240"
    style="display:none;width:100%;max-width:340px;background:#1a1a2e;border:1px solid #333;
           color:#fff;border-radius:12px;padding:12px 16px;font-size:15px;outline:none;">
  <button id="btn-start-focus" onclick="startFocus()">▶ Begin Focus</button>
  <button id="btn-cancel-focus" onclick="hideFocusSetup()">Cancel</button>
</div>

<!-- Focus overlay -->
<div id="focus-overlay">
  <div class="focus-label">Focus Session</div>
  <div id="focus-task-name">—</div>
  <div id="focus-timer">00:00</div>
  <div class="focus-label">Live Posture Score</div>
  <div id="focus-posture-bar-wrap"><div id="focus-posture-bar"></div></div>
  <button id="btn-end-focus" onclick="endFocusEarly()">End Session Early</button>
</div>

<!-- Reward screen -->
<div id="reward-screen">
  <div class="focus-label" id="reward-task-label">Focus Complete</div>
  <div id="reward-grade" class="grade-A">A</div>
  <div id="reward-score">Focus Score: 0</div>
  <div class="stat-row">
    <div class="stat-box"><div class="stat-val" id="stat-posture">—</div><div class="stat-lbl">Posture Avg</div></div>
    <div class="stat-box"><div class="stat-val" id="stat-emotion">—</div><div class="stat-lbl">Emotion Score</div></div>
    <div class="stat-box"><div class="stat-val" id="stat-xp">+0 XP</div><div class="stat-lbl">XP Earned</div></div>
  </div>
  <div class="xp-label" id="level-label">Level 1</div>
  <div id="xp-bar-wrap"><div id="xp-bar"></div></div>
  <button id="btn-done-reward" onclick="hideReward()">Continue →</button>
</div>

<!-- Side menu -->
<div id="side-menu">
  <div class="menu-item" onclick="showFocusSetup()">🎯 Focus Session</div>
  <div class="menu-item" onclick="openDashboard()">📊 Dashboard</div>
  <div class="menu-item" onclick="openHistory()">📅 History</div>
  <div class="menu-item" onclick="endSessionFull()">⏹ End Session</div>
  <div class="menu-item" onclick="toggleMenu()">✕ Close</div>
</div>

<div id="toast"></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
<script>
const socket = io();
let selectedMode     = 'motivator';
let selectedTimerMins = 25;
let focusTimerInterval = null;
let focusEndTime    = null;
let currentSuggestionKey = null;

// ── Camera streaming ──────────────────────────────────────────────────────────
let camStream       = null;
let camInterval     = null;
const CAM_FPS       = 5;       // frames per second sent to Pi (keep low for network)
const CAM_WIDTH     = 640;
const CAM_HEIGHT    = 480;
const CAM_QUALITY   = 0.7;     // JPEG quality 0-1

async function startCamera() {
  try {
    camStream = await navigator.mediaDevices.getUserMedia({
      video: { width: CAM_WIDTH, height: CAM_HEIGHT, facingMode: 'user' },
      audio: false
    });
    const video = document.getElementById('cam-video');
    video.srcObject = camStream;
    await video.play();

    document.getElementById('cam-badge').textContent = '📷 Live';
    document.getElementById('cam-badge').style.borderColor = '#44ff88';
    document.getElementById('cam-badge').style.color = '#44ff88';
    document.getElementById('cam-status').style.display = 'none';

    // Start sending frames
    const canvas = document.getElementById('cam-canvas');
    canvas.width  = CAM_WIDTH;
    canvas.height = CAM_HEIGHT;
    const ctx = canvas.getContext('2d');

    camInterval = setInterval(() => {
      if (!camStream || !camStream.active) return;
      ctx.drawImage(video, 0, 0, CAM_WIDTH, CAM_HEIGHT);
      const dataUrl = canvas.toDataURL('image/jpeg', CAM_QUALITY);
      socket.emit('camera_frame', { frame: dataUrl });
    }, 1000 / CAM_FPS);

    console.log('[Camera] Streaming at', CAM_FPS, 'fps →', CAM_WIDTH+'x'+CAM_HEIGHT);
  } catch (err) {
    console.error('[Camera] Error:', err);
    document.getElementById('cam-status').textContent = '📷 Camera denied: ' + err.message;
    document.getElementById('cam-status').style.display = 'block';
    document.getElementById('cam-badge').textContent = '📷 No cam';
    showToast('⚠ Camera access denied. Check browser permissions.');
  }
}

function stopCamera() {
  clearInterval(camInterval);
  camInterval = null;
  if (camStream) {
    camStream.getTracks().forEach(t => t.stop());
    camStream = null;
  }
}

// ── Mode picker ────────────────────────────────────────────────────────────
function selectMode(el) {
  document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  selectedMode = el.dataset.mode;
}

function startSession() {
  const userId = document.getElementById('user-id-input').value.trim() || 'user1';
  socket.emit('start_session', { mode: selectedMode, user_id: userId });
  document.getElementById('mode-screen').style.display = 'none';
  document.getElementById('loading').style.display = 'flex';
  document.getElementById('loading-text').textContent = 'Loading AI models on Pi...';
  // Start camera immediately so it's ready when AI loads
  startCamera();
}

// ── Timer preset ──────────────────────────────────────────────────────────
function selectTimer(el) {
  document.querySelectorAll('.timer-btn').forEach(b => b.classList.remove('selected'));
  el.classList.add('selected');
  if (el.dataset.mins === 'custom') {
    document.getElementById('custom-mins').style.display = 'block';
    selectedTimerMins = null;
  } else {
    document.getElementById('custom-mins').style.display = 'none';
    selectedTimerMins = parseInt(el.dataset.mins);
  }
}

// ── Focus ─────────────────────────────────────────────────────────────────
function showFocusSetup()  { document.getElementById('focus-setup').classList.add('active'); toggleMenu(); }
function hideFocusSetup()  { document.getElementById('focus-setup').classList.remove('active'); }

function startFocus() {
  const task = document.getElementById('focus-task-input').value.trim() || 'Focus session';
  let mins = selectedTimerMins;
  if (!mins) {
    mins = parseInt(document.getElementById('custom-mins').value);
    if (!mins || mins < 1) { showToast('Enter valid minutes'); return; }
  }
  hideFocusSetup();
  socket.emit('start_focus', { task, duration_s: mins * 60 });
  document.getElementById('focus-task-name').textContent = task;
  document.getElementById('observe-panel').style.display = 'none';
  document.getElementById('focus-overlay').classList.add('active');
  focusEndTime = Date.now() + mins * 60 * 1000;
  clearInterval(focusTimerInterval);
  focusTimerInterval = setInterval(updateFocusTimer, 1000);
}

function updateFocusTimer() {
  const rem = Math.max(0, Math.round((focusEndTime - Date.now()) / 1000));
  const m = Math.floor(rem / 60).toString().padStart(2, '0');
  const s = (rem % 60).toString().padStart(2, '0');
  document.getElementById('focus-timer').textContent = m + ':' + s;
  if (rem === 0) clearInterval(focusTimerInterval);
}

function endFocusEarly() { socket.emit('end_focus'); }

// ── Reward screen ─────────────────────────────────────────────────────────
function showReward(data) {
  clearInterval(focusTimerInterval);
  document.getElementById('focus-overlay').classList.remove('active');
  document.getElementById('reward-screen').classList.add('active');
  const g = document.getElementById('reward-grade');
  g.textContent = data.grade;
  g.className = 'grade-' + data.grade;
  document.getElementById('reward-score').textContent = 'Focus Score: ' + data.focus_score;
  document.getElementById('reward-task-label').textContent = data.task || 'Focus Complete';
  document.getElementById('stat-posture').textContent = data.posture_avg + '%';
  document.getElementById('stat-emotion').textContent = data.emotion_avg + '%';
  document.getElementById('stat-xp').textContent = '+' + data.xp_earned + ' XP';
  const lvl = data.level || 1, xp = data.xp || 0, cap = lvl * 200;
  document.getElementById('level-label').textContent = 'Level ' + lvl + ' · ' + xp + ' / ' + cap + ' XP';
  setTimeout(() => { document.getElementById('xp-bar').style.width = (xp/cap*100) + '%'; }, 300);
}

function hideReward() {
  document.getElementById('reward-screen').classList.remove('active');
  document.getElementById('observe-panel').style.display = 'flex';
}

// ── Socket events ─────────────────────────────────────────────────────────
socket.on('connect', () => { socket.emit('init'); });

socket.on('status', (data) => {
  if (data.type === 'waiting_mode') {
    document.getElementById('loading').style.display = 'none';
    document.getElementById('mode-screen').style.display = 'flex';
  } else if (data.type === 'ready') {
    document.getElementById('loading').style.display = 'none';
    document.getElementById('status-bar').style.display = 'flex';
    document.getElementById('observe-panel').style.display = 'flex';
    document.getElementById('status-dot').classList.add('ready');
    document.getElementById('status-text').textContent = 'Observing...';
    if (data.mode === 'tracker') document.getElementById('score-badge').style.display = 'none';
  } else if (data.type === 'error') {
    document.getElementById('status-text').textContent = 'Error: ' + data.message;
    document.getElementById('loading').style.display = 'none';
  }
});

socket.on('vision_result', (data) => {
  if (data.posture) updatePostureChip(data.posture);
  if (data.emotion) updateEmotionChip(data.emotion);
  if (data.progress !== undefined) updateProgress(data.progress);
  if (data.posture_score !== undefined) {
    document.getElementById('chip-score').textContent = 'Score: ' + data.posture_score + '%';
    document.getElementById('focus-posture-bar').style.width = data.posture_score + '%';
  }
  if (data.focus_active) focusEndTime = Date.now() + data.focus_time_left * 1000;
});

socket.on('suggestion', (data) => {
  currentSuggestionKey = data.key;
  document.getElementById('observe-panel').style.display = 'none';
  showSuggestion(data);
});

socket.on('task_confirmed', (data) => {
  showToast('✓ Task started! Complete it then tap Done.');
  document.getElementById('btn-confirm').style.display = 'none';
  document.getElementById('btn-complete').style.display = 'block';
  document.getElementById('sug-hapa').textContent = 'Stage: Intention → Action';
});

socket.on('task_completed', (data) => {
  const gap = data.intention_action_gap_s;
  showToast('Well done! Score: ' + data.score + '%' + (gap ? ' · Gap: ' + gap + 's' : ''));
  document.getElementById('score-badge').textContent = 'Score: ' + data.score + '%';
  if (data.xp) document.getElementById('xp-badge').textContent = 'Lv' + data.xp.level + ' · ' + data.xp.xp + 'XP';
  dismissCard();
  document.getElementById('observe-panel').style.display = 'flex';
  document.getElementById('status-text').textContent = 'Observing...';
});

socket.on('focus_complete', (data) => { showReward(data); });

// ── Task actions ──────────────────────────────────────────────────────────
function confirmTask()  { socket.emit('confirm_task'); }
function completeTask() { socket.emit('complete_task'); }
function dismissTask()  {
  socket.emit('dismiss_task', { key: currentSuggestionKey });
  dismissCard();
  document.getElementById('observe-panel').style.display = 'flex';
}
function dismissCard() { document.getElementById('suggestion-card').classList.remove('visible'); }

// ── UI helpers ────────────────────────────────────────────────────────────
function updateProgress(pct) {
  document.getElementById('progress-fill').style.width = pct + '%';
  document.getElementById('progress-pct').textContent = pct + '%';
  document.getElementById('observe-sub').textContent =
    pct >= 100 ? 'Generating suggestion...' : 'Suggestion in ~' + Math.max(1, Math.ceil((100-pct)/100)) + ' min';
}

function updatePostureChip(posture) {
  const chip = document.getElementById('chip-posture');
  if (!posture) return;
  if (posture.good_posture) {
    chip.textContent = '✓ ' + (posture.position || 'Good posture');
    chip.className = 'info-chip good';
  } else {
    const labels = { head_down:'↓ Head down', uneven_shoulders:'⟷ Uneven shoulders',
                     spine_lean:'↗ Spine lean', forward_hunch:'⤵ Hunching' };
    chip.textContent = labels[posture.alerts && posture.alerts[0]] || '⚠ Bad posture';
    chip.className = 'info-chip alert';
  }
}

function updateEmotionChip(emotions) {
  if (!emotions || !emotions.length) return;
  const chip = document.getElementById('chip-emotion');
  const e = emotions[0];
  const icons = { happy:'😊', sad:'😢', angry:'😠', fear:'😨', surprise:'😲', disgust:'🤢', neutral:'😐', contempt:'😒' };
  chip.textContent = (icons[e.emotion] || '') + ' ' + e.emotion;
  chip.className = 'info-chip ' + (e.state === 'positive' ? 'pos' : e.state === 'negative' ? 'neg' : '');
}

function showSuggestion(data) {
  document.getElementById('sug-category').textContent = data.category || 'Suggestion';
  document.getElementById('sug-hapa').textContent = 'Stage: Motivation';
  document.getElementById('sug-title').textContent = data.title;
  document.getElementById('sug-instr').textContent = data.instruction;
  document.getElementById('task-text').textContent = data.task || '—';
  document.getElementById('btn-confirm').style.display = data.task ? 'block' : 'none';
  document.getElementById('btn-complete').style.display = 'none';
  document.getElementById('suggestion-card').classList.add('visible');
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3500);
}

function toggleMenu()    { document.getElementById('side-menu').classList.toggle('open'); }
function openDashboard() { window.open('/dashboard', '_blank'); toggleMenu(); }
function openHistory()   { window.open('/history',   '_blank'); toggleMenu(); }
function endSessionFull() {
  socket.emit('end_session');
  stopCamera();
  toggleMenu();
  showToast('Session ended. Data saved.');
}
</script>
</body>
</html>
"""

DASHBOARD_UI = """
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Live Dashboard</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family:-apple-system,sans-serif; background:#0a0a0a; color:#fff; padding:20px; }
    h2 { font-size:18px; color:#aaa; margin-bottom:16px; }
    canvas { max-height:260px; }
    .chart-box { background:#111; border-radius:16px; padding:20px; margin-bottom:20px; }
    .metric-row { display:flex; gap:14px; margin-bottom:20px; flex-wrap:wrap; }
    .metric { background:#1a1a2e; border-radius:12px; padding:14px 20px; flex:1; min-width:130px; }
    .metric-val { font-size:28px; font-weight:700; color:#44ff88; }
    .metric-lbl { font-size:12px; color:#888; margin-top:2px; }
    #analysis { background:#111; border-radius:16px; padding:20px; }
    .analysis-row { display:flex; justify-content:space-between; padding:8px 0;
      border-bottom:1px solid #222; font-size:14px; }
    .analysis-row span { color:#44ff88; font-weight:600; }
  </style>
</head>
<body>
<h2>Live Session Dashboard</h2>
<div class="metric-row">
  <div class="metric"><div class="metric-val" id="m-posture">—</div><div class="metric-lbl">Posture Score</div></div>
  <div class="metric"><div class="metric-val" id="m-emotion">—</div><div class="metric-lbl">Emotion Valence</div></div>
  <div class="metric"><div class="metric-val" id="m-lag">—</div><div class="metric-lbl">P→E Lag (s)</div></div>
  <div class="metric"><div class="metric-val" id="m-decay">—</div><div class="metric-lbl">Decay /min</div></div>
</div>
<div class="chart-box"><canvas id="chart-posture"></canvas></div>
<div class="chart-box"><canvas id="chart-emotion"></canvas></div>
<div id="analysis">
  <h2 style="margin-bottom:12px">Analysis Metrics</h2>
  <div class="analysis-row">P→E Lag <span id="a-lag">computing...</span></div>
  <div class="analysis-row">Posture Decay Rate <span id="a-decay">computing...</span></div>
  <div class="analysis-row">Mean Posture Score <span id="a-mpos">—</span></div>
  <div class="analysis-row">Mean Emotion Valence <span id="a-mval">—</span></div>
</div>
<script>
const socket = io();
const labels = [], postureData = [], emotionData = [];

const chartPost = new Chart(document.getElementById('chart-posture'), {
  type:'line',
  data:{ labels, datasets:[{ label:'Posture Score', data:postureData,
    borderColor:'#44ff88', backgroundColor:'rgba(68,255,136,.1)', tension:.4, fill:true }] },
  options:{ animation:false, scales:{ y:{min:0,max:100,grid:{color:'#222'}}, x:{grid:{color:'#222'}} },
    plugins:{ legend:{labels:{color:'#aaa'}} } }
});
const chartEmo = new Chart(document.getElementById('chart-emotion'), {
  type:'line',
  data:{ labels, datasets:[{ label:'Emotion Valence', data:emotionData,
    borderColor:'#4488ff', backgroundColor:'rgba(68,136,255,.1)', tension:.4, fill:true }] },
  options:{ animation:false, scales:{ y:{min:-1,max:1,grid:{color:'#222'}}, x:{grid:{color:'#222'}} },
    plugins:{ legend:{labels:{color:'#aaa'}} } }
});

socket.on('vision_result', (d) => {
  const now = new Date().toLocaleTimeString();
  if (d.posture_score !== undefined) {
    labels.push(now); postureData.push(d.posture_score);
    emotionData.push(d.emotion && d.emotion[0] ? (d.emotion[0].valence||0) : (emotionData[emotionData.length-1]||0));
    if (labels.length > 60) { labels.shift(); postureData.shift(); emotionData.shift(); }
    chartPost.update(); chartEmo.update();
    document.getElementById('m-posture').textContent = d.posture_score + '%';
  }
  if (d.emotion && d.emotion[0])
    document.getElementById('m-emotion').textContent = (d.emotion[0].valence||0).toFixed(2);
});

setInterval(() => {
  fetch('/stats').then(r=>r.json()).then(s => {
    if (s.pe_lag_s != null) {
      document.getElementById('m-lag').textContent = s.pe_lag_s + 's';
      document.getElementById('a-lag').textContent = s.pe_lag_s + 's (' + (s.pe_lag_s>0?'posture leads':'emotion leads') + ')';
    }
    if (s.posture_decay_per_min != null) {
      document.getElementById('m-decay').textContent = s.posture_decay_per_min;
      document.getElementById('a-decay').textContent = s.posture_decay_per_min + ' pts/min';
    }
    if (s.mean_posture_score)   document.getElementById('a-mpos').textContent = s.mean_posture_score;
    if (s.mean_emotion_valence) document.getElementById('a-mval').textContent = s.mean_emotion_valence;
  }).catch(()=>{});
}, 5000);
</script>
</body>
</html>
"""

HISTORY_UI = """
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Session History</title>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family:-apple-system,sans-serif; background:#0a0a0a; color:#fff; padding:20px; }
    h2 { font-size:18px; color:#aaa; margin-bottom:16px; }
    .session { background:#111; border-radius:14px; padding:16px; margin-bottom:12px; }
    .session-id { font-size:12px; color:#555; margin-bottom:4px; }
    .session-stat { display:flex; gap:16px; flex-wrap:wrap; margin-top:8px; }
    .sstat { font-size:13px; color:#aaa; }
    .sstat span { color:#44ff88; font-weight:600; }
    #no-sessions { color:#555; font-size:14px; margin-top:32px; text-align:center; }
  </style>
</head>
<body>
<h2>Session History</h2>
<div id="sessions-list"><div id="no-sessions">No sessions yet.</div></div>
<script>
fetch('/history_data').then(r=>r.json()).then(sessions => {
  const el = document.getElementById('sessions-list');
  if (!sessions.length) return;
  el.innerHTML = '';
  sessions.reverse().forEach(s => {
    const d = document.createElement('div');
    d.className = 'session';
    d.innerHTML = `<div class="session-id">${s.session_id}</div>
      <div>${s.mode||'—'} mode · ${Math.round((s.duration_s||0)/60)} min</div>
      <div class="session-stat">
        <div class="sstat">P→E Lag: <span>${s.pe_lag_s!==undefined?s.pe_lag_s+'s':'—'}</span></div>
        <div class="sstat">Decay: <span>${s.posture_decay_per_min!==undefined?s.posture_decay_per_min+'/min':'—'}</span></div>
        <div class="sstat">Posture: <span>${s.mean_posture_score||'—'}</span></div>
      </div>`;
    el.appendChild(d);
  });
});
</script>
</body>
</html>
"""

# ══════════════════════════════════════════════════════════════════════════════
# Flask routes
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template_string(PHONE_UI)

@app.route('/dashboard')
def dashboard():
    return render_template_string(DASHBOARD_UI)

@app.route('/history')
def history():
    return render_template_string(HISTORY_UI)

@app.route('/history_data')
def history_data():
    summaries = []
    if os.path.exists('data'):
        for fn in os.listdir('data'):
            if fn.endswith('_summary.json'):
                try:
                    with open(os.path.join('data', fn)) as f:
                        summaries.append(json.load(f))
                except Exception:
                    pass
    return jsonify(summaries)

@app.route('/stats')
def stats():
    s = analysis_engine.get_summary() if analysis_engine else {}
    if suggestion_engine:
        s.update(suggestion_engine.get_stats())
    return jsonify(s)

# ══════════════════════════════════════════════════════════════════════════════
# SocketIO events
# ══════════════════════════════════════════════════════════════════════════════

@socketio.on('connect')
def on_connect(auth=None):
    print("[App] Client connected.")
    emit('status', {'type': 'waiting_mode'})

@socketio.on('init')
def on_init(data=None):
    emit('status', {'type': 'waiting_mode'})

@socketio.on('start_session')
def on_start_session(data):
    mode    = data.get('mode', 'supporter')
    user_id = data.get('user_id', 'user1')
    if not engines_ready:
        t = threading.Thread(target=init_engines, kwargs={'mode': mode, 'user_id': user_id}, daemon=True)
        t.start()
    else:
        emit('status', {'type': 'ready', 'message': 'Robot AI is ready!', 'mode': CURRENT_MODE})

@socketio.on('camera_frame')
def on_camera_frame(data):
    """Laptop browser sends a JPEG frame; Pi processes it."""
    if engines_ready and vision_engine:
        frame_data = data.get('frame', '')
        if frame_data:
            vision_engine.push_frame(frame_data)

@socketio.on('start_focus')
def on_start_focus(data):
    if suggestion_engine:
        suggestion_engine.start_focus(data.get('task', 'Focus session'),
                                       int(data.get('duration_s', 1500)))

@socketio.on('end_focus')
def on_end_focus(data=None):
    if suggestion_engine:
        result = suggestion_engine.end_focus()
        if result:
            emit('focus_complete', result)

@socketio.on('confirm_task')
def on_confirm_task(data=None):
    if suggestion_engine:
        result = suggestion_engine.confirm_task()
        if result:
            if data_logger:
                data_logger.log_confirm(result.get('key', ''))
            emit('task_confirmed', {'suggestion': result, 'message': f"Now complete: {result['task']}"})

@socketio.on('complete_task')
def on_complete_task(data=None):
    if suggestion_engine:
        result = suggestion_engine.complete_task()
        if result:
            gap = result.get('intention_action_gap_s')
            if data_logger:
                data_logger.log_complete(result.get('key', ''))
            score = suggestion_engine.get_score()
            emit('task_completed', {
                'suggestion': result, 'score': score,
                'intention_action_gap_s': gap,
                'message': f"Well done! Score: {score}%",
                'xp': suggestion_engine.get_xp_info(),
            })

@socketio.on('dismiss_task')
def on_dismiss_task(data=None):
    if suggestion_engine:
        suggestion_engine.dismiss_task()
        if data_logger and (data or {}).get('key'):
            data_logger.log_dismiss(data['key'])

@socketio.on('end_session')
def on_end_session(data=None):
    if data_logger and analysis_engine:
        extra = analysis_engine.get_summary()
        if suggestion_engine:
            extra.update(suggestion_engine.get_stats())
        data_logger.finalize(extra)

@socketio.on('disconnect')
def on_disconnect():
    print("[App] Client disconnected.")

# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    if GPIO_AVAILABLE:
        threading.Thread(target=touch_sensor_loop, daemon=True).start()

    os.makedirs('data', exist_ok=True)
    print("Starting server on :5000 ...")
    print("Open on your laptop: https://<PI_IP>:5000")
    print("Allow camera access when browser asks.")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, ssl_context='adhoc')
