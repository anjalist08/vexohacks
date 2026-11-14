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
import time
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
PHONE_FRESH_S = 2.0        # iPhone motion newer than this is used instead of the wrist's heading
PHONE_STRIDE_MIN_STEPS = 10
PHONE_MOVE_DEG = 45.0        # the phone turned this much: a body turn, or the phone moved in a hand?
PHONE_SETTLE_S = 0.7         # ...decided once the phone has held still this long
PHONE_DECIDE_S = 1.5         # ...and at least this long after it started moving (the wrist median lags)  # iPhone pedometer steps before its stride replaces STEP_LENGTH_M
ACC_SMOOTH = 0.35


class WristTracker(PathTracker):
    def __init__(self, step_length_m: Optional[float] = None, snap_turns: Optional[bool] = None,
                 step_source: Optional[str] = None, uncertainty_threshold_deg: Optional[float] = None,
                 phone_heading: Optional[bool] = None, **_ignored):
        # turn_rate_dps / turn_settle_s / min_turn_deg belong to PathTracker's turn model: accepted, unused
        self.step_source = step_source or getattr(config, "STEP_SOURCE", "accel")
        self.clock = time.time          # wall clock for phone freshness (tests replace it)
        # Use the iPhone's heading for the walking direction? Off by default until it is tuned on
        # real walks with ground truth; the phone's data is still logged and its stride still used.
        self.use_phone_heading = getattr(config, "PHONE_HEADING", False) if phone_heading is None else phone_heading
        super().__init__(step_length_m=step_length_m, snap_turns=snap_turns,
                         uncertainty_threshold_deg=uncertainty_threshold_deg)

    def _reset(self, t: float):
        super()._reset(t)
        self.unwrapped = 0.0
        self.smooth = 0.0
        self.facing = 0.0          # quick heading for the facing cone (~0.2 s smoothing)
        self._window = collections.deque()
        self._quiet: List[float] = []
        self._away_since: Optional[float] = None
        self._acc_s: Optional[float] = None
        self._acc_armed = True
        self._acc_last = -1e9
        self.acc_steps = 0
        self.band_steps = 0
        self._steps = 0
        # iPhone sensor fusion (tracker.on_phone): heading relative to the start, and stride
        self._phone_base: Optional[float] = None
        self._phone_raw: Optional[float] = None
        self.phone_heading: Optional[float] = None
        self._phone_wall = 0.0
        self.phone_steps: Optional[int] = None
        self.phone_distance: Optional[float] = None
        self._phone_ref: Optional[float] = None    # phone heading at the last settled moment
        self._wrist_ref = 0.0                      # wrist median at that moment
        self._phone_move_wall: Optional[float] = None
        self._phone_still_wall: Optional[float] = None
        self._phone_prev: Optional[float] = None
        self.phone_handled = 0                     # times the phone moved in a hand and was re-aligned

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
            if self.phone_fresh:          # the phone gives the heading: no need to wait for the wrist
                self._update_grid(t)
            return None

        # positive yaw about "up" = counter-clockwise = left = lower heading
        self.unwrapped -= (yaw - self.bias) * dt
        # The cone shows where you face NOW (reacts in ~0.2 s); the map's walking direction
        # uses the slower 2 s median below so arm swing does not bend the line.
        if not self.phone_fresh:
            self.facing += (1.0 - math.exp(-dt / 0.2)) * (self.unwrapped - self.facing) if dt > 0 else 0.0
        self._window.append((t, self.unwrapped))
        while self._window and t - self._window[0][0] > MEDIAN_S:
            self._window.popleft()
        self.smooth = statistics.median(v for _, v in self._window)
        self.raw_heading = wrap_deg(self.smooth)
        self._update_grid(t)
        if self.step_source == "accel" and self._footfall(t, accel_norm):
            return self._advance_locked(t, 1)
        return None

    @property
    def phone_fresh(self) -> bool:
        return (self.use_phone_heading and self.phone_heading is not None
                and self.clock() - self._phone_wall < PHONE_FRESH_S)

    @property
    def heading_source(self) -> str:
        return "phone" if self.phone_fresh else "wrist"

    def _walk_heading(self) -> float:
        """The heading the grid follows: the iPhone's (body) heading while it is arriving,
        else the wrist's 2 s median."""
        if not self.phone_fresh:
            return self.smooth
        if self._phone_move_wall is not None and self._phone_ref is not None:
            return self._phone_ref        # undecided: body turn or phone moved in the hand
        return self.phone_heading

    def _update_grid(self, t: float):
        src = self._walk_heading()
        if not self.snap_turns:
            self.heading = src
            return
        if abs(src - self.heading) <= SNAP_HYST_DEG:
            self._away_since = None
            return
        if self._away_since is None:
            self._away_since = t
            return
        if t - self._away_since >= SNAP_HOLD_S:
            self.heading = 90.0 * round(src / 90.0)
            self._away_since = None

    # --- iPhone sensor fusion ------------------------------------------------------
    def _phone_turn_check(self, now: float) -> None:
        """A real body turn shows on the phone AND the wrist; taking the phone out of a pocket or
        tilting it in a hand shows on the phone only. Once the phone settles, compare the two and
        re-align the phone when the wrist did not turn with it."""
        ph = self.phone_heading
        if self._phone_ref is None:
            self._phone_ref, self._wrist_ref, self._phone_prev = ph, self.smooth, ph
            return
        moving = abs(ph - (self._phone_prev if self._phone_prev is not None else ph)) > 1.5   # deg per 0.1 s
        self._phone_prev = ph
        if self._phone_move_wall is None:
            if abs(ph - self._phone_ref) >= PHONE_MOVE_DEG:
                self._phone_move_wall, self._phone_still_wall = now, None
            elif not moving:
                self._phone_ref, self._wrist_ref = ph, self.smooth      # follow small drifts
            return
        if moving:
            self._phone_still_wall = None
            return
        if self._phone_still_wall is None:
            self._phone_still_wall = now
        if now - self._phone_still_wall < PHONE_SETTLE_S or now - self._phone_move_wall < PHONE_DECIDE_S:
            return
        dp = ph - self._phone_ref
        dw = self.smooth - self._wrist_ref
        if self.calibrated and abs(dw) < abs(dp) / 3.0:
            # the wrist did not turn: the phone moved in the hand; keep the walking direction
            self._phone_base += dp
            self.phone_heading = self.facing = self._phone_ref
            self.phone_handled += 1
        else:
            self._phone_ref, self._wrist_ref = ph, self.smooth
        self._phone_move_wall = None

    def on_phone(self, msg: dict) -> None:
        """One {"type": "phone_motion"} message from the iPhone app: heading_deg (clockwise,
        unwrapped, gyro fusion), steps and distance_m (Apple's pedometer since the app started).
        The phone in a pocket turns with the body and does not swing like a wrist, so while these
        arrive its heading drives the walking direction, and its pedometer sets the stride."""
        with self._lock:
            h = msg.get("heading_deg")
            if isinstance(h, (int, float)):
                self._phone_raw = float(h)
                if self.running:
                    if self._phone_base is None:
                        # heading 0 = the way you faced at start; if the route is already under
                        # way, line the phone up with the walking direction so far
                        self._phone_base = float(h) - (self.smooth if self.calibrated else 0.0)
                    self.phone_heading = float(h) - self._phone_base
                    if self.use_phone_heading:
                        self.facing = self.phone_heading
                    self._phone_wall = self.clock()
                    self._phone_turn_check(self._phone_wall)
            steps, dist = msg.get("steps"), msg.get("distance_m")
            if isinstance(steps, int) and isinstance(dist, (int, float)):
                self.phone_steps, self.phone_distance = steps, float(dist)
                if steps >= PHONE_STRIDE_MIN_STEPS and dist > 0:
                    self.step_length_m = min(1.0, max(0.4, dist / steps))

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
            off = abs(self._walk_heading() - self.heading)
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
            if self._last_steps is None or not (self.calibrated or self.phone_fresh):
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
            self.heading = self.unwrapped = self.smooth = self.facing = float(wrap_deg(heading_deg))
            if self._phone_raw is not None:
                self._phone_base = self._phone_raw - self.heading
                self.phone_heading = self._phone_ref = self.heading
                self._phone_move_wall = None
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


def tracker_status(tracker) -> dict:
    """A small live snapshot for the map page (sent a few times a second): whether the
    route is recording, whether the gyro is calibrated yet, where the wearer faces right
    now (even standing still), and the step counts from both sources."""
    live = getattr(tracker, "facing", None)
    return {
        "type": "tracker",
        "model": type(tracker).__name__,
        "running": bool(tracker.running),
        "calibrated": bool(tracker.calibrated),
        "live_heading_deg": round(wrap_deg(tracker.raw_heading if live is None else live), 1),
        "walk_heading_deg": round(wrap_deg(tracker.heading), 1),
        "steps": tracker.pose.steps,
        "motion_steps": getattr(tracker, "acc_steps", None),
        "band_steps": getattr(tracker, "band_steps", None),
        "step_source": getattr(tracker, "step_source", "band"),
        "bias_dps": round(tracker.bias, 2),
        "uncertain": bool(tracker.heading_uncertain),
        "state": tracker.state,
        "heading_source": getattr(tracker, "heading_source", "wrist"),
        "stride_m": round(tracker.step_length_m, 2),
        "phone_steps": getattr(tracker, "phone_steps", None),
        "phone_handled": getattr(tracker, "phone_handled", 0),
    }
