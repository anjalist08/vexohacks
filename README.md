# Wearable Spatial Memory on the Vexo band

*Vexo remembers what you said. We make it remember **where** you said it.*

Walk a route indoors, say "remember this as the elevator", and later ask "take me back to
the entrance". You get spoken and LED guidance back along the path you actually walked, with
no map of the building.

Built at VexoHacks, 14 Nov 2026. Plan: [VexoHacks_Plan_Wearable_Spatial_Memory.md](VexoHacks_Plan_Wearable_Spatial_Memory.md).

## How it works

- **Band → path.** The band's step count gives distance. Its gyro, projected onto gravity,
  gives turns. Turns snap to 90 degrees, which keeps hallways straight, and heading-uncertainty
  triggers a red LED warning when drift or erratic motion accumulates ([tracker/pdr.py](tracker/pdr.py)).
- **Landmarks & advancing guidance.** A landmark is a name pinned to a point on the recorded route
  ([store/route_store.py](store/route_store.py)), mirrored to band storage ([store/band_mirror.py](store/band_mirror.py)).
  Return guidance ([store/guidance.py](store/guidance.py)) walks the saved path backwards and advances
  step by step as you walk, blinking faster near turns and confirming arrival.
- **Voice.** Double-tap the band, speak, and Deepgram turns it into text. Gemini 4 picks a native
  function tool ([interfaces.py](interfaces.py), [voice/gemini_client.py](voice/gemini_client.py)),
  and ElevenLabs (`config.ELEVENLABS_VOICE_ID`) speaks the answer ([voice/elevenlabs_tts.py](voice/elevenlabs_tts.py))
  after the band mic switches off so the RGB LED can show the state ([voice/loop.py](voice/loop.py)).
  The Pipecat pipeline port lives on branch `voice-pipecat`.
- **Live map page.** Python pushes route points, landmarks, advancing guidance, LED state, and link
  status over a local WebSocket (`ws://127.0.0.1:8765`) to [web/index.html](web/index.html) at
  `http://127.0.0.1:8000/web/`, with a typed command box fallback and zero API keys in the browser.

## Sponsor tracks

| Track | Where it is used |
| --- | --- |
| Deepgram: Best Voice Use Case on Pipecat | Band mic → Deepgram STT (`voice/loop.py`, and Pipecat pipeline on branch `voice-pipecat`) |
| Google DeepMind: Best Use of Gemini 4 | Gemini 4 (`gemini-4-hydrogen` / `gemini-4-argon` / `gemini-4-carbon`) picks native tools and matches spoken place names |
| ElevenLabs: Best ElevenLabs Project | Spoken turn-by-turn guidance via ElevenLabs TTS (`voice/elevenlabs_tts.py`) |

## Run it

Needs Python 3.9 or newer, and `pip install bleak` for the real band.

    python3 main.py --sim                          # scripted demo on a synthetic walk (no band, no keys)
    python3 -m unittest                            # full unit & integration test suite
    python3 -m web.ws_server --sim                 # preview live map page at http://localhost:8000/web/
    python3 -m tracker.replay data/logs/<file>.csv # replay & print ASCII trace of a logged walk
    python3 main.py --replay data/logs/<file>.csv  # replay a logged real walk + map page
    python3 main.py --band                         # live band + voice loop + map page (set BAND in config.py first)

For the real band:
1. Set `BAND` in [config.py](config.py) to the number on your band's bag (never `42`), and set
   `GEMINI_MODEL` (for example `"gemini-4-hydrogen"`).
2. Copy `.env.example` to `.env` and set `VEXO_DEEPGRAM_API_KEY`, `VEXO_GEMINI_API_KEY`, and
   `VEXO_ELEVENLABS_API_KEY` (`.env` is gitignored).
3. Close any open kit dashboard tab (only one program can connect to the band over Bluetooth at a time),
   double-tap the band so it blinks blue, run `python3 main.py --band`, and open `http://localhost:8000/web/`.

## Limits (read before judging)

- **Heading is the wrist's heading.** Arm swing adds noise. Wear the band on the same wrist,
  in the same orientation, on every run.
- **Drift.** There is no compass on the band, so the gyro heading drifts. Turn snapping and
  re-anchoring at landmarks limit it. Short routes work best.
- **No haptics on the band.** The band has no vibration motor and no speaker. Guidance is audio from the
  laptop plus LED colours. Blind and low-vision users rely on the audio. An Android phone can add
  vibration cues ([assist/](assist/README.md)); iPhone browsers cannot vibrate.
- **Carry assumption.** The laptop travels with the walker, since Bluetooth reaches about 10 m.
- **Placeholder tuning.** Step length and the turn thresholds in [config.py](config.py) are not
  calibrated until a measured walk. We quote no accuracy numbers that we did not measure.
- This is an experimental navigation aid, not a safety-critical wayfinding system. Data stays
  on the laptop, and "delete all" forgets every route.

## Layout

    config.py, interfaces.py   shared settings and data shapes
    app.py, main.py            the tools and the entry point
    tracker/  store/  voice/  web/
    assist/                    phone vibration, phone compass, arrival prompts (see assist/README.md)
    vexo-open-kit/             the band's kit (MIT), unchanged
    docs/                      earlier ideas and the original iPhone plan
    AGENTS.md                  rules for AI coding agents
