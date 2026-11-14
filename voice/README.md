# voice/ — owner: @voice

Implemented modules on branch `voice-pipecat`:

- `led_states.py`: LED vocabulary (`STATES`, `LedCue`, `turn_now_period`) and `LedController`.
- `gemini_client.py`: Pure-stdlib HTTPS Gemini 4 tool-calling client (`choose_tool`, `build_function_declarations`, `GEMINI_4_MODELS`, `RECOMMENDED_GEMINI_4_MODEL`).
- `elevenlabs_tts.py`: Pure-stdlib HTTPS ElevenLabs TTS client (`ElevenLabsSpeaker`, `speak`, `synthesize_mp3`).
- `loop.py`: Baseline tap-to-talk controller (`VoiceLoop`, zero third-party packages required).
- `pipecat_loop.py`: Pipecat pipeline port (`PipecatVoiceLoop`, `BandOpusFeeder`, `PipecatToolBridge`) for the **Deepgram on Pipecat** sponsor track.

## Gemini 4 model configuration

`config.GEMINI_MODEL` stays `None` in `config.py` for the team to set. Verified Gemini 4 model IDs (`voice.GEMINI_4_MODELS`):

- `GEMINI_MODEL = "gemini-4-hydrogen"` — **recommended** fast interactive workhorse for tap-to-talk tool calls
- `GEMINI_MODEL = "gemini-4-argon"` — balanced Gemini 4 model
- `GEMINI_MODEL = "gemini-4-carbon"` — frontier reasoning Gemini 4 model

Per Gemini 4 API rules, neither `gemini_client.py` nor `pipecat_loop.py` ever passes `temperature`, `top_p`, `top_k`, or legacy `thinking_budget` (and `"minimal"` thinking level is rejected). Both declare native function tools from `interfaces.TOOLS`.

## 1. Baseline loop (`voice/loop.py`)

Runs with Python 3.9+ stdlib only (plus the kit's `speech.py` for live band transcription):

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

## 2. Pipecat port (`voice/pipecat_loop.py`)

Optional install (isolated in `requirements-pipecat.txt` so `main` stays dependency-free):

```bash
python3 -m pip install -r requirements-pipecat.txt
```

Pipeline stages:

```text
BandOpusFeeder (Opus -> PcmDecoder -> 16 kHz mono InputAudioRawFrame)
  OR LocalAudioTransport.input() (laptop mic, 16 kHz mono)
  -> DeepgramSTTService(api_key=keys.get("deepgram"))
  -> GoogleLLMService(api_key=keys.get("gemini"), model=config.GEMINI_MODEL, tools=interfaces.TOOLS)
  -> PipecatToolBridge (stops band mic first -> app.call_tool -> LED + TextFrame)
  -> ElevenLabsTTSService(api_key=keys.get("elevenlabs"), voice_id=config.ELEVENLABS_VOICE_ID)
  -> LocalAudioTransport.output() (laptop speaker)
```

Input modes:

1. **`input_source="laptop_mic"`**: Uses `LocalAudioTransportParams(audio_in_enabled=True, audio_out_enabled=True, audio_in_sample_rate=16000)`.
2. **`input_source="band"`**: Pre-loads `vexo_open.audio.PcmDecoder()` *before* switching `band.configure(audio=True)` (`vexo-open-kit/docs/speech.md`), decodes incoming 20 ms Opus packets to 16 kHz 16-bit mono PCM `InputAudioRawFrame`s during each double-tap window (`config.LISTEN_SECONDS`), and guarantees `band.configure(audio=False)` before any tool call updates the band LED.

Keys: `keys.prepare()` runs before any SDK import; only `VEXO_GEMINI_API_KEY`, `VEXO_DEEPGRAM_API_KEY`, and `VEXO_ELEVENLABS_API_KEY` are read and passed explicitly.
