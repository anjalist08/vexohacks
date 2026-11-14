"""Routes, landmarks, notes, and guidance computed from the recorded path.

The laptop JSON file is the source of truth. A route is a personal route graph: each
recorded point is a node, each walked step is an edge, and a re-anchor ("I'm at the
elevator", or arriving somewhere) adds a zero-length edge saying two points are the same
place. Guidance is the shortest path through that graph, in either direction. It never
uses a map, and the model never supplies a coordinate.
"""
import heapq
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
    breaks: List[List[int]] = field(default_factory=list)  # [j, k]: point j was reached by a re-anchor jump,
                                                            # not a walk; it is the same place as point k (-1: unknown)

    def to_dict(self):
        return {"id": self.id, "title": self.title, "active": self.active,
                "points": [p.to_dict() for p in self.points],
                "landmarks": [l.to_dict() for l in self.landmarks], "notes": self.notes, "breaks": self.breaks}

    @staticmethod
    def from_dict(d):
        return Route(d["id"], d["title"], [PoseSample(**p) for p in d["points"]],
                     [Landmark(**l) for l in d["landmarks"]], d.get("notes", []), d.get("active", False),
                     d.get("breaks", []))


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

    def add_point(self, sample: PoseSample, jump: bool = False, same_as: int = None):
        """Record a point. jump=True: the position was reset (re-anchor), so the line to it
        was never walked and is neither drawn nor used for guidance. same_as: the index of the
        earlier point it is the same place as, which links the two in the route graph."""
        if self.current and self.current.active:
            if jump:
                self.current.breaks.append([len(self.current.points), -1 if same_as is None else same_as])
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

    def route_path(self, start: int, goal: int) -> Optional[List[int]]:
        """Shortest path of point indices from start to goal through the route graph, or None."""
        pts = self.current.points
        jumps = {j: k for j, k in self.current.breaks}
        adj = {i: [] for i in range(len(pts))}
        for i in range(1, len(pts)):
            if i in jumps:
                continue
            d = math.hypot(pts[i].x_m - pts[i - 1].x_m, pts[i].y_m - pts[i - 1].y_m)
            adj[i - 1].append((i, d))
            adj[i].append((i - 1, d))
        for j, k in jumps.items():
            if 0 <= k < len(pts):
                adj[j].append((k, 0.0))
                adj[k].append((j, 0.0))
        best = {start: 0.0}
        prev = {}
        queue = [(0.0, start)]
        while queue:
            d, i = heapq.heappop(queue)
            if i == goal:
                path = [goal]
                while path[-1] != start:
                    path.append(prev[path[-1]])
                return list(reversed(path))
            if d > best.get(i, math.inf):
                continue
            for j, w in adj[i]:
                if d + w < best.get(j, math.inf):
                    best[j] = d + w
                    prev[j] = i
                    heapq.heappush(queue, (d + w, j))
        return None

    def _walked_pairs(self, target_index: int) -> Optional[List[Tuple[PoseSample, PoseSample]]]:
        """(a, b) steps from the current point to target_index along walked edges, or None."""
        pts = self.current.points
        path = self.route_path(len(pts) - 1, target_index)
        if path is None:
            return None
        jumps = {j for j, k in self.current.breaks}
        return [(pts[a], pts[b]) for a, b in zip(path, path[1:])
                if abs(a - b) == 1 and max(a, b) not in jumps]       # skip same-place links

    def distance_back(self, target_index: int) -> float:
        pairs = self._walked_pairs(target_index) or []
        return sum(math.hypot(b.x_m - a.x_m, b.y_m - a.y_m) for a, b in pairs)

    def return_segments(self, target_index: int) -> Optional[List[dict]]:
        """The walked path from here to target_index, merged into straight segments.
        None if the route graph has no walked path there.

        Each segment: {"heading": deg, "dist": m, "start": (x, y), "end": (x, y)}, in walking
        order. Consecutive segments join end to start, so the corners form a polyline.
        """
        pairs = self._walked_pairs(target_index)
        if pairs is None:
            return None
        raw = []    # [heading, dx, dy, start_x, start_y]
        for a, b in pairs:
            dx, dy = b.x_m - a.x_m, b.y_m - a.y_m
            if math.hypot(dx, dy) < 1e-6:
                continue
            h = math.degrees(math.atan2(dx, dy))
            if raw and abs(_wrap(h - raw[-1][0])) <= config.SEGMENT_MERGE_DEG:
                seg = raw[-1]
                seg[1] += dx
                seg[2] += dy
                seg[0] = math.degrees(math.atan2(seg[1], seg[2]))
            else:
                raw.append([h, dx, dy, a.x_m, a.y_m])
        out = []
        for h, dx, dy, sx, sy in raw:
            if math.hypot(dx, dy) < config.MIN_SEGMENT_M:
                continue
            start = out[-1]["end"] if out else (sx, sy)       # keep the polyline connected
            end = (sx + dx, sy + dy)
            dist = math.hypot(end[0] - start[0], end[1] - start[1])
            out.append({"heading": math.degrees(math.atan2(end[0] - start[0], end[1] - start[1])),
                        "dist": dist, "start": start, "end": end})
        return out

    def plan_return(self, target_index: int, target_name: str, facing_deg: float,
                    step_length_m: float = None) -> List[Instruction]:
        """Turn-by-turn steps along the recorded path, back to target_index."""
        step_len = step_length_m or config.STEP_LENGTH_M
        out: List[Instruction] = []
        facing = facing_deg
        for seg in self.return_segments(target_index) or []:
            h, dist = seg["heading"], seg["dist"]
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
