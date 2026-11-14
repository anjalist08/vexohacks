// The trail page's Band card: is the band connected, how, and how full is its battery.
// Listens to the backend messages that trail.js announces ('trail-backend' events):
//   {type:'link', status}                               connected / reconnecting / reconnected / disconnected
//   {type:'band_metric', kind:'info', name, transport}  sent when the band connects
//   {type:'band_metric', kind:'battery', percent, millivolts, state}
//   {type:'band_metric', kind:'temperature', celsius}
const $ = (id) => document.getElementById(id);
let lastSeen = 0;          // when anything was last heard from the band (ms)
let link = 'not connected';
let battery = null;

function renderConn() {
  const pill = $('bandConn');
  const up = link === 'connected' || link === 'reconnected';
  const stale = up && lastSeen && Date.now() - lastSeen > 15000;
  pill.textContent = stale ? 'no data' : up ? 'connected' : link === 'reconnecting' ? 'reconnecting…'
                   : link === 'replay' ? 'replay' : link === 'simulated' ? 'simulated' : 'not connected';
  pill.className = 'pill ' + (stale ? 'cal' : up ? 'live' : link === 'reconnecting' ? 'cal' : 'bad');
  $('bandSeen').textContent = !lastSeen ? '' :
    `Last heard ${Math.max(0, Math.round((Date.now() - lastSeen) / 1000))} s ago.`;
}

function renderBattery() {
  if (!battery) return;
  const p = Math.max(0, Math.min(100, Number(battery.percent) || 0));
  const fill = $('batFill');
  fill.style.width = Math.max(2, p) + '%';
  fill.className = p <= 15 ? 'low' : p <= 35 ? 'mid' : '';
  $('batPct').textContent = p + '%';
  const charging = battery.state === 'charging' || battery.state === 'charged';
  const volts = battery.millivolts ? ` · ${(battery.millivolts / 1000).toFixed(2)} V` : '';
  $('batState').textContent = (battery.state === 'charged' ? 'charged' : charging ? 'charging' : 'on battery') + volts;
  const warn = $('bandWarn');
  warn.hidden = !(p <= 15 && !charging);
  warn.textContent = 'Battery low: plug the band in before the demo. The light is dimmed on low battery.';
}

function onMessage(m) {
  m = m || {};
  if (m.type === 'link') {
    link = m.status || 'not connected';
    if (link === 'connected' || link === 'reconnected') lastSeen = Date.now();
    renderConn();
  } else if (m.type === 'mode') {
    if (m.mode === 'REPLAY') link = 'replay';
    else if (m.mode === 'SIMULATION') link = 'simulated';
    renderConn();
  } else if (m.type === 'band_metric') {
    lastSeen = Math.max(lastSeen, (Number(m.time) || Date.now() / 1000) * 1000);
    if (m.kind === 'info') {
      $('bandName').textContent = m.name || 'Vexo band';
      $('bandVia').textContent = m.transport || '–';
    } else if (m.kind === 'battery') {
      battery = m;
      renderBattery();
    } else if (m.kind === 'temperature' && typeof m.celsius === 'number') {
      $('bandTemp').textContent = `chip ${Math.round(m.celsius)} °C`;
    }
    renderConn();
  } else if (m.type === 'point') {        // a new step means the band is talking
    if (link === 'connected' || link === 'reconnected') lastSeen = Date.now();
  }
}
window.addEventListener('trail-backend', (ev) => onMessage(ev.detail));
(window.trailBackendHistory || []).forEach(onMessage);   // what arrived before this script loaded

setInterval(renderConn, 1000);
renderConn();
