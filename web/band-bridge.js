// Connect the band in Chrome (Web Bluetooth, like the kit's dashboard) and relay it to the
// Python app over the page's local WebSocket. Python keeps tracking, voice, keys and
// guidance; this page only carries band data in and LED / microphone commands out.
//
// Rules from vexo-open-kit/AGENTS.md: only the team's band (the number comes from Python's
// config.BAND), connect only from a click, and show problems on the page.
import { Band } from '../vexo-open-kit/js/src/index.js';

const $ = (id) => document.getElementById(id);
const btn = $('bridge-btn');
const label = $('bridge-label');
let ws = null;
let band = null;
let bandNumber = null;

function wsUrl() {
  const params = new URLSearchParams(location.search);
  const custom = params.get('ws');
  if (custom && (custom.startsWith('ws://') || custom.startsWith('wss://'))) return custom;
  return 'ws://127.0.0.1:' + (params.get('ws_port') || '8765');
}

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function show(text, level) {
  label.textContent = text;
  btn.dataset.level = level || '';
}

function b64(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

function openSocket() {
  ws = new WebSocket(wsUrl());
  ws.addEventListener('message', (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === 'band_number') {
      bandNumber = Number(msg.band) || null;
      btn.disabled = !bandNumber || !!band;
      if (!band) show(bandNumber ? 'Connect band ' + bandNumber : 'Band is connected by the app', bandNumber ? '' : 'ok');
    } else if (msg.type === 'band_cmd' && band) {
      runCommand(msg).catch(() => { /* e.g. LED locked while the mic is on: Python retries */ });
    }
  });
  ws.addEventListener('close', () => setTimeout(openSocket, 1500));
}

async function runCommand(msg) {
  const a = msg.args || {};
  if (msg.op === 'configure') {
    await band.configure(a);
  } else if (msg.op === 'setLed') {
    await band.setLed(a.color || '#ffffff', { brightness: a.brightness ?? 1, pattern: a.pattern || 'solid',
                                               period: a.period || 1000 });
  } else if (msg.op === 'ledOff') {
    await band.ledOff();
  }
}

function relay(b) {
  const s = (ms) => (typeof ms === 'number' ? ms / 1000 : Date.now() / 1000);   // Python uses seconds
  b.on('motion', (m) => send({ type: 'band_event', kind: 'motion', time: s(m.time),
    ax: m.ax, ay: m.ay, az: m.az, gx: m.gx, gy: m.gy, gz: m.gz }));
  b.on('activity', (e) => send({ type: 'band_event', kind: 'activity', time: s(e.time),
    steps: e.steps, cadence: e.cadence, state: e.state, motion: e.motion }));
  b.on('event', (e) => send({ type: 'band_event', kind: 'event', time: s(e.time), event: e.kind, arg: e.arg ?? null }));
  b.on('battery', (e) => send({ type: 'band_event', kind: 'battery', percent: e.percent,
    millivolts: e.millivolts, state: e.state }));
  b.on('temperature', (e) => send({ type: 'band_event', kind: 'temperature', time: s(e.time), celsius: e.celsius }));
  b.on('audio', (e) => send({ type: 'band_event', kind: 'audio', seq: e.seq, opus: b64(e.opus) }));
  b.on('reconnecting', () => { show('Reconnecting...', 'warn'); send({ type: 'band_status', status: 'reconnecting' }); });
  b.on('reconnected', () => { show(b.name, 'ok'); send({ type: 'band_status', status: 'reconnected', name: b.name }); });
  b.on('disconnect', (e) => {
    band = null;
    show('Disconnected - double-tap the band, then connect', 'err');
    btn.disabled = false;
    send({ type: 'band_status', status: 'disconnected', reason: e.reason || '' });
  });
}

btn.addEventListener('click', async () => {
  if (band || !bandNumber) return;
  btn.disabled = true;
  show('Pick Vexo-HACK-' + String(bandNumber).padStart(2, '0') + ' in the list...', 'warn');
  try {
    const b = await Band.connect(bandNumber, { autoReconnect: true });   // only the team's band
    if (b.number !== bandNumber) { await b.disconnect(); throw new Error('That is not band ' + bandNumber + '.'); }
    band = b;
    relay(b);
    show(b.name + ' (Chrome)', 'ok');
    send({ type: 'band_status', status: 'connected', name: b.name, firmware: b.info && b.info.firmware });
  } catch (e) {
    show(e.message || String(e), 'err');      // the library's messages say what to do next
    btn.disabled = false;
  }
});

if (!('bluetooth' in navigator)) {
  btn.disabled = true;
  show('Bluetooth needs Chrome or Edge', 'err');
} else {
  btn.disabled = true;
  show('Waiting for the app...', '');
  openSocket();
}
