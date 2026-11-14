// Live trail page: connects to the band in Chrome, tracks the walk, draws it as a blue line.
// Open http://localhost:8000/web/trail.html with the server started in the repo folder.
import { Band, SimTransport } from '../vexo-open-kit/js/src/index.js';
import { Trail } from './trail-core.js';

const $ = (id) => document.getElementById(id);
const canvas = $('map');
const pen = canvas.getContext('2d');

let band = null;
let sim = null;
let log = [];                       // rows for "Download log"
const MOST_ROWS = 200000;           // ~1 hour of motion at 50/s
let samplesThisSecond = 0;
let rate = 0;

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

function say(text, warn = false) {
  $('msg').textContent = text;
  $('msg').className = warn ? 'warn' : '';
}
function setLink(text, live) {
  $('link').textContent = text;
  $('link').className = live ? 'pill live' : 'pill';
}
function record(kind, t, f) {
  if (log.length < MOST_ROWS) log.push([kind, t.toFixed(4), f.ax ?? '', f.ay ?? '', f.az ?? '', f.gx ?? '', f.gy ?? '', f.gz ?? '', f.steps ?? '', f.state ?? '']);
}

$('pretend').addEventListener('change', () => { $('simbtns').hidden = !$('pretend').checked; });

// ---- debug log: every step, turn and band reading, readable on the page and downloadable
const dbgLines = [];
const MOST_DBG = 5000;
const dbgState = { actCount: 0, lastLifetime: null, cadence: null, bandState: null, lastActAt: null, loggedState: null, mag: null };
const peaks = [];                   // [t, smoothed |a|] over the last 2 s
const wall = () => new Date().toTimeString().slice(0, 8);
function dbg(t, text) {
  const line = `${wall()}  t=${t == null ? '-' : t.toFixed(2)}  ${text}`;
  dbgLines.push(line);
  if (dbgLines.length > MOST_DBG) dbgLines.shift();
  const box = $('dbg');
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 4;
  box.textContent = dbgLines.slice(-300).join('\n');
  if (atBottom) box.scrollTop = box.scrollHeight;
}
$('saveDbg').onclick = () => {
  const settingsLine = `settings: ${JSON.stringify(settings())}\n`;
  const blob = new Blob([settingsLine + dbgLines.join('\n') + '\n'], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `debug-${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}.txt`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};
setInterval(() => {
  $('actCount').textContent = dbgState.actCount;
  $('lifetime').textContent = dbgState.lastLifetime ?? '–';
  $('cadence').textContent = dbgState.cadence == null ? '–' : `${dbgState.cadence}/min`;
  $('actAge').textContent = dbgState.lastActAt == null ? 'never' : `${((performance.now() - dbgState.lastActAt) / 1000).toFixed(1)} s ago`;
  $('mag').textContent = dbgState.mag == null ? '–' : `${dbgState.mag.toFixed(2)} g`;
  const pk = peaks.length ? Math.max(...peaks.map((p) => p[1])) : null;
  $('peak').textContent = pk == null ? '–' : `${pk.toFixed(2)} g`;
}, 250);

$('connect').onclick = async () => {
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
      say('Pick your band in the list. Double-tap it first if it is not there.');
      band = await Band.connect(number, { autoReconnect: true });
    }
    band.on('motion', (m) => {
      samplesThisSecond += 1;
      const t = m.t / 1000;
      const before = { acc: trail.accSteps, turns: trail.turns.length, cal: trail.calibrated, steps: trail.steps };
      trail.motion(t, m.ax, m.ay, m.az, m.gx, m.gy, m.gz);
      if (trail.running) record('motion', t, m);
      const mag = Math.hypot(m.ax, m.ay, m.az);
      dbgState.mag = trail.accS ?? mag;
      peaks.push([t, trail.accS ?? mag]);
      while (peaks.length && t - peaks[0][0] > 2) peaks.shift();
      if (!before.cal && trail.calibrated) dbg(t, `calibrated: gyro bias ${trail.bias.toFixed(2)} deg/s. Walk now.`);
      if (trail.accSteps > before.acc) dbg(t, `motion step #${trail.accSteps} (smoothed |a| ${trail.accS.toFixed(2)} g)${trail.o.stepSource === 'accel' ? ' -> map' : ''}`);
      if (trail.turns.length > before.turns) { const q = trail.turns.at(-1); dbg(t, `turn ${Math.abs(q.deg) >= 180 ? 'U-TURN' : q.deg < 0 ? 'LEFT' : 'RIGHT'} ${Math.abs(q.deg)} deg, walking heading now ${Math.round(trail.heading)}`); }
    });
    band.on('activity', (e) => {
      const t = e.t / 1000;
      dbgState.actCount += 1;
      const prev = dbgState.lastLifetime;
      dbgState.lastLifetime = e.steps; dbgState.cadence = e.cadence; dbgState.bandState = e.state; dbgState.lastActAt = performance.now();
      const mapBefore = trail.steps;
      trail.activity(t, e.steps, e.state);
      if (trail.running) record('activity', t, e);
      if (prev == null) dbg(t, `first activity reading: band lifetime steps ${e.steps}, state ${e.state}`);
      else if (e.steps !== prev) dbg(t, `band steps ${prev} -> ${e.steps} (+${e.steps - prev}), cadence ${e.cadence}/min, ${e.state}${trail.steps > mapBefore ? ' -> map' : trail.running ? (trail.calibrated ? '' : ' (ignored: calibrating)') : ' (ignored: route not started)'}`);
      else if (e.state !== dbgState.loggedState) dbg(t, `band state: ${e.state} (steps unchanged at ${e.steps})`);
      dbgState.loggedState = e.state;
    });
    band.on('reconnecting', () => setLink('reconnecting...', false));
    band.on('reconnected', () => setLink(`${band.name}${sim ? ' (pretend)' : ''}`, true));
    band.on('disconnect', (e) => { setLink('disconnected', false); say(`Disconnected (${e.reason}). Double-tap the band and connect again.`, true); $('connect').disabled = false; });
    await band.configure({ motion: 50, sensors: 'both', activity: 'fastest' });
    await band.setLed('#ffffff', { brightness: 0.2 });
    setLink(`${band.name}${sim ? ' (pretend)' : ''}`, true);
    dbg(null, `connected to ${band.name}${sim ? ' (PRETEND)' : ''}, firmware ${band.info?.firmware}, streams: motion 50/s, activity fastest`);
    $('start').disabled = false;
    say(sim ? 'PRETEND band connected. This is simulated data, not your walk.' : `Connected to ${band.name}. Press Start route, hold your arm still a moment, then walk.`);
  } catch (e) {
    $('connect').disabled = false;
    say(e.message, true);
  }
};

$('start').onclick = async () => {
  log = [];
  trail = new Trail(settings());
  trail.start();
  $('start').disabled = true; $('stop').disabled = false; $('save').disabled = true;
  try { await band.setLed('#00c853', { pattern: 'breathe', period: 2000 }); } catch { /* mic on: light is locked */ }
  dbg(null, `route started (steps from: ${trail.o.stepSource}, step length ${trail.o.stepLen} m). Hold still until it says Recording.`);
  say('Hold your arm still for a moment while the gyro calibrates... then walk.');
};

$('stop').onclick = async () => {
  trail.stop();
  $('start').disabled = false; $('stop').disabled = true; $('save').disabled = log.length === 0;
  try { await band.setLed('#ffffff', { brightness: 0.2 }); } catch { /* ignore */ }
  dbg(null, `route stopped: map ${trail.steps} steps, band counter ${trail.bandSteps}, motion detector ${trail.accSteps}, ${trail.distance.toFixed(1)} m`);
  say(`Stopped. ${trail.steps} steps, ${trail.distance.toFixed(1)} m. Download the log to replay or tune it.`);
};

$('clear').onclick = () => {
  const wasRunning = trail.running;
  trail = new Trail(settings());
  log = [];
  if (wasRunning) { $('start').disabled = !band; $('stop').disabled = true; }
  say('Cleared.');
};

$('save').onclick = () => {
  const header = 'kind,t,ax,ay,az,gx,gy,gz,steps,state\n';
  const blob = new Blob([header + log.map((r) => r.join(',')).join('\n') + '\n'], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `walk-${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}${sim ? '-PRETEND' : ''}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};

const simTurn = (dps) => () => sim?.playMotion(() => ({ ax: 0, ay: 0, az: 1, gx: 0, gy: 0, gz: dps }), { seconds: 1 });
$('simLeft').onclick = simTurn(90);
$('simRight').onclick = simTurn(-90);

setInterval(() => { rate = samplesThisSecond; samplesThisSecond = 0; }, 1000);

// ---- drawing ---------------------------------------------------------------------
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

function draw() {
  const W = canvas.clientWidth, H = canvas.clientHeight;
  pen.clearRect(0, 0, W, H);
  const pts = trail.points;
  let minX = 0, maxX = 0, minY = 0, maxY = 0;
  for (const p of pts) { minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y); }
  const spanX = Math.max(10, maxX - minX), spanY = Math.max(10, maxY - minY);
  const pad = 50;
  const s = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
  const mx = (minX + maxX) / 2, my = (minY + maxY) / 2;
  const X = (x) => W / 2 + (x - mx) * s;
  const Y = (y) => H / 2 - (y - my) * s;

  // grid
  const step = niceStep(s);
  pen.strokeStyle = 'rgba(60,80,110,0.10)'; pen.lineWidth = 1;
  pen.beginPath();
  for (let gx = Math.floor((mx - W / 2 / s) / step) * step; gx <= mx + W / 2 / s; gx += step) { pen.moveTo(X(gx), 0); pen.lineTo(X(gx), H); }
  for (let gy = Math.floor((my - H / 2 / s) / step) * step; gy <= my + H / 2 / s; gy += step) { pen.moveTo(0, Y(gy)); pen.lineTo(W, Y(gy)); }
  pen.stroke();

  // the blue line
  if (pts.length > 1) {
    pen.lineJoin = 'round'; pen.lineCap = 'round';
    for (const [w, c] of [[11, '#ffffff'], [6, '#1a73e8']]) {
      pen.strokeStyle = c; pen.lineWidth = w;
      pen.beginPath();
      pts.forEach((p, i) => (i ? pen.lineTo(X(p.x), Y(p.y)) : pen.moveTo(X(p.x), Y(p.y))));
      pen.stroke();
    }
  }
  // turns
  for (const t of trail.turns) {
    pen.fillStyle = '#ffffff'; pen.strokeStyle = '#5d6676'; pen.lineWidth = 2;
    pen.beginPath(); pen.arc(X(t.x), Y(t.y), 5, 0, Math.PI * 2); pen.fill(); pen.stroke();
    pen.fillStyle = '#5d6676'; pen.font = '12px system-ui, sans-serif';
    pen.fillText(Math.abs(t.deg) >= 180 ? 'U-turn' : t.deg < 0 ? 'left' : 'right', X(t.x) + 9, Y(t.y) - 8);
  }
  // start
  pen.fillStyle = '#1e8e3e'; pen.strokeStyle = '#fff'; pen.lineWidth = 3;
  pen.beginPath(); pen.arc(X(0), Y(0), 8, 0, Math.PI * 2); pen.fill(); pen.stroke();
  pen.fillStyle = '#1b2230'; pen.font = '600 12px system-ui, sans-serif'; pen.fillText('Start', X(0) + 12, Y(0) + 4);

  // you: dot + heading cone
  const h = (trail.shownHeading * Math.PI) / 180;
  const ang = Math.atan2(-Math.cos(h), Math.sin(h));
  const cx = X(trail.x), cy = Y(trail.y);
  pen.fillStyle = 'rgba(26,115,232,0.18)';
  pen.beginPath(); pen.moveTo(cx, cy); pen.arc(cx, cy, 46, ang - 0.5, ang + 0.5); pen.closePath(); pen.fill();
  pen.fillStyle = '#1a73e8'; pen.strokeStyle = '#fff'; pen.lineWidth = 3;
  pen.beginPath(); pen.arc(cx, cy, 8, 0, Math.PI * 2); pen.fill(); pen.stroke();

  // scale bar
  pen.strokeStyle = '#1b2230'; pen.lineWidth = 2;
  pen.beginPath(); pen.moveTo(16, H - 18); pen.lineTo(16 + step * s, H - 18); pen.stroke();
  pen.fillStyle = '#1b2230'; pen.font = '12px system-ui, sans-serif'; pen.fillText(`${step} m`, 16, H - 24);
  if (sim) { pen.fillStyle = '#d93025'; pen.font = '600 13px system-ui, sans-serif'; pen.fillText('PRETEND BAND: SIMULATED DATA', 16, 22); }

  // numbers
  $('steps').textContent = trail.steps;
  $('bandSteps').textContent = trail.bandSteps;
  $('accSteps').textContent = trail.accSteps;
  $('dist').textContent = `${trail.distance.toFixed(1)} m`;
  $('head').textContent = `${Math.round(trail.shownHeading)}°`;
  $('state').textContent = trail.state;
  $('rate').textContent = rate;
  const st = $('status');
  if (trail.calibrating) { st.textContent = 'calibrating: stand still'; st.className = 'pill cal'; }
  else if (trail.running) { st.textContent = 'recording'; st.className = 'pill live'; }
  else { st.textContent = 'idle'; st.className = 'pill'; }
  if (trail.running && trail.calibrated && $('msg').textContent.startsWith('Hold your arm still')) say('Recording. Walk!');
  requestAnimationFrame(draw);
}
resize();
requestAnimationFrame(draw);
