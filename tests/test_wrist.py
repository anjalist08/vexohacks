"""WristTracker on the team's real logged walks (band worn on / carried in a hand) and on
a synthetic walk. These are regression tests: real data, measured results."""
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import SpatialMemoryApp  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import feed, read_log, synthetic_walk  # noqa: E402
from tracker.wrist import WristTracker, make_tracker  # noqa: E402

LOGS = os.path.join(ROOT, "data", "logs")


def replay(name, **kw):
    events = read_log(os.path.join(LOGS, name))
    kw.setdefault("step_source", "accel")
    tr = WristTracker(step_length_m=0.7, snap_turns=True, **kw)
    tr.start(events[0][1])
    feed(tr, events)
    return tr


def route(tr):
    """Directions and step counts, e.g. 'W10 S8 W23 N8 E34' (N = the way you faced at start)."""
    out = []
    for p in tr.points[1:]:
        d = "NESW"[int(round(p.heading_deg / 90.0)) % 4]
        if out and out[-1][0] == d:
            out[-1][1] += 1
        else:
            out.append([d, 1])
    return " ".join("%s%d" % (d, n) for d, n in out)


class RealWalkTests(unittest.TestCase):
    def test_walk3_wrist_loop_closes(self):
        tr = replay("walk3-wrist-loop.csv")
        self.assertEqual(tr.pose.steps, 84)
        self.assertLess(math.hypot(tr.x, tr.y), 2.0, route(tr))     # measured: 1.0 m after 59 m
        self.assertTrue(route(tr).startswith("W10 S8 W23 N8 E3"), route(tr))

    def test_walk2_wrist_out_and_back(self):
        tr = replay("walk2-wristband.csv")
        self.assertTrue(route(tr).startswith("W24 S8 W8 S6"), route(tr))
        self.assertLess(math.hypot(tr.x, tr.y), 8.0)                # measured: 5.6 m after 72 m

    def test_walk1_carried(self):
        tr = replay("walk1-hallway-loop.csv")
        self.assertLess(math.hypot(tr.x, tr.y), 10.0)               # measured: 7.9 m after 83 m

    def test_band_steps_ignore_arm_moves_while_standing(self):
        # 13:49 live log: standing, typing and moving an arm; the motion detector counted 34 "steps"
        tr = replay("walk-20261114-134925.csv", step_source="band")
        self.assertEqual(tr.pose.steps, 0)

    def test_band_steps_close_the_loops(self):
        for name, most in (("walk3-wrist-loop.csv", 7.0), ("walk2-wristband.csv", 8.0), ("walk1-hallway-loop.csv", 8.0)):
            tr = replay(name, step_source="band")
            self.assertLess(math.hypot(tr.x, tr.y), most, name)

    def test_band_step_source_counts_band_steps(self):
        tr = replay("walk3-wrist-loop.csv", step_source="band")
        self.assertEqual(tr.pose.steps, tr.band_steps)
        self.assertGreater(tr.band_steps, 0)


class SyntheticTests(unittest.TestCase):
    def test_synthetic_l_walk_with_band_steps(self):
        ev = synthetic_walk(legs=((20, "left"), (15, None)))
        tr = make_tracker(synthetic=True, step_length_m=0.7)
        tr.start(ev[0][1])
        feed(tr, ev)
        self.assertEqual(tr.pose.steps, 35)
        self.assertAlmostEqual(tr.x, -10.5, delta=0.8)
        self.assertAlmostEqual(tr.y, 14.0, delta=0.8)
        self.assertEqual(tr.pose.heading_deg, -90.0)

    def test_return_guidance_and_reanchor_work_with_the_app(self):
        ev = synthetic_walk(legs=((20, "left"), (15, None)))
        now = [ev[0][1]]
        app = SpatialMemoryApp(make_tracker(synthetic=True), RouteStore(), speak=lambda s: None, clock=lambda: now[0])
        app.keyword_command("start route")
        feed(app.tracker, ev)
        app.keyword_command("remember this as the elevator")
        r = app.keyword_command("take me back to the start")
        self.assertTrue(r.ok, r.say)
        self.assertGreaterEqual(len(r.data["instructions"]), 2)
        self.assertTrue(app.keyword_command("I'm at the elevator").ok)

    def test_uncertainty_signal_still_fires_on_long_walks(self):
        tr = replay("walk3-wrist-loop.csv")
        seen = []
        tr2 = WristTracker(step_length_m=0.7)
        tr2.on_uncertainty(seen.append)
        events = read_log(os.path.join(LOGS, "walk3-wrist-loop.csv"))
        tr2.start(events[0][1])
        feed(tr2, events)
        self.assertEqual(tr2.heading_uncertain, tr2.uncertainty_deg >= tr2.uncertainty_threshold_deg)
        self.assertGreater(tr.uncertainty_deg, 0)


if __name__ == "__main__":
    unittest.main()
