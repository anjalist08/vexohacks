"""Live guidance: follow a synthetic walker back along the recorded path."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import SpatialMemoryApp  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import feed, synthetic_walk  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402


class Led:
    def __init__(self):
        self.state, self.history, self.brightness = "idle", [], 1.0

    def show(self, state, period=None):
        self.state = state
        self.history.append((state, period))
        return True


class NavigatorTests(unittest.TestCase):
    def setUp(self):
        walk = synthetic_walk(legs=((20, "left"), (15, None)))
        self.now = [walk[0][1]]
        self.said, self.led = [], Led()
        self.app = SpatialMemoryApp(PathTracker(step_length_m=0.7), RouteStore(), speak=self.said.append,
                                    led=self.led, clock=lambda: self.now[0])
        self.app.call_tool("start_route", {})
        self.app.call_tool("remember_landmark", {"label": "entrance"})
        self.walk(walk)
        self.app.call_tool("remember_landmark", {"label": "elevator"})
        self.points_before = len(self.app.store.current.points)

    def walk(self, events):
        feed(self.app.tracker, events)
        self.now[0] = events[-1][1]
        self.last = events

    def walk_more(self, legs, seed=3):
        steps = [f["steps"] for k, t, f in self.last if k == "activity"][-1]
        self.walk(synthetic_walk(legs=legs, t0=self.now[0] + 0.04, start_steps=steps, seed=seed, still_s=0.5))

    def test_guides_back_to_the_entrance(self):
        r = self.app.call_tool("navigate_to", {"target": "lm1"})
        self.assertTrue(r.ok)
        self.said.clear()
        # 20 steps remain after the corner; "arrived" fires 2 steps early and the walker stops there
        self.walk_more(((0, "around"), (15, "right"), (18, None)))
        self.assertIn("In 5 steps, turn right.", self.said)
        self.assertIn("Turn right now, then walk 20 steps.", self.said)
        self.assertEqual(self.said[-1], "You have reached the entrance.")
        states = [s for s, p in self.led.history]
        self.assertIn("turn_now", states)
        self.assertEqual(states[-1], "arrived")
        self.assertIsNone(self.app.navigator)
        p = self.app.tracker.pose        # re-anchored at the entrance
        self.assertAlmostEqual(p.x_m, 0.0, places=6)
        self.assertAlmostEqual(p.y_m, 0.0, places=6)

    def test_turn_blink_speeds_up(self):
        self.app.call_tool("navigate_to", {"target": "start"})
        self.walk_more(((0, "around"), (15, "right"), (20, None)))
        periods = [p for s, p in self.led.history if s == "turn_now"]
        self.assertGreaterEqual(len(periods), 2)
        self.assertGreater(periods[0], periods[-1])

    def test_return_walk_is_not_recorded(self):
        self.app.call_tool("navigate_to", {"target": "start"})
        self.walk_more(((0, "around"), (15, "right"), (18, None)))
        # only the re-anchor point at the destination is added
        self.assertEqual(len(self.app.store.current.points), self.points_before + 1)

    def test_off_route(self):
        self.app.call_tool("navigate_to", {"target": "start"})
        self.said.clear()
        self.walk_more(((0, "left"), (10, None)))        # walks south instead of east
        self.assertTrue(any(s.startswith("I'm not sure where we are") for s in self.said))
        self.assertEqual(self.led.state, "uncertain")
        self.assertTrue(self.app.navigator.off_route)

    def test_wrong_way(self):
        self.app.call_tool("navigate_to", {"target": "start"})
        self.said.clear()
        self.walk_more(((0, "around"), (10, "around"), (7, None)))
        self.assertIn("You're walking away from the start. Turn around.", self.said)

    def test_stop_route_ends_guidance(self):
        self.app.call_tool("navigate_to", {"target": "start"})
        self.app.call_tool("stop_route", {})
        self.assertIsNone(self.app.navigator)


if __name__ == "__main__":
    unittest.main()
