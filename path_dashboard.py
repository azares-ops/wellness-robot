"""Run on Pi: python3 /home/claude/patch_dashboard.py"""

NEW_DASHBOARD = '''DASHBOARD_UI = """
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Posture & Emotion — Live Dashboard</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Syne:wght@400;700;800&display=swap');

    :root {
      --bg:       #060608;
      --surface:  #0e0e12;
      --border:   #1e1e28;
      --green:    #39ff8f;
      --blue:     #4d9fff;
      --orange:   #ff8c42;
      --red:      #ff4466;
      --text:     #e8e8f0;
      --muted:    #55556a;
    }

    * { margin:0; padding:0; box-sizing:border-box; }

    body {
      font-family: 'Syne', sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      padding: 24px;
    }

    /* ── Header ── */
    .header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      margin-bottom: 28px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }
    .header h1 {
      font-size: 20px;
      font-weight: 800;
      letter-spacing: -0.5px;
    }
    .header h1 span { color: var(--green); }
    #live-badge {
      display: flex; align-items: center; gap: 7px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px; color: var(--muted);
    }
    #live-dot {
      width: 7px; height: 7px; border-radius: 50%;
      background: var(--muted);
      transition: background .4s;
    }
    #live-dot.active { background: var(--green); box-shadow: 0 0 8px var(--green); }

    /* ── KPI row ── */
    .kpi-row {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-bottom: 20px;
    }
    @media(max-width:700px){ .kpi-row { grid-template-columns: repeat(2,1fr); } }

    .kpi {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px 18px;
      position: relative;
      overflow: hidden;
    }
    .kpi::before {
      content: '';
      position: absolute; top:0; left:0; right:0; height:2px;
      background: var(--accent, var(--green));
    }
    .kpi-val {
      font-family: 'JetBrains Mono', monospace;
      font-size: 30px;
      font-weight: 700;
      line-height: 1;
      color: var(--accent, var(--green));
      margin-bottom: 6px;
    }
    .kpi-lbl { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
    .kpi.blue  { --accent: var(--blue); }
    .kpi.orange{ --accent: var(--orange); }
    .kpi.red   { --accent: var(--red); }

    /* ── Chart panels ── */
    .charts-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 20px;
    }
    @media(max-width:800px){ .charts-grid { grid-template-columns: 1fr; } }

    .chart-panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 20px;
    }
    .chart-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }
    .chart-title {
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 1.5px;
      color: var(--muted);
    }
    .chart-current {
      font-family: 'JetBrains Mono', monospace;
      font-size: 22px;
      font-weight: 700;
    }
    .chart-panel canvas { width:100% !important; height:180px !important; }

    /* ── Combined chart ── */
    .combined-panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 20px;
      margin-bottom: 20px;
    }
    .combined-panel canvas { width:100% !important; height:220px !important; }

    /* ── Alert / emotion timeline ── */
    .timeline-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 20px;
    }
    @media(max-width:700px){ .timeline-grid { grid-template-columns:1fr; } }

    .timeline-panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px;
    }
    .timeline-title {
      font-size: 11px; font-weight:700; text-transform:uppercase;
      letter-spacing:1.5px; color:var(--muted); margin-bottom:12px;
    }
    .timeline-feed {
      display: flex;
      flex-direction: column;
      gap: 6px;
      max-height: 200px;
      overflow-y: auto;
    }
    .timeline-feed::-webkit-scrollbar { width:3px; }
    .timeline-feed::-webkit-scrollbar-thumb { background:var(--border); border-radius:2px; }

    .tl-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 10px;
      border-radius: 8px;
      background: rgba(255,255,255,.03);
      border-left: 3px solid transparent;
      font-size: 13px;
      animation: fadeIn .3s ease;
    }
    @keyframes fadeIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }

    .tl-item.good   { border-left-color: var(--green); }
    .tl-item.alert  { border-left-color: var(--red); }
    .tl-item.pos    { border-left-color: var(--green); }
    .tl-item.neg    { border-left-color: var(--red); }
    .tl-item.neutral{ border-left-color: var(--muted); }

    .tl-time {
      font-family: 'JetBrains Mono', monospace;
      font-size: 10px; color: var(--muted); white-space: nowrap;
    }
    .tl-label { flex:1; }
    .tl-score {
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px; color: var(--muted);
    }

    /* ── Stats row ── */
    .stats-panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px 20px;
    }
    .stats-title {
      font-size: 11px; font-weight:700; text-transform:uppercase;
      letter-spacing:1.5px; color:var(--muted); margin-bottom:14px;
    }
    .stats-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:10px; }
    @media(min-width:600px){ .stats-grid { grid-template-columns:repeat(4,1fr); } }
    .stat-row {
      display:flex; flex-direction:column; gap:4px;
      padding:12px; background:rgba(255,255,255,.03); border-radius:8px;
    }
    .stat-key { font-size:11px; color:var(--muted); }
    .stat-val {
      font-family:'JetBrains Mono',monospace;
      font-size:15px; font-weight:700; color:var(--green);
    }
  </style>
</head>
<body>

<div class="header">
  <h1>Posture <span>&</span> Emotion</h1>
  <div id="live-badge"><div id="live-dot"></div><span id="live-time">--:--:--</span></div>
</div>

<!-- KPIs -->
<div class="kpi-row">
  <div class="kpi">
    <div class="kpi-val" id="kpi-posture">—</div>
    <div class="kpi-lbl">Posture Score</div>
  </div>
  <div class="kpi blue">
    <div class="kpi-val" id="kpi-valence">—</div>
    <div class="kpi-lbl">Emotion Valence</div>
  </div>
  <div class="kpi orange">
    <div class="kpi-val" id="kpi-emotion">—</div>
    <div class="kpi-lbl">Current Emotion</div>
  </div>
  <div class="kpi red">
    <div class="kpi-val" id="kpi-alert">—</div>
    <div class="kpi-lbl">Active Alert</div>
  </div>
</div>

<!-- Combined overlay chart -->
<div class="combined-panel">
  <div class="chart-header">
    <div class="chart-title">Posture Score &amp; Emotion Valence — Combined</div>
  </div>
  <canvas id="chart-combined"></canvas>
</div>

<!-- Individual charts -->
<div class="charts-grid">
  <div class="chart-panel">
    <div class="chart-header">
      <div class="chart-title">Posture Score</div>
      <div class="chart-current" id="cur-posture" style="color:var(--green)">—</div>
    </div>
    <canvas id="chart-posture"></canvas>
  </div>
  <div class="chart-panel">
    <div class="chart-header">
      <div class="chart-title">Emotion Valence</div>
      <div class="chart-current" id="cur-valence" style="color:var(--blue)">—</div>
    </div>
    <canvas id="chart-emotion"></canvas>
  </div>
</div>

<!-- Timelines -->
<div class="timeline-grid">
  <div class="timeline-panel">
    <div class="timeline-title">⚠ Posture Alert Log</div>
    <div class="timeline-feed" id="posture-feed">
      <div class="tl-item neutral"><span class="tl-label" style="color:var(--muted)">Waiting for data...</span></div>
    </div>
  </div>
  <div class="timeline-panel">
    <div class="timeline-title">😐 Emotion Log</div>
    <div class="timeline-feed" id="emotion-feed">
      <div class="tl-item neutral"><span class="tl-label" style="color:var(--muted)">Waiting for data...</span></div>
    </div>
  </div>
</div>

<!-- Analysis stats -->
<div class="stats-panel">
  <div class="stats-title">Session Analysis</div>
  <div class="stats-grid">
    <div class="stat-row"><div class="stat-key">P→E Lag</div><div class="stat-val" id="s-lag">—</div></div>
    <div class="stat-row"><div class="stat-key">Posture Decay /min</div><div class="stat-val" id="s-decay">—</div></div>
    <div class="stat-row"><div class="stat-key">Mean Posture</div><div class="stat-val" id="s-mpos">—</div></div>
    <div class="stat-row"><div class="stat-key">Mean Valence</div><div class="stat-val" id="s-mval">—</div></div>
  </div>
</div>

<script>
const socket = io();

// ── Data buffers (last 90 points) ────────────────────────────────────────
const MAX = 90;
const labels      = [];
const postureData = [];
const valenceData = [];

let lastPostureAlert = null;
let lastEmotion      = null;

// ── Chart defaults ────────────────────────────────────────────────────────
Chart.defaults.color = '#55556a';
Chart.defaults.font.family = "'JetBrains Mono', monospace";
Chart.defaults.font.size   = 10;

const gridColor  = '#1e1e28';
const tickColor  = '#55556a';

// ── Combined chart ────────────────────────────────────────────────────────
const combinedCtx = document.getElementById('chart-combined').getContext('2d');
const chartCombined = new Chart(combinedCtx, {
  type: 'line',
  data: {
    labels,
    datasets: [
      {
        label: 'Posture Score',
        data: postureData,
        borderColor: '#39ff8f',
        backgroundColor: 'rgba(57,255,143,.07)',
        borderWidth: 2,
        tension: 0.4,
        fill: true,
        pointRadius: 0,
        yAxisID: 'yPosture',
      },
      {
        label: 'Emotion Valence',
        data: valenceData,
        borderColor: '#4d9fff',
        backgroundColor: 'rgba(77,159,255,.07)',
        borderWidth: 2,
        tension: 0.4,
        fill: true,
        pointRadius: 0,
        yAxisID: 'yValence',
      }
    ]
  },
  options: {
    animation: false,
    responsive: true,
    interaction: { mode: 'index', intersect: false },
    scales: {
      x: { grid:{color:gridColor}, ticks:{color:tickColor, maxTicksLimit:8} },
      yPosture: {
        type: 'linear', position: 'left',
        min: 0, max: 100,
        grid: { color: gridColor },
        ticks: { color: '#39ff8f' },
        title: { display:true, text:'Posture %', color:'#39ff8f', font:{size:10} }
      },
      yValence: {
        type: 'linear', position: 'right',
        min: -1, max: 1,
        grid: { drawOnChartArea: false },
        ticks: { color: '#4d9fff' },
        title: { display:true, text:'Valence', color:'#4d9fff', font:{size:10} }
      }
    },
    plugins: {
      legend: { labels:{ color:'#aaa', boxWidth:12, padding:16 } },
      tooltip: {
        backgroundColor:'#0e0e12',
        borderColor:'#1e1e28',
        borderWidth:1,
        titleColor:'#aaa',
        bodyColor:'#e8e8f0',
      }
    }
  }
});

// ── Individual posture chart ───────────────────────────────────────────────
const chartPost = new Chart(document.getElementById('chart-posture'), {
  type: 'line',
  data: {
    labels,
    datasets: [{
      label: 'Posture Score',
      data: postureData,
      borderColor: '#39ff8f',
      backgroundColor: (ctx) => {
        const g = ctx.chart.ctx.createLinearGradient(0,0,0,180);
        g.addColorStop(0,'rgba(57,255,143,.25)');
        g.addColorStop(1,'rgba(57,255,143,0)');
        return g;
      },
      borderWidth: 2, tension: 0.4, fill: true, pointRadius: 0,
    }]
  },
  options: {
    animation: false, responsive:true,
    scales: {
      y: { min:0, max:100, grid:{color:gridColor}, ticks:{color:tickColor} },
      x: { grid:{color:gridColor}, ticks:{color:tickColor, maxTicksLimit:6} }
    },
    plugins: { legend:{display:false} }
  }
});

// ── Individual emotion chart ───────────────────────────────────────────────
const chartEmo = new Chart(document.getElementById('chart-emotion'), {
  type: 'line',
  data: {
    labels,
    datasets: [{
      label: 'Valence',
      data: valenceData,
      borderColor: '#4d9fff',
      backgroundColor: (ctx) => {
        const g = ctx.chart.ctx.createLinearGradient(0,0,0,180);
        g.addColorStop(0,'rgba(77,159,255,.25)');
        g.addColorStop(1,'rgba(77,159,255,0)');
        return g;
      },
      borderWidth: 2, tension: 0.4, fill: true, pointRadius: 0,
    }]
  },
  options: {
    animation: false, responsive:true,
    scales: {
      y: {
        min: -1, max: 1,
        grid: { color: gridColor,
          // zero line highlight
          lineWidth: ctx => ctx.tick.value === 0 ? 2 : 1,
        },
        ticks: { color: tickColor }
      },
      x: { grid:{color:gridColor}, ticks:{color:tickColor, maxTicksLimit:6} }
    },
    plugins: { legend:{display:false} }
  }
});

// ── Socket handler ─────────────────────────────────────────────────────────
socket.on('connect', () => {
  document.getElementById('live-dot').classList.add('active');
});
socket.on('disconnect', () => {
  document.getElementById('live-dot').classList.remove('active');
});

socket.on('vision_result', (d) => {
  const now = new Date();
  const t   = now.toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  document.getElementById('live-time').textContent = t;

  const score   = d.posture_score !== undefined ? parseInt(d.posture_score) : null;
  const emotion = d.emotion && d.emotion[0] ? d.emotion[0] : null;
  const valence = emotion ? (emotion.valence || 0) : null;

  // Push to buffers
  if (score !== null) {
    labels.push(t);
    postureData.push(score);
    valenceData.push(valence !== null ? valence : (valenceData[valenceData.length-1] || 0));

    if (labels.length > MAX) {
      labels.shift(); postureData.shift(); valenceData.shift();
    }

    chartCombined.update('none');
    chartPost.update('none');
    chartEmo.update('none');

    // KPI + current value
    document.getElementById('kpi-posture').textContent  = score + '%';
    document.getElementById('cur-posture').textContent  = score + '%';
    const pc = score >= 80 ? 'var(--green)' : score >= 50 ? 'var(--orange)' : 'var(--red)';
    document.getElementById('kpi-posture').style.color  = pc;
    document.getElementById('cur-posture').style.color  = pc;
  }

  if (valence !== null) {
    document.getElementById('kpi-valence').textContent  = valence.toFixed(2);
    document.getElementById('cur-valence').textContent  = valence.toFixed(2);
    const vc = valence > 0.1 ? 'var(--green)' : valence < -0.1 ? 'var(--red)' : 'var(--blue)';
    document.getElementById('kpi-valence').style.color  = vc;
    document.getElementById('cur-valence').style.color  = vc;
  }

  if (emotion) {
    const icons = {happy:'😊',sad:'😢',angry:'😠',fear:'😨',surprise:'😲',
                   disgust:'🤢',neutral:'😐',contempt:'😒'};
    const icon = icons[emotion.emotion] || '😐';
    document.getElementById('kpi-emotion').textContent = icon + ' ' + emotion.emotion;
  }

  // ── Posture alert log ──────────────────────────────────────────────────
  if (d.posture) {
    const alerts = d.posture.alerts || [];
    const alertStr = alerts.length ? alerts.join(', ') : 'good';

    document.getElementById('kpi-alert').textContent =
      alerts.length ? alerts[0].replace('_',' ') : '✓ good';
    document.getElementById('kpi-alert').style.color =
      alerts.length ? 'var(--red)' : 'var(--green)';

    // Only log when alert state changes
    if (alertStr !== lastPostureAlert) {
      lastPostureAlert = alertStr;
      const feed  = document.getElementById('posture-feed');
      const isGood = alerts.length === 0;
      const labelMap = {
        head_down:'↓ Head down', uneven_shoulders:'⟷ Uneven shoulders',
        spine_lean:'↗ Spine lean', forward_hunch:'⤵ Hunching'
      };
      const text = isGood ? '✓ Good posture'
        : alerts.map(a => labelMap[a] || a).join(' + ');

      // Remove placeholder
      const ph = feed.querySelector('.tl-item.neutral span[style]');
      if (ph) ph.closest('.tl-item').remove();

      const item = document.createElement('div');
      item.className = 'tl-item ' + (isGood ? 'good' : 'alert');
      item.innerHTML = `<span class="tl-time">${t}</span>
        <span class="tl-label">${text}</span>
        <span class="tl-score">${score !== null ? score+'%' : ''}</span>`;
      feed.insertBefore(item, feed.firstChild);
      // Keep last 30
      while (feed.children.length > 30) feed.removeChild(feed.lastChild);
    }
  }

  // ── Emotion log ────────────────────────────────────────────────────────
  if (emotion) {
    const emoLabel = emotion.emotion;
    if (emoLabel !== lastEmotion) {
      lastEmotion = emoLabel;
      const feed  = document.getElementById('emotion-feed');
      const state = emotion.state || 'neutral';
      const icons2 = {happy:'😊',sad:'😢',angry:'😠',fear:'😨',surprise:'😲',
                      disgust:'🤢',neutral:'😐',contempt:'😒'};

      const ph = feed.querySelector('.tl-item.neutral span[style]');
      if (ph) ph.closest('.tl-item').remove();

      const item = document.createElement('div');
      item.className = 'tl-item ' + (state==='positive'?'pos':state==='negative'?'neg':'neutral');
      item.innerHTML = `<span class="tl-time">${t}</span>
        <span class="tl-label">${icons2[emoLabel]||'😐'} ${emoLabel}</span>
        <span class="tl-score">${valence !== null ? valence.toFixed(2) : ''}</span>`;
      feed.insertBefore(item, feed.firstChild);
      while (feed.children.length > 30) feed.removeChild(feed.lastChild);
    }
  }
});

// ── Stats polling ──────────────────────────────────────────────────────────
setInterval(() => {
  fetch('/stats').then(r=>r.json()).then(s => {
    if (s.pe_lag_s != null)
      document.getElementById('s-lag').textContent =
        s.pe_lag_s + 's (' + (s.pe_lag_s > 0 ? 'P leads' : 'E leads') + ')';
    if (s.posture_decay_per_min != null)
      document.getElementById('s-decay').textContent = s.posture_decay_per_min + '/min';
    if (s.mean_posture_score)
      document.getElementById('s-mpos').textContent = s.mean_posture_score + '%';
    if (s.mean_emotion_valence)
      document.getElementById('s-mval').textContent = s.mean_emotion_valence;
  }).catch(()=>{});
}, 5000);
</script>
</body>
</html>
"""'''

with open('/home/who/grok_robo/app.py', 'r') as f:
    content = f.read()

# Find and replace DASHBOARD_UI
import re
pattern = r'DASHBOARD_UI = """.*?"""'
if re.search(pattern, content, re.DOTALL):
    content = re.sub(pattern, NEW_DASHBOARD, content, flags=re.DOTALL)
    with open('/home/who/grok_robo/app.py', 'w') as f:
        f.write(content)
    print("✓ DASHBOARD_UI replaced successfully")
else:
    print("✗ DASHBOARD_UI pattern not found")
    print("  Writing to standalone dashboard.html instead...")
    html = NEW_DASHBOARD.split('= """')[1].rsplit('"""', 1)[0]
    with open('/home/who/grok_robo/dashboard_standalone.html', 'w') as f:
        f.write(html)
    print("  Written to dashboard_standalone.html")
