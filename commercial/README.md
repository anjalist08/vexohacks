# Wayback Trail × Vexo: 60-second commercial

A one-minute spot for the Wayback Trail assistant on the Vexo band. It uses Apple's
system colours and the Montserrat font.

    open commercial/index.html                 # or serve the folder and open it in a browser
    python3 commercial/build.py audio          # music bed + ElevenLabs narration (voice River)
    python3 commercial/build.py video          # renders every frame and writes out/wayback-trail-commercial.mp4

The page draws every frame from one function of time, so it plays live in a browser and
renders frame-for-frame to video (`render.mjs`, using the pre-installed Playwright).

## Storyboard

| Time | Scene | Transition in |
| --- | --- | --- |
| 0:00 | "Every place you go leaves a trail." Vexo × Wayback Trail lockup | fade from black |
| 0:05 | Close-up of the band on a wrist: listening (blue), landmark saved (purple), recording (amber) | zoom through |
| 0:13 | Walker, plus the app overlay drawing the path as they move, then guidance back with the turn-left buzz | push |
| 0:22 | 🙈 can't see: it speaks · 🙉 can't hear: it glows and buzzes · 🙊 can't speak: tap and type | card fall-away |
| 0:31 | Crowded: a plaza from above | iris |
| 0:36 | Everyone: a blind person with a cane hears the turn, a Deaf person sees the light and feels the buzz, a non-speaking person types "take me back" | blur dissolve |
| 0:42 | Isolated: out of a cave, down a mountain | push |
| 0:48 | Across the nation (US dot map), then around the globe (WHO figures) | zoom |
| 0:55 | Narrator: "This is the Wayback Trail." | blur dissolve |

## What is real and what is dramatised

- The path in the app overlay is **`data/logs/walk3-wrist-loop.csv` replayed through
  `tracker/wrist.py`**: 92 steps, about 64 m at the placeholder step length. It is labelled
  on screen as a replay simulated in real time, never as live sensing (see `AGENTS.md`).
- "Walk 39 steps, then turn left" is computed in the page the way `store/guidance.py`
  computes it: the saved path walked backwards, with legs merged.
- The buzz bars use the `turn_left` pattern from `store/haptics.py`. LED colours follow
  the plan's feedback vocabulary.
- The band has no vibration motor. Haptics come from the paired iPhone or Apple Watch, and
  the end card says so. The 🙊 card shows the typed command box and the Talk/Stop buttons that
  really exist; it does not claim tap-coded commands.
- The crowd, "Everyone" (blind, Deaf, non-speaking), cave and mountain scenes are illustrations. The end card
  carries a dramatisation and "not a safety-critical system" line.
- The global figures come from the WHO World Report on Vision (2019: 2.2 billion people with
  a vision impairment) and the World Report on Hearing (2021: 1.5 billion with hearing loss).
- Captions are burned in, so the spot works with the sound off.

## Narration

`build.py audio` reads `VEXO_ELEVENLABS_API_KEY` only through `keys.py`, sends it in the
`xi-api-key` header, and writes `audio/narration.mp3` plus `audio/timing.json` (captions follow
the real clip lengths). If ElevenLabs refuses, it keeps the music bed (`audio/music.mp3`), and
the page speaks the lines with the browser's voice.
