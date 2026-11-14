# Demo versions

Every rendered cut of the 60-second Wayback Trail x Vexo commercial, so each iteration
can be tracked and watched. Open the `.mp4` files directly, or serve this folder and
open `index.html` to see them all with their change notes:

    cd demo-versions && python3 -m http.server 8090   # then http://localhost:8090

Add the next version after a render with
`python3 commercial/build.py snapshot "Title" "change" ...`. That copies
`commercial/out/wayback-trail-commercial.mp4` here, makes a thumbnail, and updates
`versions.json` and this file.

| Version | Date | Commit | File | What changed |
| --- | --- | --- | --- | --- |
| v2: Three walkers + River narration | 2026-11-14 | `2bd5924` | [v2-three-walkers-river-narration.mp4](v2-three-walkers-river-narration.mp4) | Unfamiliar scene now has three slots: a blind walker (cane, spoken + left-ear cue), a Deaf walker (light + buzz) and a non-speaking walker (typed command)<br>Desert and Antarctica removed; all other scenes unchanged<br>ElevenLabs narration in the team's River voice, captions timed to the real clips, ending on "This is the Wayback Trail." |
| v1: First cut | 2026-11-14 | `304163c` | [v1-desert-antarctica-music-only.mp4](v1-desert-antarctica-music-only.mp4) | Full 60-second spot: intro, wrist close-up, walk with live app overlay, 🙈🙉🙊 cards, crowded, unfamiliar, isolated, nation and globe, end card<br>Unfamiliar scene: desert and Antarctica split screen<br>Music bed and burned-in captions only, no spoken narration (the ElevenLabs key was refused) |
