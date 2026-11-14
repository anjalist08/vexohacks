"""Dashboard server: state shape, live events and the command endpoint. No band needed."""
import json
import os
import socket
import sys
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import SpatialMemoryApp  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import feed, synthetic_walk  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402
from web.server import Dashboard  # noqa: E402


class Led:
    state = "idle"
    brightness = 1.0

    def show(self, state, period=None):
        self.state = state
        return True


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class DashboardTests(unittest.TestCase):
    def setUp(self):
        walk = synthetic_walk(legs=((20, "left"), (15, None)))
        now = [walk[0][1]]
        self.app = SpatialMemoryApp(PathTracker(step_length_m=0.7), RouteStore(), speak=lambda s: None,
                                    led=Led(), clock=lambda: now[0])
        self.dash = Dashboard(self.app, "SIMULATION")
        self.port = free_port()
        self.server = self.dash.serve(self.port)
        self.app.call_tool("start_route", {})
        feed(self.app.tracker, walk)
        self.app.call_tool("remember_landmark", {"label": "elevator"})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def post(self, text, origin=None):
        req = urllib.request.Request(self.url("/command"), data=json.dumps({"text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        if origin:
            req.add_header("Origin", origin)
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def test_state(self):
        with urllib.request.urlopen(self.url("/state"), timeout=5) as r:
            s = json.loads(r.read())
        self.assertEqual(s["label"], "SIMULATION")
        self.assertEqual(s["pose"]["steps"], 35)
        self.assertEqual([l["label"] for l in s["landmarks"]], ["elevator"])
        self.assertEqual(s["led"]["state"], "landmark_saved")
        self.assertEqual(s["say"], "Saved: elevator.")

    def test_page_is_served(self):
        with urllib.request.urlopen(self.url("/"), timeout=5) as r:
            self.assertIn(b"Vexo Spatial Memory", r.read())

    def test_command_runs_a_tool(self):
        body = self.post("take me back to the start")
        self.assertTrue(body["ok"])
        self.assertTrue(body["say"].startswith("Turn around"))
        self.assertEqual(self.dash.state()["guidance"][-1]["turn"], "arrive")

    def test_other_sites_cannot_send_commands(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("start route", origin="https://evil.example")
        self.assertEqual(e.exception.code, 403)

    def test_events_stream_starts_with_state(self):
        with urllib.request.urlopen(self.url("/events"), timeout=5) as r:
            line = r.readline().decode()
        self.assertTrue(line.startswith("data: "))
        self.assertEqual(json.loads(line[6:])["pose"]["steps"], 35)


if __name__ == "__main__":
    unittest.main()
