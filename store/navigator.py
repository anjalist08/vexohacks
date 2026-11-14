"""Live guidance along the recorded path: the product's own router.

There is no map service indoors (no GPS, no floor plan), so the route is the path the
person actually walked, walked backwards. The navigator follows each new position from
the tracker and says what to do next:

- "In 4 steps, turn left." ahead of each corner, then "Turn left now, then walk 18 steps."
- The LED blinks white faster as the corner gets closer (turn_now), then breathes white.
- Arrival within ARRIVE_STEPS of the destination: spoken, green then rainbow, and the
  position is reset to the destination to cancel drift.
- Off route (farther than OFF_ROUTE_M from the path) or the wrong way: red blink and a
  request to re-anchor ("I'm at the elevator").

Code computes every position, distance and turn. The model only chooses the destination.
"""
import math
from typing import List, Optional, Tuple

import config
from interfaces import Instruction, PoseSample, ToolResult
from voice.led_states import turn_now_period

UNCERTAIN = "I'm not sure where we are. Say where you are to re-anchor, or go back the way you came."


def _project(p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]):
    """Closest point on segment a-b to p: returns (fraction 0..1, distance)."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    cx, cy = ax + t * dx, ay + t * dy
    return t, math.hypot(p[0] - cx, p[1] - cy)


class Navigator:
    def __init__(self, segments: List[dict], instructions: List[Instruction], target_name: str,
                 step_length_m: float):
        self.segments = segments
        self.instructions = instructions          # one per segment, then "arrive"
        self.target_name = target_name
        self.step_len = step_length_m
        self.corners = [segments[0]["start"]] + [s["end"] for s in segments] if segments else []
        self.cum = [0.0]
        for s in segments:
            self.cum.append(self.cum[-1] + s["dist"])
        self.total = self.cum[-1]
        self.progress = 0.0
        self.max_progress = 0.0
        self.offset = 0.0
        self.seg = 0
        self.warned = set()
        self.turned = set()
        self.passed = set()
        self.off_route = False
        self.wrong_way = False
        self._off_count = 0
        self.arrived = not segments

    @property
    def target(self) -> Optional[Tuple[float, float]]:
        return self.corners[-1] if self.corners else None

    def steps(self, metres: float) -> int:
        return max(0, int(round(metres / self.step_len)))

    # --- following the walker ----------------------------------------------------
    def update(self, pose: PoseSample) -> List[ToolResult]:
        """A new position. Returns what to say and show now (often nothing)."""
        if self.arrived:
            return []
        out: List[ToolResult] = []
        self._locate((pose.x_m, pose.y_m))

        # Off the path, or walking away from the destination.
        if self.offset > config.OFF_ROUTE_M:
            self._off_count += 1
            if self._off_count >= 3 and not self.off_route:
                self.off_route = True
                out.append(ToolResult(False, UNCERTAIN, "uncertain", {"nav": "off-route"}))
            return out
        self._off_count = 0
        if self.off_route and self.offset < config.OFF_ROUTE_M * 0.6:
            self.off_route = False
            out.append(ToolResult(True, "Back on the route. " + self.next_text(), "navigating", {"nav": "back"}))
        if self.max_progress - self.progress > config.WRONG_WAY_M and not self.wrong_way:
            self.wrong_way = True
            out.append(ToolResult(False, "You're walking away from the %s. Turn around." % self.target_name,
                                  "uncertain", {"nav": "wrong-way"}))
        elif self.wrong_way and self.progress >= self.max_progress - 1.0:
            self.wrong_way = False
            out.append(ToolResult(True, "That's right. " + self.next_text(), "navigating", {"nav": "back"}))
        self.max_progress = max(self.max_progress, self.progress)

        # Arrived.
        if self.total - self.progress <= config.ARRIVE_STEPS * self.step_len:
            self.arrived = True
            out.append(ToolResult(True, "You have reached the %s." % self.target_name, "arrived", {"nav": "arrived"}))
            return out

        # Corners ahead.
        for k in range(1, len(self.segments)):
            ahead = self.cum[k] - self.progress
            turn = self.instructions[k].turn
            if ahead < -1.0:
                if k in self.turned and k not in self.passed:
                    self.passed.add(k)
                    out.append(ToolResult(True, "", "navigating", {"nav": "passed", "corner": k}))
                continue
            n = ahead / self.step_len
            walk_after = self.instructions[k].steps
            if n <= config.TURN_NOW_STEPS and k not in self.turned:
                self.turned.add(k)
                self.warned.add(k)
                out.append(ToolResult(True, "%s now, then walk %d steps." % (_verb(turn), walk_after), "turn_now",
                                      {"nav": "turn", "corner": k, "led_period": turn_now_period(0)}))
            elif n <= config.TURN_WARN_STEPS and k not in self.warned:
                self.warned.add(k)
                out.append(ToolResult(True, "In %d steps, %s." % (max(1, round(n)), _verb(turn).lower()), "turn_now",
                                      {"nav": "warn", "corner": k, "led_period": turn_now_period(round(n))}))
            break       # only the next corner matters
        return out

    def _locate(self, p):
        """Project p onto the path, searching from the segment before the current one."""
        best = None
        for j in range(max(0, self.seg - 1), len(self.segments)):
            t, d = _project(p, self.corners[j], self.corners[j + 1])
            if best is None or d < best[2] - 1e-9:
                best = (j, t, d)
        if best is None:
            return
        j, t, d = best
        self.seg = j
        self.progress = self.cum[j] + t * self.segments[j]["dist"]
        self.offset = d

    # --- for speech and the dashboard -------------------------------------------
    def next_text(self) -> str:
        for k in range(1, len(self.segments)):
            ahead = self.cum[k] - self.progress
            if ahead > 0:
                return "In %d steps, %s." % (max(1, self.steps(ahead)), _verb(self.instructions[k].turn).lower())
        return "Walk %d steps to the %s." % (max(1, self.steps(self.total - self.progress)), self.target_name)

    def status(self) -> dict:
        next_turn, to_turn = None, None
        for k in range(1, len(self.segments)):
            ahead = self.cum[k] - self.progress
            if ahead > 0:
                next_turn, to_turn = self.instructions[k].turn, self.steps(ahead)
                break
        return {"target": self.target_name, "segment": self.seg, "progress_m": round(self.progress, 2),
                "total_m": round(self.total, 2), "remaining_steps": self.steps(self.total - self.progress),
                "next_turn": next_turn, "steps_to_turn": to_turn, "offset_m": round(self.offset, 2),
                "off_route": self.off_route, "wrong_way": self.wrong_way, "arrived": self.arrived,
                "corners": [[round(x, 3), round(y, 3)] for x, y in self.corners]}


def _verb(turn: str) -> str:
    return {"left": "Turn left", "right": "Turn right", "around": "Turn around"}.get(turn, "Keep going")
