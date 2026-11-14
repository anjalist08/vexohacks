"""Core tests on synthetic walks. Run: python3 -m unittest   (or: python3 -m pytest)"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import SpatialMemoryApp, parse_keywords  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import feed, read_log, synthetic_walk, write_log  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402
from voice.led_states import STATES, LedController, turn_now_period  # noqa: E402


def walked(legs, snap=True, **kw):
    ev = synthetic_walk(legs=legs, **kw)
    tr = PathTracker(step_length_m=0.7, snap_turns=snap)
    tr.start(ev[0][1])
    feed(tr, ev)
    return tr


class TrackerTests(unittest.TestCase):
    def test_l_walk_with_snapping(self):
        tr = walked(((20, "left"), (15, None)))
        p = tr.pose
        self.assertEqual(p.steps, 35)
        self.assertAlmostEqual(p.x_m, -10.5, places=1)
        self.assertAlmostEqual(p.y_m, 14.0, places=1)
        self.assertEqual(p.heading_deg, -90.0)

    def test_turn_while_still_is_kept(self):
        # The synthetic walker stops at the corner (state "still") while turning.
        tr = walked(((10, "right"), (10, None)))
        self.assertEqual(tr.pose.heading_deg, 90.0)
        self.assertGreater(tr.pose.x_m, 6.5)

    def test_bias_is_measured(self):
        tr = walked(((5, None),), bias_dps=2.0)
        self.assertAlmostEqual(tr.bias, 2.0, delta=0.5)

    def test_without_snapping_stays_close(self):
        p = walked(((20, "left"), (15, None)), snap=False).pose
        self.assertAlmostEqual(p.heading_deg, -90.0, delta=5.0)
        self.assertAlmostEqual(p.x_m, -10.5, delta=1.0)

    def test_reanchor(self):
        tr = walked(((10, None),))
        tr.reanchor(1.0, 2.0, 90.0)
        self.assertEqual((tr.pose.x_m, tr.pose.y_m, tr.heading), (1.0, 2.0, 90.0))


class StoreAndAppTests(unittest.TestCase):
    def make_app(self, path=None):
        walk = synthetic_walk(legs=((20, "left"), (15, None)))
        now = [walk[0][1]]
        out = []
        app = SpatialMemoryApp(PathTracker(step_length_m=0.7), RouteStore(path), speak=out.append, led=None,
                               clock=lambda: now[0])
        app.call_tool("start_route", {})
        app.call_tool("remember_landmark", {"label": "entrance"})
        feed(app.tracker, walk)
        app.call_tool("remember_landmark", {"label": "elevator", "note": "near the blue sign"})
        return app, out

    def test_return_to_start_reverses_the_path(self):
        app, _ = self.make_app()
        r = app.call_tool("navigate_to", {"target": "start"})
        turns = [(i["turn"], i["steps"]) for i in r.data["instructions"]]
        self.assertEqual(turns, [("around", 15), ("right", 20), ("arrive", 0)])
        self.assertEqual(r.led, "navigating")

    def test_unknown_landmark_is_rejected(self):
        app, _ = self.make_app()
        r = app.call_tool("navigate_to", {"target": "lm99"})
        self.assertFalse(r.ok)
        self.assertEqual(r.led, "uncertain")

    def test_bad_tool_calls_are_rejected(self):
        app, _ = self.make_app()
        self.assertFalse(app.call_tool("teleport", {}).ok)
        self.assertFalse(app.call_tool("remember_landmark", {}).ok)
        self.assertFalse(app.call_tool("navigate_to", {"target": "start", "x": 3}).ok)

    def test_find_landmark_by_label_and_note(self):
        app, _ = self.make_app()
        self.assertEqual(app.store.find_landmark("where was the elevator")[0][0].label, "elevator")
        self.assertEqual(app.store.find_landmark("blue sign")[0][0].label, "elevator")
        self.assertEqual(app.store.find_landmark("parking"), [])

    def test_keyword_fallback(self):
        app, _ = self.make_app()
        self.assertEqual(parse_keywords("take me back to the entrance", app.store), ("navigate_to", {"target": "lm1"}))
        self.assertEqual(parse_keywords("remember this as the cafe near the stairs", app.store),
                         ("remember_landmark", {"label": "cafe", "note": "near the stairs"}))
        self.assertEqual(parse_keywords("I'm at the elevator", app.store), ("reanchor", {"landmark_id": "lm2"}))
        self.assertEqual(parse_keywords("mode light only", app.store), ("set_mode", {"mode": "light-only"}))

    def test_output_modes(self):
        app, out = self.make_app()
        out.clear()
        app.call_tool("set_mode", {"mode": "light-only"})
        app.call_tool("find_landmark", {"query": "elevator"})
        self.assertEqual(out, [])

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "routes.json")
            app, _ = self.make_app(path)
            again = RouteStore(path)
            self.assertEqual([l.label for l in again.all_landmarks()], ["entrance", "elevator"])
            self.assertEqual(len(again.current.points), len(app.store.current.points))

    def test_log_round_trip(self):
        ev = synthetic_walk(legs=((5, None),))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "walk.csv")
            write_log(path, ev)
            back = read_log(path)
        self.assertEqual(len(back), len(ev))
        steps = lambda events: [f["steps"] for k, t, f in events if k == "activity"]
        self.assertEqual(steps(back), steps(ev))
        self.assertAlmostEqual(back[0][2]["gz"], ev[0][2]["gz"], places=6)


class FakeBand:
    def __init__(self, deny=False):
        self.calls, self.deny = [], deny

    def set_led(self, color, **kw):
        if self.deny:
            e = Exception("denied")
            e.code = "denied"
            raise e
        self.calls.append((color, kw))

    def led_off(self):
        self.calls.append(("off", {}))


class LedTests(unittest.TestCase):
    def test_no_state_uses_blue(self):
        for name, cue in STATES.items():
            self.assertNotEqual((cue.color or "").lower(), "#0000ff", name)

    def test_recording_and_navigating_differ(self):
        self.assertNotEqual((STATES["recording"].color, STATES["recording"].pattern),
                            (STATES["navigating"].color, STATES["navigating"].pattern))

    def test_mic_lock_is_handled(self):
        self.assertFalse(LedController(FakeBand(deny=True)).show("recording"))
        band = FakeBand()
        self.assertTrue(LedController(band).show("navigating"))
        self.assertEqual(band.calls[-1][1]["pattern"], "breathe")

    def test_turn_blinks_faster_when_close(self):
        self.assertLess(turn_now_period(1), turn_now_period(10))


if __name__ == "__main__":
    unittest.main()
