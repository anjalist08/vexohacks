"""Unit tests for the baseline voice subsystem (`voice/`).

Uses pure fakes/stubs for band, Deepgram STT, Gemini HTTPS, and ElevenLabs TTS.
Never connects to a real or simulated Vexo band and never makes network calls.
"""
import io
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import keys  # noqa: E402
from app import SpatialMemoryApp  # noqa: E402
from interfaces import TOOLS  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import feed, synthetic_walk  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402
from voice import (  # noqa: E402
    ElevenLabsError,
    ElevenLabsSpeaker,
    GEMINI_4_MODELS,
    GeminiError,
    LedController,
    RECOMMENDED_GEMINI_4_MODEL,
    VoiceLoop,
    build_function_declarations,
    build_request_payload,
    choose_tool,
    synthesize_mp3,
)
from voice.elevenlabs_tts import _NoRedirect as ElevenNoRedirect  # noqa: E402
from voice.gemini_client import _NoRedirect as GeminiNoRedirect  # noqa: E402


class FakeHttpResponse:
    def __init__(self, body_bytes: bytes, status: int = 200):
        self._buf = io.BytesIO(body_bytes)
        self.status = status

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class CapturingOpener:
    """Records `urllib.request.Request` calls and returns canned responses or errors."""

    def __init__(self, responder):
        self.responder = responder
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append((req, timeout))
        return self.responder(req, timeout)


class StrictFakeBand:
    """Mimics the Vexo band's audio/LED lock: `set_led` fails with `denied` while `audio=True`."""

    def __init__(self):
        self.audio_on = False
        self.events = []
        self._handlers = {}

    def on(self, event_name, fn):
        self._handlers.setdefault(event_name, []).append(fn)

    def off(self, event_name, fn):
        handlers = self._handlers.get(event_name, [])
        if fn in handlers:
            handlers.remove(fn)

    def configure(self, **kwargs):
        if "audio" in kwargs:
            self.audio_on = bool(kwargs["audio"])
            self.events.append(("configure_audio", self.audio_on))

    def wait(self, seconds):
        self.events.append(("wait", seconds))

    def set_led(self, color, **kwargs):
        if self.audio_on:
            err = Exception("The band refused LED_SET because the microphone is on.")
            err.code = "denied"
            self.events.append(("set_led_denied", color))
            raise err
        self.events.append(("set_led", color, kwargs))

    def led_off(self):
        if self.audio_on:
            err = Exception("denied")
            err.code = "denied"
            raise err
        self.events.append(("led_off", {}))


def _header_ci(req, name: str):
    target = name.lower()
    for k, v in req.header_items():
        if k.lower() == target:
            return v
    return None


class GeminiClientTests(unittest.TestCase):
    def test_function_declarations_match_tools(self):
        decls = build_function_declarations(TOOLS)
        by_name = {d["name"]: d for d in decls}
        self.assertEqual(set(by_name), {t["name"] for t in TOOLS})
        self.assertNotIn("parameters", by_name["stop_route"])
        rem = by_name["remember_landmark"]["parameters"]
        self.assertEqual(rem["type"], "object")
        self.assertEqual(rem["required"], ["label"])
        self.assertIn("floor", rem["properties"])
        self.assertIn("note", rem["properties"])
        mode_prop = by_name["set_mode"]["parameters"]["properties"]["mode"]
        self.assertEqual(mode_prop["enum"], ["both", "light-only", "voice-only"])

    def test_choose_tool_builds_valid_request_and_hides_key_from_url(self):
        secret = "test-vexo-gemini-tok"

        def responder(_req, _timeout):
            body = {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "remember_landmark",
                                        "args": {
                                            "label": "elevator",
                                            "note": "near the blue sign",
                                            "floor": None,
                                        },
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
            return FakeHttpResponse(json.dumps(body).encode("utf-8"))

        opener = CapturingOpener(responder)
        env = {"VEXO_GEMINI_API_KEY": secret}
        with mock.patch.dict(os.environ, env, clear=True):
            name, args = choose_tool(
                "remember this as the elevator near the blue sign",
                landmark_summary="lm1=entrance",
                route_active=True,
                model="gemini-4-hydrogen",
                opener=opener,
            )

        self.assertEqual(name, "remember_landmark")
        self.assertEqual(args, {"label": "elevator", "note": "near the blue sign"})
        self.assertEqual(len(opener.requests), 1)
        req, _ = opener.requests[0]
        self.assertEqual(
            req.full_url,
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-4-hydrogen:generateContent",
        )
        self.assertNotIn(secret, req.full_url)
        self.assertNotIn("key=", req.full_url)
        self.assertEqual(_header_ci(req, "x-goog-api-key"), secret)

        sent_raw = req.data.decode("utf-8")
        sent = json.loads(sent_raw)
        self.assertEqual(sent["toolConfig"]["functionCallingConfig"]["mode"], "ANY")
        self.assertIn("lm1=entrance", sent["systemInstruction"]["parts"][0]["text"])
        self.assertEqual(
            len(sent["tools"][0]["functionDeclarations"]),
            len(TOOLS),
        )
        for forbidden in (
            "temperature",
            "topP",
            "top_p",
            "topK",
            "top_k",
            "thinkingBudget",
            "thinking_budget",
        ):
            self.assertNotIn(forbidden, sent)
            self.assertNotIn(forbidden, sent_raw)

    def test_gemini_4_models_and_thinking_level_rules(self):
        self.assertEqual(RECOMMENDED_GEMINI_4_MODEL, "gemini-4-hydrogen")
        self.assertEqual(
            set(GEMINI_4_MODELS),
            {"gemini-4-hydrogen", "gemini-4-argon", "gemini-4-carbon"},
        )
        default_payload = build_request_payload("start route", landmark_summary="none")
        self.assertNotIn("generationConfig", default_payload)
        for forbidden in (
            "temperature",
            "topP",
            "top_p",
            "topK",
            "top_k",
            "thinkingBudget",
            "thinking_budget",
        ):
            self.assertNotIn(forbidden, json.dumps(default_payload))
        # "minimal" is prohibited on gemini-4-hydrogen
        with self.assertRaises(GeminiError):
            build_request_payload("start route", landmark_summary="none", thinking_level="minimal")
        low_payload = build_request_payload("start route", landmark_summary="none", thinking_level="low")
        self.assertEqual(low_payload["generationConfig"]["thinkingConfig"]["thinkingLevel"], "low")

    def test_choose_tool_fails_when_model_unset(self):
        self.assertIsNone(config.GEMINI_MODEL)
        with mock.patch.dict(os.environ, {"VEXO_GEMINI_API_KEY": "test-vexo-gemini-tok"}, clear=True):
            with self.assertRaises(GeminiError) as ctx:
                choose_tool("start route", landmark_summary="none")
        self.assertIn("GEMINI_MODEL", str(ctx.exception))

    def test_http_error_reports_status_only_without_leaking_key_or_body(self):
        secret = "test-vexo-secret-999"
        untrusted_body = b'{"error": {"message": "echoed test-vexo-secret-999 quota"}}'

        def responder(req, _timeout):
            raise urllib.error.HTTPError(
                req.full_url, 429, "Too Many Requests", {}, io.BytesIO(untrusted_body)
            )

        opener = CapturingOpener(responder)
        with self.assertRaises(GeminiError) as ctx:
            choose_tool(
                "where is the entrance",
                landmark_summary="lm1=entrance",
                model="gemini-4-hydrogen",
                api_key=secret,
                opener=opener,
            )
        msg = str(ctx.exception)
        self.assertIn("429", msg)
        self.assertNotIn(secret, msg)
        self.assertNotIn("quota", msg)

    def test_no_redirect_handler_blocks_redirects(self):
        handler = GeminiNoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "https://example.com"))

    def test_generic_gemini_env_keys_are_ignored(self):
        env = {
            "GEMINI_API_KEY": "personal-key-do-not-touch",
            "GOOGLE_API_KEY": "personal-google-key",
            "OPENAI_API_KEY": "personal-openai-key",
        }
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(keys, "ENV_FILE", "/nonexistent/.env"):
            with self.assertRaises(GeminiError):
                choose_tool("start route", landmark_summary="none", model="gemini-4-hydrogen")
            self.assertNotIn("GEMINI_API_KEY", os.environ)
            self.assertNotIn("GOOGLE_API_KEY", os.environ)
            self.assertNotIn("OPENAI_API_KEY", os.environ)


class ElevenLabsSpeakerTests(unittest.TestCase):
    def test_elevenlabs_sends_header_plays_audio_and_deletes_temp_mp3(self):
        secret = "test-vexo-xi-token"
        fake_mp3 = b"ID3-fake-mp3-payload"
        played_files = []

        def responder(_req, _timeout):
            return FakeHttpResponse(fake_mp3)

        def fake_player(path: str):
            self.assertTrue(path.endswith(".mp3"))
            self.assertTrue(os.path.exists(path))
            with open(path, "rb") as f:
                played_files.append((path, f.read()))

        opener = CapturingOpener(responder)
        said_lines = []
        speaker = ElevenLabsSpeaker(
            api_key=secret,
            opener=opener,
            player=fake_player,
            allow_macos_say=False,
            on_say=said_lines.append,
        )
        backend = speaker("Saved: elevator.")

        self.assertEqual(backend, "elevenlabs")
        self.assertEqual(said_lines, ["Saved: elevator."])
        self.assertEqual(len(played_files), 1)
        temp_path, content = played_files[0]
        self.assertEqual(content, fake_mp3)
        self.assertFalse(os.path.exists(temp_path))

        req, _ = opener.requests[0]
        self.assertEqual(
            req.full_url,
            "https://api.elevenlabs.io/v1/text-to-speech/%s" % config.ELEVENLABS_VOICE_ID,
        )
        self.assertNotIn(secret, req.full_url)
        self.assertEqual(_header_ci(req, "xi-api-key"), secret)
        self.assertEqual(_header_ci(req, "accept"), "audio/mpeg")

    def test_temp_mp3_deleted_even_when_player_raises(self):
        captured_paths = []

        def broken_player(path: str):
            captured_paths.append(path)
            raise OSError("speaker disconnected")

        opener = CapturingOpener(lambda _req, _t: FakeHttpResponse(b"mp3-bytes"))
        say_calls = []
        speaker = ElevenLabsSpeaker(
            api_key="test-vexo-xi-token",
            opener=opener,
            player=broken_player,
            allow_macos_say=True,
            say_runner=say_calls.append,
            on_say=lambda _t: None,
        )
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            backend = speaker("Turn left, walk 15 steps.")

        self.assertEqual(backend, "macos_say")
        self.assertEqual(say_calls, ["Turn left, walk 15 steps."])
        self.assertEqual(len(captured_paths), 1)
        self.assertFalse(os.path.exists(captured_paths[0]))

    def test_fallback_to_macos_say_and_print_when_key_missing_or_http_fails(self):
        env = {"ELEVENLABS_API_KEY": "personal-eleven-key"}
        say_calls = []
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(keys, "ENV_FILE", "/nonexistent/.env"):
            speaker = ElevenLabsSpeaker(
                allow_macos_say=True,
                say_runner=say_calls.append,
                on_say=lambda _t: None,
            )
            self.assertEqual(speaker("Route started."), "macos_say")
            self.assertEqual(say_calls, ["Route started."])
            self.assertNotIn("ELEVENLABS_API_KEY", os.environ)

            # Now disable macOS say too -> falls back to print("[SAY] ...")
            with mock.patch("builtins.print") as mock_print:
                speaker_print = ElevenLabsSpeaker(allow_macos_say=False)
                self.assertEqual(speaker_print("Route saved."), "print")
                mock_print.assert_called_once_with("    [SAY] Route saved.")

    def test_synthesize_mp3_http_error_hides_key(self):
        secret = "test-vexo-xi-hidden"

        def responder(req, _timeout):
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized", {}, io.BytesIO(b"bad test-vexo-xi-hidden")
            )

        with self.assertRaises(ElevenLabsError) as ctx:
            synthesize_mp3("Hello", api_key=secret, opener=CapturingOpener(responder))
        self.assertIn("401", str(ctx.exception))
        self.assertNotIn(secret, str(ctx.exception))
        self.assertIsNone(
            ElevenNoRedirect().redirect_request(None, None, 307, "Redirect", {}, "https://example.com")
        )


class VoiceLoopTests(unittest.TestCase):
    def setUp(self):
        self._leds = []

    def tearDown(self):
        for led in self._leds:
            if led._timer is not None:
                led._timer.cancel()
                led._timer = None

    def _make_app_with_band(self):
        band = StrictFakeBand()
        led = LedController(band=band)
        self._leds.append(led)
        walk = synthetic_walk(legs=((20, "left"), (15, None)))
        now = [walk[0][1]]
        app = SpatialMemoryApp(
            PathTracker(step_length_m=0.7),
            RouteStore(),
            speak=lambda _t: None,
            led=led,
            clock=lambda: now[0],
        )
        app.call_tool("start_route", {})
        if led._timer is not None:
            led._timer.cancel()
            led._timer = None
        feed(app.tracker, walk)
        band.events.clear()
        return app, band, led

    def test_end_to_end_double_tap_turn_unlocks_led_before_output(self):
        app, band, led = self._make_app_with_band()

        # Fake Deepgram STT listener that turns mic on (`audio=True`, locking LED) then off
        listen_threads = []
        turn_done = threading.Event()

        def fake_listen(b, seconds):
            listen_threads.append(threading.current_thread().name)
            b.configure(audio=True)
            try:
                b.wait(seconds)
                return "remember this as the elevator near the blue sign"
            finally:
                b.configure(audio=False)

        # Fake Gemini HTTPS opener returning tool call
        def gemini_responder(_req, _timeout):
            body = {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "remember_landmark",
                                        "args": {
                                            "label": "elevator",
                                            "note": "near the blue sign",
                                        },
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
            return FakeHttpResponse(json.dumps(body).encode("utf-8"))

        gemini_opener = CapturingOpener(gemini_responder)

        # Fake ElevenLabs HTTPS opener + player
        tts_opener = CapturingOpener(lambda _req, _t: FakeHttpResponse(b"MP3DATA"))
        played = []

        def fake_player(mp3_path: str):
            played.append(os.path.exists(mp3_path))
            turn_done.set()

        speaker = ElevenLabsSpeaker(
            api_key="test-vexo-xi",
            opener=tts_opener,
            player=fake_player,
            allow_macos_say=False,
            on_say=lambda _t: None,
        )

        voice_loop = VoiceLoop.create(
            app,
            band=band,
            listen_seconds=4.0,
            listen_fn=fake_listen,
            choose_fn=lambda text, landmark_summary, route_active=False: choose_tool(
                text,
                landmark_summary=landmark_summary,
                route_active=route_active,
                model="gemini-4-hydrogen",
                api_key="test-vexo-gm",
                opener=gemini_opener,
            ),
            speaker=speaker,
            log_fn=lambda _m: None,
        )

        voice_loop.start_background()
        try:
            caller_thread = threading.current_thread().name
            queued = voice_loop.on_double_tap()
            self.assertTrue(queued)
            self.assertTrue(turn_done.wait(timeout=3.0), "Background voice turn did not finish")
            # Wait briefly for LED show right after speak() completes
            deadline = time.time() + 1.0
            while led.state != "landmark_saved" and time.time() < deadline:
                time.sleep(0.01)
        finally:
            voice_loop.stop()

        # 1. Listener ran on worker thread, NEVER on the caller/event thread
        self.assertEqual(len(listen_threads), 1)
        self.assertNotEqual(listen_threads[0], caller_thread)

        # 2. Landmark saved in store
        landmarks = app.store.all_landmarks()
        self.assertEqual(len(landmarks), 1)
        self.assertEqual(landmarks[0].label, "elevator")
        self.assertEqual(landmarks[0].note, "near the blue sign")

        # 3. ElevenLabs called with config.ELEVENLABS_VOICE_ID ("SAz9YHcvj6GT2YYXdXww")
        self.assertEqual(played, [True])
        tts_req, _ = tts_opener.requests[0]
        self.assertTrue(tts_req.full_url.endswith("/" + config.ELEVENLABS_VOICE_ID))

        # 4. Strict band ordering: audio=True -> wait -> audio=False -> set_led (zero denied errors!)
        event_kinds = [e[0] for e in band.events]
        self.assertNotIn("set_led_denied", event_kinds)
        self.assertEqual(
            event_kinds,
            ["configure_audio", "wait", "configure_audio", "set_led"],
        )
        self.assertIs(band.events[0][1], True)
        self.assertIs(band.events[2][1], False)
        self.assertEqual(band.events[3][1], "#a020f0")  # purple landmark_saved
        self.assertEqual(led.state, "landmark_saved")

    def test_on_double_tap_returns_immediately_and_ignores_extra_taps_while_busy(self):
        app, band, _ = self._make_app_with_band()
        entered_listen = threading.Event()
        release_listen = threading.Event()
        turns = []

        def slow_listen(b, _seconds):
            b.configure(audio=True)
            entered_listen.set()
            release_listen.wait(timeout=3.0)
            b.configure(audio=False)
            turns.append(1)
            return ""

        voice_loop = VoiceLoop(
            app,
            band=band,
            listen_fn=slow_listen,
            log_fn=lambda _m: None,
        )
        voice_loop.start_background()
        try:
            t0 = time.time()
            self.assertTrue(voice_loop.on_double_tap())
            elapsed = time.time() - t0
            self.assertLess(elapsed, 0.05)
            self.assertTrue(entered_listen.wait(timeout=2.0))
            # While busy listening, extra double-taps must be ignored
            self.assertFalse(voice_loop.on_double_tap())
            release_listen.set()
            time.sleep(0.05)
        finally:
            release_listen.set()
            voice_loop.stop()

        self.assertEqual(len(turns), 1)

    def test_voice_loop_forces_mic_off_if_custom_listener_leaves_mic_on_or_raises(self):
        app, band, led = self._make_app_with_band()
        app.speak = lambda _t: None
        logs = []

        # Listener turns mic on and forgets to turn it off
        def leaky_listen(b, _seconds):
            b.configure(audio=True)
            return "remember this as the lobby"

        voice_loop = VoiceLoop(
            app,
            band=band,
            listen_fn=leaky_listen,
            log_fn=logs.append,
        )
        # Also exercises fallback to keyword_command because GEMINI_MODEL is None!
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(keys, "ENV_FILE", "/nonexistent/.env"):
            result = voice_loop.run_turn()

        self.assertIsNotNone(result)
        self.assertTrue(result.ok)
        self.assertFalse(band.audio_on)
        self.assertEqual(led.state, "landmark_saved")
        self.assertNotIn("set_led_denied", [e[0] for e in band.events])

    def test_gemini_fallbacks_to_keyword_command_on_unset_model_missing_key_or_http_error(self):
        app, band, _ = self._make_app_with_band()
        spoken = []
        app.speak = spoken.append
        app.call_tool("remember_landmark", {"label": "entrance"})
        spoken.clear()

        logs = []
        voice_loop = VoiceLoop(app, band=band, log_fn=logs.append)

        # Case 1: config.GEMINI_MODEL is None -> keyword fallback
        r1 = voice_loop.run_turn(say_text="where was the entrance")
        self.assertIsNotNone(r1)
        self.assertTrue(r1.ok)
        self.assertIn("entrance", r1.say)

        # Case 2: GEMINI_MODEL set, VEXO_GEMINI_API_KEY missing -> keyword fallback
        with mock.patch.object(config, "GEMINI_MODEL", "gemini-4-hydrogen"), \
                mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(keys, "ENV_FILE", "/nonexistent/.env"):
            r2 = voice_loop.run_turn(say_text="remember this as the stairs")
            self.assertIsNotNone(r2)
            self.assertTrue(r2.ok)
            self.assertEqual(r2.say, "Saved: stairs.")

        # Case 3: Gemini HTTP 500 error -> keyword fallback
        def fail_500(req, _timeout):
            raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {}, io.BytesIO(b"err"))

        failing_loop = VoiceLoop(
            app,
            band=band,
            choose_fn=lambda text, landmark_summary, route_active=False: choose_tool(
                text,
                landmark_summary=landmark_summary,
                route_active=route_active,
                model="gemini-4-hydrogen",
                api_key="test-vexo-gm",
                opener=CapturingOpener(fail_500),
            ),
            log_fn=logs.append,
        )
        r3 = failing_loop.run_turn(say_text="take me back to the entrance")
        self.assertIsNotNone(r3)
        self.assertTrue(r3.ok)
        self.assertEqual(r3.led, "navigating")

    def test_deepgram_missing_key_and_partial_transcript_fallback(self):
        app, band, led = self._make_app_with_band()
        app.speak = lambda _t: None
        led.show("recording")
        band.events.clear()
        logs = []
        voice_loop = VoiceLoop(app, band=band, log_fn=logs.append)

        # Missing VEXO_DEEPGRAM_API_KEY -> never turns mic on, reapplies LED, returns None
        with mock.patch.dict(os.environ, {"DEEPGRAM_API_KEY": "personal-dg"}, clear=True), \
                mock.patch.object(keys, "ENV_FILE", "/nonexistent/.env"):
            res = voice_loop.run_turn()
        self.assertIsNone(res)
        self.assertFalse(band.audio_on)
        self.assertEqual(band.events[-1][0], "set_led")  # reapply recording LED

        # Interrupted Deepgram stream after partial transcript -> mic turned off before keyword fallback
        class FakeSpeechModule:
            @staticmethod
            def listen(b, _seconds, on_text=None):
                b.configure(audio=True)
                if on_text:
                    on_text("remember this as the fountain", False)
                raise RuntimeError("socket dropped while mic still on")

        band.events.clear()
        with mock.patch.dict(os.environ, {"VEXO_DEEPGRAM_API_KEY": "test-vexo-dg"}, clear=True), \
                mock.patch("voice.loop._load_kit_speech", return_value=FakeSpeechModule):
            res2 = voice_loop.run_turn()

        self.assertIsNotNone(res2)
        self.assertTrue(res2.ok)
        self.assertFalse(band.audio_on)
        self.assertEqual(app.store.all_landmarks()[-1].label, "fountain")
        self.assertNotIn("set_led_denied", [e[0] for e in band.events])
        self.assertEqual(led.state, "landmark_saved")


if __name__ == "__main__":
    unittest.main()
