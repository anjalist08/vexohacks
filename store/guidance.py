"""Step-by-step return guidance session that advances as PoseSamples arrive.

All geometry (segment merging, turn angles, waypoint distances, projected progress)
is computed deterministically in code from the recorded route points.
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import config
from interfaces import Instruction, PoseSample
from voice.led_states import turn_now_period

TURN_DIRECTIONS = ("left", "right", "around")


def _wrap(a: float) -> float:
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


@dataclass
class GuidanceSegment:
    """One straight leg of a planned return route."""
    index: int
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    heading_deg: float
    distance_m: float
    steps: int
    instruction: Instruction

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "start_x": round(self.start_x, 3),
            "start_y": round(self.start_y, 3),
            "end_x": round(self.end_x, 3),
            "end_y": round(self.end_y, 3),
            "heading_deg": round(self.heading_deg, 1),
            "distance_m": round(self.distance_m, 2),
            "steps": self.steps,
            "instruction": self.instruction.to_dict(),
        }


@dataclass
class GuidanceUpdate:
    """State changes produced by feeding one PoseSample to GuidanceSession."""
    advanced: bool = False
    arrived: bool = False
    say: Optional[str] = None
    led: Optional[str] = None
    led_period: Optional[int] = None
    current_index: int = 0
    steps_left: Optional[int] = None


@dataclass
class GuidanceSession:
    """Tracks progress along a planned return trip as the user walks."""
    target_name: str
    target_x: float
    target_y: float
    step_length_m: float
    segments: List[GuidanceSegment] = field(default_factory=list)
    instructions: List[Instruction] = field(default_factory=list)
    waypoints: List[Tuple[float, float]] = field(default_factory=list)
    current_index: int = 0
    active: bool = True
    _last_turn_steps_left: Optional[int] = field(default=None, repr=False)
    _awaiting_turn_align: bool = field(default=False, repr=False)

    @property
    def arrival_radius_m(self) -> float:
        return max(self.step_length_m * 1.15, 0.85)

    @property
    def current_instruction(self) -> Optional[Instruction]:
        if 0 <= self.current_index < len(self.instructions):
            return self.instructions[self.current_index]
        return None

    def cancel(self) -> None:
        self.active = False

    def to_dict(self) -> dict:
        return {
            "instructions": [i.to_dict() for i in self.instructions],
            "current_index": self.current_index,
            "active": self.active,
            "target_name": self.target_name,
            "waypoints": [[round(x, 3), round(y, 3)] for x, y in self.waypoints],
        }

    def update(self, sample: PoseSample) -> GuidanceUpdate:
        """Advance guidance state from a newly emitted PoseSample."""
        if not self.active or not self.instructions:
            return GuidanceUpdate(current_index=self.current_index)

        if self.current_index >= len(self.segments):
            # Already at the terminal "arrive" instruction.
            self.active = False
            arrive = self.instructions[-1]
            return GuidanceUpdate(
                advanced=True,
                arrived=True,
                say=arrive.text,
                led="arrived",
                current_index=len(self.instructions) - 1,
                steps_left=0,
            )

        seg = self.segments[self.current_index]
        px, py = sample.x_m, sample.y_m
        dx = seg.end_x - seg.start_x
        dy = seg.end_y - seg.start_y
        seg_len = max(seg.distance_m, math.hypot(dx, dy))

        if seg_len > 1e-6:
            ux, uy = dx / seg_len, dy / seg_len
            proj = (px - seg.start_x) * ux + (py - seg.start_y) * uy
        else:
            proj = seg_len

        dist_to_end = math.hypot(seg.end_x - px, seg.end_y - py)
        is_final_leg = (self.current_index == len(self.segments) - 1)
        dist_to_dest = math.hypot(self.target_x - px, self.target_y - py)

        radius = self.arrival_radius_m
        reached_waypoint = (
            dist_to_end <= radius
            or proj >= seg_len - 0.5 * self.step_length_m
            or (is_final_leg and dist_to_dest <= radius)
        )

        if reached_waypoint:
            self.current_index += 1
            self._last_turn_steps_left = None
            next_inst = self.instructions[self.current_index]
            if next_inst.turn == "arrive" or self.current_index >= len(self.segments):
                self.active = False
                self._awaiting_turn_align = False
                return GuidanceUpdate(
                    advanced=True,
                    arrived=True,
                    say=next_inst.text,
                    led="arrived",
                    current_index=self.current_index,
                    steps_left=0,
                )

            is_turn = next_inst.turn in TURN_DIRECTIONS
            self._awaiting_turn_align = is_turn
            return GuidanceUpdate(
                advanced=True,
                arrived=False,
                say=next_inst.text,
                led="turn_now" if is_turn else "navigating",
                led_period=turn_now_period(0) if is_turn else None,
                current_index=self.current_index,
                steps_left=next_inst.steps,
            )

        # Not yet at waypoint: check if walker aligned onto this leg after a corner turn.
        aligned_now = False
        if self._awaiting_turn_align:
            heading_aligned = abs(_wrap(sample.heading_deg - seg.heading_deg)) <= 45.0
            if (heading_aligned and proj >= 0.1 * self.step_length_m) or proj >= 0.75 * self.step_length_m:
                self._awaiting_turn_align = False
                aligned_now = True

        # Check approaching turn at end of current walking segment.
        rem_m = min(dist_to_end, max(0.0, seg_len - proj)) if proj >= 0.0 else dist_to_end
        steps_left = int(round(rem_m / self.step_length_m))

        next_idx = self.current_index + 1
        next_is_turn = (
            next_idx < len(self.instructions)
            and self.instructions[next_idx].turn in TURN_DIRECTIONS
        )

        if next_is_turn and 1 <= steps_left <= 3:
            self._awaiting_turn_align = False
            if self._last_turn_steps_left is None or steps_left < self._last_turn_steps_left:
                self._last_turn_steps_left = steps_left
                return GuidanceUpdate(
                    advanced=False,
                    arrived=False,
                    led="turn_now",
                    led_period=turn_now_period(steps_left),
                    current_index=self.current_index,
                    steps_left=steps_left,
                )
            return GuidanceUpdate(current_index=self.current_index, steps_left=steps_left)

        if aligned_now:
            return GuidanceUpdate(
                advanced=False,
                arrived=False,
                led="navigating",
                current_index=self.current_index,
                steps_left=steps_left,
            )

        return GuidanceUpdate(current_index=self.current_index, steps_left=steps_left)


GuidanceNavigator = GuidanceSession


def build_guidance_session(
    pts: List[PoseSample],
    target_name: str,
    facing_deg: float,
    step_length_m: Optional[float] = None,
) -> GuidanceSession:
    """Build merged walking segments and spoken instructions along `pts`."""
    step_len = step_length_m or config.STEP_LENGTH_M
    if not pts:
        arrive = Instruction("arrive", 0, 0.0, "You have reached the %s." % target_name)
        return GuidanceSession(target_name, 0.0, 0.0, step_len, [], [arrive], [], 0, False)

    raw = []  # [heading, dx, dy, start_x, start_y, end_x, end_y]
    for a, b in zip(pts, pts[1:]):
        dx, dy = b.x_m - a.x_m, b.y_m - a.y_m
        if math.hypot(dx, dy) < 1e-6:
            continue
        h = math.degrees(math.atan2(dx, dy))
        if raw and abs(_wrap(h - raw[-1][0])) <= config.SEGMENT_MERGE_DEG:
            seg = raw[-1]
            seg[1] += dx
            seg[2] += dy
            seg[0] = math.degrees(math.atan2(seg[1], seg[2]))
            seg[5] = b.x_m
            seg[6] = b.y_m
        else:
            raw.append([h, dx, dy, a.x_m, a.y_m, b.x_m, b.y_m])

    kept = [s for s in raw if math.hypot(s[1], s[2]) >= config.MIN_SEGMENT_M]

    instructions: List[Instruction] = []
    segments: List[GuidanceSegment] = []
    waypoints: List[Tuple[float, float]] = [(pts[0].x_m, pts[0].y_m)]
    facing = facing_deg

    for idx, (h, dx, dy, sx, sy, ex, ey) in enumerate(kept):
        dist = math.hypot(dx, dy)
        steps = max(1, int(round(dist / step_len)))
        delta = _wrap(h - facing)
        if abs(delta) < 45:
            turn, text = "straight", "Walk straight %d steps." % steps
        elif abs(delta) > 135:
            turn, text = "around", "Turn around, walk %d steps." % steps
        elif delta > 0:
            turn, text = "right", "Turn right, walk %d steps." % steps
        else:
            turn, text = "left", "Turn left, walk %d steps." % steps
        inst = Instruction(turn, steps, round(dist, 2), text)
        instructions.append(inst)
        segments.append(GuidanceSegment(idx, sx, sy, ex, ey, h, dist, steps, inst))
        waypoints.append((ex, ey))
        facing = h

    target_x, target_y = pts[-1].x_m, pts[-1].y_m
    if waypoints[-1] != (target_x, target_y):
        waypoints.append((target_x, target_y))

    instructions.append(Instruction("arrive", 0, 0.0, "You have reached the %s." % target_name))
    active = len(segments) > 0
    return GuidanceSession(
        target_name=target_name,
        target_x=target_x,
        target_y=target_y,
        step_length_m=step_len,
        segments=segments,
        instructions=instructions,
        waypoints=waypoints,
        current_index=0,
        active=active,
    )
