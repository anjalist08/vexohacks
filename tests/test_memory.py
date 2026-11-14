"""Tests for @memory deliverables: advancing guidance, band mirror, WebSocket & web safety."""
import json
import os
import socket
import sys
import threading
import unittest
from http.client import HTTPConnection
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT_EXAMPLES = os.path.join(REPO_ROOT, "vexo-open-kit", "examples", "python")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if KIT_EXAMPLES not in sys.path:
    sys.path.insert(0, KIT_EXAMPLES)

import tiny_websocket  # noqa: E402
from app import SpatialMemoryApp  # noqa: E402
from interfaces import Landmark, PoseSample  # noqa: E402
from store.band_mirror import MAX_SLOT_BYTES, BandLandmarkMirror, encode_landmark_slot  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import feed, synthetic_walk  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402
from voice.led_states import turn_now_period  # noqa: E402
from web.ws_server import MapWebSocketServer, _SafeStaticHandler, _start_static_http  # noqa: E402


class RecordingLed:
    """Test double recording (state, period) calls made by SpatialMemoryApp."""

    def __init__(self):
        self.state = "idle"
        self.brightness = 1.0
        self.calls = []

    def show(self, state, period=None):
        self.state = state
        self.calls.append((state, period))
        return True


class FakeBandStorage:
    """In-memory stand-in for band.storage enforcing 0..999 keys and <=232 UTF-8 bytes."""

    def __init__(self, fail_mode=None):
        self.slots = {}
        self.fail_mode = fail_mode

    def _check_fail(self):
        if self.fail_mode:
            err = RuntimeError(self.fail_mode)
            err.code = self.fail_mode
            raise err

    def put(self, key, text):
        self._check_fail()
        if not isinstance(key, int) or not (0 <= key < 1000):
            raise ValueError("invalid slot key: %r" % (key,))
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_SLOT_BYTES:
            raise ValueError("slot overflow: %d bytes > %d" % (len(encoded), MAX_SLOT_BYTES))
        self.slots[key] = text

    def get_text(self, key):
        self._check_fail()
        return self.slots.get(key)

    def delete(self, key):
        self._check_fail()
        self.slots.pop(key, None)


class AdvancingGuidanceTests(unittest.TestCase):
    def build_l_route_app(self, mirror=None):
        leg1 = synthetic_walk(legs=((20, "left"),))
        now = [leg1[0][1]]
        spoken = []
        led = RecordingLed()
        events = []
        app = SpatialMemoryApp(
            PathTracker(step_length_m=0.7),
            RouteStore(),
            speak=spoken.append,
            led=led,
            clock=lambda: now[0],
            band_mirror=mirror,
        )
        app.on_event(events.append)

        app.call_tool("start_route", {"title": "lobby to studio"})
        app.call_tool("remember_landmark", {"label": "entrance"})

        feed(app.tracker, leg1)
        now[0] = leg1[-1][1]
        app.call_tool("remember_landmark", {"label": "elevator", "floor": "2", "note": "near the blue sign"})

        steps1 = [f["steps"] for k, _, f in leg1 if k == "activity"][-1]
        leg2 = synthetic_walk(legs=((15, None),), t0=now[0] + 0.04, start_steps=steps1, seed=2)
        feed(app.tracker, leg2)
        now[0] = leg2[-1][1]
        return app, spoken, led, events, now

    def test_step_by_step_guidance_advances_around_corner_and_arrives(self):
        app, spoken, led, events, now = self.build_l_route_app()
        outbound_point_count = len(app.store.current.points)

        # Verify end of outbound L-walk is near (-10.5, 14.0) facing -90 deg.
        pose0 = app.tracker.pose
        self.assertAlmostEqual(pose0.x_m, -10.5, places=1)
        self.assertAlmostEqual(pose0.y_m, 14.0, places=1)
        self.assertEqual(pose0.heading_deg, -90.0)

        spoken.clear()
        led.calls.clear()
        events.clear()

        res = app.call_tool("navigate_to", {"target": "start"})
        self.assertTrue(res.ok)
        self.assertEqual(res.led, "navigating")
        self.assertEqual(
            [(i["turn"], i["steps"]) for i in res.data["instructions"]],
            [("around", 15), ("right", 20), ("arrive", 0)],
        )
        self.assertIsNotNone(app.navigator)
        self.assertTrue(app.navigator.active)
        self.assertEqual(app.navigator.current_index, 0)

        spoken.clear()
        led.calls.clear()

        # Walk 15 steps back along +x (heading = 90) from (-10.5, 14.0) to (0.0, 14.0).
        t = now[0]
        base_steps = pose0.steps
        for step_i in range(1, 16):
            t += 0.5
            x = pose0.x_m + step_i * 0.7
            y = pose0.y_m
            app.on_pose(PoseSample(t=t, x_m=x, y_m=y, heading_deg=90.0, steps=base_steps + step_i))

        # Near the corner, turn_now must have triggered with strictly decreasing periods!
        turn_periods = [period for state, period in led.calls if state == "turn_now" and period is not None]
        self.assertGreaterEqual(len(turn_periods), 2)
        self.assertEqual(turn_periods, sorted(turn_periods, reverse=True))
        self.assertLess(turn_periods[-1], turn_periods[0])
        self.assertEqual(turn_periods[0], turn_now_period(3))

        # At the corner (0, 14), guidance must have advanced to leg 1 and spoken it.
        self.assertEqual(app.navigator.current_index, 1)
        self.assertTrue(app.navigator.active)
        self.assertIn("Turn right, walk 20 steps.", spoken)

        # Turn right (heading = 180) and walk 20 steps south from (0.0, 14.0) to (0.0, 0.0).
        for step_j in range(1, 21):
            t += 0.5
            y = 14.0 - step_j * 0.7
            app.on_pose(PoseSample(t=t, x_m=0.0, y_m=y, heading_deg=180.0, steps=base_steps + 15 + step_j))

        # Once aligned on leg 1, LED returned to "navigating", and upon reaching (0, 0) fired "arrived"!
        led_states = [s for s, _ in led.calls]
        self.assertIn("navigating", led_states)
        self.assertEqual(led_states[-1], "arrived")
        self.assertIn("You have reached the start.", spoken)
        self.assertFalse(app.navigator.active)
        self.assertEqual(app.navigator.current_index, 2)

        # Outbound recorded points were not polluted by return-trip footsteps.
        self.assertEqual(len(app.store.current.points), outbound_point_count)

        # Guidance events were emitted for initial plan, corner advance, and final arrival.
        guidance_events = [e for e in events if e["type"] == "guidance"]
        self.assertGreaterEqual(len(guidance_events), 3)
        self.assertFalse(guidance_events[-1]["active"])

    def test_guidance_respects_output_modes_and_cancellation(self):
        app, spoken, led, _, now = self.build_l_route_app()
        app.call_tool("set_mode", {"mode": "light-only"})
        spoken.clear()
        led.calls.clear()

        app.call_tool("navigate_to", {"target": "lm2"})  # back to elevator at (0, 14)
        self.assertEqual(spoken, [])
        self.assertTrue(app.navigator.active)

        # Walk back 15 steps to elevator at (0, 14): should arrive silently with "arrived" LED.
        pose0 = app.tracker.pose
        for step_i in range(1, 16):
            app.on_pose(PoseSample(now[0] + step_i * 0.5, pose0.x_m + step_i * 0.7, pose0.y_m, 90.0, pose0.steps + step_i))
        self.assertEqual(spoken, [])
        self.assertEqual(led.calls[-1][0], "arrived")
        self.assertFalse(app.navigator.active)

        # Start another guidance session, then verify stop_route cancels it cleanly.
        app.call_tool("set_mode", {"mode": "both"})
        app.call_tool("navigate_to", {"target": "start"})
        self.assertTrue(app.navigator.active)
        app.call_tool("stop_route", {})
        self.assertFalse(app.navigator.active)


class BandMirrorTests(unittest.TestCase):
    def test_band_mirror_round_trip_and_byte_limit(self):
        storage = FakeBandStorage()
        mirror = BandLandmarkMirror(storage)

        lm1 = Landmark("lm1", "entrance", 0, floor="G", note="glass revolving doors")
        slot1 = mirror.mirror(lm1)
        self.assertEqual(slot1, 0)
        loaded = mirror.read(slot1)
        self.assertIsNotNone(loaded)
        self.assertEqual((loaded.id, loaded.label, loaded.point_index, loaded.floor, loaded.note),
                         ("lm1", "entrance", 0, "G", "glass revolving doors"))

        # Huge multi-byte UTF-8 note & label must still fit within <= 232 UTF-8 bytes!
        huge_note = "🧭 café corner — " * 40
        lm2 = Landmark("lm2", "elevator bank east", 28, floor="B2", note=huge_note)
        raw = encode_landmark_slot(lm2)
        self.assertLessEqual(len(raw.encode("utf-8")), MAX_SLOT_BYTES)
        slot2 = mirror.mirror(lm2)
        self.assertEqual(slot2, 1)

        all_lms = mirror.read_all()
        self.assertEqual([item.id for item in all_lms], ["lm1", "lm2"])

        # Secret-like strings are scrubbed before ever touching band storage.
        lm_secret = Landmark("lm3", "desk", 5, note="OPENAI_API_KEY and sk-1234567890abcdefghijklmnop")
        s3 = mirror.mirror(lm_secret)
        self.assertNotIn("OPENAI_API_KEY", storage.slots[s3])
        self.assertNotIn("sk-12345", storage.slots[s3])

        # Delete & clear
        self.assertTrue(mirror.delete("lm1"))
        self.assertIsNone(mirror.read(slot1))
        mirror.clear()
        self.assertEqual(storage.slots, {})

    def test_band_mirror_handles_busy_storage_gracefully(self):
        busy_storage = FakeBandStorage(fail_mode="busy")
        mirror = BandLandmarkMirror(busy_storage)
        self.assertIsNone(mirror.mirror(Landmark("lm1", "lobby", 0)))
        self.assertIsNone(mirror.read(0))


class WebSocketServerTests(unittest.TestCase):
    @staticmethod
    def _open_ws(srv: MapWebSocketServer):
        """Connect tiny_websocket.WebSocket over 127.0.0.1 TCP (or socketpair in restricted sandboxes)."""
        url = "ws://127.0.0.1:%d/" % srv.port
        try:
            return tiny_websocket.WebSocket(url, timeout=3)
        except tiny_websocket.WebSocketError as exc:
            if "Operation not permitted" not in str(exc):
                raise
            client_sock, server_sock = socket.socketpair()
            srv.attach_socket(server_sock)
            with mock.patch.object(socket, "create_connection", return_value=client_sock):
                return tiny_websocket.WebSocket(url, timeout=3)

    @staticmethod
    def _recv_json(ws, timeout=2.0):
        raw = ws.recv(timeout=timeout)
        if raw is None:
            raise AssertionError("WebSocket closed unexpectedly")
        return json.loads(raw)

    def _drain_until(self, ws, predicate, max_messages=25, timeout=2.0):
        seen = []
        for _ in range(max_messages):
            msg = self._recv_json(ws, timeout=timeout)
            seen.append(msg)
            if predicate(msg):
                return seen
        raise AssertionError("Condition not met within %d messages; saw: %r" % (max_messages, seen))

    def test_websocket_end_to_end_commands_stream_and_multi_tab_snapshot(self):
        now = [1_700_000_000.0]
        app = SpatialMemoryApp(PathTracker(step_length_m=0.7), RouteStore(), speak=lambda _: None, clock=lambda: now[0])

        with MapWebSocketServer(app, host="127.0.0.1", port=0, mode="SIMULATION") as srv:
            self.assertGreater(srv.port, 0)

            ws1 = self._open_ws(srv)
            try:
                # 1. Initial snapshot: mode, link, led, guidance
                initial = self._drain_until(ws1, lambda m: m.get("type") == "guidance")
                by_type = {m["type"]: m for m in initial}
                self.assertEqual(by_type["mode"]["mode"], "SIMULATION")
                self.assertEqual(by_type["link"]["status"], "simulated")
                self.assertEqual(by_type["led"]["state"], "idle")
                self.assertFalse(by_type["guidance"]["active"])

                # 2. Send typed command: start route
                ws1.send(json.dumps({"type": "command", "text": "start route"}))
                after_start = self._drain_until(
                    ws1,
                    lambda m: m.get("type") == "led" and m.get("state") == "route_started",
                )
                types_seen = [m["type"] for m in after_start]
                self.assertIn("reset", types_seen)
                self.assertIn("point", types_seen)
                self.assertIn("say", types_seen)

                # 3. Feed PoseSamples along +y and save a landmark via typed command
                app.on_pose(PoseSample(t=now[0] + 1.0, x_m=0.0, y_m=3.5, heading_deg=0.0, steps=5))
                pt_msgs = self._drain_until(ws1, lambda m: m.get("type") == "point" and m.get("steps") == 5)
                self.assertAlmostEqual(pt_msgs[-1]["y_m"], 3.5)

                ws1.send(json.dumps({"type": "command", "text": "remember this as lobby"}))
                lm_msgs = self._drain_until(
                    ws1,
                    lambda m: m.get("type") == "led" and m.get("state") == "landmark_saved",
                )
                lm_event = [m for m in lm_msgs if m["type"] == "landmark"][0]
                self.assertEqual(lm_event["label"], "lobby")
                self.assertAlmostEqual(lm_event["y_m"], 3.5)

                # 4. Walk further and trigger return guidance over WebSocket
                app.on_pose(PoseSample(t=now[0] + 3.0, x_m=0.0, y_m=10.5, heading_deg=0.0, steps=15))
                self._drain_until(ws1, lambda m: m.get("type") == "point" and m.get("steps") == 15)

                ws1.send(json.dumps({"type": "command", "text": "take me back to start"}))
                nav_msgs = self._drain_until(
                    ws1,
                    lambda m: m.get("type") == "led" and m.get("state") == "navigating",
                )
                guidance_event = [m for m in nav_msgs if m["type"] == "guidance"][0]
                self.assertTrue(guidance_event["active"])
                self.assertEqual(guidance_event["instructions"][0]["turn"], "around")

                # 5. Open a second tab (ws2) and verify full state restoration snapshot!
                ws2 = self._open_ws(srv)
                try:
                    snap2 = self._drain_until(ws2, lambda m: m.get("type") == "guidance")
                    snap_landmarks = [m for m in snap2 if m["type"] == "landmark"]
                    snap_points = [m for m in snap2 if m["type"] == "point"]
                    self.assertEqual(len(snap_landmarks), 1)
                    self.assertEqual(snap_landmarks[0]["label"], "lobby")
                    self.assertGreaterEqual(len(snap_points), 3)
                    self.assertTrue([m for m in snap2 if m["type"] == "guidance"][0]["active"])

                    # Link status broadcast reaches both tabs
                    srv.send_link("reconnecting")
                    self.assertEqual(self._drain_until(ws1, lambda m: m.get("type") == "link")[-1]["status"], "reconnecting")
                    self.assertEqual(self._drain_until(ws2, lambda m: m.get("type") == "link")[-1]["status"], "reconnecting")

                    # "delete all" clears routes and broadcasts reset
                    ws2.send(json.dumps({"type": "command", "text": "delete all"}))
                    self._drain_until(ws1, lambda m: m.get("type") == "reset")
                    self.assertEqual(app.store.routes, [])
                finally:
                    ws2.close()
            finally:
                ws1.close()

    @staticmethod
    def _http_get(httpd, port: int, path: str):
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
            conn.close()
            return status, body
        except PermissionError:
            client_sock, server_sock = socket.socketpair()
            t = threading.Thread(
                target=lambda: _SafeStaticHandler(server_sock, ("127.0.0.1", 0), httpd, directory=REPO_ROOT),
                daemon=True,
            )
            t.start()
            conn = HTTPConnection("127.0.0.1", port, timeout=3)
            conn.sock = client_sock
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
            conn.close()
            server_sock.close()
            t.join(timeout=1.0)
            return status, body

    def test_static_http_blocks_dotfiles_and_serves_web_page(self):
        httpd = _start_static_http("127.0.0.1", 0, REPO_ROOT)
        port = httpd.server_address[1]
        try:
            status_ok, body = self._http_get(httpd, port, "/web/index.html")
            self.assertEqual(status_ok, 200)
            self.assertIn("Wearable Spatial Memory", body)

            status_env, _ = self._http_get(httpd, port, "/.env")
            self.assertEqual(status_env, 403)

            status_git, _ = self._http_get(httpd, port, "/.git/HEAD")
            self.assertEqual(status_git, 403)
        finally:
            httpd.shutdown()
            httpd.server_close()


class WebSafetyAuditTests(unittest.TestCase):
    FORBIDDEN_DOM_SINKS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")
    FORBIDDEN_KEY_NAMES = (
        "VEXO_GEMINI_API_KEY",
        "VEXO_DEEPGRAM_API_KEY",
        "VEXO_ELEVENLABS_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "DEEPGRAM_API_KEY",
        "ELEVENLABS_API_KEY",
    )

    def test_web_assets_contain_no_unsafe_html_sinks_or_api_keys(self):
        web_dir = os.path.join(REPO_ROOT, "web")
        checked = 0
        for fname in os.listdir(web_dir):
            fpath = os.path.join(web_dir, fname)
            if not os.path.isfile(fpath) or not fname.endswith((".html", ".js", ".css", ".py", ".md")):
                continue
            checked += 1
            with open(fpath, encoding="utf-8") as f:
                content = f.read()
            if fname.endswith((".html", ".js")):
                for sink in self.FORBIDDEN_DOM_SINKS:
                    self.assertNotIn(sink, content, "%s must not use %s" % (fname, sink))
            for key_name in self.FORBIDDEN_KEY_NAMES:
                self.assertNotIn(key_name, content, "%s must not reference %s" % (fname, key_name))
        self.assertGreaterEqual(checked, 4)


if __name__ == "__main__":
    unittest.main()
