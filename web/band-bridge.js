// Connect the band in Chrome (Web Bluetooth, like the kit's dashboard) and relay it to the
// Python app over the page's local WebSocket. Python keeps tracking, voice, keys and
// guidance; this page only carries band data in and LED / microphone commands out.
//
// Rules from vexo-open-kit/AGENTS.md: only the team's band (the number comes from Python's
// config.BAND), connect only from a click, and show problems on the page.
import { Band } from '../vexo-open-kit/js/src/index.js';
import { relayBand, runBandCommand } from './band-relay.js';

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
      runBandCommand(band, msg).catch(() => { /* e.g. LED locked while the mic is on: Python retries */ });
    }
  });
  ws.addEventListener('close', () => setTimeout(openSocket, 1500));
}

btn.addEventListener('click', async () => {
  if (band || !bandNumber) return;
  btn.disabled = true;
  show('Pick Vexo-HACK-' + String(bandNumber).padStart(2, '0') + ' in the list...', 'warn');
  try {
    const b = await Band.connect(bandNumber, { autoReconnect: true });   // only the team's band
    if (b.number !== bandNumber) { await b.disconnect(); throw new Error('That is not band ' + bandNumber + '.'); }
    band = b;
    relayBand(b, send, (state) => {
      if (state === 'reconnecting') show('Reconnecting...', 'warn');
      else if (state === 'reconnected') show(b.name, 'ok');
      else if (state === 'disconnected') {
        band = null;
        show('Disconnected - double-tap the band, then connect', 'err');
        btn.disabled = false;
      }
    });
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
