"""The map page's Talk button, typed text through the voice loop, and voice status events."""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import SpatialMemoryApp  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402
from voice.loop import VoiceLoop  # noqa: E402
from web.ws_server import MapWebSocketServer  # noqa: E402


class Client:
    def __init__(self):
        self.sent = []

    def send_json(self, msg):
        self.sent.append(msg)
        return True


class FakeLoop:
    def __init__(self, band=object()):
        self.band, self.taps, self.turns = band, 0, []
        self.done = threading.Event()

    def on_double_tap(self):
        self.taps += 1

    def run_turn(self, say_text=None):
        self.turns.append(say_text)
        self.done.set()


def make_app():
    return SpatialMemoryApp(PathTracker(), RouteStore(), speak=lambda t: None, clock=time.time)


class TalkButtonTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.server = MapWebSocketServer(self.app, mode="LIVE")

    def test_talk_starts_a_listening_turn(self):
        loop = FakeLoop()
        self.server.voice_loop = loop
        self.server._handle_client_message(Client(), '{"type": "talk"}')
        self.assertEqual(loop.taps, 1)

    def test_talk_without_band_explains(self):
        client = Client()
        self.server._handle_client_message(client, '{"type": "talk"}')
        self.assertEqual(client.sent[-1]["type"], "voice")
        self.assertEqual(client.sent[-1]["state"], "error")
        self.assertIn("--band", client.sent[-1]["text"])

    def test_typed_text_goes_through_the_voice_loop(self):
        loop = FakeLoop()
        self.server.voice_loop = loop
        self.server._handle_client_message(Client(), '{"type": "command", "text": "save this spot as the desk"}')
        self.assertTrue(loop.done.wait(2))
        self.assertEqual(loop.turns, ["save this spot as the desk"])

    def test_typed_text_without_voice_loop_uses_keywords(self):
        self.server._handle_client_message(Client(), '{"type": "command", "text": "start route"}')
        self.assertIsNotNone(self.app.store.current)


class VoiceStatusEventTests(unittest.TestCase):
    def test_typed_turn_reports_heard_thinking_done(self):
        app = make_app()
        events = []
        app.on_event(lambda e: events.append(e) if e.get("type") == "voice" else None)
        loop = VoiceLoop(app, choose_fn=lambda words, **kw: ("start_route", {}))
        loop.run_turn(say_text="let's begin a new route")
        states = [e["state"] for e in events]
        self.assertEqual(states, ["heard", "thinking", "done"])
        self.assertEqual(events[0]["text"], "let's begin a new route")
        self.assertTrue(events[-1]["say"].startswith("Route started"))
        self.assertEqual(events[-1]["tool"], "start_route")



class ToggleListenTests(unittest.TestCase):
    """Double-tap = mic on; double-tap again (or a pause after speech) = mic off, then answer."""

    def make(self, script):
        from unittest import mock
        import config

        class Band:
            def __init__(self):
                self.audio, self.handlers, self.t = False, {}, 0.0

            def on(self, kind, fn):
                self.handlers[kind] = fn

            def off(self, kind, fn):
                self.handlers.pop(kind, None)

            def configure(self, audio=None, **kw):
                if audio is not None:
                    self.audio = audio

            def wait(self, seconds):
                time.sleep(0.01)
                script(self, loop)

        class Ears:
            def __init__(self):
                self.on_text = None

            def start(self, on_text):
                self.on_text = on_text
                return self

            def feed(self, *a):
                pass

            def stop(self):
                return " ".join(spoken)

        spoken = []
        ears = Ears()

        class Speech:
            @staticmethod
            def create(**options):
                return ears

        app = make_app()
        loop = VoiceLoop(app, band=Band(), choose_fn=lambda words, **kw: ("start_route", {}))
        loop._ears, loop._spoken = ears, spoken
        patches = [mock.patch("voice.loop._load_kit_speech", return_value=Speech),
                   mock.patch.object(config, "VOICE_CHIMES", False),
                   mock.patch.object(config, "LISTEN_MAX_SECONDS", 3.0),
                   mock.patch.dict(os.environ, {"VEXO_DEEPGRAM_API_KEY": "test-vexo-dg"})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return loop

    def test_second_double_tap_stops_listening(self):
        calls = {"n": 0}

        def script(band, loop):
            calls["n"] += 1
            if calls["n"] == 3:
                loop._spoken.append("start route")
                loop._ears.on_text("start route", True)
            if calls["n"] == 5:
                loop.on_double_tap()          # second double-tap, before any pause
        loop = self.make(script)
        t0 = time.time()
        res = loop.run_turn()
        self.assertLess(time.time() - t0, 1.5)
        self.assertFalse(loop.band.audio)     # mic is off again
        self.assertFalse(loop._listening)
        self.assertTrue(res.ok)
        self.assertTrue(res.say.startswith("Route started"))

    def test_pause_after_speech_stops_listening(self):
        import config
        calls = {"n": 0}

        def script(band, loop):
            calls["n"] += 1
            if calls["n"] == 2:
                loop._spoken.append("start route")
                loop._ears.on_text("start route", True)
        loop = self.make(script)
        from unittest import mock
        with mock.patch.object(config, "LISTEN_PAUSE_STOP_SECONDS", 0.2):
            t0 = time.time()
            res = loop.run_turn()
        self.assertLess(time.time() - t0, 2.0)
        self.assertFalse(loop.band.audio)
        self.assertTrue(res.ok)


if __name__ == "__main__":
    unittest.main()
