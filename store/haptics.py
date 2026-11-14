"""Haptic coach: turns "which way am I facing" + "which way is the route" into buzz cues
for the phone in your pocket. The band cannot vibrate, so the phone does.

Every few times a second, HapticCoach.update() compares the wearer's facing direction (the
wrist tracker's live heading) with the heading of the current leg of the guidance, and
returns a hint (for the phone's arrow) plus, when it is time, one cue to buzz:

    wrong_left / wrong_right   facing the wrong way: turn left / right (repeats)
    on_track                   now facing the right way (once, "locked on")
    tick                       still on track, light reassurance while walking
    turn_soon                  a turn is 1-4 steps ahead (ticks speed up)
    turn_left / turn_right / turn_around   turn now (once per corner)
    arrived                    stop: you have reached the place (once)
    lost                       stop: position uncertain, re-anchor (repeats)

Headings are clockwise from the route's start direction (see interfaces.py), so a positive
error means the route is to the right. Code computes every angle; nothing is guessed.
"""
import math
import time
from typing import Callable, Optional

# Vibration patterns for navigator.vibrate(): on, off, on, ... in milliseconds.
PATTERNS = {
    "wrong_left": [120, 120, 120],
    "wrong_right": [120, 120, 120, 120, 120],
    "on_track": [600],
    "tick": [50],
    "turn_soon": [80],
    "turn_left": [500, 150, 150],
    "turn_right": [500, 150, 150, 150, 150],
    "turn_around": [500, 150, 500],
    "arrived": [700, 200, 700, 200, 700],
    "lost": [100, 60, 100, 60, 100, 60, 100, 60, 100],
}

ON_TRACK_DEG = 30.0       # facing within this of the route counts as on track
WRONG_DEG = 50.0          # farther than this counts as the wrong way (hysteresis between)
REPEAT_WRONG_S = 2.5
REPEAT_TICK_S = 4.0
REPEAT_LOST_S = 4.0
TURN_SOON_STEPS = 4


def wrap(a: float) -> float:
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


class HapticCoach:
    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.aligned = False
        self._last = {}               # cue -> when it last fired
        self._nav = None              # the guidance session seen last time
        self._index = None            # its leg index seen last time
        self._arrived_sent = False

    def _due(self, cue: str, every: float) -> bool:
        now = self.clock()
        if now - self._last.get(cue, -1e9) >= every:
            self._last[cue] = now
            return True
        return False

    def update(self, nav, facing_deg: float, pose=None, uncertain: bool = False) -> dict:
        """One look at the situation. Returns {"hint": {...}, "cue": name or None}."""
        hint = {"type": "haptic_hint", "active": False}
        if nav is None:
            self._reset()
            return {"hint": hint, "cue": None}

        if nav is not self._nav:                 # a new trip
            self._reset()
            self._nav = nav
            self._index = nav.current_index

        segments = nav.segments
        arrived = (not nav.active) and nav.current_index >= len(segments)
        if arrived:
            hint.update(active=False, arrived=True, target=nav.target_name)
            if not self._arrived_sent:
                self._arrived_sent = True
                return {"hint": hint, "cue": "arrived"}
            return {"hint": hint, "cue": None}
        if not nav.active:                       # cancelled
            return {"hint": hint, "cue": None}

        if uncertain:
            hint.update(active=True, lost=True, target=nav.target_name)
            return {"hint": hint, "cue": "lost" if self._due("lost", REPEAT_LOST_S) else None}

        seg = segments[nav.current_index]
        error = wrap(seg.heading_deg - facing_deg)     # + : the route is to the right
        steps_left = None
        if pose is not None and nav.step_length_m > 0:
            steps_left = int(round(math.hypot(seg.end_x - pose.x_m, seg.end_y - pose.y_m) / nav.step_length_m))
        next_turn = None
        if nav.current_index + 1 < len(nav.instructions):
            t = nav.instructions[nav.current_index + 1].turn
            next_turn = t if t in ("left", "right", "around") else None
        hint.update(active=True, error_deg=round(error, 1), target=nav.target_name,
                    steps_left=steps_left, next_turn=next_turn, leg=nav.current_index)

        # A new leg began: "turn now", in the direction of this leg's instruction.
        if self._index != nav.current_index:
            self._index = nav.current_index
            self.aligned = False
            turn = nav.instructions[nav.current_index].turn
            if turn in ("left", "right", "around"):
                return {"hint": hint, "cue": "turn_" + turn}

        if abs(error) > WRONG_DEG or (not self.aligned and abs(error) > ON_TRACK_DEG):
            self.aligned = False
            cue = "wrong_right" if error > 0 else "wrong_left"
            hint["state"] = cue
            return {"hint": hint, "cue": cue if self._due("wrong", REPEAT_WRONG_S) else None}

        hint["state"] = "on_track"
        if not self.aligned:
            self.aligned = True
            self._last["tick"] = self.clock()
            return {"hint": hint, "cue": "on_track"}

        if next_turn and steps_left is not None and 1 <= steps_left <= TURN_SOON_STEPS:
            hint["state"] = "turn_soon"
            return {"hint": hint, "cue": "turn_soon" if self._due("turn_soon", 0.35 * steps_left) else None}
        return {"hint": hint, "cue": "tick" if self._due("tick", REPEAT_TICK_S) else None}

    def _reset(self):
        self.aligned = False
        self._last = {}
        self._nav = None
        self._index = None
        self._arrived_sent = False


def cue_message(cue: str, hint: dict) -> dict:
    """The message the phone page receives for one buzz."""
    return {"type": "haptic", "cue": cue, "pattern": PATTERNS[cue], "target": hint.get("target"),
            "error_deg": hint.get("error_deg")}
