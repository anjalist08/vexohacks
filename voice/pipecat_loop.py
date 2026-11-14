"""Pipecat voice pipeline port for the Vexo band (`voice-pipecat` branch).

Pipeline:
    (Band Opus -> 16 kHz PCM via PcmDecoder  OR  Laptop mic via LocalAudioTransport)
    -> DeepgramSTTService
    -> GoogleLLMService (configured with `interfaces.TOOLS` + `app.landmark_summary()`)
    -> PipecatToolBridge (`app.call_tool`, unlocking band LED before `app.output`)
    -> ElevenLabsTTSService (`config.ELEVENLABS_VOICE_ID`)
    -> LocalAudioTransport speaker output

Key & band safety invariants:
- `keys.prepare()` runs BEFORE any Pipecat, Deepgram, Google, ElevenLabs, or kit import.
- Keys come ONLY from `keys.get("deepgram" | "gemini" | "elevenlabs")` and are passed
  explicitly to each service constructor.
- Pipecat is imported lazily so `import voice.pipecat_loop` and `python3 -m unittest`
  succeed even when `pipecat-ai` is not installed.
- `BandOpusFeeder` pre-loads `vexo_open.audio.PcmDecoder()` BEFORE `band.configure(audio=True)`
  (`vexo-open-kit/docs/speech.md`) and forces `band.configure(audio=False)` before any tool
  sets the band's LED (`vexo-open-kit/AGENTS.md` rule 4).
- `on_double_tap` only sets a `threading.Event` and never blocks the band handler thread.
"""
import asyncio
import inspect
import os
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import config
import keys

keys.prepare()

from interfaces import TOOLS, ToolResult  # noqa: E402
from voice.gemini_client import (  # noqa: E402
    RECOMMENDED_GEMINI_4_MODEL,
    build_function_declarations,
    build_system_instruction,
)

KIT_PYTHON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "vexo-open-kit",
    "python",
)
INPUT_SOURCES = ("band", "laptop_mic")
PCM_SAMPLE_RATE = 16000
PCM_CHANNELS = 1

DEEPGRAM_NOTICE = (
    "Note: while this runs, everything the band's microphone hears is sent over the "
    "internet to Deepgram (deepgram.com). Tell the people near the band."
)


class PipecatConfigError(Exception):
    """Raised when configuration, keys, or input source settings are invalid."""


class PipecatUnavailableError(Exception):
    """Raised when `pipecat-ai` is required at runtime and is not installed."""


@dataclass
class FallbackInputAudioRawFrame:
    """Lightweight fallback frame representation used when Pipecat is stubbed in tests."""
    audio: bytes
    sample_rate: int = PCM_SAMPLE_RATE
    num_channels: int = PCM_CHANNELS


@dataclass
class FallbackTextFrame:
    """Lightweight fallback text frame representation for TTS testing."""
    text: str


@dataclass
class PipecatBundle:
    """Lazily loaded (or test-injected) Pipecat classes."""
    DeepgramSTTService: Any
    GoogleLLMService: Any
    ElevenLabsTTSService: Any
    LocalAudioTransport: Any
    LocalAudioTransportParams: Any
    Pipeline: Any
    PipelineTask: Any
    PipelineRunner: Any
    InputAudioRawFrame: Any
    TextFrame: Any
    FunctionSchema: Optional[Any] = None
    ToolsSchema: Optional[Any] = None


def _load_pcm_decoder_cls():
    keys.prepare()
    if KIT_PYTHON not in sys.path:
        sys.path.insert(0, KIT_PYTHON)
    from vexo_open.audio import PcmDecoder  # type: ignore
    return PcmDecoder


def load_pipecat_bundle() -> PipecatBundle:
    """Lazily import Pipecat only when building a live pipeline."""
    keys.prepare()
    try:
        from pipecat.frames.frames import InputAudioRawFrame, TextFrame
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.runner import PipelineRunner
        from pipecat.pipeline.task import PipelineTask

        try:
            from pipecat.services.deepgram.stt import DeepgramSTTService
        except ImportError:
            from pipecat.services.deepgram import DeepgramSTTService  # type: ignore

        try:
            from pipecat.services.google.llm import GoogleLLMService
        except ImportError:
            from pipecat.services.google import GoogleLLMService  # type: ignore

        try:
            from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
        except ImportError:
            from pipecat.services.elevenlabs import ElevenLabsTTSService  # type: ignore

        from pipecat.transports.local.audio import (
            LocalAudioTransport,
            LocalAudioTransportParams,
        )

        try:
            from pipecat.adapters.schemas.function_schema import FunctionSchema
            from pipecat.adapters.schemas.tools_schema import ToolsSchema
        except ImportError:
            FunctionSchema = None
            ToolsSchema = None

        return PipecatBundle(
            DeepgramSTTService=DeepgramSTTService,
            GoogleLLMService=GoogleLLMService,
            ElevenLabsTTSService=ElevenLabsTTSService,
            LocalAudioTransport=LocalAudioTransport,
            LocalAudioTransportParams=LocalAudioTransportParams,
            Pipeline=Pipeline,
            PipelineTask=PipelineTask,
            PipelineRunner=PipelineRunner,
            InputAudioRawFrame=InputAudioRawFrame,
            TextFrame=TextFrame,
            FunctionSchema=FunctionSchema,
            ToolsSchema=ToolsSchema,
        )
    except ImportError as exc:
        raise PipecatUnavailableError(
            "Pipecat is not installed. Install optional dependencies with: "
            "python3 -m pip install -r requirements-pipecat.txt"
        ) from exc


def build_pipecat_tools(
    tools: Optional[List[dict]] = None,
    bundle: Optional[PipecatBundle] = None,
) -> Any:
    """Build Pipecat `ToolsSchema` if available, else Gemini `functionDeclarations` list."""
    specs = list(TOOLS if tools is None else tools)
    if bundle is not None and bundle.FunctionSchema is not None and bundle.ToolsSchema is not None:
        fn_schemas = []
        for spec in specs:
            params = spec.get("parameters") or {}
            properties: Dict[str, dict] = {}
            required: List[str] = []
            for pname, pspec in params.items():
                prop: Dict[str, Any] = {"type": pspec.get("type", "string")}
                if "description" in pspec:
                    prop["description"] = pspec["description"]
                if "enum" in pspec:
                    prop["enum"] = list(pspec["enum"])
                properties[pname] = prop
                if pspec.get("required"):
                    required.append(pname)
            fn_schemas.append(
                bundle.FunctionSchema(
                    name=spec["name"],
                    description=spec.get("description", ""),
                    properties=properties,
                    required=required,
                )
            )
        return bundle.ToolsSchema(standard_tools=fn_schemas)
    return [{"function_declarations": build_function_declarations(specs)}]


class BandOpusFeeder:
    """Decodes Vexo band Opus packets to 16 kHz 16-bit mono PCM `InputAudioRawFrame`s.

    Pre-initializes `PcmDecoder()` BEFORE `band.configure(audio=True)` so the multi-second
    first-load of `av` never eats into the `LISTEN_SECONDS` recording window, and turns
    `audio=False` in `finally:` so the band LED unlocks before any tool updates the LED.
    """

    def __init__(
        self,
        band,
        frame_sink: Callable[[Any], Any],
        decoder_factory: Optional[Callable[[], Any]] = None,
        frame_cls: Any = FallbackInputAudioRawFrame,
        listen_seconds: Optional[float] = None,
        notice_fn: Optional[Callable[[str], None]] = print,
    ) -> None:
        self.band = band
        self.frame_sink = frame_sink
        self._decoder_factory = decoder_factory or _load_pcm_decoder_cls
        self._frame_cls = frame_cls
        self.listen_seconds = listen_seconds
        self._notice_fn = notice_fn

        self._decoder: Optional[Any] = None
        self._active = False
        self._mic_configured_on = False
        self._lock = threading.Lock()

        self._tap_event = threading.Event()
        self._stop_event = threading.Event()
        self._busy = False
        self._worker: Optional[threading.Thread] = None

    @property
    def active(self) -> bool:
        return self._active

    def preload_decoder(self) -> Any:
        """Load `PcmDecoder` once before opening the band's microphone."""
        if self._decoder is None:
            if self._notice_fn is not None:
                self._notice_fn("Loading the sound decoder...")
            self._decoder = self._decoder_factory()
        return self._decoder

    def start_window(self) -> None:
        """Pre-load decoder, print Deepgram notice, attach handler, and switch mic ON."""
        with self._lock:
            if self._active:
                return
            self.preload_decoder()
            if self._notice_fn is not None:
                self._notice_fn(DEEPGRAM_NOTICE)
            self._active = True
            self.band.on("audio", self._on_audio)
            try:
                self.band.configure(audio=True)
                self._mic_configured_on = True
            except Exception:
                self._active = False
                self.band.off("audio", self._on_audio)
                raise

    def stop_window(self) -> None:
        """Detach audio handler, flush decoder, and switch mic OFF so LED unlocks."""
        with self._lock:
            was_active = self._active
            was_mic_on = self._mic_configured_on
            self._active = False
            self._mic_configured_on = False

        if not was_active and not was_mic_on:
            return

        try:
            self.band.off("audio", self._on_audio)
            if self._decoder is not None and hasattr(self._decoder, "flush"):
                tail = self._decoder.flush()
                if tail:
                    self._push_pcm(tail)
        finally:
            try:
                self.band.configure(audio=False)
            except Exception:
                pass

    def record_turn_window(self, seconds: Optional[float] = None) -> None:
        """Open band mic for one tap-to-talk window (`config.LISTEN_SECONDS`) then close it."""
        duration = (
            float(seconds)
            if seconds is not None
            else (
                float(self.listen_seconds)
                if self.listen_seconds is not None
                else float(config.LISTEN_SECONDS)
            )
        )
        self.start_window()
        try:
            self.band.wait(duration)
        finally:
            self.stop_window()

    def on_double_tap(self, _event=None) -> bool:
        """Non-blocking handler for `band.on('double-tap', ...)`; never blocks band thread."""
        if self._busy:
            return False
        self._tap_event.set()
        return True

    def start_background(self) -> threading.Thread:
        """Run a background daemon thread servicing queued `on_double_tap` turns."""
        if self._worker is not None and self._worker.is_alive():
            return self._worker
        self._stop_event.clear()
        worker = threading.Thread(
            target=self._worker_loop,
            name="vexo-pipecat-band-feeder",
            daemon=True,
        )
        self._worker = worker
        worker.start()
        return worker

    def stop_background(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        self._tap_event.set()
        worker = self._worker
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=timeout)
        self._worker = None
        self.stop_window()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._tap_event.wait(timeout=0.1):
                continue
            self._tap_event.clear()
            if self._stop_event.is_set():
                break
            self._busy = True
            try:
                self.record_turn_window()
            finally:
                self._busy = False

    def _on_audio(self, audio_event: Any) -> None:
        if not self._active or self._decoder is None:
            return
        pcm = self._decoder.feed(audio_event)
        if pcm:
            self._push_pcm(pcm)

    def _push_pcm(self, pcm: bytes) -> None:
        frame = self._frame_cls(
            audio=bytes(pcm),
            sample_rate=PCM_SAMPLE_RATE,
            num_channels=PCM_CHANNELS,
        )
        out = self.frame_sink(frame)
        if inspect.isawaitable(out):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(out)
            except RuntimeError:
                asyncio.run(out)


class PipecatToolBridge:
    """Bridges Gemini LLM tool calls inside Pipecat to `SpatialMemoryApp.call_tool`.

    Guarantees:
    1. Calls `before_tool_output` (e.g., `BandOpusFeeder.stop_window`) BEFORE `app.call_tool`
       so the band microphone is guaranteed OFF before `app.output` updates the LED.
    2. Suppresses duplicate direct speaker invocation inside `app.call_tool` and forwards
       `result.say` as a `TextFrame` to `ElevenLabsTTSService` once (when not `light-only`).
    """

    def __init__(
        self,
        app,
        tts_frame_sink: Optional[Callable[[Any], Any]] = None,
        before_tool_output: Optional[Callable[[], None]] = None,
        text_frame_cls: Any = FallbackTextFrame,
        on_say: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.app = app
        self.tts_frame_sink = tts_frame_sink
        self.before_tool_output = before_tool_output
        self.text_frame_cls = text_frame_cls
        self.on_say = on_say

    def execute_tool(self, name: str, args: Optional[dict] = None) -> ToolResult:
        """Synchronously validate and run `name` on `self.app`, emitting TTS frame & LED."""
        if self.before_tool_output is not None:
            self.before_tool_output()

        original_speak = self.app.speak

        def _capture_terminal_only(spoken_text: str) -> None:
            if self.on_say is not None:
                self.on_say(spoken_text)
            else:
                print("    [SAY] %s" % spoken_text)

        self.app.speak = _capture_terminal_only
        try:
            result = self.app.call_tool(name, dict(args or {}))
        finally:
            self.app.speak = original_speak

        if self.app.mode != "light-only" and result.say and self.tts_frame_sink is not None:
            frame = self.text_frame_cls(text=result.say)
            out = self.tts_frame_sink(frame)
            if inspect.isawaitable(out):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(out)
                except RuntimeError:
                    asyncio.run(out)

        return result

    def register_all(self, llm_service: Any, tools: Optional[List[dict]] = None) -> None:
        """Register every tool in `interfaces.TOOLS` on `GoogleLLMService`."""
        specs = list(TOOLS if tools is None else tools)
        for spec in specs:
            tool_name = spec["name"]
            llm_service.register_function(tool_name, self._make_async_handler(tool_name))

    def _make_async_handler(self, fixed_name: str):
        async def _handler(*pos_args, **kw_args):
            # Supports both modern Pipecat `FunctionCallParams` (single arg)
            # and legacy 6-arg `(function_name, tool_call_id, args, llm, context, result_callback)`
            if len(pos_args) == 1 and hasattr(pos_args[0], "arguments"):
                params = pos_args[0]
                fn_name = getattr(params, "function_name", fixed_name) or fixed_name
                raw_args = dict(getattr(params, "arguments", None) or {})
                result = self.execute_tool(fn_name, raw_args)
                # If no explicit tts_frame_sink was wired, push TextFrame via params.llm if present
                if (
                    self.tts_frame_sink is None
                    and self.app.mode != "light-only"
                    and result.say
                    and hasattr(params, "llm")
                    and hasattr(params.llm, "push_frame")
                ):
                    maybe = params.llm.push_frame(self.text_frame_cls(text=result.say))
                    if inspect.isawaitable(maybe):
                        await maybe
                cb = getattr(params, "result_callback", None)
                if callable(cb):
                    maybe_cb = cb({"ok": result.ok, "say": result.say, "led": result.led})
                    if inspect.isawaitable(maybe_cb):
                        await maybe_cb
                return result

            fn_name = pos_args[0] if len(pos_args) >= 1 and isinstance(pos_args[0], str) else fixed_name
            raw_args = pos_args[2] if len(pos_args) >= 3 and isinstance(pos_args[2], dict) else kw_args
            llm_obj = pos_args[3] if len(pos_args) >= 4 else None
            result_cb = pos_args[5] if len(pos_args) >= 6 else None

            result = self.execute_tool(fn_name, dict(raw_args or {}))
            if (
                self.tts_frame_sink is None
                and self.app.mode != "light-only"
                and result.say
                and llm_obj is not None
                and hasattr(llm_obj, "push_frame")
            ):
                maybe = llm_obj.push_frame(self.text_frame_cls(text=result.say))
                if inspect.isawaitable(maybe):
                    await maybe
            if callable(result_cb):
                maybe_cb = result_cb({"ok": result.ok, "say": result.say, "led": result.led})
                if inspect.isawaitable(maybe_cb):
                    await maybe_cb
            return result

        return _handler


class PipecatVoiceLoop:
    """Assembles and runs the Deepgram -> Gemini -> ElevenLabs Pipecat pipeline."""

    def __init__(
        self,
        app,
        input_source: str = "band",
        band=None,
        model: Optional[str] = None,
        voice_id: Optional[str] = None,
        listen_seconds: Optional[float] = None,
        bundle: Optional[PipecatBundle] = None,
        decoder_factory: Optional[Callable[[], Any]] = None,
        on_say: Optional[Callable[[str], None]] = None,
        notice_fn: Optional[Callable[[str], None]] = print,
    ) -> None:
        keys.prepare()
        if input_source not in INPUT_SOURCES:
            raise PipecatConfigError(
                "input_source must be one of %s, got %r." % (INPUT_SOURCES, input_source)
            )
        if input_source == "band" and band is None:
            raise PipecatConfigError("input_source='band' requires a `band` instance.")

        self.app = app
        self.input_source = input_source
        self.band = band
        self.model = model
        self.voice_id = voice_id
        self.listen_seconds = listen_seconds
        self._bundle = bundle
        self._decoder_factory = decoder_factory
        self._on_say = on_say
        self._notice_fn = notice_fn

        self.stt: Optional[Any] = None
        self.llm: Optional[Any] = None
        self.tts: Optional[Any] = None
        self.transport: Optional[Any] = None
        self.pipeline: Optional[Any] = None
        self.task: Optional[Any] = None
        self.tool_bridge: Optional[PipecatToolBridge] = None
        self.band_feeder: Optional[BandOpusFeeder] = None

    def _resolve_keys_and_config(self) -> Dict[str, str]:
        keys.prepare()
        resolved_model = self.model if self.model is not None else config.GEMINI_MODEL
        if not resolved_model or not str(resolved_model).strip():
            raise PipecatConfigError(
                "GEMINI_MODEL is not set in config.py (recommended Gemini 4 model: '%s')."
                % RECOMMENDED_GEMINI_4_MODEL
            )
        resolved_voice = (
            self.voice_id if self.voice_id is not None else config.ELEVENLABS_VOICE_ID
        )
        if not resolved_voice or not str(resolved_voice).strip():
            raise PipecatConfigError("ELEVENLABS_VOICE_ID is not set in config.py.")

        try:
            deepgram_key = keys.get("deepgram", required=True)
            gemini_key = keys.get("gemini", required=True)
            elevenlabs_key = keys.get("elevenlabs", required=True)
        except SystemExit as exc:
            raise PipecatConfigError(str(exc)) from exc

        return {
            "deepgram_key": deepgram_key,
            "gemini_key": gemini_key,
            "elevenlabs_key": elevenlabs_key,
            "model": str(resolved_model).strip(),
            "voice_id": str(resolved_voice).strip(),
        }

    def build(self) -> Any:
        """Instantiate services with explicit `VEXO_` keys and wire the pipeline."""
        cfg = self._resolve_keys_and_config()
        bundle = self._bundle or load_pipecat_bundle()

        landmark_summary = self.app.landmark_summary()
        route_active = bool(
            self.app.store.current and getattr(self.app.store.current, "active", False)
        )
        system_instruction = build_system_instruction(
            landmark_summary=landmark_summary,
            route_active=route_active,
        )
        tools_schema = build_pipecat_tools(TOOLS, bundle=bundle)

        # Gemini 4 prohibits custom `temperature`, `top_p`, `top_k`, and `thinking_budget`.
        # Pass only explicit credentials, model id, system instruction, and native tool schemas.
        self.stt = bundle.DeepgramSTTService(api_key=cfg["deepgram_key"])
        self.llm = bundle.GoogleLLMService(
            api_key=cfg["gemini_key"],
            model=cfg["model"],
            system_instruction=system_instruction,
            tools=tools_schema,
        )
        self.tts = bundle.ElevenLabsTTSService(
            api_key=cfg["elevenlabs_key"],
            voice_id=cfg["voice_id"],
        )

        if self.input_source == "laptop_mic":
            transport_params = bundle.LocalAudioTransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=PCM_SAMPLE_RATE,
                audio_in_channels=PCM_CHANNELS,
            )
            self.transport = bundle.LocalAudioTransport(transport_params)
            stages = [
                self.transport.input(),
                self.stt,
                self.llm,
                self.tts,
                self.transport.output(),
            ]
        else:
            transport_params = bundle.LocalAudioTransportParams(
                audio_in_enabled=False,
                audio_out_enabled=True,
            )
            self.transport = bundle.LocalAudioTransport(transport_params)
            stages = [
                self.stt,
                self.llm,
                self.tts,
                self.transport.output(),
            ]

        self.pipeline = bundle.Pipeline(stages)
        self.task = bundle.PipelineTask(self.pipeline)

        def _queue_frame(frame: Any) -> Any:
            if hasattr(self.task, "queue_frame"):
                return self.task.queue_frame(frame)
            if hasattr(self.task, "queue_frames"):
                return self.task.queue_frames([frame])
            return None

        if self.input_source == "band":
            if self.app.led is not None and getattr(self.app.led, "band", None) is None:
                self.app.led.band = self.band
            self.band_feeder = BandOpusFeeder(
                band=self.band,
                frame_sink=_queue_frame,
                decoder_factory=self._decoder_factory,
                frame_cls=bundle.InputAudioRawFrame,
                listen_seconds=self.listen_seconds,
                notice_fn=self._notice_fn,
            )
            self.band_feeder.preload_decoder()

        def _tts_sink(text_frame: Any) -> Any:
            if hasattr(self.tts, "queue_frame"):
                return self.tts.queue_frame(text_frame)
            if hasattr(self.tts, "push_frame"):
                return self.tts.push_frame(text_frame)
            return _queue_frame(text_frame)

        self.tool_bridge = PipecatToolBridge(
            app=self.app,
            tts_frame_sink=_tts_sink,
            before_tool_output=(
                self.band_feeder.stop_window if self.band_feeder is not None else None
            ),
            text_frame_cls=bundle.TextFrame,
            on_say=self._on_say,
        )
        self.tool_bridge.register_all(self.llm, TOOLS)
        return self.task

    def on_double_tap(self, event=None) -> bool:
        """Delegate band double-taps to `BandOpusFeeder.on_double_tap` (non-blocking)."""
        if self.band_feeder is None:
            return False
        return self.band_feeder.on_double_tap(event)

    async def run_async(self) -> None:
        """Build (if needed) and run the Pipecat `PipelineTask`."""
        bundle = self._bundle or load_pipecat_bundle()
        if self.task is None:
            self.build()
        runner = bundle.PipelineRunner()
        if self.band_feeder is not None:
            self.band_feeder.start_background()
        try:
            await runner.run(self.task)
        finally:
            if self.band_feeder is not None:
                self.band_feeder.stop_background()
