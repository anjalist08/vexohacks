// Wayback trail page. Two sources:
// - backend (default): python3 main.py --band holds the band and runs tracking, voice,
//   landmarks and guidance; this page draws what it reports over its WebSocket and sends
//   typed commands back. Voice works here (double-tap the band).
// - direct: the page connects to the band itself in Chrome (Web Bluetooth) and tracks with
//   trail-core.js. Map only, no voice. Good for tuning.
// The band takes one connection at a time: use one source, not both.
import { Band, SimTransport } from '../vexo-open-kit/js/src/index.js';
import { Trail } from './trail-core.js';

const $ = (id) => document.getElementById(id);
const canvas = $('map');
const pen = canvas.getContext('2d');
const source = () => $('source').value;

// ---------------------------------------------------------------- shared view state
// Everything the map and panels draw, filled by either source.
let view = emptyView();
function emptyView() {
  return {
    points: [{ x: 0, y: 0, h: 0, steps: 0 }], // the recorded walk
    back: [],                                   // points walked while being guided back
    turns: [], landmarks: [], waypoints: [],
    x: 0, y: 0, facing: 0, steps: 0, accSteps: null, bandSteps: null, distance: 0,
    state: '–', running: false, calibrated: false, uncertain: false, bias: null,
    guidance: { instructions: [], current_index: 0, active: false },
  };
}

// ---------------------------------------------------------------- debug log
const dbgLines = [];
const wall = () => new Date().toTimeString().slice(0, 8);
function dbg(text) {
  dbgLines.push(`${wall()}  ${text}`);
  if (dbgLines.length > 5000) dbgLines.shift();
  const box = $('dbg');
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 4;
  box.textContent = dbgLines.slice(-300).join('\n');
  if (atBottom) box.scrollTop = box.scrollHeight;
}
function download(name, text, type) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
const stamp = () => new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
$('saveDbg').onclick = () => download(`debug-${stamp()}.txt`, dbgLines.join('\n') + '\n', 'text/plain');

function say(text, warn = false) { $('msg').textContent = text; $('msg').className = warn ? 'warn' : ''; }
function setLink(text, live) { $('link').textContent = text; $('link').className = live ? 'pill live' : 'pill'; }

// ---------------------------------------------------------------- source switch
function applySource() {
  const direct = source() === 'direct';
  $('directOpts').hidden = !direct;
  $('backendOpts').hidden = direct;
  $('settingsCard').hidden = !direct;
  $('voiceCard').hidden = direct;
  $('rateRow').hidden = !direct;
  $('simbtns').hidden = !(direct && $('pretend').checked);
}
$('source').addEventListener('change', applySource);
$('pretend').addEventListener('change', applySource);
applySource();

$('connect').onclick = () => (source() === 'direct' ? connectDirect() : connectBackend());
$('start').onclick = () => (source() === 'direct' ? startDirect() : command('start route'));
$('stop').onclick = () => (source() === 'direct' ? stopDirect() : command('stop route'));
$('clear').onclick = () => { if (source() === 'direct') { trail = new Trail(settings()); log = []; } view = emptyView(); renderVoice(); say('View cleared.'); };
$('save').onclick = () => {
  if (source() === 'direct') {
    const header = 'kind,t,ax,ay,az,gx,gy,gz,steps,state\n';
    download(`walk-${stamp()}${sim ? '-PRETEND' : ''}.csv`, header + log.map((r) => r.join(',')).join('\n') + '\n', 'text/csv');
  } else if (backendLog) {
    window.open(backendLog, '_blank', 'noopener');
  }
};

// ================================================================= backend source
let socket = null;
let backendLog = null;
let lastTracker = null;

function connectBackend() {
  if (socket && socket.readyState <= 1) socket.close();
  const port = Number($('wsPort').value) || 8765;
  const host = location.hostname && location.hostname !== 'localhost' ? location.hostname : '127.0.0.1';
  const url = `ws://${host}:${port}`;
  say(`Connecting to main.py at ${url}...`);
  socket = new WebSocket(url);
  socket.onopen = () => {
    setLink('backend connected', true);
    $('start').disabled = false; $('stop').disabled = false;
    view = emptyView();
    dbg(`connected to backend ${url}`);
    say('Connected to main.py. Press Start route (or double-tap the band and say it), hold your arm still a moment, then walk.');
  };
  socket.onclose = () => {
    setLink('backend not connected', false);
    $('start').disabled = true; $('stop').disabled = true;
    say(`No connection to main.py on port ${port}. Is "python3 main.py --band --ws-port ${port} --http-port 8091" running? Press Connect to retry.`, true);
  };
  socket.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    onBackend(m);
  };
}

function command(text) {
  if (!socket || socket.readyState !== 1) { say('Not connected to main.py. Press Connect first.', true); return; }
  socket.send(JSON.stringify({ type: 'command', text }));
  dbg(`> ${text}`);
}
$('cmdForm').addEventListener('submit', (e) => { e.preventDefault(); const t = $('cmd').value.trim(); if (t) { command(t); $('cmd').value = ''; } });
document.querySelectorAll('.chips button').forEach((b) => { b.onclick = () => command(b.dataset.cmd); });

function onBackend(m) {
  switch (m.type) {
    case 'mode': {
      const pill = $('modePill');
      pill.hidden = false;
      pill.textContent = m.mode;
      pill.className = m.mode === 'LIVE' ? 'pill live' : 'pill bad';
      if (m.mode !== 'LIVE') say(`${m.mode}: this is not live sensing.`, true);
      dbg(`mode ${m.mode}`);
      break;
    }
    case 'link': setLink(`band: ${m.status}`, m.status === 'connected' || m.status === 'reconnected'); dbg(`band link ${m.status}`); break;
    case 'reset': view = emptyView(); dbg('route started (view reset)'); renderVoice(); break;
    case 'point': {
      const p = { x: +m.x_m || 0, y: +m.y_m || 0, h: +m.heading_deg || 0, steps: +m.steps || 0 };
      const line = view.guidance.active ? view.back : view.points;
      const prev = line.length ? line[line.length - 1] : view.points[view.points.length - 1];
      if (prev && Math.abs(((p.h - prev.h + 540) % 360) - 180) >= 45 && line === view.points) {
        const deg = ((p.h - prev.h + 540) % 360) - 180;
        view.turns.push({ x: prev.x, y: prev.y, deg });
        dbg(`turn ${Math.abs(deg) >= 180 ? 'U-TURN' : deg < 0 ? 'LEFT' : 'RIGHT'}, walking heading ${Math.round(p.h)}`);
      }
      if (prev && line.length) view.distance += Math.hypot(p.x - prev.x, p.y - prev.y);
      line.push(p);
      view.x = p.x; view.y = p.y; view.steps = p.steps;
      break;
    }
    case 'landmark': {
      const lm = { id: m.id, label: m.label, x: m.x_m, y: m.y_m, floor: m.floor, note: m.note };
      const i = view.landmarks.findIndex((l) => l.id === lm.id);
      if (i >= 0) view.landmarks[i] = lm; else view.landmarks.push(lm);
      dbg(`landmark saved: ${lm.label}${lm.floor ? ' (floor ' + lm.floor + ')' : ''}`);
      renderVoice();
      break;
    }
    case 'guidance':
      view.guidance = { instructions: m.instructions || [], current_index: m.current_index || 0, active: !!m.active };
      view.waypoints = (m.waypoints || []).map(([x, y]) => ({ x, y }));
      if (!view.guidance.active) view.back = [];
      renderVoice();
      break;
    case 'say': $('say').textContent = m.text || ''; dbg(`said: ${m.text}`); break;
    case 'led': $('ledPill').textContent = `LED ${m.state}`; break;
    case 'tracker': {
      const was = lastTracker;
      lastTracker = m;
      Object.assign(view, {
        running: m.running, calibrated: m.calibrated, uncertain: m.uncertain,
        facing: m.live_heading_deg, accSteps: m.motion_steps, bandSteps: m.band_steps,
        state: m.state, bias: m.bias_dps,
      });
      if (m.log) { backendLog = m.log; $('save').disabled = false; }
      if (was && !was.calibrated && m.calibrated && m.running) dbg(`calibrated: gyro bias ${m.bias_dps} deg/s. Walk now.`);
      if (was && was.running !== m.running) dbg(m.running ? 'recording started' : 'recording stopped');
      if (was && !was.uncertain && m.uncertain) dbg('position may be off: re-anchor at a landmark ("I\'m at the ...")');
      break;
    }
    default: break;
  }
}

function hintItem(text) {
  const li = document.createElement('li');
  li.className = 'hint';
  li.textContent = text;
  return li;
}

function renderVoice() {
  const lms = view.landmarks;
  $('lmCount').textContent = lms.length;
  $('lmList').replaceChildren();
  if (!lms.length) $('lmList').appendChild(hintItem('None yet.'));
  for (const l of lms) {
    const li = document.createElement('li');
    li.textContent = l.label + (l.floor ? ` (floor ${l.floor})` : '') + (l.note ? ` – ${l.note}` : '');
    $('lmList').appendChild(li);
  }
  const g = view.guidance;
  $('guideState').textContent = g.active ? 'guiding' : g.instructions.length ? 'planned' : 'inactive';
  $('guideState').className = g.active ? 'pill live' : 'pill';
  $('guideList').replaceChildren();
  if (!g.instructions.length) $('guideList').appendChild(hintItem('Ask "take me back to the start".'));
  g.instructions.forEach((ins, i) => {
    const li = document.createElement('li');
    li.textContent = ins.text || `${ins.turn} ${ins.steps} steps`;
    if (g.active && i === g.current_index) li.className = 'now';
    $('guideList').appendChild(li);
  });
}

// ================================================================= direct source
let band = null;
let sim = null;
let log = [];
const MOST_ROWS = 200000;
let samplesThisSecond = 0;
let rate = 0;
const peaks = [];
let lifetime = null;

const settings = () => ({
  stepLen: Number($('stepLen').value) || 0.7,
  accThr: Number($('accThr').value) || 1.12,
  snap: $('snap').checked,
  flip: $('flip').checked,
  stepSource: $('stepSource').value,
  ...(sim ? { quietGyro: 40 } : {}),   // the pretend band never holds perfectly still
});
let trail = new Trail(settings());
for (const id of ['stepLen', 'accThr', 'snap', 'flip', 'stepSource']) {
  $(id).addEventListener('change', () => Object.assign(trail.o, settings()));
}
function record(kind, t, f) {
  if (log.length < MOST_ROWS) log.push([kind, t.toFixed(4), f.ax ?? '', f.ay ?? '', f.az ?? '', f.gx ?? '', f.gy ?? '', f.gz ?? '', f.steps ?? '', f.state ?? '']);
}

async function connectDirect() {
  if (socket && socket.readyState <= 1) socket.close();
  const number = Number($('band').value);
  try {
    $('connect').disabled = true;
    if ($('pretend').checked) {
      say('Connecting to a pretend band (not real sensing)...');
      sim = new SimTransport(number, { autoTap: false });
      band = await Band.connect(number, { transport: sim });
      sim.setActivity('walk', { cadence: 110 });
      $('stepSource').value = 'band';     // the pretend band's motion has no footsteps in it
      Object.assign(trail.o, settings());
    } else {
      say('Pick your band in the list. Double-tap it first if it is not there. (Stop main.py first: one connection at a time.)');
      band = await Band.connect(number, { autoReconnect: true });
    }
    band.on('motion', (m) => {
      samplesThisSecond += 1;
      const t = m.t / 1000;
      const before = { acc: trail.accSteps, turns: trail.turns.length, cal: trail.calibrated };
      trail.motion(t, m.ax, m.ay, m.az, m.gx, m.gy, m.gz);
      if (trail.running) record('motion', t, m);
      peaks.push([t, trail.accS ?? Math.hypot(m.ax, m.ay, m.az)]);
      while (peaks.length && t - peaks[0][0] > 2) peaks.shift();
      if (!before.cal && trail.calibrated) dbg(`calibrated: gyro bias ${trail.bias.toFixed(2)} deg/s. Walk now.`);
      if (trail.turns.length > before.turns) { const q = trail.turns.at(-1); dbg(`turn ${Math.abs(q.deg) >= 180 ? 'U-TURN' : q.deg < 0 ? 'LEFT' : 'RIGHT'}`); }
      syncDirect();
    });
    band.on('activity', (e) => {
      const t = e.t / 1000;
      if (lifetime != null && e.steps !== lifetime) dbg(`band steps ${lifetime} -> ${e.steps}, ${e.state}`);
      lifetime = e.steps;
      trail.activity(t, e.steps, e.state);
      if (trail.running) record('activity', t, e);
      syncDirect();
    });
    band.on('reconnecting', () => setLink('reconnecting...', false));
    band.on('reconnected', () => setLink(`${band.name}${sim ? ' (pretend)' : ''}`, true));
    band.on('disconnect', (e) => { setLink('disconnected', false); say(`Disconnected (${e.reason}). Double-tap the band and connect again.`, true); $('connect').disabled = false; });
    await band.configure({ motion: 50, sensors: 'both', activity: 'fastest' });
    await band.setLed('#ffffff', { brightness: 0.2 });
    setLink(`${band.name}${sim ? ' (pretend)' : ''}`, true);
    $('start').disabled = false;
    dbg(`connected directly to ${band.name}${sim ? ' (PRETEND)' : ''}`);
    say(sim ? 'PRETEND band connected. This is simulated data, not your walk.' : `Connected to ${band.name}. Press Start route, hold your arm still a moment, then walk.`);
  } catch (e) {
    $('connect').disabled = false;
    say(e.message, true);
  }
}

function syncDirect() {
  Object.assign(view, {
    points: trail.points, turns: trail.turns, x: trail.x, y: trail.y, facing: trail.shownHeading,
    steps: trail.steps, accSteps: trail.accSteps, bandSteps: trail.bandSteps, distance: trail.distance,
    state: trail.state, running: trail.running, calibrated: trail.calibrated, bias: trail.calibrated ? trail.bias : null,
  });
}

async function startDirect() {
  log = [];
  trail = new Trail(settings());
  trail.start();
  syncDirect();
  $('start').disabled = true; $('stop').disabled = false; $('save').disabled = true;
  try { await band.setLed('#00c853', { pattern: 'breathe', period: 2000 }); } catch { /* mic on: light is locked */ }
  dbg(`route started (steps from: ${trail.o.stepSource}). Hold still until it says recording.`);
  say('Hold your arm still for a moment while the gyro calibrates... then walk.');
}

async function stopDirect() {
  trail.stop();
  syncDirect();
  $('start').disabled = false; $('stop').disabled = true; $('save').disabled = log.length === 0;
  try { await band.setLed('#ffffff', { brightness: 0.2 }); } catch { /* ignore */ }
  dbg(`route stopped: ${trail.steps} steps, ${trail.distance.toFixed(1)} m`);
  say(`Stopped. ${trail.steps} steps, ${trail.distance.toFixed(1)} m. Download the log to replay or tune it.`);
}

const simTurn = (dps) => () => sim?.playMotion(() => ({ ax: 0, ay: 0, az: 1, gx: 0, gy: 0, gz: dps }), { seconds: 1 });
$('simLeft').onclick = simTurn(90);
$('simRight').onclick = simTurn(-90);
setInterval(() => { rate = samplesThisSecond; samplesThisSecond = 0; }, 1000);

// ================================================================= drawing
function resize() {
  const r = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(r.width * dpr);
  canvas.height = Math.round(r.height * dpr);
  pen.setTransform(dpr, 0, 0, dpr, 0, 0);
}
new ResizeObserver(resize).observe(canvas);

function niceStep(pxPerM) {
  for (const s of [0.5, 1, 2, 5, 10, 20, 50, 100, 200]) if (s * pxPerM >= 50) return s;
  return 500;
}
function line(pts, widths) {
  if (pts.length < 2) return;
  pen.lineJoin = 'round'; pen.lineCap = 'round';
  for (const [w, c, dash] of widths) {
    pen.setLineDash(dash || []);
    pen.strokeStyle = c; pen.lineWidth = w;
    pen.beginPath();
    pts.forEach((p, i) => (i ? pen.lineTo(X(p.x), Y(p.y)) : pen.moveTo(X(p.x), Y(p.y))));
    pen.stroke();
  }
  pen.setLineDash([]);
}
let X = (x) => x, Y = (y) => y;

function draw() {
  const W = canvas.clientWidth, H = canvas.clientHeight;
  pen.clearRect(0, 0, W, H);
  const v = view;
  const all = [...v.points, ...v.back, ...v.waypoints, ...v.landmarks.filter((l) => typeof l.x === 'number')];
  let minX = 0, maxX = 0, minY = 0, maxY = 0;
  for (const p of all) { minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y); }
  const spanX = Math.max(10, maxX - minX), spanY = Math.max(10, maxY - minY);
  const pad = 50;
  const s = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
  const mx = (minX + maxX) / 2, my = (minY + maxY) / 2;
  X = (x) => W / 2 + (x - mx) * s;
  Y = (y) => H / 2 - (y - my) * s;

  // grid
  const step = niceStep(s);
  pen.strokeStyle = 'rgba(60,80,110,0.10)'; pen.lineWidth = 1;
  pen.beginPath();
  for (let gx = Math.floor((mx - W / 2 / s) / step) * step; gx <= mx + W / 2 / s; gx += step) { pen.moveTo(X(gx), 0); pen.lineTo(X(gx), H); }
  for (let gy = Math.floor((my - H / 2 / s) / step) * step; gy <= my + H / 2 / s; gy += step) { pen.moveTo(0, Y(gy)); pen.lineTo(W, Y(gy)); }
  pen.stroke();

  line(v.points, [[11, '#ffffff'], [6, '#1a73e8']]);                    // the blue line: your walk
  line(v.waypoints, [[5, 'rgba(10,165,194,0.9)', [10, 8]]]);            // planned way back
  line(v.back, [[11, '#ffffff'], [6, '#0aa5c2']]);                      // walked while guided back

  for (const t of v.turns) {
    pen.fillStyle = '#ffffff'; pen.strokeStyle = '#5d6676'; pen.lineWidth = 2;
    pen.beginPath(); pen.arc(X(t.x), Y(t.y), 5, 0, Math.PI * 2); pen.fill(); pen.stroke();
    pen.fillStyle = '#5d6676'; pen.font = '12px system-ui, sans-serif';
    pen.fillText(Math.abs(t.deg) >= 180 ? 'U-turn' : t.deg < 0 ? 'left' : 'right', X(t.x) + 9, Y(t.y) - 8);
  }
  for (const l of v.landmarks) {
    if (typeof l.x !== 'number') continue;
    pen.fillStyle = '#8e44ad'; pen.strokeStyle = '#fff'; pen.lineWidth = 3;
    pen.beginPath(); pen.arc(X(l.x), Y(l.y), 8, 0, Math.PI * 2); pen.fill(); pen.stroke();
    pen.fillStyle = '#4a235a'; pen.font = '600 12.5px system-ui, sans-serif';
    pen.fillText(l.label, X(l.x) + 12, Y(l.y) + 4);
  }
  pen.fillStyle = '#1e8e3e'; pen.strokeStyle = '#fff'; pen.lineWidth = 3;
  pen.beginPath(); pen.arc(X(0), Y(0), 8, 0, Math.PI * 2); pen.fill(); pen.stroke();
  pen.fillStyle = '#1b2230'; pen.font = '600 12px system-ui, sans-serif'; pen.fillText('Start', X(0) + 12, Y(0) + 16);

  // you: dot + cone for where you face now
  const h = ((v.facing || 0) * Math.PI) / 180;
  const ang = Math.atan2(-Math.cos(h), Math.sin(h));
  const cx = X(v.x), cy = Y(v.y);
  if (v.running && v.calibrated) {
    pen.fillStyle = 'rgba(26,115,232,0.18)';
    pen.beginPath(); pen.moveTo(cx, cy); pen.arc(cx, cy, 46, ang - 0.5, ang + 0.5); pen.closePath(); pen.fill();
  }
  pen.fillStyle = v.uncertain ? '#d93025' : '#1a73e8'; pen.strokeStyle = '#fff'; pen.lineWidth = 3;
  pen.beginPath(); pen.arc(cx, cy, 8, 0, Math.PI * 2); pen.fill(); pen.stroke();

  pen.strokeStyle = '#1b2230'; pen.lineWidth = 2;
  pen.beginPath(); pen.moveTo(16, H - 18); pen.lineTo(16 + step * s, H - 18); pen.stroke();
  pen.fillStyle = '#1b2230'; pen.font = '12px system-ui, sans-serif'; pen.fillText(`${step} m`, 16, H - 24);
  if (source() === 'direct' && sim) { pen.fillStyle = '#d93025'; pen.font = '600 13px system-ui, sans-serif'; pen.fillText('PRETEND BAND: SIMULATED DATA', 16, 22); }

  // panels
  $('steps').textContent = v.steps;
  $('accSteps').textContent = v.accSteps ?? '–';
  $('bandSteps').textContent = v.bandSteps ?? '–';
  $('dist').textContent = `${v.distance.toFixed(1)} m`;
  $('head').textContent = v.running && v.calibrated ? `${Math.round(v.facing)}°` : '–';
  $('state').textContent = v.state;
  $('rate').textContent = rate;
  $('bias').textContent = v.bias == null ? '–' : `${(+v.bias).toFixed(2)} °/s`;
  $('lifetime').textContent = lifetime ?? '–';
  const pk = peaks.length ? Math.max(...peaks.map((p) => p[1])) : null;
  $('mag').textContent = pk == null ? '–' : `${peaks.at(-1)[1].toFixed(2)} / ${pk.toFixed(2)} g`;
  const st = $('status');
  if (v.running && !v.calibrated) { st.textContent = 'calibrating: hold still'; st.className = 'pill cal'; }
  else if (v.running && v.uncertain) { st.textContent = 'recording, unsure'; st.className = 'pill bad'; }
  else if (v.running) { st.textContent = 'recording'; st.className = 'pill live'; }
  else { st.textContent = 'not recording'; st.className = 'pill'; }
  requestAnimationFrame(draw);
}
resize();
requestAnimationFrame(draw);

// ?ws_port=8790 in the address: connect to main.py straight away (main.py prints this link).
{
  const q = new URLSearchParams(location.search);
  if (q.get('ws_port')) { $('wsPort').value = q.get('ws_port'); $('source').value = 'backend'; applySource(); connectBackend(); }
  if (q.get('source') === 'direct') { $('source').value = 'direct'; applySource(); }
}
