"""Guidance on imperfect walks: an early turn, arriving, and re-anchor jumps."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import SpatialMemoryApp  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import feed, synthetic_walk  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402


def make_tracker():
    """The team's tracker for synthetic walks (WristTracker when tracker-port is merged)."""
    try:
        from tracker.wrist import make_tracker as wrist_make
        return wrist_make(synthetic=True, step_length_m=0.7)
    except ImportError:
        return PathTracker(step_length_m=0.7)


class Led:
    def __init__(self):
        self.calls = []

    def show(self, state, period=None):
        self.calls.append((state, period))
        return True


class RobustGuidanceTests(unittest.TestCase):
    def setUp(self):
        walk = synthetic_walk(legs=((20, "left"), (15, None)))     # north 20, west 15
        self.now = [walk[0][1]]
        self.said, self.led = [], Led()
        self.app = SpatialMemoryApp(make_tracker(), RouteStore(), speak=self.said.append, led=self.led,
                                    clock=lambda: self.now[0])
        self.app.call_tool("start_route", {})
        self.app.call_tool("remember_landmark", {"label": "entrance"})
        self.walk(walk)
        self.app.call_tool("remember_landmark", {"label": "elevator"})
        self.outbound = len(self.app.store.current.points)

    def walk(self, events):
        feed(self.app.tracker, events)
        self.now[0] = events[-1][1]
        self.last = events

    def next_walk(self, legs, seed):
        steps = [f["steps"] for k, t, f in self.last if k == "activity"][-1]
        return synthetic_walk(legs=legs, t0=self.now[0] + 0.04, start_steps=steps, seed=seed, still_s=0.5)

    def walk_more(self, legs, seed=3):
        self.walk(self.next_walk(legs, seed))

    def walk_until_arrived(self, legs, seed=3):
        """Walk until guidance says "arrived", then stop, as a person would."""
        events = self.next_walk(legs, seed)
        for i, ev in enumerate(events):
            feed(self.app.tracker, [ev])
            if self.app.navigator is not None and not self.app.navigator.active:
                break
        self.now[0] = events[i][1]
        self.last = events[: i + 1]

    def outbound_legs(self):
        """(turn, steps) of the way back as planned from the recorded route, for any tracker."""
        r = self.app.call_tool("navigate_to", {"target": "start"})
        return [(i["turn"], i["steps"]) for i in r.data["instructions"]]

    def test_turning_one_step_early_still_advances_and_arrives(self):
        (t1, first), (t2, second), _ = self.outbound_legs()
        self.said.clear()
        # this walker turns one step before the corner, then walks on until told "arrived"
        self.walk_until_arrived(((0, "around"), (first - 1, "right"), (second + 6, None)))
        self.assertIn("Turn right, walk %d steps." % second, self.said)
        self.assertEqual(self.said[-1], "You have reached the start.")
        self.assertFalse(self.app.navigator.active)

    def test_arrival_resets_position_and_recording_resumes(self):
        (_, first), (_, second), _ = self.outbound_legs()
        self.walk_until_arrived(((0, "around"), (first, "right"), (second + 6, None)))
        self.assertEqual(self.said[-1], "You have reached the start.")
        route = self.app.store.current
        self.assertEqual(route.breaks, [self.outbound])           # the reset, recorded as a jump
        p = self.app.tracker.pose
        self.assertAlmostEqual(p.x_m, 0.0, places=6)              # back exactly at the start
        self.assertAlmostEqual(p.y_m, 0.0, places=6)
        before = len(route.points)
        self.walk_more(((5, None),), seed=4)                       # keep walking after arriving
        self.assertGreater(len(route.points), before)

    def test_after_arriving_it_routes_forward_through_the_same_place(self):
        (_, first), (_, second), _ = self.outbound_legs()
        self.walk_until_arrived(((0, "around"), (first, "right"), (second + 6, None)))
        r = self.app.call_tool("navigate_to", {"target": "lm2"})  # the elevator, from the entrance
        turns = [(i["turn"], i["steps"]) for i in r.data["instructions"]]
        self.assertEqual([t for t, n in turns], ["around", "left", "arrive"])
        self.assertEqual([n for t, n in turns][:2], [second, first])   # the walked route, not a diagonal

    def test_reanchor_is_a_jump_not_a_walked_line(self):
        self.app.call_tool("reanchor", {"landmark_id": "lm1"})     # "I'm at the entrance"
        route = self.app.store.current
        self.assertEqual(route.breaks, [self.outbound])
        r = self.app.call_tool("navigate_to", {"target": "lm2"})
        steps = sum(i["steps"] for i in r.data["instructions"])
        self.assertGreaterEqual(steps, 34)                         # ~35 along the route, not ~25 diagonal


if __name__ == "__main__":
    unittest.main()
