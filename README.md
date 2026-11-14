# Wearable Spatial Memory on the Vexo band

*Vexo remembers what you said. We make it remember **where** you said it.*

Walk a route indoors, say "remember this as the elevator", and later ask "take me back to
the entrance". You get spoken and LED guidance back along the path you actually walked, with
no map of the building.

Built at VexoHacks, 14 Nov 2026. Plan: [VexoHacks_Plan_Wearable_Spatial_Memory.md](VexoHacks_Plan_Wearable_Spatial_Memory.md).

## How it works

- **Band → path.** The band's step count gives distance. Its gyro, projected onto gravity,
  gives turns. Turns snap to 90 degrees, which keeps hallways straight
  ([tracker/pdr.py](tracker/pdr.py)).
- **Landmarks.** A landmark is a name pinned to a point on the recorded route
  ([store/route_store.py](store/route_store.py)).
- **Return.** The route is walked backwards and merged into "turn, walk N steps" instructions.
  Code computes every turn and distance.
- **Voice** (in progress, [voice/](voice/)). Double-tap the band, speak, and Deepgram turns it
  into text. Gemini picks a tool ([interfaces.py](interfaces.py)), and ElevenLabs speaks the
  answer. The band's RGB LED shows the state.

## Sponsor tracks

| Track | Where it is used |
| --- | --- |
| Deepgram: Best Voice Use Case on Pipecat | Band mic → Deepgram STT in a Pipecat pipeline (`voice/`, in progress) |
| Google DeepMind: Best Use of Gemini 4 | Gemini picks the tool and matches spoken place names |
| ElevenLabs: Best ElevenLabs Project | Spoken turn-by-turn guidance |

## Run it

Needs Python 3.9 or newer, and `pip install bleak` for the real band.

    python3 main.py --sim             # scripted demo on a synthetic walk (no band, no keys)
    python3 -m unittest               # tests
    python3 main.py --band            # live band: set BAND in config.py first
    python3 main.py --replay data/logs/<file>.csv   # replay a logged real walk

For the real band, double-tap it first and close the kit dashboard, because only one program
can connect at a time. Copy `.env.example` to `.env` for the API keys. `.env` is gitignored.

## Limits (read before judging)

- **Heading is the wrist's heading.** Arm swing adds noise. Wear the band on the same wrist,
  in the same orientation, on every run.
- **Drift.** There is no compass on the band, so the gyro heading drifts. Turn snapping and
  re-anchoring at landmarks limit it. Short routes work best.
- **No haptics.** The band has no vibration motor and no speaker. Guidance is audio from the
  laptop plus LED colours. Blind and low-vision users rely on the audio.
- **Carry assumption.** The laptop travels with the walker, since Bluetooth reaches about 10 m.
- **Placeholder tuning.** Step length and the turn thresholds in [config.py](config.py) are not
  calibrated until a measured walk. We quote no accuracy numbers that we did not measure.
- This is an experimental navigation aid, not a safety-critical wayfinding system. Data stays
  on the laptop, and "delete all" forgets every route.

## Layout

    config.py, interfaces.py   shared settings and data shapes
    app.py, main.py            the tools and the entry point
    tracker/  store/  voice/  web/
    vexo-open-kit/             the band's kit (MIT), unchanged
    docs/                      earlier ideas and the original iPhone plan
    AGENTS.md                  rules for AI coding agents
