"""Unit tests for `voice/pipecat_loop.py` on branch `voice-pipecat`.

Uses lightweight stubs for Pipecat services/frames, `PcmDecoder`, and Vexo band Opus events
so all tests pass on Python 3.9+ without `pipecat-ai`, `av`, live keys, or band hardware.
"""
import asyncio
import os
import sys
import threading
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import keys  # noqa: E402
from app import SpatialMemoryApp  # noqa: E402
from interfaces import TOOLS  # noqa: E402
from store.route_store import RouteStore  # noqa: E402
from tracker.events import feed, synthetic_walk  # noqa: E402
from tracker.pdr import PathTracker  # noqa: E402
from voice.led_states import LedController  # noqa: E402
from voice.pipecat_loop import (  # noqa: E402
    DEEPGRAM_NOTICE,
    BandOpusFeeder,
    PipecatBundle,
    PipecatConfigError,
    PipecatVoiceLoop,
)


@dataclass
class StubInputAudioRawFrame:
    audio: bytes
    sample_rate: int
    num_channels: int


@dataclass
class StubTextFrame:
    text: str


@dataclass
class StubFunctionSchema:
    name: str
    description: str
    properties: dict
    required: list


@dataclass
class StubToolsSchema:
    standard_tools: list


class StubDeepgramSTTService:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class StubGoogleLLMService:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.registered = {}
        self.pushed_frames = []

    def register_function(self, name, handler):
        self.registered[name] = handler

    async def push_frame(self, frame):
        self.pushed_frames.append(frame)


class StubElevenLabsTTSService:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.queued_frames = []

    def queue_frame(self, frame):
        self.queued_frames.append(frame)


class StubLocalAudioTransportParams:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class StubLocalAudioTransport:
    def __init__(self, params):
        self.params = params

    def input(self):
        return ("transport_in", self.params.kwargs)

    def output(self):
        return ("transport_out", self.params.kwargs)


class StubPipeline:
    def __init__(self, stages):
        self.stages = list(stages)


class StubPipelineTask:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.queued_frames = []

    def queue_frame(self, frame):
        self.queued_frames.append(frame)


class StubPipelineRunner:
    def __init__(self):
        self.ran_tasks = []

    async def run(self, task):
        self.ran_tasks.append(task)


def make_stub_bundle() -> PipecatBundle:
    return PipecatBundle(
        DeepgramSTTService=StubDeepgramSTTService,
        GoogleLLMService=StubGoogleLLMService,
        ElevenLabsTTSService=StubElevenLabsTTSService,
        LocalAudioTransport=StubLocalAudioTransport,
        LocalAudioTransportParams=StubLocalAudioTransportParams,
        Pipeline=StubPipeline,
        PipelineTask=StubPipelineTask,
        PipelineRunner=StubPipelineRunner,
        InputAudioRawFrame=StubInputAudioRawFrame,
        TextFrame=StubTextFrame,
        FunctionSchema=StubFunctionSchema,
        ToolsSchema=StubToolsSchema,
    )


class FakeOpusBand:
    """Fake Vexo band emitting Opus packets while `audio=True` and locking LED while mic is on."""

    def __init__(self, packets_on_wait=()):
        self.audio_on = False
        self.timeline = []
        self._handlers = {}
        self._packets_on_wait = list(packets_on_wait)

    def on(self, event, fn):
        self._handlers.setdefault(event, []).append(fn)

    def off(self, event, fn):
        lst = self._handlers.get(event, [])
        if fn in lst:
            lst.remove(fn)

    def emit_audio(self, opus_bytes: bytes, seq: int):
        pkt = SimpleNamespace(opus=opus_bytes, seq=seq)
        for fn in list(self._handlers.get("audio", [])):
            fn(pkt)

    def configure(self, **kwargs):
        if "audio" in kwargs:
            self.audio_on = bool(kwargs["audio"])
            self.timeline.append(("configure_audio", self.audio_on))

    def wait(self, seconds):
        self.timeline.append(("wait", seconds))
        for seq, pkt in enumerate(self._packets_on_wait):
            self.emit_audio(pkt, seq)

    def set_led(self, color, **kwargs):
        if self.audio_on:
            err = Exception("denied: mic is on")
            err.code = "denied"
            self.timeline.append(("set_led_denied", color))
            raise err
        self.timeline.append(("set_led", color, kwargs))

    def led_off(self):
        if self.audio_on:
            err = Exception("denied")
            err.code = "denied"
            raise err
        self.timeline.append(("led_off", {}))


class FakePcmDecoder:
    """Stubs `vexo_open.audio.PcmDecoder` turning each Opus packet into 320 16-bit samples."""

    def __init__(self, timeline):
        self._timeline = timeline
        self._timeline.append(("decoder_init",))
        self.fed = []

    def feed(self, packet, seq=None) -> bytes:
        opus = packet.opus if hasattr(packet, "opus") else bytes(packet)
        self.fed.append(opus)
        self._timeline.append(("decoder_feed", opus))
        return b"\x01\x00" * 320  # 640 bytes = 20 ms at 16 kHz mono 16-bit

    def flush(self) -> bytes:
        self._timeline.append(("decoder_flush",))
        return b"\x02\x00" * 80


class PipecatVoiceLoopTests(unittest.TestCase):
    def setUp(self):
        self._leds = []

    def tearDown(self):
        for led in self._leds:
            if led._timer is not None:
                led._timer.cancel()
                led._timer = None

    def _make_app(self, band=None):
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
        if band is not None:
            band.timeline.clear()
        return app, led

    def test_band_opus_feeder_preloads_decoder_before_mic_on_and_emits_16khz_pcm(self):
        band = FakeOpusBand(packets_on_wait=[b"opus-pkt-1", b"opus-pkt-2"])
        frames = []
        notices = []

        feeder = BandOpusFeeder(
            band=band,
            frame_sink=frames.append,
            decoder_factory=lambda: FakePcmDecoder(band.timeline),
            frame_cls=StubInputAudioRawFrame,
            listen_seconds=3.5,
            notice_fn=notices.append,
        )

        feeder.record_turn_window()

        # Verify strict sequence: decoder_init BEFORE configure_audio=True, and configure_audio=False at end
        self.assertEqual(
            band.timeline,
            [
                ("decoder_init",),
                ("configure_audio", True),
                ("wait", 3.5),
                ("decoder_feed", b"opus-pkt-1"),
                ("decoder_feed", b"opus-pkt-2"),
                ("decoder_flush",),
                ("configure_audio", False),
            ],
        )
        self.assertIn(DEEPGRAM_NOTICE, notices)
        # Two 20 ms frames + one flushed tail frame, all 16 kHz mono
        self.assertEqual(len(frames), 3)
        self.assertEqual(len(frames[0].audio), 640)
        self.assertEqual(frames[0].sample_rate, 16000)
        self.assertEqual(frames[0].num_channels, 1)
        self.assertFalse(band.audio_on)

    def test_double_tap_on_feeder_runs_on_background_worker_not_caller_thread(self):
        band = FakeOpusBand(packets_on_wait=[b"opus-tap"])
        wait_threads = []
        done = threading.Event()

        orig_wait = band.wait

        def tracked_wait(seconds):
            wait_threads.append(threading.current_thread().name)
            orig_wait(seconds)
            done.set()

        band.wait = tracked_wait
        frames = []
        feeder = BandOpusFeeder(
            band=band,
            frame_sink=frames.append,
            decoder_factory=lambda: FakePcmDecoder(band.timeline),
            frame_cls=StubInputAudioRawFrame,
            listen_seconds=0.1,
            notice_fn=lambda _m: None,
        )
        feeder.start_background()
        try:
            caller = threading.current_thread().name
            self.assertTrue(feeder.on_double_tap())
            self.assertTrue(done.wait(timeout=2.0))
        finally:
            feeder.stop_background()

        self.assertEqual(len(wait_threads), 1)
        self.assertNotEqual(wait_threads[0], caller)
        self.assertGreaterEqual(len(frames), 1)
        self.assertFalse(band.audio_on)

    def test_pipecat_build_passes_explicit_vexo_keys_and_supports_both_inputs(self):
        band = FakeOpusBand()
        app, _ = self._make_app(band=band)
        bundle = make_stub_bundle()

        env = {
            "VEXO_DEEPGRAM_API_KEY": "test-vexo-dg-key",
            "VEXO_GEMINI_API_KEY": "test-vexo-gm-key",
            "VEXO_ELEVENLABS_API_KEY": "test-vexo-xi-key",
            "GEMINI_API_KEY": "personal-should-be-dropped",
            "OPENAI_API_KEY": "personal-openai-should-be-dropped",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            # 1) Laptop mic mode
            loop_laptop = PipecatVoiceLoop(
                app=app,
                input_source="laptop_mic",
                model="gemini-4-hydrogen",
                bundle=bundle,
                notice_fn=lambda _m: None,
            )
            task_laptop = loop_laptop.build()
            self.assertEqual(loop_laptop.stt.kwargs["api_key"], "test-vexo-dg-key")
            self.assertEqual(loop_laptop.llm.kwargs["api_key"], "test-vexo-gm-key")
            self.assertEqual(loop_laptop.llm.kwargs["model"], "gemini-4-hydrogen")
            for forbidden in (
                "temperature",
                "topP",
                "top_p",
                "topK",
                "top_k",
                "thinkingBudget",
                "thinking_budget",
                "params",
            ):
                self.assertNotIn(forbidden, loop_laptop.llm.kwargs)
            self.assertEqual(loop_laptop.tts.kwargs["api_key"], "test-vexo-xi-key")
            self.assertEqual(loop_laptop.tts.kwargs["voice_id"], config.ELEVENLABS_VOICE_ID)
            self.assertTrue(loop_laptop.transport.params.kwargs["audio_in_enabled"])
            self.assertTrue(loop_laptop.transport.params.kwargs["audio_out_enabled"])
            self.assertEqual(loop_laptop.transport.params.kwargs["audio_in_sample_rate"], 16000)
            self.assertEqual(len(task_laptop.pipeline.stages), 5)
            self.assertNotIn("GEMINI_API_KEY", os.environ)
            self.assertNotIn("OPENAI_API_KEY", os.environ)

            # 2) Band Opus mode
            loop_band = PipecatVoiceLoop(
                app=app,
                input_source="band",
                band=band,
                model="gemini-4-hydrogen",
                bundle=bundle,
                decoder_factory=lambda: FakePcmDecoder(band.timeline),
                notice_fn=lambda _m: None,
            )
            task_band = loop_band.build()
            self.assertFalse(loop_band.transport.params.kwargs["audio_in_enabled"])
            self.assertTrue(loop_band.transport.params.kwargs["audio_out_enabled"])
            self.assertEqual(len(task_band.pipeline.stages), 4)
            # PcmDecoder was preloaded during build() BEFORE any audio=True!
            self.assertEqual(band.timeline, [("decoder_init",)])
            self.assertEqual(set(loop_band.llm.registered), {t["name"] for t in TOOLS})

    def test_tool_bridge_unlocks_band_led_before_app_output_and_pushes_tts_once(self):
        band = FakeOpusBand()
        app, led = self._make_app(band=band)
        bundle = make_stub_bundle()

        direct_speak_calls = []
        app.speak = direct_speak_calls.append
        terminal_says = []

        env = {
            "VEXO_DEEPGRAM_API_KEY": "test-vexo-dg",
            "VEXO_GEMINI_API_KEY": "test-vexo-gm",
            "VEXO_ELEVENLABS_API_KEY": "test-vexo-xi",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            loop = PipecatVoiceLoop(
                app=app,
                input_source="band",
                band=band,
                model="gemini-4-hydrogen",
                bundle=bundle,
                decoder_factory=lambda: FakePcmDecoder(band.timeline),
                on_say=terminal_says.append,
                notice_fn=lambda _m: None,
            )
            loop.build()

        # Simulate band mic window currently OPEN (LED locked solid blue!) when LLM emits tool call
        loop.band_feeder.start_window()
        band.emit_audio(b"live-opus-frame", seq=0)
        self.assertTrue(band.audio_on)

        handler = loop.llm.registered["remember_landmark"]
        callback_payloads = []
        params = SimpleNamespace(
            function_name="remember_landmark",
            arguments={"label": "elevator", "note": "near the blue sign"},
            llm=loop.llm,
            result_callback=callback_payloads.append,
        )
        result = asyncio.run(handler(params))

        # 1. Tool succeeded and saved landmark
        self.assertTrue(result.ok)
        self.assertEqual(app.store.all_landmarks()[-1].label, "elevator")

        # 2. Band mic was switched OFF before `app.output` set the purple LED (zero `denied`!)
        self.assertFalse(band.audio_on)
        self.assertNotIn("set_led_denied", [e[0] for e in band.timeline])
        self.assertEqual(led.state, "landmark_saved")
        self.assertEqual(band.timeline[-1][0], "set_led")
        self.assertEqual(band.timeline[-1][1], "#a020f0")

        # 3. `result.say` routed once to `ElevenLabsTTSService` without firing `app.speak` audio twice
        self.assertEqual(direct_speak_calls, [])
        self.assertEqual(terminal_says, ["Saved: elevator."])
        self.assertEqual(len(loop.tts.queued_frames), 1)
        self.assertEqual(loop.tts.queued_frames[0].text, "Saved: elevator.")
        self.assertEqual(len(callback_payloads), 1)
        self.assertTrue(callback_payloads[0]["ok"])

    def test_missing_model_or_generic_keys_only_raises_pipecat_config_error(self):
        band = FakeOpusBand()
        app, _ = self._make_app(band=band)
        bundle = make_stub_bundle()

        # Default config.GEMINI_MODEL is None -> raises PipecatConfigError
        with mock.patch.dict(
            os.environ,
            {
                "VEXO_DEEPGRAM_API_KEY": "dg",
                "VEXO_GEMINI_API_KEY": "gm",
                "VEXO_ELEVENLABS_API_KEY": "xi",
            },
            clear=True,
        ):
            loop = PipecatVoiceLoop(app=app, input_source="band", band=band, bundle=bundle)
            with self.assertRaises(PipecatConfigError):
                loop.build()

        # Generic keys without VEXO_* keys -> rejected cleanly
        with mock.patch.dict(
            os.environ,
            {
                "DEEPGRAM_API_KEY": "personal-dg",
                "GEMINI_API_KEY": "personal-gm",
                "ELEVENLABS_API_KEY": "personal-xi",
            },
            clear=True,
        ), mock.patch.object(keys, "ENV_FILE", "/nonexistent/.env"):
            loop2 = PipecatVoiceLoop(
                app=app,
                input_source="laptop_mic",
                model="gemini-4-hydrogen",
                bundle=bundle,
            )
            with self.assertRaises(PipecatConfigError):
                loop2.build()


if __name__ == "__main__":
    unittest.main()
