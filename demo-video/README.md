# Wayback working demo (60 s, simulated screen recording)

A one-minute demo of the working product, built from [`submission/DEMO_VIDEO_GUIDE.md`](../submission/DEMO_VIDEO_GUIDE.md).
The **iPhone is on the left** (a simulated screen recording of the Wayback app). On the **right** is the
walker wearing the band, with the app's live updates: what was said, which tool ran, what Wayback
said back, the band light, the iPhone buzz and the directions.

    python3 demo-video/build.py plan     # run the simulation, make the ElevenLabs voices, the plan and the audio mix
    python3 demo-video/build.py video    # render every frame and write out/wayback-working-demo.mp4
    python3 demo-video/build.py all

## What is real and what is simulated

- **Simulated:** the walk. `simulate.py` feeds a synthetic L-shaped walk (`tracker/events.synthetic_walk`:
  12 steps, a right turn, 9 steps, then back) into the app. It is labelled on screen as a simulated
  screen recording, never as live sensing.
- **Real code:** everything on screen comes from running the project's own code on that walk:
  `app.py` (tools, events, band light), `tracker/wrist.py` (position, steps, facing),
  `store/guidance.py` (the route back: "Turn around, walk 8 steps", "Turn left, walk 13 steps"),
  and `store/haptics.py` (the buzz coach: `wrong_left` while facing away, `on_track`, `turn_soon`,
  `turn_left`, `arrived`). The phone's banner, feed labels and buzz names follow the iPhone app
  (`ios/Wayback/Wayback/ContentView.swift`, `Guide.swift`).
- **Commands:** in this simulation the tool is picked by the app's keyword fallback
  (`app.parse_keywords`). Live, Gemini 4 picks from the same tool list. The end card says so.
- **Voices (ElevenLabs):** the walker is Chris, Wayback speaks in River (`config.ELEVENLABS_VOICE_ID`),
  and the narrator is Sarah. The key is read only through `keys.py`. Every spoken line is captioned.
- **Speed:** the outward walk plays at about 1.6× and is labelled on screen; the walk back plays at about 1×.
- **Sound:** a synthesised backing track, plus a low hum for each iPhone buzz in its real pattern.

## Timeline

| Time | Beat |
| --- | --- |
| 0:00 | Title |
| 0:04 | The app finds Vexo-HACK-80 and the band flashes white |
| 0:09 | Double-tap, "Start route" → `start_route()`, "Route started", green then amber light |
| 0:13 | "Remember this as the entrance" → `remember_landmark`, purple light, Entrance pin |
| 0:17 | The walk out (sped up): the trail draws, 21 steps, the turn snaps to 90° |
| 0:27 | "Remember this as the elevator" → Elevator pin |
| 0:31 | "Take me back to the entrance" → `navigate_to`; facing away, so ADJUST HEADING · Turn around with `wrong_left` buzzes |
| 0:35 | Turns around → `on_track` (locked on); "Turn left in 3 steps" with `turn_soon` ticks; "Turn left, walk 13 steps" |
| 0:51 | "You have reached the entrance" → `arrived` buzz, green then rainbow light |
| 0:54 | Band mic → Deepgram → Gemini 4 → Wayback code → ElevenLabs + buzz. "This is the Wayback Trail." |
