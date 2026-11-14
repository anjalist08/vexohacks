"""Tests for assist/: vibration cues, compass correction, arrival prompts, phone link.
Synthetic walks only, no band. Run: python3 -m unittest"""
import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vexo-open-kit", "examples", "python"))

from app import SpatialMemoryApp  # noqa: E402
from assist import attach  # noqa: E402
from assist.compass import CompassCorrector, circular_mean  # noqa: E402
from assist.haptics import HAPTIC_PATTERNS, cue_for_result  # noqa: E402
from interfaces import ToolResult  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import feed, synthetic_walk  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402


class Recorder:
    def __init__(self):
        self.said, self.buzzed = [], []

    def send(self, msg):
        self.buzzed.append(msg["cue"])


def recorded(rec):
    walk = synthetic_walk(legs=((20, "left"), (15, None)))
    now = [walk[0][1]]
    app = SpatialMemoryApp(PathTracker(step_length_m=0.7), RouteStore(), speak=rec.said.append,
                           clock=lambda: now[0])
    helper = attach(app, send=rec.send)
    app.call_tool("start_route", {})
    app.call_tool("remember_landmark", {"label": "entrance"})
    feed(app.tracker, walk)
    now[0] = walk[-1][1]
    app.call_tool("remember_landmark", {"label": "elevator"})

    def walk_more(legs, seed):
        ev = synthetic_walk(legs=legs, t0=now[0] + 0.04, start_steps=app.tracker._last_steps,
                            seed=seed, still_s=0.5)
        feed(app.tracker, ev)
        now[0] = ev[-1][1]
    walk_more(((10, None),), 2)
    return app, helper, walk_more


class HapticTests(unittest.TestCase):
    def test_left_and_right_feel_different(self):
        self.assertNotEqual(len(HAPTIC_PATTERNS["turn_left"]), len(HAPTIC_PATTERNS["turn_right"]))

    def test_patterns_are_valid_vibrate_lists(self):
        for name, p in HAPTIC_PATTERNS.items():
            self.assertTrue(p and all(isinstance(ms, int) and 0 < ms <= 1000 for ms in p), name)

    def test_cue_from_guidance_and_led(self):
        guide = ToolResult(True, "x", "navigating", {"instructions": [{"turn": "left"}]})
        self.assertEqual(cue_for_result(guide), "turn_left")
        self.assertEqual(cue_for_result(ToolResult(False, "x", "uncertain")), "uncertain")
        self.assertIsNone(cue_for_result(ToolResult(True, "Note saved.", None)))

    def test_light_only_mode_sends_no_vibration(self):
        rec = Recorder()
        app, _, _ = recorded(rec)
        app.call_tool("set_mode", {"mode": "light-only"})
        rec.buzzed.clear()
        app.call_tool("navigate_to", {"target": "start"})
        self.assertEqual(rec.buzzed, [])


class CompassTests(unittest.TestCase):
    def tracker(self):
        ev = synthetic_walk(legs=((5, None),))
        tr = PathTracker(step_length_m=0.7, snap_turns=True)
        tr.start(ev[0][1])
        feed(tr, ev)
        return tr

    def feed(self, cc, start, seconds, heading, jitter=0.0):
        out = None
        for i in range(int(seconds * 5)):
            j = jitter * (1 if i % 2 else -1)
            out = cc.on_compass(start + i * 0.2, heading + j) or out
        return out

    def test_circular_mean_wraps(self):
        mean, spread = circular_mean([350, 10])
        self.assertAlmostEqual(mean, 0.0, delta=0.01)
        self.assertLess(spread, 15)

    def test_missed_turn_is_corrected(self):
        tr = self.tracker()
        cc = CompassCorrector(tr)
        self.feed(cc, 0, 3, 100.0)                 # facing the start direction: compass 100
        self.assertEqual(tr.heading, 0.0)
        self.assertEqual(self.feed(cc, 3, 6, 10.0), -90.0)   # the user turned left, the gyro missed it
        self.assertEqual(tr.heading, -90.0)
        self.assertEqual(cc.corrections, 1)

    def test_agreeing_compass_changes_nothing(self):
        tr = self.tracker()
        cc = CompassCorrector(tr)
        self.feed(cc, 0, 10, 100.0, jitter=4)
        self.assertEqual((tr.heading, cc.corrections), (0.0, 0))

    def test_noisy_or_off_grid_readings_are_ignored(self):
        tr = self.tracker()
        cc = CompassCorrector(tr)
        self.feed(cc, 0, 3, 100.0)
        self.assertIsNone(self.feed(cc, 3, 8, 10.0, jitter=40))   # magnetic noise
        self.assertIsNone(self.feed(cc, 8, 8, 55.0))               # 45 degrees off: not a hallway
        self.assertEqual(tr.heading, 0.0)

    def test_short_glitch_is_ignored(self):
        tr = self.tracker()
        cc = CompassCorrector(tr)
        self.feed(cc, 0, 3, 100.0)
        self.assertIsNone(self.feed(cc, 3, 2, 10.0))               # shorter than the hold time
        self.assertEqual(tr.heading, 0.0)


class ArrivalTests(unittest.TestCase):
    def test_return_trip_prompts_and_arrives(self):
        rec = Recorder()
        app, helper, walk_more = recorded(rec)
        r = app.call_tool("navigate_to", {"target": "start"})
        self.assertTrue(r.ok)
        self.assertEqual(rec.buzzed[-1], "turn_around")
        walk_more(((0, "around"), (9, None)), 3)
        self.assertEqual(rec.buzzed[-1], "confirm_prompt")
        self.assertIn("elevator", rec.said[-1])
        elevator = app.store.current.points[app.store.find_landmark("elevator")[0][0].point_index]
        heading_before = app.tracker.heading
        helper.confirm()
        p = app.tracker.pose
        self.assertEqual((p.x_m, p.y_m), (elevator.x_m, elevator.y_m))
        self.assertEqual(app.tracker.heading, heading_before)    # still facing the way back
        walk_more(((15, "right"), (18, None)), 4)
        self.assertIn("Are you at the", rec.said[-1])
        helper.confirm()
        self.assertEqual(rec.buzzed[-1], "arrived")

    def test_no_prompt_while_recording(self):
        rec = Recorder()
        recorded(rec)
        self.assertNotIn("confirm_prompt", rec.buzzed)

    def test_phone_messages_are_checked(self):
        rec = Recorder()
        _, helper, _ = recorded(rec)
        helper.on_phone_message({"type": "compass", "heading": "north"})   # ignored, no crash
        helper.on_phone_message({"type": "confirm"})                       # nothing asked yet
        self.assertIsNone(helper.confirm())


class PhoneLinkTests(unittest.TestCase):
    def test_websocket_round_trip_needs_the_token(self):
        from urllib.error import HTTPError
        from urllib.request import urlopen

        from assist.phone_server import PhoneHub, start
        from tiny_websocket import WebSocket, WebSocketError

        got = []
        hub = PhoneHub(on_message=got.append)
        server, url = start(hub, "127.0.0.1", 0)
        port = server.server_address[1]
        token = url.split("k=")[1]
        try:
            with self.assertRaises(HTTPError):
                urlopen("http://127.0.0.1:%d/" % port, timeout=5)
            with self.assertRaises(WebSocketError):
                WebSocket("ws://127.0.0.1:%d/ws?k=wrong" % port, timeout=5)
            page = urlopen("http://127.0.0.1:%d/?k=%s" % (port, token), timeout=5).read()
            self.assertIn(b"navigator.vibrate", page)
            ws = WebSocket("ws://127.0.0.1:%d/ws?k=%s" % (port, token), timeout=5)
            self.assertTrue(hub.connected.wait(5))
            hub.broadcast({"type": "haptic", "cue": "arrived", "pattern": [700], "say": "hi"})
            self.assertEqual(json.loads(ws.recv(timeout=5))["cue"], "arrived")
            ws.send(json.dumps({"type": "confirm"}))
            for _ in range(50):
                if got:
                    break
                time.sleep(0.05)
            self.assertEqual(got, [{"type": "confirm"}])
            ws.close()
        finally:
            server.shutdown()
            server.server_close()


class NtfyTests(unittest.TestCase):
    def sender(self, posts, now):
        from assist.notify import NtfySender
        return NtfySender("vexo-test-topic-123456", post=lambda u, b, h: posts.append((u, b, h)) or 200,
                          clock=lambda: now[0], background=False)

    def test_only_key_moments_and_never_names(self):
        from assist.haptics import haptic_message
        posts, now = [], [0.0]
        send = self.sender(posts, now)
        self.assertFalse(send(haptic_message("turn_left", "Turn left, walk 18 steps.")))
        self.assertTrue(send(haptic_message("confirm_prompt", "Are you at the elevator?")))
        url, body, headers = posts[0]
        self.assertEqual(url, "https://ntfy.sh/vexo-test-topic-123456")
        self.assertNotIn(b"elevator", body)
        self.assertEqual(headers["Priority"], "high")

    def test_repeats_are_held_back(self):
        from assist.haptics import haptic_message
        posts, now = [], [0.0]
        send = self.sender(posts, now)
        send(haptic_message("arrived"))
        send(haptic_message("arrived"))
        now[0] = 5.0
        send(haptic_message("arrived"))
        self.assertEqual(len(posts), 2)

    def test_failure_does_not_stop_guidance(self):
        from assist.haptics import haptic_message
        from assist.notify import NtfySender

        def broken(*a):
            raise OSError("offline")
        send = NtfySender("vexo-test-topic-123456", post=broken, background=False)
        self.assertTrue(send(haptic_message("uncertain")))
        self.assertEqual(send.sent, 0)

    def test_short_topics_are_refused(self):
        from assist.notify import NtfySender, new_topic
        with self.assertRaises(ValueError):
            NtfySender("vexo")
        self.assertGreater(len(new_topic()), 20)

    def test_demo_sends_only_generic_notifications(self):
        from assist import demo
        from assist.notify import NtfySender, fan_out
        posts, ticks = [], iter(range(0, 10000, 10))     # each cue 10 s apart, as on a real walk
        ntfy = NtfySender("vexo-test-topic-123456", post=lambda u, b, h: posts.append(b) or 200,
                          clock=lambda: float(next(ticks)), background=False)
        demo.run(send=fan_out(lambda m: None, ntfy), speak=lambda t: None)
        self.assertEqual([b.decode() for b in posts],
                         ["Are you at a saved place? Double-tap for yes.",
                          "Are you at a saved place? Double-tap for yes.", "You have arrived."])


if __name__ == "__main__":
    unittest.main()
