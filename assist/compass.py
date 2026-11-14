"""Correct gyro drift with the phone's compass.

The band has no compass, so its heading drifts. A phone does have one. Only the change
since "start route" is used: the first steady reading becomes heading 0, so it does not
matter how the phone sits in the pocket, as long as it stays put (the same rule as
wearing the band the same way).

Indoors a compass is easily thrown off by steel and electronics, so a correction is made
only when all of these hold:
- the readings of the last WINDOW_S seconds agree within MAX_SPREAD_DEG,
- they point within MAX_OFF_GRID_DEG of a 90-degree direction (the hallway grid that the
  tracker's turn snapping already assumes),
- that direction differs from the tracker's heading, and has done so for HOLD_S seconds.
Then the tracker is re-anchored to that direction at its current position.

All thresholds are PLACEHOLDERS until a real walk measures them. Quote no accuracy gain
from this until then. Without turn snapping (config.SNAP_TURNS False) nothing is corrected.
"""
import math
from collections import deque
from typing import Optional

WINDOW_S = 2.0
MAX_SPREAD_DEG = 15.0
MAX_OFF_GRID_DEG = 20.0
HOLD_S = 3.0


def wrap_deg(a: float) -> float:
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


def circular_mean(degs):
    """(mean in degrees, spread in degrees) of a list of angles."""
    s = sum(math.sin(math.radians(d)) for d in degs) / len(degs)
    c = sum(math.cos(math.radians(d)) for d in degs) / len(degs)
    r = min(1.0, math.hypot(s, c))
    spread = math.degrees(math.sqrt(-2.0 * math.log(r))) if r > 1e-9 else 180.0
    return math.degrees(math.atan2(s, c)), spread


class CompassCorrector:
    def __init__(self, tracker, window_s=WINDOW_S, max_spread_deg=MAX_SPREAD_DEG,
                 max_off_grid_deg=MAX_OFF_GRID_DEG, hold_s=HOLD_S):
        self.tracker = tracker
        self.window_s = window_s
        self.max_spread_deg = max_spread_deg
        self.max_off_grid_deg = max_off_grid_deg
        self.hold_s = hold_s
        self.corrections = 0
        self.reset()

    def reset(self):
        """Call at "start route": the next steady reading becomes heading 0."""
        self.reference: Optional[float] = None
        self._readings = deque()
        self._candidate: Optional[float] = None
        self._candidate_since: Optional[float] = None

    def on_compass(self, t: float, heading_deg: float) -> Optional[float]:
        """One reading: t in seconds, heading clockwise from north. Returns a new route
        heading when it corrected the tracker, else None."""
        self._readings.append((t, heading_deg % 360.0))
        while self._readings and self._readings[0][0] < t - self.window_s:
            self._readings.popleft()
        if len(self._readings) < 3 or self._readings[-1][0] - self._readings[0][0] < 0.5 * self.window_s:
            return None
        mean, spread = circular_mean([d for _, d in self._readings])
        if spread > self.max_spread_deg:          # turning, or a magnetic disturbance
            self._candidate = None
            return None
        if self.reference is None:
            self.reference = mean
            return None
        if not getattr(self.tracker, "snap_turns", True) or not self.tracker.running:
            return None
        rel = wrap_deg(mean - self.reference)
        target = wrap_deg(90.0 * round(rel / 90.0))
        if abs(wrap_deg(rel - target)) > self.max_off_grid_deg or \
                abs(wrap_deg(target - self.tracker.heading)) < 1.0:
            self._candidate = None
            return None
        if self._candidate != target:
            self._candidate, self._candidate_since = target, t
            return None
        if t - self._candidate_since < self.hold_s:
            return None
        pose = self.tracker.pose
        self.tracker.reanchor(pose.x_m, pose.y_m, target, t)
        self.corrections += 1
        self._candidate = None
        return target
