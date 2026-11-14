// Replay a logged walk (CSV from the trail page's "Download log") through web/trail-core.js
// and print where it ends. For tuning on real data without walking again.
//   node tools/replay_trail.mjs data/logs/walk1-hallway-loop.csv [band|accel] [stepLen] [accThr]
import { readFileSync } from 'node:fs';
import { Trail } from '../web/trail-core.js';

const [file, stepSource = 'accel', stepLen = '0.7', accThr = '1.12'] = process.argv.slice(2);
if (!file) { console.log('usage: node tools/replay_trail.mjs FILE.csv [band|accel] [stepLen] [accThr]'); process.exit(1); }
const lines = readFileSync(file, 'utf8').trim().split('\n');
const cols = lines[0].split(',');
const rows = lines.slice(1).map((l) => Object.fromEntries(l.split(',').map((v, i) => [cols[i], v])));
const tr = new Trail({ stepSource, stepLen: Number(stepLen), accThr: Number(accThr) });
tr.start(Number(rows[0].t));
for (const r of rows) {
  const t = Number(r.t);
  if (r.kind === 'motion') tr.motion(t, +r.ax, +r.ay, +r.az, +r.gx, +r.gy, +r.gz);
  else if (r.kind === 'activity') tr.activity(t, Number(r.steps), r.state);
}
const f = (v) => v.toFixed(1);
const dir = (h) => 'NESW'[((Math.round(h / 90) % 4) + 4) % 4];
const segs = [];
for (let i = 1; i < tr.points.length; i++) {
  const d = dir(tr.points[i].h);
  if (segs.length && segs.at(-1)[0] === d) segs.at(-1)[1] += 1; else segs.push([d, 1]);
}
console.log(`route (direction + steps, N = the way you faced at start): ${segs.map(([d, n]) => d + n).join(' ')}`);
console.log(`steps used ${tr.steps} (band counter ${tr.bandSteps}, motion ${tr.accSteps}), path ${f(tr.distance)} m`);
console.log(`gyro bias at end ${tr.bias.toFixed(2)} deg/s, turns: ${tr.turns.map((q) => (q.deg < 0 ? 'L' : 'R')).join(' ')}`);
console.log(`ends at x=${f(tr.x)} y=${f(tr.y)}: ${f(Math.hypot(tr.x, tr.y))} m from the start`);
