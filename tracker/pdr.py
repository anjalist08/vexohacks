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

Heading is clockwise from the start direction (see interfaces.py). A positive yaw
rate about "up" is a left (counter-clockwise) turn, so it lowers the heading.
"""
import math
import threading
from typing import Callable, List, Optional

import config
from interfaces import PoseSample


def wrap_deg(a: float) -> float:
    """Angle in (-180, 180]."""
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


class PathTracker:
    def __init__(self, step_length_m: float = None, snap_turns: bool = None):
        self.step_length_m = config.STEP_LENGTH_M if step_length_m is None else step_length_m
        self.snap_turns = config.SNAP_TURNS if snap_turns is None else snap_turns
        self._lock = threading.Lock()
        self._listeners: List[Callable[[PoseSample], None]] = []
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
        self._quiet_since: Optional[float] = None
        self._step_base: Optional[int] = None
        self._last_steps: Optional[int] = None
        self.state = "still"
        self.points = [PoseSample(t, 0.0, 0.0, 0.0, 0)]

    def start(self, t: float):
        """Begin a route at (0, 0) facing heading 0. Stand still for CALIBRATION_S."""
        with self._lock:
            self._reset(t)
            self.running = True
        return self.points[0]

    def stop(self):
        with self._lock:
            self.running = False

    def on_sample(self, fn: Callable[[PoseSample], None]):
        """Call fn(PoseSample) for every new route point."""
        self._listeners.append(fn)

    # --- sensor input ----------------------------------------------------------
    def on_motion(self, t: float, ax: float, ay: float, az: float, gx: float, gy: float, gz: float):
        """One motion sample: accelerometer in g, gyro in degrees/second."""
        if not self.running or gx is None or ax is None:
            return
        with self._lock:
            g = self._gravity
            if g is None:
                g = [ax, ay, az]
            else:
                a = config.GRAVITY_ALPHA
                g = [g[0] + a * (ax - g[0]), g[1] + a * (ay - g[1]), g[2] + a * (az - g[2])]
            self._gravity = g
            norm = math.sqrt(g[0] ** 2 + g[1] ** 2 + g[2] ** 2)
            if norm < 0.3:          # free fall or garbage: no "up" to project onto
                self._last_motion_t = t
                return
            yaw = (gx * g[0] + gy * g[1] + gz * g[2]) / norm

            if t < self._calib_until:
                self._calib.append(yaw)
                self._last_motion_t = t
                return
            if not self.calibrated:
                if self._calib:
                    self.bias = sum(self._calib) / len(self._calib)
                self.calibrated = True

            dt = 0.0 if self._last_motion_t is None else max(0.0, min(0.2, t - self._last_motion_t))
            self._last_motion_t = t
            rate = yaw - self.bias

            # Still and quiet: let the bias drift towards what the gyro reads now.
            if self.state == "still" and not self._turning and abs(rate) < config.STILL_GYRO_DPS:
                self.bias += config.BIAS_UPDATE_ALPHA * (yaw - self.bias)
                rate = yaw - self.bias

            self.raw_heading = wrap_deg(self.raw_heading - rate * dt)
            self._track_turn(t, rate)

    def _track_turn(self, t: float, rate: float):
        if abs(rate) > config.TURN_RATE_DPS:
            if not self._turning:
                self._turning = True
                self._turn_start_raw = self.raw_heading
            self._quiet_since = None
            if not self.snap_turns:
                self.heading = self.raw_heading
            return
        if not self.snap_turns:
            self.heading = self.raw_heading
            self._turning = False
            return
        if self._turning:
            if self._quiet_since is None:
                self._quiet_since = t
            elif t - self._quiet_since >= config.TURN_SETTLE_S:
                net = wrap_deg(self.raw_heading - self._turn_start_raw)
                snapped = 90.0 * round(net / 90.0) if abs(net) >= config.MIN_TURN_DEG else 0.0
                self.heading = wrap_deg(self.heading + snapped)
                self.raw_heading = self.heading
                self._turning = False
                self._quiet_since = None

    def on_activity(self, t: float, steps: int, state: str) -> Optional[PoseSample]:
        """One activity reading. steps is the band's lifetime total."""
        if not self.running:
            return None
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
            d = new * self.step_length_m
            h = math.radians(self.heading)
            self.x += d * math.sin(h)
            self.y += d * math.cos(h)
            sample = PoseSample(t, self.x, self.y, self.heading, steps - self._step_base)
            self.points.append(sample)
        for fn in self._listeners:
            fn(sample)
        return sample

    # --- corrections -----------------------------------------------------------
    def reanchor(self, x: float, y: float, heading_deg: float, t: float = None):
        """The user confirmed they stand at a known point: reset position and heading."""
        with self._lock:
            self.x, self.y = x, y
            self.heading = self.raw_heading = wrap_deg(heading_deg)
            self._turning = False
            last = self.points[-1]
            sample = PoseSample(last.t if t is None else t, x, y, self.heading, last.steps)
            self.points.append(sample)
        for fn in self._listeners:
            fn(sample)
        return sample

    @property
    def pose(self) -> PoseSample:
        return self.points[-1]
