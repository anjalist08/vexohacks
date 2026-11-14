"""Pedestrian dead reckoning from the band: steps for distance, gyro yaw for direction.

How it works (BUILD plan, "Path tracking", with the plan amendments):
- Gravity is a low-pass of the accelerometer. Yaw rate is the gyro vector projected
  onto gravity, so it does not matter how the band sits on the wrist.
- The first CALIBRATION_S seconds after start() measure the gyro bias (stand still).
- Yaw is integrated all the time, not only while walking: people often stop at a
  corner, so the band reads "still" exactly while they turn.
- "still" periods with a quiet gyro only nudge the bias estimate.
- With SNAP_TURNS, a turn that has settled is rounded to the nearest 90 degrees and
  the heading is reset to that value, so small gyro errors do not pile up.
- Each batch of new steps moves the position by steps * STEP_LENGTH_M along the heading.
- Heading uncertainty accumulates from uncalibrated walking, ambiguous/diagonal turn
  residuals, chaotic wrist acceleration/jitter, and long unanchored step drift, firing
  on_uncertainty(True/False) transitions for the red "uncertain" LED state.

Heading is clockwise from the start direction (see interfaces.py). A positive yaw
rate about "up" is a left (counter-clockwise) turn, so it lowers the heading.
"""
import math
import threading
from typing import Callable, List, Optional

import config
from interfaces import PoseSample

UNCERTAINTY_THRESHOLD_DEFAULT = 35.0
UNCALIBRATED_STEP_DEG = 20.0
DRIFT_PER_STEP_DEG = 0.4
CLEAN_SNAP_DEADBAND_DEG = 10.0
UNSNAPPED_CURVE_DEG = 15.0
MIN_ACCEL_G = 0.3
MAX_ACCEL_G = 2.5
BAD_ACCEL_UNCERTAINTY_DEG = 4.0
BAD_ACCEL_RATE_DPS = 80.0
YAW_REVERSAL_UNCERTAINTY_DEG = 8.0
MAX_TURN_DURATION_S = 4.0
NON_SETTLING_TURN_DPS = 25.0


def wrap_deg(a: float) -> float:
    """Angle in (-180, 180]."""
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


class PathTracker:
    def __init__(
        self,
        step_length_m: Optional[float] = None,
        snap_turns: Optional[bool] = None,
        turn_rate_dps: Optional[float] = None,
        turn_settle_s: Optional[float] = None,
        min_turn_deg: Optional[float] = None,
        uncertainty_threshold_deg: Optional[float] = None,
    ):
        self.step_length_m = config.STEP_LENGTH_M if step_length_m is None else step_length_m
        self.snap_turns = config.SNAP_TURNS if snap_turns is None else snap_turns
        self.turn_rate_dps = config.TURN_RATE_DPS if turn_rate_dps is None else turn_rate_dps
        self.turn_settle_s = config.TURN_SETTLE_S if turn_settle_s is None else turn_settle_s
        self.min_turn_deg = config.MIN_TURN_DEG if min_turn_deg is None else min_turn_deg
        self.uncertainty_threshold_deg = (
            UNCERTAINTY_THRESHOLD_DEFAULT
            if uncertainty_threshold_deg is None
            else uncertainty_threshold_deg
        )
        self._lock = threading.Lock()
        self._listeners: List[Callable[[PoseSample], None]] = []
        self._uncertainty_listeners: List[Callable[[bool], None]] = []
        self._was_uncertain = False
        self.uncertainty_deg = 0.0
        self.running = False
        self.points: List[PoseSample] = []
        self._reset(0.0)

    # --- lifecycle -----------------------------------------------------------
    def _reset(self, t: float):
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0        # heading used for moves (snapped when snap_turns)
        self.raw_heading = 0.0    # integrated gyro heading
        self.bias = 0.0
        self.calibrated = False
        self._calib: List[float] = []
        self._calib_until = t + config.CALIBRATION_S
        self._gravity = None
        self._last_motion_t: Optional[float] = None
        self._turning = False
        self._turn_start_raw = 0.0
        self._turn_start_t: Optional[float] = None
        self._last_turn_sign = 0
        self._quiet_since: Optional[float] = None
        self._step_base: Optional[int] = None
        self._last_steps: Optional[int] = None
        self.state = "still"
        self.uncertainty_deg = 0.0
        self._was_uncertain = False
        self.points = [PoseSample(t, 0.0, 0.0, 0.0, 0)]

    def start(self, t: float):
        """Begin a route at (0, 0) facing heading 0. Stand still for CALIBRATION_S."""
        notify_uncertain: Optional[bool] = None
        unc_listeners: List[Callable[[bool], None]] = []
        with self._lock:
            was_uncertain = self._was_uncertain
            self._reset(t)
            self.running = True
            if was_uncertain:
                notify_uncertain = False
                unc_listeners = list(self._uncertainty_listeners)
            first = self.points[0]
        if notify_uncertain is not None:
            for fn in unc_listeners:
                fn(notify_uncertain)
        return first

    def stop(self):
        with self._lock:
            self.running = False

    def on_sample(self, fn: Callable[[PoseSample], None]):
        """Call fn(PoseSample) for every new route point."""
        self._listeners.append(fn)

    def on_uncertainty(self, fn: Callable[[bool], None]):
        """Call fn(is_uncertain) whenever heading_uncertain transitions False<->True."""
        self._uncertainty_listeners.append(fn)

    @property
    def heading_uncertain(self) -> bool:
        return self.uncertainty_deg >= self.uncertainty_threshold_deg

    def _consume_uncertainty_transition_locked(self) -> Optional[bool]:
        now_uncertain = self.uncertainty_deg >= self.uncertainty_threshold_deg
        if now_uncertain != self._was_uncertain:
            self._was_uncertain = now_uncertain
            return now_uncertain
        return None

    # --- sensor input ----------------------------------------------------------
    def on_motion(self, t: float, ax: float, ay: float, az: float, gx: float, gy: float, gz: float):
        """One motion sample: accelerometer in g, gyro in degrees/second."""
        if not self.running or gx is None or ax is None:
            return
        notify_uncertain: Optional[bool] = None
        unc_listeners: List[Callable[[bool], None]] = []
        with self._lock:
            self._on_motion_locked(t, ax, ay, az, gx, gy, gz)
            notify_uncertain = self._consume_uncertainty_transition_locked()
            if notify_uncertain is not None:
                unc_listeners = list(self._uncertainty_listeners)
        if notify_uncertain is not None:
            for fn in unc_listeners:
                fn(notify_uncertain)

    def _on_motion_locked(self, t: float, ax: float, ay: float, az: float, gx: float, gy: float, gz: float):
        dt = 0.0 if self._last_motion_t is None else max(0.0, min(0.2, t - self._last_motion_t))
        accel_norm = math.sqrt(ax ** 2 + ay ** 2 + az ** 2)

        g = self._gravity
        if g is None:
            g = [ax, ay, az]
        else:
            a = config.GRAVITY_ALPHA
            g = [g[0] + a * (ax - g[0]), g[1] + a * (ay - g[1]), g[2] + a * (az - g[2])]
        self._gravity = g
        norm = math.sqrt(g[0] ** 2 + g[1] ** 2 + g[2] ** 2)

        bad_accel = (
            accel_norm < MIN_ACCEL_G
            or accel_norm > MAX_ACCEL_G
            or norm < MIN_ACCEL_G
            or norm > MAX_ACCEL_G
        )
        if bad_accel:
            self.uncertainty_deg += max(BAD_ACCEL_UNCERTAINTY_DEG, BAD_ACCEL_RATE_DPS * dt)

        if norm < MIN_ACCEL_G:      # free fall or garbage: no "up" to project onto
            self._last_motion_t = t
            return
        yaw = (gx * g[0] + gy * g[1] + gz * g[2]) / norm

        if t < self._calib_until:
            if not bad_accel:
                self._calib.append(yaw)
            self._last_motion_t = t
            return
        if not self.calibrated:
            if self._calib:
                self.bias = sum(self._calib) / len(self._calib)
            self.calibrated = True

        self._last_motion_t = t
        rate = yaw - self.bias

        # Still and quiet: let the bias drift towards what the gyro reads now.
        if self.state == "still" and not self._turning and abs(rate) < config.STILL_GYRO_DPS:
            self.bias += config.BIAS_UPDATE_ALPHA * (yaw - self.bias)
            rate = yaw - self.bias

        self.raw_heading = wrap_deg(self.raw_heading - rate * dt)
        self._track_turn(t, rate, dt)

    def _track_turn(self, t: float, rate: float, dt: float = 0.0):
        if abs(rate) > self.turn_rate_dps:
            sign = 1 if rate > 0.0 else -1
            if not self._turning:
                self._turning = True
                self._turn_start_raw = self.raw_heading
                self._turn_start_t = t
                self._last_turn_sign = sign
            else:
                if self._last_turn_sign != 0 and sign != self._last_turn_sign:
                    self.uncertainty_deg += YAW_REVERSAL_UNCERTAINTY_DEG
                    self._last_turn_sign = sign
                if self._turn_start_t is not None and (t - self._turn_start_t) > MAX_TURN_DURATION_S:
                    self.uncertainty_deg += NON_SETTLING_TURN_DPS * dt
            self._quiet_since = None
            if not self.snap_turns:
                self.heading = self.raw_heading
            return
        if not self.snap_turns:
            self.heading = self.raw_heading
            self._turning = False
            self._turn_start_t = None
            self._last_turn_sign = 0
            return
        if self._turning:
            if self._quiet_since is None:
                self._quiet_since = t
            elif t - self._quiet_since >= self.turn_settle_s:
                prev_raw = self.raw_heading
                net = wrap_deg(self.raw_heading - self._turn_start_raw)
                snapped = 90.0 * round(net / 90.0) if abs(net) >= self.min_turn_deg else 0.0
                new_heading = wrap_deg(self.heading + snapped)
                net_residual = abs(wrap_deg(net - snapped))
                snap_residual = abs(wrap_deg(prev_raw - new_heading))
                disc = max(net_residual, snap_residual)
                if disc > CLEAN_SNAP_DEADBAND_DEG:
                    self.uncertainty_deg += disc
                else:
                    self.uncertainty_deg += snap_residual
                self.heading = new_heading
                self.raw_heading = self.heading
                self._turning = False
                self._turn_start_t = None
                self._last_turn_sign = 0
                self._quiet_since = None

    def on_activity(self, t: float, steps: int, state: str) -> Optional[PoseSample]:
        """One activity reading. steps is the band's lifetime total."""
        if not self.running:
            return None
        notify_uncertain: Optional[bool] = None
        unc_listeners: List[Callable[[bool], None]] = []
        with self._lock:
            self.state = state
            if self._step_base is None:
                self._step_base = steps
                self._last_steps = steps
                return None
            new = steps - self._last_steps
            self._last_steps = steps
            if new <= 0:            # no new steps, or the band's counter restarted
                if new < 0:
                    self._step_base = steps - self.points[-1].steps
                return None

            if not self.calibrated:
                self.uncertainty_deg += UNCALIBRATED_STEP_DEG * new
            self.uncertainty_deg += DRIFT_PER_STEP_DEG * new
            if self.snap_turns and not self._turning:
                unsnapped = abs(wrap_deg(self.raw_heading - self.heading))
                if unsnapped > UNSNAPPED_CURVE_DEG:
                    self.uncertainty_deg += 0.25 * unsnapped * new

            d = new * self.step_length_m
            h = math.radians(self.heading)
            self.x += d * math.sin(h)
            self.y += d * math.cos(h)
            sample = PoseSample(t, self.x, self.y, self.heading, steps - self._step_base)
            self.points.append(sample)
            pose_listeners = list(self._listeners)
            notify_uncertain = self._consume_uncertainty_transition_locked()
            if notify_uncertain is not None:
                unc_listeners = list(self._uncertainty_listeners)
        for fn in pose_listeners:
            fn(sample)
        if notify_uncertain is not None:
            for fn in unc_listeners:
                fn(notify_uncertain)
        return sample

    # --- corrections -----------------------------------------------------------
    def reanchor(self, x: float, y: float, heading_deg: float, t: Optional[float] = None):
        """The user confirmed they stand at a known point: reset position and heading."""
        notify_uncertain: Optional[bool] = None
        unc_listeners: List[Callable[[bool], None]] = []
        with self._lock:
            self.x, self.y = x, y
            self.heading = self.raw_heading = wrap_deg(heading_deg)
            self._turning = False
            self._turn_start_t = None
            self._last_turn_sign = 0
            self._quiet_since = None
            self.uncertainty_deg = 0.0
            if self._was_uncertain:
                self._was_uncertain = False
                notify_uncertain = False
                unc_listeners = list(self._uncertainty_listeners)
            last = self.points[-1]
            sample = PoseSample(last.t if t is None else t, x, y, self.heading, last.steps)
            self.points.append(sample)
            pose_listeners = list(self._listeners)
        for fn in pose_listeners:
            fn(sample)
        if notify_uncertain is not None:
            for fn in unc_listeners:
                fn(notify_uncertain)
        return sample

    @property
    def pose(self) -> PoseSample:
        return self.points[-1]
