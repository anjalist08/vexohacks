// Shared by the map page (band-bridge.js) and the trail page (trail-voice.js): relay a band
// connected in Chrome to the Python app, and run the app's commands on it. Times are sent
// in seconds, as Python's kit uses.

function b64(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

export function relayBand(b, send, onState) {
  const s = (ms) => (typeof ms === 'number' ? ms / 1000 : Date.now() / 1000);
  b.on('motion', (m) => send({ type: 'band_event', kind: 'motion', time: s(m.time),
    ax: m.ax, ay: m.ay, az: m.az, gx: m.gx, gy: m.gy, gz: m.gz }));
  b.on('activity', (e) => send({ type: 'band_event', kind: 'activity', time: s(e.time),
    steps: e.steps, cadence: e.cadence, state: e.state, motion: e.motion }));
  b.on('event', (e) => send({ type: 'band_event', kind: 'event', time: s(e.time), event: e.kind, arg: e.arg ?? null }));
  b.on('battery', (e) => send({ type: 'band_event', kind: 'battery', percent: e.percent,
    millivolts: e.millivolts, state: e.state }));
  b.on('temperature', (e) => send({ type: 'band_event', kind: 'temperature', time: s(e.time), celsius: e.celsius }));
  b.on('audio', (e) => send({ type: 'band_event', kind: 'audio', seq: e.seq, opus: b64(e.opus) }));
  b.on('reconnecting', () => { onState('reconnecting'); send({ type: 'band_status', status: 'reconnecting' }); });
  b.on('reconnected', () => { onState('reconnected'); send({ type: 'band_status', status: 'reconnected', name: b.name }); });
  b.on('disconnect', (e) => { onState('disconnected'); send({ type: 'band_status', status: 'disconnected', reason: e.reason || '' }); });
}

export async function runBandCommand(band, msg) {
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
