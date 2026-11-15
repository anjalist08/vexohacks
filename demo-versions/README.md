# Demo versions

Every rendered cut of the 60-second Wayback Trail x Vexo commercial and the working demo, so each iteration
can be tracked and watched. Open the `.mp4` files directly, or serve this folder and
open `index.html` to see them all with their change notes:

    cd demo-versions && python3 -m http.server 8090   # then http://localhost:8090

Add the next version after a render with
`python3 commercial/build.py snapshot "Title" "change" ...`. That copies
`commercial/out/wayback-trail-commercial.mp4` here, makes a thumbnail, and updates
`versions.json` and this file.

| Version | Date | Commit | File | What changed |
| --- | --- | --- | --- | --- |
| Demo final v2: Working demo: the iPhone app's newest behaviour | 2026-11-15 | `5146cfe` | [demo-final-v2.mp4](demo-final-v2.mp4) | Matches the iPhone app's newest behaviour (branch clean-app) on main's redesigned screen<br>One buzz rule: silence while facing away, a steady pulse while facing the way to walk, three long buzzes on arrival<br>Directions spoken one at a time: "Turn around, walk 8 steps.", "In 5 steps, turn left.", "Turn left now, then walk 13 steps."<br>"Route started." with no hold-still wait; arrival two steps early, as the app does<br>The phone shows clean-app's camera picture (simulated hallway view); the status line shows what the app last said<br>New narrator line: "No buzz means turn. A steady pulse means you're on course." |
| Demo final v1: Working demo: phone, walker and live updates | 2026-11-15 | `0a6cd8b` | [demo-final-v1.mp4](demo-final-v1.mp4) | 60-second working demo: a simulated iPhone screen recording on the left; the walker and the app's live updates on the right<br>Everything on screen comes from running the real Wayback code (app.py, tracker, route guidance, buzz coach) on a synthetic L-shaped walk, labelled as a simulation<br>Start route, save the entrance and the elevator, then "Take me back to the entrance": Turn around, locked-on buzz, turn left, arrived<br>Hallway graphics: entrance doors, the Elevator sign at the corner, the elevator, Saved pins and green floor arrows on the way back<br>ElevenLabs voices: the walker (Chris), Wayback (River) and a narrator (Sarah), all captioned |
| v3: App buzzes turn you | 2026-11-14 | `553195e` | [v3-app-buzzes-turn-you.mp4](v3-app-buzzes-turn-you.mp4) | Every buzz now comes from the Wayback iPhone app: the app card shakes and the phone in the pocket ripples; the band only listens and glows<br>Walk scene: you ask "Take me back to the elevator", the app buzzes 2 short soft pulses (wrong_left) with a turn-left arrow until you face the route, then one long buzz (on_track, locked on), then light ticks guide you back<br>Narration: "Every time you ask, the Wayback app buzzes until you face the right way." and "Can't hear? The band glows, and the app buzzes."<br>Cards, the Deaf walker and the end card say the buzzes come from the app |
| v2: Three walkers + River narration | 2026-11-14 | `2bd5924` | [v2-three-walkers-river-narration.mp4](v2-three-walkers-river-narration.mp4) | Unfamiliar scene now has three slots: a blind walker (cane, spoken + left-ear cue), a Deaf walker (light + buzz) and a non-speaking walker (typed command)<br>Desert and Antarctica removed; all other scenes unchanged<br>ElevenLabs narration in the team's River voice, captions timed to the real clips, ending on "This is the Wayback Trail." |
| v1: First cut | 2026-11-14 | `304163c` | [v1-desert-antarctica-music-only.mp4](v1-desert-antarctica-music-only.mp4) | Full 60-second spot: intro, wrist close-up, walk with live app overlay, 🙈🙉🙊 cards, crowded, unfamiliar, isolated, nation and globe, end card<br>Unfamiliar scene: desert and Antarctica split screen<br>Music bed and burned-in captions only, no spoken narration (the ElevenLabs key was refused) |
