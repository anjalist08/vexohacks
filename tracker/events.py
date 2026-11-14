"""Sensor events as plain data, so a live band, a logged walk and a synthetic walk
all feed the tracker the same way.

An event is a tuple (kind, t, fields):
    ("motion",   t, {"ax", "ay", "az", "gx", "gy", "gz"})   g and degrees/second
    ("activity", t, {"steps", "state"})                        lifetime steps, still/walk/run

Logs are CSV with the columns in COLUMNS. Every test walk should be logged: a real
logged walk replayed through the tracker is the Bronze demo fallback, and it must be
labelled as a replay.
"""
import csv
import math
import os
import random
import time
from typing import Iterable, List, Optional, Sequence, Tuple, Union

COLUMNS = ["kind", "t", "ax", "ay", "az", "gx", "gy", "gz", "steps", "state", "heading_deg", "distance_m"]
# kind "phone": the iPhone app's phone_motion (heading_deg, and steps + distance_m when known)
Event = Tuple[str, float, dict]


def feed(tracker, events: Iterable[Event]):
    """Push events into a PathTracker in order."""
    for kind, t, f in events:
        if kind == "motion":
            tracker.on_motion(t, f["ax"], f["ay"], f["az"], f["gx"], f["gy"], f["gz"])
        elif kind == "activity":
            tracker.on_activity(t, f["steps"], f["state"])
        elif kind == "phone" and hasattr(tracker, "on_phone"):
            tracker.on_phone(dict(f, type="phone_motion"))


class SampleLogger:
    """Append events to a timestamped CSV in log_dir."""

    def __init__(self, log_dir: str, label: str = "walk"):
        os.makedirs(log_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = os.path.join(log_dir, "%s-%s.csv" % (label, stamp))
        self._file = open(self.path, "w", newline="")
        self._csv = csv.DictWriter(self._file, fieldnames=COLUMNS)
        self._csv.writeheader()

    def log(self, kind: str, t: float, fields: dict):
        row = {"kind": kind, "t": "%.4f" % t}
        row.update({k: v for k, v in fields.items() if k in COLUMNS})
        self._csv.writerow(row)

    def flush(self):
        """Push what is logged so far to disk, so the map page can offer it while recording."""
        try:
            self._file.flush()
        except ValueError:      # closed
            pass

    def close(self):
        self._file.close()


def read_log(path: str) -> List[Event]:
    events = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t = float(row["t"])
            if row["kind"] == "motion":
                events.append(("motion", t, {k: float(row[k]) for k in ("ax", "ay", "az", "gx", "gy", "gz")}))
            elif row["kind"] == "activity":
                events.append(("activity", t, {"steps": int(row["steps"]), "state": row["state"]}))
            elif row["kind"] == "phone" and row.get("heading_deg"):
                f = {"heading_deg": float(row["heading_deg"])}
                if row.get("steps") and row.get("distance_m"):
                    f["steps"], f["distance_m"] = int(row["steps"]), float(row["distance_m"])
                events.append(("phone", t, f))
    return events


def write_log(path: str, events: Iterable[Event]):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for kind, t, fields in events:
            row = {"kind": kind, "t": "%.4f" % t}
            row.update(fields)
            w.writerow(row)


def synthetic_walk(legs: Sequence[Tuple[int, Optional[Union[str, float]]]] = ((20, "left"), (15, None)),
                   cadence: float = 110.0, motion_hz: float = 25.0, activity_hz: float = 10.0,
                   bias_dps: float = 0.8, noise_dps: float = 1.5, still_s: float = 2.5,
                   turn_s: float = 1.5, end_still_s: float = 1.0, start_steps: int = 5000,
                   t0: float = 1_700_000_000.0, seed: int = 1) -> List[Event]:
    """A made-up walk for tests and the --sim demo. Not real sensing.

    legs: (steps, then_turn) pairs; then_turn is "left", "right", "around", a yaw angle
    in degrees (+yaw = counter-clockwise), or None.
    The walker stops at each corner while turning, so the band reads "still" during
    turns, which is the case the plan amendments fixed.
    """
    rng = random.Random(seed)
    phases = [("still", still_s, 0.0)]
    for steps, turn in legs:
        if steps > 0:
            phases.append(("walk", steps / (cadence / 60.0), steps))
        if turn is not None and turn != "":
            if isinstance(turn, (int, float)):
                deg = float(turn)
            else:
                deg = {"left": 90.0, "right": -90.0, "around": 180.0}[turn]   # +yaw = counter-clockwise
            phases.append(("turn", turn_s, deg))
    phases.append(("still", end_still_s, 0.0))

    events: List[Event] = []
    t = t0
    cum_steps = 0.0
    next_activity = t0
    dt = 1.0 / motion_hz
    step_hz = cadence / 60.0
    target_steps = 0
    for kind, length, deg in phases:
        n = max(1, int(round(length * motion_hz)))
        if kind == "walk":
            target_steps += deg       # for walk phases, the third value is the step count
        for i in range(n):
            s = i * dt
            walking = kind == "walk"
            swing = math.sin(2 * math.pi * step_hz / 2 * (t - t0)) if walking else 0.0
            gz = bias_dps + rng.gauss(0, noise_dps)
            if kind == "turn":
                peak = deg * math.pi / (2 * length)        # half-sine profile that integrates to deg
                gz += peak * math.sin(math.pi * s / length)
            events.append(("motion", t, {
                "ax": 0.08 * swing + rng.gauss(0, 0.01), "ay": 0.05 * swing + rng.gauss(0, 0.01),
                "az": 1.0 + rng.gauss(0, 0.01),
                "gx": 20.0 * swing + rng.gauss(0, noise_dps), "gy": 15.0 * swing + rng.gauss(0, noise_dps),
                "gz": gz}))
            if walking:
                cum_steps = min(cum_steps + step_hz * dt, target_steps)
                if i == n - 1:
                    cum_steps = target_steps     # every step of the leg is counted
            if t >= next_activity:
                events.append(("activity", t, {"steps": start_steps + int(cum_steps),
                                               "state": "walk" if walking else "still"}))
                next_activity += 1.0 / activity_hz
            t += dt
    return events
