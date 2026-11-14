// Path tracking for the live trail page, tuned on two real walks (data/logs/walk1-*, walk2-*):
// - gravity = low-pass of the accelerometer; yaw rate = gyro projected onto gravity, so it
//   does not matter how the band sits on the wrist
// - calibration waits for real stillness: the first quietN samples in a row with the gyro
//   below quietGyro set the gyro bias (a fixed 2-second window caught a moving hand)
// - the bias keeps being re-estimated whenever the band is still again
// - heading = gyro integrated all the time, then a rolling MEDIAN over medianS seconds:
//   arm swing on the wrist makes the raw heading swing by up to ~100 degrees, the median
//   keeps the direction you are actually walking
// - with snap, the heading is held on a 90-degree grid (hallways) and only moves to another
//   grid line when the median stays more than snapHyst degrees away for snapHoldS seconds.
//   Errors do not pile up turn after turn, as long as drift stays under ~45 degrees.
// - every step moves the position by stepLen along the heading
// Heading is in degrees, clockwise from the direction you faced at start (0 = ahead, 90 = right).

export const DEFAULTS = {
  stepLen: 0.7,          // metres per step (PLACEHOLDER until measured)
  gravityAlpha: 0.05,    // low-pass weight for gravity, per motion sample
  quietGyro: 6,          // deg/s: total gyro below this...
  quietN: 15,            // ...for this many samples in a row (~0.3 s at 50/s) = band at rest
  biasAlpha: 0.02,
  medianS: 2.0,          // seconds of heading the rolling median covers
  snap: true,            // hold the heading on a 90-degree grid
  snapHyst: 50,          // degrees away from the current grid line before moving
  snapHoldS: 0.5,        // ...for at least this long
  flip: false,           // swap left and right if the band's axes are mirrored
  stepSource: 'accel',   // 'accel' (detector below) or 'band' (band's step counter: starts ~15 s late)
  accThr: 1.12,          // g: smoothed |a| above this is a step...
  accLow: 1.03,          // ...once it has dropped below this since the last step
  accMinGapS: 0.28,      // at most ~3.5 steps a second
  accSmooth: 0.35,       // smoothing weight for |a|
};

const median = (xs) => {
  const v = [...xs].sort((a, b) => a - b);
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
};

export const wrap = (a) => {
  const r = ((((a + 180) % 360) + 360) % 360) - 180;
  return r === -180 ? 180 : r;
};

export class Trail {
  constructor(options = {}) {
    this.o = { ...DEFAULTS, ...options };
    this.reset();
  }

  reset() {
    this.running = false;
    this.x = 0; this.y = 0;
    this.heading = 0;           // heading used for steps (grid line when snapping)
    this.unwrapped = 0;         // integrated gyro heading, not wrapped
    this.smooth = 0;            // rolling median of unwrapped (walking direction)
    this.facing = 0;            // quick heading for the facing cone (~0.2 s smoothing)
    this.bias = 0; this.calibrated = false; this.quiet = [];
    this.window = [];           // [t, unwrapped] over the last medianS seconds
    this.awaySince = null;
    this.g = null; this.lastT = null;
    this.bandLast = null; this.bandSteps = 0;
    this.accSteps = 0; this.accArmed = true; this.accLastStep = -Infinity; this.accS = null;
    this.steps = 0;
    this.state = '–';
    this.points = [{ x: 0, y: 0, h: 0, steps: 0 }];
    this.turns = [];
  }

  start() {
    this.reset();
    this.running = true;
  }

  stop() { this.running = false; }

  get calibrating() { return this.running && !this.calibrated; }

  /** Heading to draw: where you are facing now (smoothed), wrapped to -180..180. */
  get shownHeading() { return wrap(this.facing); }

  /** For tools that still read .raw */
  get raw() { return wrap(this.unwrapped); }

  motion(t, ax, ay, az, gx, gy, gz) {
    if (!this.running || ax == null || gx == null) return;
    const a = this.o.gravityAlpha;
    const g = this.g ? [this.g[0] + a * (ax - this.g[0]), this.g[1] + a * (ay - this.g[1]), this.g[2] + a * (az - this.g[2])]
      : [ax, ay, az];
    this.g = g;
    const norm = Math.hypot(g[0], g[1], g[2]);
    if (norm < 0.3) { this.lastT = t; return; }
    let yaw = (gx * g[0] + gy * g[1] + gz * g[2]) / norm;
    if (this.o.flip) yaw = -yaw;
    const dt = this.lastT == null ? 0 : Math.max(0, Math.min(0.2, t - this.lastT));
    this.lastT = t;

    // Stillness: calibrate the first time, then keep the bias honest.
    if (Math.hypot(gx, gy, gz) < this.o.quietGyro) {
      this.quiet.push(yaw);
      if (this.quiet.length > this.o.quietN) this.quiet.shift();
      if (this.quiet.length === this.o.quietN) {
        if (!this.calibrated) { this.bias = median(this.quiet); this.calibrated = true; }
        else this.bias += this.o.biasAlpha * (median(this.quiet) - this.bias);
      }
    } else {
      this.quiet = [];
    }
    if (!this.calibrated) return;       // hold still: nothing is tracked until the gyro is calibrated

    // positive yaw about "up" = counter-clockwise = left = lower heading
    this.unwrapped -= (yaw - this.bias) * dt;
    if (dt > 0) this.facing += (1 - Math.exp(-dt / 0.2)) * (this.unwrapped - this.facing);
    this.window.push([t, this.unwrapped]);
    while (this.window.length && t - this.window[0][0] > this.o.medianS) this.window.shift();
    this.smooth = median(this.window.map((w) => w[1]));
    this._heading(t);
    this._accStep(t, Math.hypot(ax, ay, az));
  }

  _heading(t) {
    if (!this.o.snap) { this.heading = this.smooth; return; }
    if (Math.abs(this.smooth - this.heading) <= this.o.snapHyst) { this.awaySince = null; return; }
    if (this.awaySince == null) { this.awaySince = t; return; }
    if (t - this.awaySince < this.o.snapHoldS) return;
    const next = 90 * Math.round(this.smooth / 90);
    if (next !== this.heading) this.turns.push({ x: this.x, y: this.y, deg: next - this.heading });
    this.heading = next;
    this.awaySince = null;
  }

  _accStep(t, mag) {
    const k = this.o.accSmooth;
    this.accS = this.accS == null ? mag : this.accS + k * (mag - this.accS);
    if (this.accArmed && this.accS > this.o.accThr && t - this.accLastStep >= this.o.accMinGapS) {
      this.accSteps += 1;
      this.accLastStep = t;
      this.accArmed = false;
      if (this.o.stepSource === 'accel') this._advance(1);
    } else if (this.accS < this.o.accLow) {
      this.accArmed = true;
    }
  }

  /** One activity reading. steps is the band's lifetime total. */
  activity(t, steps, state) {
    if (!this.running) return;
    this.state = state;
    if (this.bandLast == null || !this.calibrated) { this.bandLast = steps; return; }
    const n = steps - this.bandLast;
    this.bandLast = steps;
    if (n <= 0) return;                 // nothing new, or the band's counter restarted
    this.bandSteps += n;
    if (this.o.stepSource === 'band') this._advance(n);
  }

  _advance(n) {
    const d = n * this.o.stepLen;
    const h = (this.heading * Math.PI) / 180;
    this.x += d * Math.sin(h);
    this.y += d * Math.cos(h);
    this.steps += n;
    this.points.push({ x: this.x, y: this.y, h: this.heading, steps: this.steps });
  }

  get distance() { return this.steps * this.o.stepLen; }
}
