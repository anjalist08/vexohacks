"""Chrome Bluetooth bridge: band data in from the page, commands out, and the app using it."""
import base64
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import SpatialMemoryApp  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402
from voice.led_states import LedController  # noqa: E402
from web.bridge_band import BridgeBand, configure_streams, wire  # noqa: E402
from web.ws_server import MapWebSocketServer  # noqa: E402


class Client:
    def __init__(self):
        self.sent = []

    def send_json(self, msg):
        self.sent.append(msg)
        return True


class BridgeBandTests(unittest.TestCase):
    def setUp(self):
        self.out = []
        self.band = BridgeBand(self.out.append, number=80)

    def test_name_and_number(self):
        self.assertEqual(self.band.name, "Vexo-HACK-80")

    def test_commands_go_to_the_page(self):
        self.band.configure(audio=True)
        self.assertTrue(self.band.audio)
        self.band.set_led("#ffb000", brightness=0.5, pattern="breathe", period=2000)
        self.band.led_off()
        self.assertEqual([m["op"] for m in self.out], ["configure", "setLed", "ledOff"])
        self.assertEqual(self.out[1]["args"]["pattern"], "breathe")

    def test_events_reach_handlers(self):
        taps, audio = [], []
        self.band.on("double-tap", lambda e: taps.append(e.kind))
        self.band.on("audio", lambda e: audio.append((e.seq, e.opus)))
        self.band.receive({"type": "band_event", "kind": "event", "event": "double-tap", "arg": 0, "time": 1.0})
        self.band.receive({"type": "band_event", "kind": "audio", "seq": 7,
                           "opus": base64.b64encode(b"\x01\x02").decode()})
        self.assertEqual(taps, ["double-tap"])
        self.assertEqual(audio, [(7, b"\x01\x02")])

    def test_off_removes_a_handler(self):
        seen = []
        fn = seen.append
        self.band.on("audio", fn)
        self.band.off("audio", fn)
        self.band.receive({"kind": "audio", "seq": 1, "opus": ""})
        self.assertEqual(seen, [])

    def test_streams_match_band_source(self):
        configure_streams(self.band)
        args = self.out[-1]["args"]
        self.assertTrue(args["events"])
        self.assertIn("motion", args)
        self.assertIn("activity", args)

    def test_wire_feeds_the_tracker_and_double_tap(self):
        tracker = PathTracker(step_length_m=0.7)
        tracker.start(1000.0)
        taps = []
        wire(self.band, tracker, on_double_tap=lambda: taps.append(1))
        for i in range(3):
            self.band.receive({"kind": "activity", "time": 1001.0 + i, "steps": 100 + 2 * i,
                               "cadence": 110, "state": "walk", "motion": 0.3})
        self.band.receive({"kind": "event", "event": "double-tap", "time": 1005.0})
        self.assertEqual(tracker.pose.steps, 4)
        self.assertEqual(taps, [1])


class ServerBridgeTests(unittest.TestCase):
    def setUp(self):
        self.app = SpatialMemoryApp(PathTracker(), RouteStore(), speak=lambda t: None, clock=time.time)
        self.server = MapWebSocketServer(self.app, mode="LIVE")

    def test_band_number_only_when_bridging(self):
        msgs = self.server._build_initial_snapshot()
        self.assertIn({"type": "band_number", "band": None}, msgs)
        self.server.bridge = BridgeBand(lambda m: None, number=80)
        msgs = self.server._build_initial_snapshot()
        self.assertIn({"type": "band_number", "band": 80}, msgs)

    def test_band_events_and_status_are_routed(self):
        band = BridgeBand(lambda m: None, number=80)
        seen, statuses = [], []
        band.on("battery", lambda e: seen.append(e.percent))
        self.server.bridge = band
        self.server.on_bridge_status = statuses.append
        self.server._handle_client_message(Client(), '{"type": "band_event", "kind": "battery", "percent": 41}')
        self.server._handle_client_message(Client(), '{"type": "band_status", "status": "connected"}')
        self.assertEqual(seen, [41])
        self.assertEqual(statuses[0]["status"], "connected")

    def test_led_controller_drives_the_bridged_band(self):
        out = []
        led = LedController(BridgeBand(out.append, number=80))
        self.assertTrue(led.show("navigating"))
        self.assertEqual(out[-1]["op"], "setLed")
        self.assertEqual(out[-1]["args"]["color"], "#ffffff")


if __name__ == "__main__":
    unittest.main()
