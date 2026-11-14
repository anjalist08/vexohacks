// Path tracking for the live trail page. Same method as tracker/pdr.py, in JavaScript so
// the page can run on its own in Chrome:
// - gravity = low-pass of the accelerometer; yaw rate = gyro projected onto gravity, so it
//   does not matter how the band sits on the wrist
// - the first calibS seconds after start() measure the gyro bias (stand still)
// - yaw is integrated all the time; still + quiet periods only nudge the bias
// - with snap, a settled turn is rounded to the nearest 90 degrees
// - every step moves the position by stepLen along the heading
// Heading is in degrees, clockwise from the direction you faced at start (0 = ahead, 90 = right).
// Steps can come from the band's own step counter or from a simple peak detector on the
// accelerometer, so the two can be compared on a real walk.

export const DEFAULTS = {
  stepLen: 0.7,          // metres per step (PLACEHOLDER until measured)
  gravityAlpha: 0.05,    // low-pass weight for gravity, per motion sample
  calibS: 2.0,           // seconds standing still after start
  snap: true,            // round settled turns to 90 degrees
  turnRate: 25,          // deg/s above this counts as turning
  settleS: 0.6,          // quiet time before a turn counts as finished
  minTurn: 45,           // net turns smaller than this are ignored (snap only)
  stillGyro: 3,          // deg/s: below this while "still" re-estimates the bias
  biasAlpha: 0.02,
  flip: false,           // swap left and right if the band's axes are mirrored
  stepSource: 'band',    // 'band' (band's step counter) or 'accel' (detector below)
  accThr: 1.12,          // g: smoothed |a| above this is a step...
  accLow: 1.03,          // ...once it has dropped below this since the last step
  accMinGapS: 0.28,      // at most ~3.5 steps a second
  accSmooth: 0.35,       // smoothing weight for |a|
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
    this.heading = 0; this.raw = 0; this.bias = 0;
    this.calib = []; this.calibUntil = Infinity; this.calibrated = false;
    this.g = null; this.lastT = null;
    this.turning = false; this.turnStart = 0; this.quietSince = null;
    this.bandLast = null; this.bandSteps = 0;
    this.accSteps = 0; this.accArmed = true; this.accLastStep = -Infinity; this.accS = null;
    this.steps = 0;
    this.state = '–';
    this.points = [{ x: 0, y: 0, h: 0, steps: 0 }];
    this.turns = [];
  }

  start(tSec) {
    this.reset();
    this.running = true;
    this.calibUntil = tSec + this.o.calibS;
  }

  stop() { this.running = false; }

  get calibrating() { return this.running && !this.calibrated; }

  /** Heading to draw: the live gyro heading while a turn is under way. */
  get shownHeading() { return this.turning || !this.o.snap ? this.raw : this.heading; }

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

    if (t < this.calibUntil) { this.calib.push(yaw); this.lastT = t; return; }
    if (!this.calibrated) {
      if (this.calib.length) this.bias = this.calib.reduce((s, v) => s + v, 0) / this.calib.length;
      this.calibrated = true;
    }

    const dt = this.lastT == null ? 0 : Math.max(0, Math.min(0.2, t - this.lastT));
    this.lastT = t;
    let rate = yaw - this.bias;
    if (this.state === 'still' && !this.turning && Math.abs(rate) < this.o.stillGyro) {
      this.bias += this.o.biasAlpha * (yaw - this.bias);
      rate = yaw - this.bias;
    }
    // positive yaw about "up" = counter-clockwise = left = lower heading
    this.raw = wrap(this.raw - rate * dt);
    this._turn(t, rate);
    this._accStep(t, Math.hypot(ax, ay, az));
  }

  _turn(t, rate) {
    if (!this.o.snap) { this.heading = this.raw; this.turning = Math.abs(rate) > this.o.turnRate; return; }
    if (Math.abs(rate) > this.o.turnRate) {
      if (!this.turning) { this.turning = true; this.turnStart = this.raw; }
      this.quietSince = null;
      return;
    }
    if (!this.turning) return;
    if (this.quietSince == null) { this.quietSince = t; return; }
    if (t - this.quietSince < this.o.settleS) return;
    const net = wrap(this.raw - this.turnStart);
    const snapped = Math.abs(net) >= this.o.minTurn ? 90 * Math.round(net / 90) : 0;
    this.heading = wrap(this.heading + snapped);
    this.raw = this.heading;
    this.turning = false;
    this.quietSince = null;
    if (snapped) this.turns.push({ x: this.x, y: this.y, deg: snapped });
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
