"""Routes, landmarks, notes, and return guidance computed from the recorded path.

The laptop JSON file is the source of truth. Return guidance walks the saved points
backwards: it never uses a map, and the model never supplies a coordinate.
"""
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import config
from interfaces import Instruction, Landmark, PoseSample

STOPWORDS = {"the", "a", "an", "to", "back", "where", "was", "is", "my", "me", "take", "i", "of", "this",
             "that", "it", "go", "get", "find", "please", "at", "by", "near", "next", "in", "on", "and",
             "did", "we", "us", "our", "place", "spot", "called", "remember", "as"}


def words(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOPWORDS]


def _wrap(a: float) -> float:
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


@dataclass
class Route:
    id: str
    title: str
    points: List[PoseSample] = field(default_factory=list)
    landmarks: List[Landmark] = field(default_factory=list)
    notes: List[dict] = field(default_factory=list)       # {"point_index", "text"} not tied to a landmark
    active: bool = True

    def to_dict(self):
        return {"id": self.id, "title": self.title, "active": self.active,
                "points": [p.to_dict() for p in self.points],
                "landmarks": [l.to_dict() for l in self.landmarks], "notes": self.notes}

    @staticmethod
    def from_dict(d):
        return Route(d["id"], d["title"], [PoseSample(**p) for p in d["points"]],
                     [Landmark(**l) for l in d["landmarks"]], d.get("notes", []), d.get("active", False))


class RouteStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self.routes: List[Route] = []
        self._next_landmark = 1
        if path and os.path.exists(path):
            self.load(path)

    # --- recording ---------------------------------------------------------------
    @property
    def current(self) -> Optional[Route]:
        return self.routes[-1] if self.routes else None

    def start_route(self, title: str, first_point: PoseSample) -> Route:
        if self.current:
            self.current.active = False
        route = Route("r%d" % (len(self.routes) + 1), title or "route %d" % (len(self.routes) + 1), [first_point])
        self.routes.append(route)
        return route

    def stop_route(self):
        if self.current:
            self.current.active = False
        self.save()

    def add_point(self, sample: PoseSample):
        if self.current and self.current.active:
            self.current.points.append(sample)

    # --- landmarks and notes ---------------------------------------------------
    def all_landmarks(self) -> List[Landmark]:
        return [l for r in self.routes for l in r.landmarks]

    def get_landmark(self, landmark_id: str) -> Optional[Landmark]:
        for l in self.all_landmarks():
            if l.id == landmark_id:
                return l
        return None

    def route_of(self, landmark: Landmark) -> Route:
        for r in self.routes:
            if landmark in r.landmarks:
                return r
        raise KeyError(landmark.id)

    def remember_landmark(self, label: str, floor: str = None, note: str = None, transcript: str = None) -> Landmark:
        route = self.current
        if route is None:
            raise ValueError("no route")
        lm = Landmark("lm%d" % self._next_landmark, label.strip(), len(route.points) - 1, floor, note, transcript)
        self._next_landmark += 1
        route.landmarks.append(lm)
        self.save()
        return lm

    def save_note(self, text: str, landmark_id: str = None):
        if landmark_id:
            lm = self.get_landmark(landmark_id)
            if lm is None:
                raise KeyError(landmark_id)
            lm.note = text if not lm.note else lm.note + "; " + text
            self.save()
            return lm
        if self.current is None:
            raise ValueError("no route")
        self.current.notes.append({"point_index": len(self.current.points) - 1, "text": text})
        self.save()
        return None

    def find_landmark(self, query: str) -> List[Tuple[Landmark, float]]:
        """Landmarks whose label (or note) shares words with the query, best first."""
        q = set(words(query))
        if not q:
            return []
        found = []
        for lm in self.all_landmarks():
            label = set(words(lm.label))
            note = set(words(lm.note or ""))
            score = len(q & label) / max(1, len(label)) + 0.5 * len(q & note) / max(1, len(note) or 1)
            if score > 0:
                found.append((lm, round(score, 3)))
        found.sort(key=lambda p: -p[1])
        return found

    # --- return guidance -----------------------------------------------------------
    def path_back(self, target_index: int) -> List[PoseSample]:
        """Points from the current position back to target_index, in walking order."""
        pts = self.current.points
        return list(reversed(pts[target_index:]))

    def distance_back(self, target_index: int) -> float:
        pts = self.path_back(target_index)
        return sum(math.hypot(b.x_m - a.x_m, b.y_m - a.y_m) for a, b in zip(pts, pts[1:]))

    def plan_return(self, target_index: int, target_name: str, facing_deg: float,
                    step_length_m: float = None) -> List[Instruction]:
        """Turn-by-turn steps along the recorded path, back to target_index."""
        step_len = step_length_m or config.STEP_LENGTH_M
        pts = self.path_back(target_index)

        segments = []    # [heading, dx, dy]
        for a, b in zip(pts, pts[1:]):
            dx, dy = b.x_m - a.x_m, b.y_m - a.y_m
            if math.hypot(dx, dy) < 1e-6:
                continue
            h = math.degrees(math.atan2(dx, dy))
            if segments and abs(_wrap(h - segments[-1][0])) <= config.SEGMENT_MERGE_DEG:
                seg = segments[-1]
                seg[1] += dx
                seg[2] += dy
                seg[0] = math.degrees(math.atan2(seg[1], seg[2]))
            else:
                segments.append([h, dx, dy])
        segments = [s for s in segments if math.hypot(s[1], s[2]) >= config.MIN_SEGMENT_M]

        out: List[Instruction] = []
        facing = facing_deg
        for h, dx, dy in segments:
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
            out.append(Instruction(turn, steps, round(dist, 2), text))
            facing = h
        out.append(Instruction("arrive", 0, 0.0, "You have reached the %s." % target_name))
        return out

    # --- files ---------------------------------------------------------------------
    def save(self, path: str = None):
        path = path or self.path
        if not path:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump({"routes": [r.to_dict() for r in self.routes], "next_landmark": self._next_landmark}, f, indent=1)

    def load(self, path: str):
        with open(path) as f:
            d = json.load(f)
        self.routes = [Route.from_dict(r) for r in d.get("routes", [])]
        self._next_landmark = d.get("next_landmark", len(self.all_landmarks()) + 1)

    def delete_all(self):
        """The user's delete control: forget every route and landmark."""
        self.routes = []
        self._next_landmark = 1
        if self.path and os.path.exists(self.path):
            os.remove(self.path)
