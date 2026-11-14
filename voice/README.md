# voice/ — owner: @voice

Implemented modules on the baseline branch:

- `led_states.py`: LED vocabulary (`STATES`, `LedCue`, `turn_now_period`) and `LedController`.
- `gemini_client.py`: Pure-stdlib HTTPS Gemini 4 tool-calling client (`choose_tool`, `build_function_declarations`, `GEMINI_4_MODELS`, `RECOMMENDED_GEMINI_4_MODEL`). Sends `VEXO_GEMINI_API_KEY` via `x-goog-api-key` header (never in URL query strings), blocks HTTP redirects, declares native `functionDeclarations` with `toolConfig.functionCallingConfig.mode = "ANY"`, and omits `temperature`, `topP` / `top_p`, `topK` / `top_k`, and legacy `thinkingBudget` per the Gemini 4 builder guide.
- `elevenlabs_tts.py`: Pure-stdlib HTTPS ElevenLabs TTS client (`ElevenLabsSpeaker`, `speak`, `synthesize_mp3`). Sends `VEXO_ELEVENLABS_API_KEY` via `xi-api-key` header to `config.ELEVENLABS_VOICE_ID` (`SAz9YHcvj6GT2YYXdXww`), plays audio on the laptop speaker (`afplay` on macOS), cleans up temporary MP3 files in `finally:`, and falls back to MiniMax, then macOS `say`, then terminal `[SAY]` output.
- `minimax_tts.py`: backup voice (MiniMax T2A, `config.MINIMAX_TTS_MODEL` / `MINIMAX_VOICE_ID`). Used only when ElevenLabs has no key or fails, and only if `VEXO_MINIMAX_API_KEY` is set. Key in the `Authorization: Bearer` header, redirects refused, errors report status numbers only. ElevenLabs stays the main voice for its sponsor track.
- `loop.py`: Baseline tap-to-talk controller (`VoiceLoop`).

## Gemini 4 model configuration

`config.GEMINI_MODEL` is left `None` in `config.py` for the team to set. Verified Gemini 4 model IDs (`voice.GEMINI_4_MODELS`):

- `GEMINI_MODEL = "gemini-4-hydrogen"` — **recommended** fast interactive workhorse for tap-to-talk tool calls
- `GEMINI_MODEL = "gemini-4-argon"` — balanced Gemini 4 model
- `GEMINI_MODEL = "gemini-4-carbon"` — frontier reasoning Gemini 4 model

Per Gemini 4 API rules, requests never include custom `temperature`, `top_p`, `top_k`, or legacy `thinking_budget` (and `"minimal"` thinking level is rejected).

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
4. `choose_tool` sends the transcript, native `interfaces.TOOLS` `functionDeclarations`, and `app.landmark_summary()` to `config.GEMINI_MODEL`. If Gemini is unconfigured or unavailable, `VoiceLoop` falls back to `app.keyword_command(words)`.
5. `app.call_tool(name, args)` validates arguments and calls `app.output(result)`: `ElevenLabsSpeaker` speaks `result.say` (with MiniMax / `say` / `print` fallback) and `LedController` shows `result.led` now that the microphone is off.

Keys: `keys.prepare()` runs at start-up before any SDK or kit `speech` import, stripping generic environment variables (`GEMINI_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`) and passing explicit `VEXO_*` keys only. Tap-to-talk only: never always-on listening.

## 2. Pipecat port (separate `voice-pipecat` branch)

For the Deepgram sponsor track (`DeepgramSTTService` -> `GoogleLLMService` with `interfaces.TOOLS` -> `ElevenLabsTTSService` -> local audio out, supporting both laptop microphone input and Vexo band Opus decoded via `vexo_open.audio.PcmDecoder`), see branch `voice-pipecat`.
