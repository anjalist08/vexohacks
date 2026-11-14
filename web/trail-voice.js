// Voice controls for the trail page (backend mode): Talk / Stop, live status, "Try saying"
// suggestions, and the Chrome Bluetooth button for main.py --bridge.
//
// trail.js stays in charge of the map and its WebSocket. It announces every backend message
// as a 'trail-backend' event and offers window.trailBackend.send / .command, used here.
import { Band } from '../vexo-open-kit/js/src/index.js';
import { relayBand, runBandCommand } from './band-relay.js';

const $ = (id) => document.getElementById(id);
const talkBtn = $('talkBtn');
const vStatus = $('vStatus');
const vHeard = $('vHeard');
const tryChips = $('tryChips');

const route = { started: false, landmarks: [], guiding: false, target: '' };
let listeningToggle = false;
let watchdog = null;

function status(text, warn) {
  vStatus.textContent = text;
  vStatus.classList.toggle('warn', !!warn);
}

function heard(text, typed) {
  vHeard.replaceChildren();
  if (!text) return;
  vHeard.append(typed ? 'You typed: ' : 'Heard: ');
  const q = document.createElement('q');
  q.textContent = text;
  vHeard.append(q);
}

function setVoice(state, m) {
  clearTimeout(watchdog);
  listeningToggle = state === 'listening' && !!m.toggle;
  const busy = ['starting', 'listening', 'heard', 'thinking'].includes(state);
  talkBtn.disabled = busy && !listeningToggle;
  talkBtn.classList.toggle('listening', state === 'starting' || state === 'listening');
  talkBtn.textContent = listeningToggle ? 'Stop' : busy ? '…' : 'Talk';
  if (state === 'starting') { status('Turning the band\'s microphone on…'); heard(''); }
  else if (state === 'listening') {
    heard('');
    status(m.toggle ? 'Listening — speak now. Double-tap again (or pause) when you\'re done.'
                    : 'Listening — speak now (the band\'s light is blue).');
  } else if (state === 'heard' || state === 'thinking') { status('Understanding what you said…'); heard(m.text, m.typed); }
  else if (state === 'done') status(m.say || 'Done.');
  else if (state === 'nothing' || state === 'error') status(m.text || 'Something went wrong. Try again.', true);
  else status('Double-tap the band (or press Talk), speak, then double-tap again.');
  if (busy) watchdog = setTimeout(() => setVoice('error', { text: 'No answer from the band. Check the terminal, then try again.' }), 25000);
}

function suggestions() {
  const last = route.landmarks.length ? route.landmarks[route.landmarks.length - 1] : 'desk';
  if (route.guiding) return ['how far is it?', `I'm at the ${route.target || last}`, 'stop route'];
  if (route.started) {
    return [`save this spot as the ${route.landmarks.length ? 'kitchen' : 'desk'}`, `where is the ${last}?`,
            'take me back to the start', `take me to the ${last}`, 'stop route'];
  }
  return ['start route'];
}

function renderChips() {
  tryChips.replaceChildren();
  for (const text of suggestions()) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = `“${text}”`;
    b.title = 'Say this after a double-tap, or click to send it as text';
    b.onclick = () => window.trailBackend?.command(text);
    tryChips.append(b);
  }
}

talkBtn.addEventListener('click', () => {
  if (!window.trailBackend?.send({ type: 'talk' })) {
    setVoice('error', { text: 'Not connected to main.py. Press Connect first.' });
    return;
  }
  if (!listeningToggle) setVoice('starting', {});
});

// --- Chrome Bluetooth (main.py --bridge) ----------------------------------------
const bridgeBtn = $('bridgeBtn');
const bridgeLabel = $('bridgeLabel');
let band = null;
let bandNumber = null;

function bridgeShow(text, level) { bridgeLabel.textContent = text; bridgeBtn.dataset.level = level || ''; }

bridgeBtn.addEventListener('click', async () => {
  if (band || !bandNumber) return;
  bridgeBtn.disabled = true;
  bridgeShow(`Pick Vexo-HACK-${String(bandNumber).padStart(2, '0')} in the list…`, '');
  try {
    const b = await Band.connect(bandNumber, { autoReconnect: true });   // only the team's band
    if (b.number !== bandNumber) { await b.disconnect(); throw new Error(`That is not band ${bandNumber}.`); }
    band = b;
    relayBand(b, (msg) => window.trailBackend?.send(msg), (state) => {
      if (state === 'disconnected') { band = null; bridgeBtn.disabled = false; bridgeShow('Reconnect band (Chrome)', 'err'); }
      else bridgeShow(state === 'reconnecting' ? 'Reconnecting…' : `${b.name} (Chrome)`, state === 'reconnecting' ? '' : 'ok');
    });
    bridgeShow(`${b.name} (Chrome)`, 'ok');
    window.trailBackend?.send({ type: 'band_status', status: 'connected', name: b.name });
  } catch (e) {
    bridgeShow(e.message || String(e), 'err');      // the library's messages say what to do next
    bridgeBtn.disabled = false;
  }
});

// --- messages from main.py --------------------------------------------------------
window.addEventListener('trail-backend', (ev) => {
  const m = ev.detail || {};
  switch (m.type) {
    case 'voice': setVoice(m.state || 'ready', m); return;
    case 'band_number':
      bandNumber = Number(m.band) || null;
      bridgeBtn.hidden = !bandNumber || !('bluetooth' in navigator);
      return;
    case 'band_cmd':
      if (band) runBandCommand(band, m).catch(() => { /* LED is locked while the mic is on */ });
      return;
    case 'reset': route.started = true; route.landmarks = []; route.guiding = false; break;
    case 'point': route.started = true; break;
    case 'landmark':
      if (m.label && !route.landmarks.includes(m.label)) route.landmarks.push(m.label);
      route.started = true;
      break;
    case 'guidance': route.guiding = !!m.active; route.target = m.target_name || ''; break;
    default: return;
  }
  renderChips();
});

setVoice('ready', {});
renderChips();
