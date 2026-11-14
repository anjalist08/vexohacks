"""Routes, landmarks, notes, and return guidance computed from the recorded path.

The laptop JSON file is the source of truth. Return guidance walks the saved points
backwards: it never uses a map, and the model never supplies a coordinate.

A re-anchor (arriving somewhere, or "I'm at the elevator") resets the position. The point
it adds is a jump, listed in Route.breaks: it was never walked, so it is not drawn or used
as a path, and it is linked to the earlier point at the same place, so guidance can route
through that place in either direction.
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
from store.guidance import GuidanceSession, build_guidance_session

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
    breaks: List[int] = field(default_factory=list)       # indices of points reached by a re-anchor jump

    def to_dict(self):
        return {"id": self.id, "title": self.title, "active": self.active,
                "points": [p.to_dict() for p in self.points],
                "landmarks": [l.to_dict() for l in self.landmarks], "notes": self.notes,
                "breaks": self.breaks}

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

    def add_point(self, sample: PoseSample, jump: bool = False):
        """Record a point. jump=True: a re-anchor put the walker here; nobody walked the line to it."""
        if self.current and self.current.active:
            if jump:
                self.current.breaks.append(len(self.current.points))
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
    def path_back(self, target_index: int, from_pose: Optional[PoseSample] = None) -> List[PoseSample]:
        """Points from the current position back to target_index, in walking order."""
        pts = self.current.points
        if not pts:
            return []
        at_last = from_pose is None or math.hypot(from_pose.x_m - pts[-1].x_m, from_pose.y_m - pts[-1].y_m) <= 1e-4
        if at_last and not self.current.breaks:
            return list(reversed(pts[target_index:]))
        if at_last:
            from_idx = len(pts) - 1
        else:
            # Walker moved during a previous return trip without appending reverse points:
            # start from the closest recorded point on the route.
            from_idx = min(
                range(len(pts)),
                key=lambda idx: math.hypot(from_pose.x_m - pts[idx].x_m, from_pose.y_m - pts[idx].y_m),
            )
        if self.current.breaks:
            order = self._graph_path(from_idx, target_index)
        elif from_idx >= target_index:
            order = list(range(from_idx, target_index - 1, -1))
        else:
            order = list(range(from_idx, target_index + 1))
        sub = []
        for i in order:      # same-place links add a duplicate point: keep one
            if not sub or math.hypot(pts[i].x_m - sub[-1].x_m, pts[i].y_m - sub[-1].y_m) > 1e-6:
                sub.append(pts[i])
        if not at_last and sub and math.hypot(from_pose.x_m - sub[0].x_m, from_pose.y_m - sub[0].y_m) > 0.25:
            sub = [from_pose] + sub
        return sub

    def _graph_path(self, start: int, goal: int) -> List[int]:
        """Shortest index path through the route graph: walked steps are edges, and each jump
        point is linked (length 0) to the earlier point at the same place. A jump is never an edge."""
        pts = self.current.points
        breaks = set(self.current.breaks)
        adj = {i: [] for i in range(len(pts))}
        for i in range(1, len(pts)):
            if i not in breaks:
                d = math.hypot(pts[i].x_m - pts[i - 1].x_m, pts[i].y_m - pts[i - 1].y_m)
                adj[i - 1].append((i, d))
                adj[i].append((i - 1, d))
        for j in breaks:
            same = [k for k in range(j) if k not in breaks
                    and math.hypot(pts[k].x_m - pts[j].x_m, pts[k].y_m - pts[j].y_m) <= 0.05]
            for k in same:
                adj[j].append((k, 0.0))
                adj[k].append((j, 0.0))
        best, prev, queue = {start: 0.0}, {}, [(0.0, start)]
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
                    best[j], prev[j] = d + w, i
                    heapq.heappush(queue, (d + w, j))
        return [start]       # no walked path: guidance will say it is already there

    def distance_back(self, target_index: int) -> float:
        pts = self.path_back(target_index)
        return sum(math.hypot(b.x_m - a.x_m, b.y_m - a.y_m) for a, b in zip(pts, pts[1:]))

    def plan_return_session(self, target_index: int, target_name: str, facing_deg: float,
                            step_length_m: Optional[float] = None,
                            from_pose: Optional[PoseSample] = None) -> GuidanceSession:
        """Build a step-by-step GuidanceSession back to target_index."""
        pts = self.path_back(target_index, from_pose=from_pose)
        return build_guidance_session(pts, target_name, facing_deg, step_length_m)

    def plan_return(self, target_index: int, target_name: str, facing_deg: float,
                    step_length_m: float = None) -> List[Instruction]:
        """Turn-by-turn steps along the recorded path, back to target_index."""
        return self.plan_return_session(target_index, target_name, facing_deg, step_length_m).instructions

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
