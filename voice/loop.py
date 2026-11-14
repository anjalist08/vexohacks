"""Baseline tap-to-talk voice loop (`VoiceLoop`).

Connects one spoken turn end to end:
    double-tap -> worker thread -> band mic on -> Deepgram STT -> band mic off
    -> Gemini tool choice -> SpatialMemoryApp.call_tool -> ElevenLabs TTS -> band LED

Critical band invariants (`vexo-open-kit/AGENTS.md`):
1. `on_double_tap` NEVER calls `speech.listen` on the band's event-handler thread;
   it only sets a `threading.Event` (ignoring extra taps while busy), and a separate
   worker thread (or `poll_once`) executes `run_turn()`.
2. While the band's microphone is on (`audio=True`), the band locks its LED solid blue
   and rejects `set_led` with `denied`. The microphone is always switched off
   (`band.configure(audio=False)`) BEFORE `app.call_tool`, `app.keyword_command`,
   or `led.reapply` runs.
"""
import os
import sys
import threading
from typing import Callable, Optional, Tuple

import config
import keys
from interfaces import ToolResult
from voice.elevenlabs_tts import ElevenLabsError, ElevenLabsSpeaker
from voice.gemini_client import GeminiError, choose_tool

KIT_EXAMPLES_PYTHON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "vexo-open-kit",
    "examples",
    "python",
)


def _printable(text: str, limit: int = 200) -> str:
    """Speech text, safe to print: no terminal control characters, at most `limit` chars."""
    clean = "".join(c if c.isprintable() else " " for c in str(text))
    return clean[:limit] + ("..." if len(clean) > limit else "")


def _safe_mic_off(band) -> None:
    """Switch off the band's microphone so the LED unlocks."""
    if band is None or not hasattr(band, "configure"):
        return
    try:
        band.configure(audio=False)
    except Exception:
        pass


def _band_mic_looks_on(band) -> bool:
    if band is None:
        return False
    for attr in ("audio", "audio_on", "mic_on", "_audio_on"):
        val = getattr(band, attr, False)
        if isinstance(val, bool) and val:
            return True
    return False


def _safe_error_summary(exc: BaseException) -> str:
    """Summarize an error without ever echoing raw third-party payloads or secrets."""
    if isinstance(exc, (GeminiError, ElevenLabsError)):
        return str(exc)
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return "code=%s" % code
    return exc.__class__.__name__


def _load_kit_speech():
    keys.prepare()
    if KIT_EXAMPLES_PYTHON not in sys.path:
        sys.path.insert(0, KIT_EXAMPLES_PYTHON)
    import speech  # type: ignore
    return speech


class VoiceLoop:
    """Tap-to-talk controller bridging Vexo band audio, Deepgram, Gemini, and ElevenLabs."""

    def __init__(
        self,
        app,
        band=None,
        listen_seconds: Optional[float] = None,
        listen_fn: Optional[Callable[..., Optional[str]]] = None,
        choose_fn: Optional[Callable[..., Tuple[str, dict]]] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        keys.prepare()
        self.app = app
        self.band = band
        self.listen_seconds = listen_seconds
        self._listen_fn = listen_fn
        self._choose_fn = choose_fn
        self._log_fn = log_fn

        self._tap_event = threading.Event()
        self._stop_event = threading.Event()
        self._turn_lock = threading.Lock()
        self._busy = False
        self._worker: Optional[threading.Thread] = None

    @classmethod
    def create(
        cls,
        app,
        band=None,
        listen_seconds: Optional[float] = None,
        listen_fn: Optional[Callable[..., Optional[str]]] = None,
        choose_fn: Optional[Callable[..., Tuple[str, dict]]] = None,
        speaker: Optional[ElevenLabsSpeaker] = None,
        log_fn: Optional[Callable[[str], None]] = None,
        **speaker_kwargs
    ) -> "VoiceLoop":
        """Build a `VoiceLoop` and wire `ElevenLabsSpeaker` onto `app.speak`."""
        keys.prepare()
        app.speak = speaker or ElevenLabsSpeaker(**speaker_kwargs)
        if app.led is not None and band is not None and getattr(app.led, "band", None) is None:
            app.led.band = band
        return cls(
            app=app,
            band=band,
            listen_seconds=listen_seconds,
            listen_fn=listen_fn,
            choose_fn=choose_fn,
            log_fn=log_fn,
        )

    @property
    def busy(self) -> bool:
        return self._busy

    def on_double_tap(self, _event=None) -> bool:
        """Non-blocking handler for `band.on('double-tap', ...)` / `band_source.connect(...)`.

        Never listens inside the band event handler thread; only flags `_tap_event`.
        Returns True if a turn was queued, False if ignored because a turn is active.
        """
        if self._busy:
            return False
        self._tap_event.set()
        return True

    def start_background(self) -> threading.Thread:
        """Start a daemon worker thread that runs one turn per queued double-tap."""
        if self._worker is not None and self._worker.is_alive():
            return self._worker
        self._stop_event.clear()
        worker = threading.Thread(
            target=self._worker_loop,
            name="vexo-voice-loop",
            daemon=True,
        )
        self._worker = worker
        worker.start()
        return worker

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the background worker thread cleanly."""
        self._stop_event.set()
        self._tap_event.set()
        worker = self._worker
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=timeout)
        self._worker = None

    def poll_once(self, timeout: float = 0.2) -> Optional[ToolResult]:
        """Wait up to `timeout` seconds for a double-tap and run one turn on this thread."""
        if not self._tap_event.wait(timeout=timeout):
            return None
        self._tap_event.clear()
        if self._stop_event.is_set():
            return None
        return self.run_turn()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._tap_event.wait(timeout=0.1):
                continue
            self._tap_event.clear()
            if self._stop_event.is_set():
                break
            try:
                self.run_turn()
            except Exception as exc:
                self._log("Voice turn error (%s)." % _safe_error_summary(exc))

    def _status(self, state: str, **fields) -> None:
        """Tell the map page where the turn is: listening, heard, thinking, done, nothing, error."""
        emit = getattr(self.app, "_emit", None)
        if callable(emit):
            try:
                emit(dict({"type": "voice", "state": state}, **fields))
            except Exception:
                pass

    def _log(self, message: str) -> None:
        if self._log_fn is not None:
            self._log_fn(message)
        else:
            print("    [VOICE] %s" % message, file=sys.stderr)

    def _restore_led(self) -> None:
        led = getattr(self.app, "led", None)
        if led is not None and hasattr(led, "reapply"):
            led.reapply()

    def run_turn(self, say_text: Optional[str] = None) -> Optional[ToolResult]:
        """Execute a single tap-to-talk turn (or typed `say_text` bypass)."""
        with self._turn_lock:
            self._busy = True
            try:
                return self._run_turn_locked(say_text=say_text)
            finally:
                self._busy = False

    def _run_turn_locked(self, say_text: Optional[str] = None) -> Optional[ToolResult]:
        keys.prepare()
        if say_text is not None:
            words = str(say_text).strip()
            if words:
                self._status("heard", text=_printable(words), typed=True)
        else:
            ok, heard, partial_fallback = self._listen_once()
            if partial_fallback:
                self._status("heard", text=_printable(partial_fallback))
                result = self.app.keyword_command(partial_fallback)
                self._status("done", say=result.say if result else "")
                return result
            if not ok:
                self._status("error", text="I couldn't hear that. Check the band and try again.")
                self._restore_led()
                return None
            words = (heard or "").strip()
            self._log('Heard: "%s"' % _printable(words) if words else "Heard nothing (speak while the light is blue).")
            if words:
                self._status("heard", text=_printable(words))

        if not words:
            self._status("nothing", text="I didn't hear anything. Tap Talk, then speak right away.")
            self._restore_led()
            return None

        landmark_summary = self.app.landmark_summary()
        route_active = bool(
            self.app.store.current and getattr(self.app.store.current, "active", False)
        )
        chooser = self._choose_fn or choose_tool
        self._status("thinking", text=_printable(words))

        try:
            tool_name, tool_args = chooser(
                words,
                landmark_summary=landmark_summary,
                route_active=route_active,
            )
        except (Exception, SystemExit) as exc:
            self._log(
                "Gemini unavailable (%s); falling back to keyword command."
                % _safe_error_summary(exc)
            )
            result = self.app.keyword_command(words)
            self._status("done", say=result.say if result else "", tool="keyword")
            return result

        self._log("Gemini chose %s %s" % (tool_name, _printable(str(tool_args))))
        result = self.app.call_tool(tool_name, tool_args)
        self._status("done", say=result.say if result else "", tool=tool_name, ok=bool(result and result.ok))
        return result

    def _listen_once(self) -> Tuple[bool, str, str]:
        """Record one window on `self.band` and guarantee `audio=False` before returning.

        Returns `(ok, transcript, partial_for_keyword_fallback)`.
        """
        if self.band is None:
            self._log("No band connected; cannot record microphone audio.")
            return False, "", ""

        seconds = (
            float(self.listen_seconds)
            if self.listen_seconds is not None
            else float(config.LISTEN_SECONDS)
        )

        if self._listen_fn is not None:
            try:
                transcript = self._listen_fn(self.band, seconds)
                return True, transcript or "", ""
            except (Exception, SystemExit) as exc:
                _safe_mic_off(self.band)
                self._log("Speech-to-text failed (%s)." % _safe_error_summary(exc))
                return False, "", ""
            finally:
                if _band_mic_looks_on(self.band):
                    _safe_mic_off(self.band)

        if not keys.get("deepgram", required=False):
            self._log("Missing VEXO_DEEPGRAM_API_KEY; cannot transcribe band audio.")
            return False, "", ""

        partials = []

        def _on_text(text: str, _final: bool) -> None:
            cleaned = (text or "").strip()
            if cleaned:
                partials.append(cleaned)

        try:
            speech = _load_kit_speech()
            self._status("listening", seconds=seconds)
            # keyterm: Deepgram nova-3 prompt for a word the wrist mic often mishears (the kit
            # sends one keyterm; it cannot repeat the parameter).
            transcript = speech.listen(self.band, seconds, on_text=_on_text, keyterm="landmark")
            return True, transcript or "", ""
        except (Exception, SystemExit) as exc:
            _safe_mic_off(self.band)
            if partials:
                self._log(
                    "Deepgram interrupted (%s); using partial transcript with keyword fallback."
                    % _safe_error_summary(exc)
                )
                return False, "", partials[-1]
            self._log("Deepgram transcription failed (%s)." % _safe_error_summary(exc))
            return False, "", ""
        finally:
            if _band_mic_looks_on(self.band):
                _safe_mic_off(self.band)
