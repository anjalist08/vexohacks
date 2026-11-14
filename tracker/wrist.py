"""Wrist-worn path tracking, tuned on real walks with the band on a wrist.

Same interface as PathTracker (start, stop, on_motion, on_activity, on_sample,
on_uncertainty, heading_uncertain, reanchor, pose, points), so the app, the voice loop
and the map page use it unchanged. It differs in three places, each found on a real
logged walk (data/logs/walk1-*, walk2-*, walk3-*):

1. Calibration waits for real stillness. The gyro bias is the median of the first
   QUIET_N samples in a row with the gyro below QUIET_GYRO_DPS, instead of a fixed
   window after start (walk 1's window caught a moving hand: bias off by 1.2 deg/s).
   Nothing is tracked until then. The bias is re-estimated whenever the band is still.
2. Heading = the integrated gyro (projected onto gravity), then a rolling MEDIAN over
   MEDIAN_S seconds. Arm swing rocks the raw heading by up to ~100 degrees and kept the
   old "turning" detector busy, so turns never settled (walk 2: 22 m off). With
   snapping, the walking heading is held on a 90-degree grid and moves to another grid
   line only when the median stays more than SNAP_HYST_DEG away for SNAP_HOLD_S.
3. Steps come from a peak detector on the accelerometer (STEP_SOURCE "accel"). The
   band's own step counter started ~15 s late on walk 1 and then updated once a second.
   STEP_SOURCE "band" uses the band's counter (synthetic walks have no footfalls).

Replays (tests/test_wrist.py): walk 3, a 59 m loop, ends 1.0 m from its start.
"""
import collections
import math
import statistics
from typing import Callable, List, Optional

import config
from interfaces import PoseSample
from tracker.pdr import (
    BAD_ACCEL_RATE_DPS,
    BAD_ACCEL_UNCERTAINTY_DEG,
    DRIFT_PER_STEP_DEG,
    MAX_ACCEL_G,
    MIN_ACCEL_G,
    UNCALIBRATED_STEP_DEG,
    PathTracker,
    wrap_deg,
)

QUIET_GYRO_DPS = 6.0       # total gyro below this...
QUIET_N = 15               # ...for this many samples in a row (~0.3 s at 50/s) = at rest
MEDIAN_S = 2.0             # seconds of heading in the rolling median
SNAP_HYST_DEG = 50.0       # degrees from the current grid line before moving to another
SNAP_HOLD_S = 0.5
OFF_GRID_DEG = 30.0        # median this far off the grid while walking adds uncertainty
ACC_THR_G = 1.12           # smoothed |a| above this is a footfall...
ACC_LOW_G = 1.03           # ...once it has dropped below this since the last one
ACC_MIN_GAP_S = 0.28
ACC_SMOOTH = 0.35


class WristTracker(PathTracker):
    def __init__(self, step_length_m: Optional[float] = None, snap_turns: Optional[bool] = None,
                 step_source: Optional[str] = None, uncertainty_threshold_deg: Optional[float] = None,
                 **_ignored):
        # turn_rate_dps / turn_settle_s / min_turn_deg belong to PathTracker's turn model: accepted, unused
        self.step_source = step_source or getattr(config, "STEP_SOURCE", "accel")
        super().__init__(step_length_m=step_length_m, snap_turns=snap_turns,
                         uncertainty_threshold_deg=uncertainty_threshold_deg)

    def _reset(self, t: float):
        super()._reset(t)
        self.unwrapped = 0.0
        self.smooth = 0.0
        self._window = collections.deque()
        self._quiet: List[float] = []
        self._away_since: Optional[float] = None
        self._acc_s: Optional[float] = None
        self._acc_armed = True
        self._acc_last = -1e9
        self.acc_steps = 0
        self.band_steps = 0
        self._steps = 0

    # --- motion ------------------------------------------------------------------
    def on_motion(self, t, ax, ay, az, gx, gy, gz):
        if not self.running or gx is None or ax is None:
            return
        with self._lock:
            sample = self._wrist_motion_locked(t, ax, ay, az, gx, gy, gz)
            pose_listeners = list(self._listeners) if sample else []
            notify = self._consume_uncertainty_transition_locked()
            unc_listeners = list(self._uncertainty_listeners) if notify is not None else []
        for fn in pose_listeners:
            fn(sample)
        for fn in unc_listeners:
            fn(notify)

    def _wrist_motion_locked(self, t, ax, ay, az, gx, gy, gz) -> Optional[PoseSample]:
        dt = 0.0 if self._last_motion_t is None else max(0.0, min(0.2, t - self._last_motion_t))
        self._last_motion_t = t
        accel_norm = math.sqrt(ax * ax + ay * ay + az * az)
        g = self._gravity
        a = config.GRAVITY_ALPHA
        g = [ax, ay, az] if g is None else [g[0] + a * (ax - g[0]), g[1] + a * (ay - g[1]), g[2] + a * (az - g[2])]
        self._gravity = g
        norm = math.sqrt(g[0] ** 2 + g[1] ** 2 + g[2] ** 2)
        if accel_norm < MIN_ACCEL_G or accel_norm > MAX_ACCEL_G or norm < MIN_ACCEL_G or norm > MAX_ACCEL_G:
            self.uncertainty_deg += max(BAD_ACCEL_UNCERTAINTY_DEG, BAD_ACCEL_RATE_DPS * dt)
        if norm < MIN_ACCEL_G:
            return None
        yaw = (gx * g[0] + gy * g[1] + gz * g[2]) / norm

        if math.sqrt(gx * gx + gy * gy + gz * gz) < QUIET_GYRO_DPS:
            self._quiet.append(yaw)
            if len(self._quiet) > QUIET_N:
                self._quiet.pop(0)
            if len(self._quiet) == QUIET_N:
                m = statistics.median(self._quiet)
                if not self.calibrated:
                    self.bias = m
                    self.calibrated = True
                else:
                    self.bias += config.BIAS_UPDATE_ALPHA * (m - self.bias)
        else:
            self._quiet = []
        if not self.calibrated:
            return None

        # positive yaw about "up" = counter-clockwise = left = lower heading
        self.unwrapped -= (yaw - self.bias) * dt
        self._window.append((t, self.unwrapped))
        while self._window and t - self._window[0][0] > MEDIAN_S:
            self._window.popleft()
        self.smooth = statistics.median(v for _, v in self._window)
        self.raw_heading = wrap_deg(self.smooth)
        self._update_grid(t)
        if self.step_source == "accel" and self._footfall(t, accel_norm):
            return self._advance_locked(t, 1)
        return None

    def _update_grid(self, t: float):
        if not self.snap_turns:
            self.heading = self.smooth
            return
        if abs(self.smooth - self.heading) <= SNAP_HYST_DEG:
            self._away_since = None
            return
        if self._away_since is None:
            self._away_since = t
            return
        if t - self._away_since >= SNAP_HOLD_S:
            self.heading = 90.0 * round(self.smooth / 90.0)
            self._away_since = None

    def _footfall(self, t: float, mag: float) -> bool:
        self._acc_s = mag if self._acc_s is None else self._acc_s + ACC_SMOOTH * (mag - self._acc_s)
        if self._acc_armed and self._acc_s > ACC_THR_G and t - self._acc_last >= ACC_MIN_GAP_S:
            self._acc_armed = False
            self._acc_last = t
            self.acc_steps += 1
            return True
        if self._acc_s < ACC_LOW_G:
            self._acc_armed = True
        return False

    def _advance_locked(self, t: float, n: int) -> PoseSample:
        if not self.calibrated:
            self.uncertainty_deg += UNCALIBRATED_STEP_DEG * n
        self.uncertainty_deg += DRIFT_PER_STEP_DEG * n
        if self.snap_turns and self._away_since is None:
            # walking clearly off the grid (a diagonal or a curve), not just mid-turn
            off = abs(self.smooth - self.heading)
            if off > OFF_GRID_DEG:
                self.uncertainty_deg += 0.25 * (off - OFF_GRID_DEG) * n
        d = n * self.step_length_m
        h = math.radians(self.heading)
        self.x += d * math.sin(h)
        self.y += d * math.cos(h)
        self._steps += n
        sample = PoseSample(t, self.x, self.y, wrap_deg(self.heading), self._steps)
        self.points.append(sample)
        return sample

    # --- activity ------------------------------------------------------------------
    def on_activity(self, t: float, steps: int, state: str) -> Optional[PoseSample]:
        if not self.running:
            return None
        with self._lock:
            self.state = state
            if self._last_steps is None or not self.calibrated:
                self._last_steps = steps
                return None
            new = steps - self._last_steps
            self._last_steps = steps
            if new <= 0:
                return None
            self.band_steps += new
            if self.step_source != "band":
                return None
            sample = self._advance_locked(t, new)
            pose_listeners = list(self._listeners)
            notify = self._consume_uncertainty_transition_locked()
            unc_listeners = list(self._uncertainty_listeners) if notify is not None else []
        for fn in pose_listeners:
            fn(sample)
        for fn in unc_listeners:
            fn(notify)
        return sample

    # --- corrections -----------------------------------------------------------------
    def reanchor(self, x: float, y: float, heading_deg: float, t: Optional[float] = None):
        sample = super().reanchor(x, y, heading_deg, t)
        with self._lock:
            # keep the median and the grid continuous with the confirmed heading
            self.heading = self.unwrapped = self.smooth = float(wrap_deg(heading_deg))
            self._window.clear()
            self._away_since = None
        return sample


def make_tracker(synthetic: bool = False, **kwargs) -> PathTracker:
    """The tracker config.TRACKER_MODEL asks for. Synthetic walks have no footfalls in their
    accelerometer data, so the wrist model counts the band's steps for them."""
    if getattr(config, "TRACKER_MODEL", "wrist") == "wrist":
        if synthetic:
            kwargs.setdefault("step_source", "band")
        return WristTracker(**kwargs)
    kwargs.pop("step_source", None)
    return PathTracker(**kwargs)
