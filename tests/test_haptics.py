"""Haptic coach: buzz cues from facing direction and the route's next leg."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interfaces import PoseSample  # noqa: E402
from store.guidance import build_guidance_session  # noqa: E402
from store.haptics import PATTERNS, HapticCoach, cue_message  # noqa: E402


def l_route():
    """Walk back east 10 m from (-10, 14), then south 14 m to the start (0, 0)."""
    pts = [PoseSample(0, -10.0, 14.0, 90.0, 0)]
    pts += [PoseSample(i, -10.0 + i * 0.7, 14.0, 90.0, i) for i in range(1, 15)]
    pts += [PoseSample(20 + i, 0.0, 14.0 - i * 0.7, 180.0, 14 + i) for i in range(1, 21)]
    return build_guidance_session(pts, "kitchen", facing_deg=90.0, step_length_m=0.7)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class CoachTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.coach = HapticCoach(clock=self.clock)
        self.nav = l_route()
        self.here = PoseSample(0, -10.0, 14.0, 90.0, 0)

    def look(self, facing, pose=None, uncertain=False):
        return self.coach.update(self.nav, facing, pose or self.here, uncertain)

    def test_wrong_way_says_which_way_to_turn(self):
        self.assertEqual(self.look(0.0)["cue"], "wrong_right")     # route goes east (90): turn right
        self.clock.t += 0.5
        self.assertIsNone(self.look(0.0)["cue"])                   # not again until it repeats
        self.clock.t += 3.0
        self.assertEqual(self.look(0.0)["cue"], "wrong_right")
        self.assertEqual(self.look(180.0)["cue"], None)            # same "wrong" timer
        self.clock.t += 3.0
        self.assertEqual(self.look(180.0)["cue"], "wrong_left")

    def test_lock_on_then_quiet_ticks(self):
        self.look(0.0)
        r = self.look(85.0)
        self.assertEqual(r["cue"], "on_track")
        self.assertEqual(r["hint"]["state"], "on_track")
        self.clock.t += 1.0
        self.assertIsNone(self.look(100.0)["cue"])
        self.clock.t += 4.0
        self.assertEqual(self.look(95.0)["cue"], "tick")

    def test_hysteresis_keeps_lock_between_30_and_50_degrees(self):
        self.look(90.0)                                            # locked on
        self.clock.t += 0.2
        self.assertNotIn(self.look(130.0)["cue"], ("wrong_left", "wrong_right"))   # 40 deg off: still on track
        self.clock.t += 3.0
        self.assertEqual(self.look(150.0)["cue"], "wrong_left")    # 60 deg off: wrong way

    def test_turn_soon_then_turn_now(self):
        self.look(90.0)                                            # on track, walking east
        near = PoseSample(5, -1.4, 14.0, 90.0, 12)                 # 2 steps from the corner
        self.clock.t += 2.0
        r = self.look(90.0, near)
        self.assertEqual(r["cue"], "turn_soon")
        self.assertEqual(r["hint"]["next_turn"], "right")
        self.nav.current_index = 1                                 # guidance moved to the next leg
        r = self.look(90.0, PoseSample(6, 0.0, 14.0, 90.0, 14))
        self.assertEqual(r["cue"], "turn_right")

    def test_arrived_once_then_quiet(self):
        self.nav.current_index = len(self.nav.segments)
        self.nav.active = False
        self.assertEqual(self.look(180.0)["cue"], "arrived")
        self.clock.t += 5.0
        self.assertIsNone(self.look(180.0)["cue"])

    def test_lost_repeats(self):
        self.assertEqual(self.look(90.0, uncertain=True)["cue"], "lost")
        self.clock.t += 1.0
        self.assertIsNone(self.look(90.0, uncertain=True)["cue"])
        self.clock.t += 4.0
        self.assertEqual(self.look(90.0, uncertain=True)["cue"], "lost")

    def test_no_guidance_no_buzz(self):
        r = self.coach.update(None, 0.0)
        self.assertIsNone(r["cue"])
        self.assertFalse(r["hint"]["active"])

    def test_every_cue_has_a_pattern_and_message(self):
        for cue in ("wrong_left", "wrong_right", "on_track", "tick", "turn_soon", "turn_left",
                    "turn_right", "turn_around", "arrived", "lost"):
            msg = cue_message(cue, {"target": "kitchen"})
            self.assertEqual(msg["type"], "haptic")
            self.assertEqual(msg["pattern"], PATTERNS[cue])
        self.assertNotEqual(PATTERNS["wrong_left"], PATTERNS["wrong_right"])
        self.assertNotEqual(PATTERNS["turn_left"], PATTERNS["turn_right"])



class PhoneAccessTests(unittest.TestCase):
    """Other devices may only open the phone page, and only with the token."""

    def handler(self, path, ip, token="s3cret"):
        from web.ws_server import _SafeStaticHandler
        cls = type("H", (_SafeStaticHandler,), {"phone_token": token})
        h = cls.__new__(cls)          # no socket: only the path rules are tested
        h.path, h.client_address = path, (ip, 50000)
        return h

    def test_laptop_unchanged(self):
        self.assertFalse(self.handler("/web/trail.html", "127.0.0.1")._is_forbidden_path())
        self.assertTrue(self.handler("/.env", "127.0.0.1")._is_forbidden_path())

    def test_phone_needs_token_and_gets_only_the_phone_page(self):
        lan = "192.168.1.23"
        self.assertFalse(self.handler("/web/phone.html?ws_port=8765&token=s3cret", lan)._is_forbidden_path())
        self.assertTrue(self.handler("/web/phone.html?token=wrong", lan)._is_forbidden_path())
        self.assertTrue(self.handler("/web/phone.html", lan)._is_forbidden_path())
        self.assertTrue(self.handler("/web/trail.html?token=s3cret", lan)._is_forbidden_path())
        self.assertTrue(self.handler("/config.py?token=s3cret", lan)._is_forbidden_path())

    def test_no_phone_mode_means_no_other_devices(self):
        self.assertTrue(self.handler("/web/phone.html?token=", "192.168.1.23", token=None)._is_forbidden_path())


class PhoneHandshakeTests(unittest.TestCase):
    def shake(self, peer, path, token):
        import time as _t
        from app import SpatialMemoryApp
        from store.route_store import RouteStore
        from tracker.pdr import PathTracker
        from web.ws_server import MapWebSocketServer

        class Sock:
            def __init__(self):
                self.data, self.sent = (b"GET " + path.encode() + b" HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
                                        b"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                                        b"Sec-WebSocket-Version: 13\r\n\r\n"), b""

            def settimeout(self, t):
                pass

            def recv(self, n):
                d, self.data = self.data[:n], self.data[n:]
                return d

            def sendall(self, b):
                self.sent += b

            def getpeername(self):
                return (peer, 50000)

        server = MapWebSocketServer(SpatialMemoryApp(PathTracker(), RouteStore(), speak=lambda t: None,
                                                     clock=_t.time), mode="LIVE")
        server.phone_token = token
        sock = Sock()
        return server._perform_handshake(sock), sock.sent

    def test_phone_handshake(self):
        ok, sent = self.shake("192.168.1.23", "/?token=s3cret", "s3cret")
        self.assertTrue(ok)
        ok, sent = self.shake("192.168.1.23", "/?token=nope", "s3cret")
        self.assertFalse(ok)
        self.assertIn(b"403", sent)
        ok, _ = self.shake("192.168.1.23", "/", None)
        self.assertFalse(ok)
        ok, _ = self.shake("127.0.0.1", "/", None)            # this laptop: no token needed
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
