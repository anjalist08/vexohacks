"""End-to-end integration tests across tracker, store, app, voice, and web."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KIT_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "vexo-open-kit", "examples", "python")
if KIT_PY not in sys.path:
    sys.path.insert(0, KIT_PY)

from app import SpatialMemoryApp  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tests.test_core import FakeBand  # noqa: E402
from tests.test_memory import WebSocketServerTests  # noqa: E402
from tracker.events import feed, synthetic_walk  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402
from voice.led_states import LedController  # noqa: E402
from voice.loop import VoiceLoop  # noqa: E402
from web.ws_server import MapWebSocketServer  # noqa: E402


class _FakeVoiceBand(FakeBand):
    def __init__(self):
        super().__init__(deny=False)
        self.audio = False

    def configure(self, **kw):
        if "audio" in kw:
            self.audio = bool(kw["audio"])
            self.deny = self.audio


class FullSystemIntegrationTests(unittest.TestCase):
    def test_uncertainty_triggers_red_led_and_reanchor_recovers(self):
        band = _FakeVoiceBand()
        led = LedController(band)
        spoken = []
        tracker = PathTracker(step_length_m=0.7, snap_turns=True, uncertainty_threshold_deg=30.0)
        app = SpatialMemoryApp(tracker, RouteStore(), speak=spoken.append, led=led)

        with MapWebSocketServer(app, host="127.0.0.1", port=0, mode="SIMULATION") as srv:
            ws = WebSocketServerTests._open_ws(srv)
            try:
                app.call_tool("start_route", {"title": "hallway"})
                app.call_tool("remember_landmark", {"label": "lobby"})

                # Walk with two ambiguous ~40 deg diagonal turns so snap discrepancy exceeds 30 deg.
                diag_walk = synthetic_walk(legs=((8, 40.0), (8, 40.0), (5, None)))
                feed(tracker, diag_walk)

                self.assertTrue(tracker.heading_uncertain)
                self.assertEqual(led.state, "uncertain")
                self.assertTrue(any("not sure where we are" in s for s in spoken))

                # Voice loop turn says "I'm at the lobby" -> Gemini picks reanchor("lm1") -> clears uncertainty!
                vloop = VoiceLoop(
                    app,
                    band=band,
                    listen_fn=lambda b, sec: "I'm at the lobby",
                    choose_fn=lambda text, **kw: ("reanchor", {"landmark_id": "lm1"}),
                )
                res = vloop.run_turn()
                self.assertTrue(res.ok)
                self.assertFalse(tracker.heading_uncertain)
                self.assertEqual(led.state, "recording")

                # Verify WebSocket client observed the uncertain and recording LED transitions.
                led_states = []
                for _ in range(120):
                    raw = ws.recv(timeout=1.0)
                    msg = json.loads(raw)
                    if msg.get("type") == "led":
                        led_states.append(msg.get("state"))
                        if "uncertain" in led_states and led_states[-1] == "recording":
                            break
                self.assertIn("uncertain", led_states)
                self.assertEqual(led_states[-1], "recording")
            finally:
                ws.close()


if __name__ == "__main__":
    unittest.main()
