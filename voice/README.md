# voice/ — owner: @voice

Implemented modules on the baseline branch:

- `led_states.py`: LED vocabulary (`STATES`, `LedCue`, `turn_now_period`) and `LedController`.
- `gemini_client.py`: Pure-stdlib HTTPS Gemini tool-calling client (`choose_tool`, `build_function_declarations`). Sends `VEXO_GEMINI_API_KEY` via `x-goog-api-key` header (never in URL query strings), blocks HTTP redirects, sets `functionCallingConfig.mode = "ANY"`, and converts `interfaces.TOOLS` + `app.landmark_summary()` into grounded tool calls.
- `elevenlabs_tts.py`: Pure-stdlib HTTPS ElevenLabs TTS client (`ElevenLabsSpeaker`, `speak`, `synthesize_mp3`). Sends `VEXO_ELEVENLABS_API_KEY` via `xi-api-key` header to `config.ELEVENLABS_VOICE_ID` (`SAz9YHcvj6GT2YYXdXww`), plays audio on the laptop speaker (`afplay` on macOS), cleans up temporary MP3 files in `finally:`, and falls back to macOS `say` and terminal `[SAY]` output.
- `loop.py`: Baseline tap-to-talk controller (`VoiceLoop`).

## 1. Baseline loop

Wiring with `SpatialMemoryApp` and `tracker.band_source`:

```python
from voice import LedController, VoiceLoop

led = LedController()
app = SpatialMemoryApp(tracker, store, led=led)
voice_loop = VoiceLoop.create(app)
band = band_source.connect(tracker, logger, on_double_tap=voice_loop.on_double_tap)
voice_loop.band = band
led.band = band
voice_loop.start_background()
```

One turn (`VoiceLoop.run_turn`):

1. `on_double_tap()` sets an internal `threading.Event` and returns immediately so it never blocks the band's event-dispatch thread (`vexo-open-kit/AGENTS.md`). Extra taps while a turn is running are ignored.
2. The worker thread records `config.LISTEN_SECONDS` on the band via Deepgram (`speech.listen`). While `audio=True`, the band locks its LED solid blue.
3. `audio=False` is guaranteed before any tool or LED call runs.
4. `choose_tool` sends the transcript, `interfaces.TOOLS`, and `app.landmark_summary()` to `config.GEMINI_MODEL`. If Gemini is unconfigured or unavailable, `VoiceLoop` falls back to `app.keyword_command(words)`.
5. `app.call_tool(name, args)` validates arguments and calls `app.output(result)`: `ElevenLabsSpeaker` speaks `result.say` (with `say` / `print` fallback) and `LedController` shows `result.led` now that the microphone is off.

Keys: `keys.prepare()` runs at start-up before any SDK or kit `speech` import, stripping generic environment variables (`GEMINI_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`) and passing explicit `VEXO_*` keys only. Tap-to-talk only: never always-on listening.

## 2. Pipecat port (separate `voice-pipecat` branch)

For the Deepgram sponsor track (`DeepgramSTTService` -> `GoogleLLMService` with `interfaces.TOOLS` -> `ElevenLabsTTSService` -> local audio out, supporting both laptop microphone input and Vexo band Opus decoded via `vexo_open.audio.PcmDecoder`), see branch `voice-pipecat`.
