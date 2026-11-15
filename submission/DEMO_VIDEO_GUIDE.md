# Wayback — Hackathon Working Demo Video Guide

This guide covers everything needed to film, assemble, and submit a **working end-to-end product demo video** of **Wayback** (`Vexo band + native iOS spatial memory & haptic guide`), alongside the 60-second concept commercial already in [`wayback-trail-commercial.mp4`](wayback-trail-commercial.mp4).

---

## 1. Two-Part Video Strategy (Recommended Structure: 2:00–2:30 Total)

| Segment | Length | Source | Purpose |
| :--- | :--- | :--- | :--- |
| **Part A — Vision Cold Open (Optional)** | `0:00–0:20` (or full `0:60`) | [`wayback-trail-commercial.mp4`](wayback-trail-commercial.mp4) | Sets up the problem & multimodal accessibility story (`🙈 🙉 🙊`) with captions + ElevenLabs *River* voiceover. |
| **Part B — Live Working Hardware + iOS Demo** | `1:30–2:00` | Filmed in one hallway take + iPhone screen recording | Proves real **Vexo band BLE**, **wrist-mic Deepgram STT**, **Gemini 4 tool calling**, **fused indoor tracking**, **Core Haptics turn coaching**, and **ElevenLabs River TTS** working live. |

> **Team Honesty Rule (`AGENTS.md`):** Any live walk segment uses real hardware sensing. If you include B-roll from `--replay` or `-demo`, keep its on-screen `REPLAY` / demo label visible and never present replayed data as live sensing.

---

## 2. 5-Minute Pre-Flight Checklist (Before Pressing Record)

### Hardware (`Vexo-HACK-80`)
- [ ] **Battery ≥ 25%** — check the top pill in the Wayback iPhone app (`Vexo-HACK-80 · 82%`). Brief USB-C power also wakes the band if needed.
- [ ] **Only ONE device holds the band** — make sure `python3 main.py` is **not** running on a laptop when filming iPhone Standalone mode, and close any Chrome Web Bluetooth tab.
- [ ] **Never pair in iOS Settings → Bluetooth** — Wayback connects directly inside the app via CoreBluetooth (`GET_INFO` verified).
- [ ] **Wear position** — strap the band snug on the wrist you will double-tap; tap the top-left pill in the Wayback app once to trigger a **white LED flash** confirming the Bluetooth link on camera.

### iPhone (`Wayback` App)
- [ ] **API Keys verified** — tap **Settings (`⚙️`) → Band Telemetry, API Keys & Haptics** and confirm `Deepgram`, `Gemini`, and `ElevenLabs` all show green **`Saved`**.
- [ ] **Band Number matches your band** — **Settings (`⚙️`) → Band Number** (`80` for `Vexo-HACK-80`, or your assigned band number).
- [ ] **Haptics enabled** — confirm **Vibrate for Directions** is ON in Settings, and iOS *Settings → Sounds & Haptics → System Haptics* is ON.
- [ ] **Audio audible on camera** — unplug headphones and turn iPhone media volume to ~80% so **ElevenLabs River** spoken guidance is clearly heard on the camera mic.
- [ ] **Do Not Disturb ON** — enable Focus / Do Not Disturb so banners do not interrupt the screen recording.
- [ ] **Start iOS Screen Recording** — swipe down Control Center → tap **Screen Recording** (so you can place a crisp Picture-in-Picture iPhone screen overlay next to the hallway camera video).

### Filming Space
- [ ] Pick an **L-shaped indoor hallway** (e.g., lobby/doorway → 10–12 steps straight → 90° turn → 8–10 steps to an elevator, kitchen, or water fountain). Short indoor legs with a clear 90° corner look dramatic on the live map and trigger every haptic & LED state cleanly.

---

## 3. Shot-by-Shot Live Demo Script (One Continuous 90–120s Walk)

Have **Person A** wear the Vexo band and hold the iPhone (so the camera sees both their wrist LED and the iPhone screen, or put the phone in pocket during the return walk while iOS Screen Recording captures the screen), and **Person B** film right beside/behind them.

### Beat 1 — Hook & Live Connection (`0:00–0:15`)
- **Action:** Hold wrist with Vexo band next to the iPhone showing Wayback's single-screen map (`Vexo-HACK-80 · iPhone + band` green indicator). Tap the top pill once so the band flashes white on camera.
- **Say to camera:**
  > *"Vexo remembers what you said—Wayback makes it remember **where** you said it. With no GPS, no cameras, and no floorplan, we fuse the Vexo band and iPhone sensors to build a personal indoor trail you can follow back by voice, light, and directional pocket buzzes."*

### Beat 2 — Start Route & Pin First Landmark by Voice (`0:15–0:35`)
- **Action 1 (Start Route):**
  1. **Double-tap** the Vexo band → band LED turns **solid blue** (wrist mic streaming Opus to Deepgram).
  2. Speak clearly: **`"Start route"`** → pause (or double-tap again).
  3. **What happens on camera:** Band blinks **green** then breathes **amber**; ElevenLabs *River* says *"Route started"*; the Home **Live Activity** card logs `YOU: "start route"` and `WAYBACK: Started route`.
- **Action 2 (Pin Origin Landmark):**
  1. **Double-tap** the band → say: **`"Remember this as the entrance"`**.
  2. **What happens on camera:** Band glows **solid purple** (`landmark_saved`), River says *"Saved: entrance"*, a purple **`Entrance`** pin drops at `(0, 0)` on the map, and a floating `Entrance` chip appears above the bottom dock.

### Beat 3 — Walk an L-Shaped Path & Pin Second Landmark (`0:35–1:05`)
- **Action:**
  1. Walk **10–12 steps** down the hall → make a **90° turn** (left or right) → walk **8–10 steps** to a second spot (e.g., elevator or kitchen).
  2. Keep the iPhone screen visible (or rely on the screen recording PiP): the **blue trail** extends step-by-step and snaps cleanly around the 90° corner.
  3. At the second spot, **double-tap** the band and say: **`"Remember this as the elevator"`** *(or tap **Save place → Elevator** preset chip to demonstrate 1-tap non-speaking `🙊` input!)*.
  4. **What happens on camera:** Band glows **purple**, **`Elevator`** pin & chip appear on the map, and Live Activity logs `WAYBACK: Added landmark: Elevator`.

### Beat 4 — Wrong-Way Buzz Coach → Lock-On → Return Guidance (`1:05–1:45`) *(Hero Moment)*
- **Action:**
  1. **Stay facing away** from the way back (keep facing down the hall, *not* turned around yet).
  2. **Double-tap** the band and say: **`"Take me back to the entrance"`** *(or tap the `Entrance` / `Back to start` chip)*.
  3. **Show Wrong-Way Coaching:**
     - Because you are facing away from the return leg, the top Guidance Banner turns **orange** (`ADJUST HEADING · Turn around` / `Turn left`), the directional arrow points behind you, the iPhone plays repeating directional haptics (`wrong_left ••` / `wrong_right •••`), and **Live Activity** logs `BUZZ: Turn left (buzz ••)`.
  4. **Turn Your Body Toward the Route:**
     - Smoothly turn around until facing back along the dashed green path.
     - Immediately, the banner turns **green** (`GUIDING · Walk 8 steps`), the arrow locks straight up, and the phone fires **one long lock-on buzz (`on_track ━━━`)** (`BUZZ: Facing the right way`), followed by gentle `1.5s` keep-alive ticks while aligned.
  5. **Walk the Corner & Arrive:**
     - Walk back toward the corner: 1–4 steps before the corner, pulses quicken (`turn_soon ····`) and the wrist LED blinks white faster.
     - Turn 90° onto the final leg: River announces the final stretch.
     - Reach the entrance: the phone plays **3 long arrival buzzes (`arrived ━━━`)**, the Vexo band flashes **green → rainbow party mode**, River announces *"You have arrived at the entrance"*, and Wayback automatically re-anchors at `(0, 0)` to zero out drift.

### Beat 5 — Close & Sponsor Callout (`1:45–2:05`)
- **Action (Optional 10s):** Briefly open **Settings (`⚙️`) → Band Telemetry, API Keys & Haptics** or point to the **Live Activity** feed on Home showing the full transcript + tool + haptic trace.
- **Closing line:**
  > *"Every spoken wrist command goes from Vexo Opus audio into **Deepgram Nova-3**, **Gemini 4** (`gemini-4-hydrogen`) native function calling picks the spatial tool while deterministic graph code computes every metre and turn, and **ElevenLabs River** + iPhone **Core Haptics** guide every walker—whether you navigate by voice, light, or touch. This is Wayback."*

---

## 4. Sponsor Track Visual Checklist (For Judges)

Make sure at least one clear shot in the video shows each of these:

| Sponsor Track | What Judges Should See / Hear in the Video |
| :--- | :--- |
| **Vexo Hardware** | Double-tap gesture on `Vexo-HACK-80`, solid blue mic LED, amber recording breathe, purple landmark flash, rainbow arrival LED, and live BLE telemetry on iPhone. |
| **Google DeepMind (Gemini 4)** | Natural or imperfect wrist-mic phrasing (e.g., *"remember this as the entrance"*, *"take me back to the entrance"*, *"where is the elevator?"*) routed via `gemini-4-hydrogen` tool calling into deterministic spatial actions in the **Live Activity** feed. |
| **ElevenLabs** | Clear audio of the **River** voice speaking route start, landmark confirmations, turn-by-turn legs, and arrival announcements. |
| **Deepgram / Pipecat** | Real-time wrist-mic Opus speech transcription (`YOU: "…"`) appearing in the app's Live Activity feed / laptop terminal (`voice-pipecat` branch also implements the full `BandOpusFeeder` Pipecat pipeline). |

---

## 5. Backup / Fallback Plans (Zero-Risk Recording)

If Bluetooth RF congestion at the venue or low band battery ever blocks a live take, use one of these **transparently labeled** fallbacks:

### Backup A — Laptop Trail Dashboard + Phone Web Haptics (`--bridge --phone` or `--band --phone`)
If you want the big desktop dashboard (`web/trail.html`) on screen alongside the iPhone:
```bash
python3 main.py --bridge --phone
```
Open `http://localhost:8000/web/trail.html?ws_port=8765` on the Mac and paste the printed phone link into Wayback (`Settings ⚙️ → Link with Laptop over Wi-Fi`).

### Backup B — Real Logged Wrist Walk Replay (Clearly Labeled `REPLAY`)
Replays the team's real 92-step wrist loop (`data/logs/walk3-wrist-loop.csv`, which closes within `1.0 m` of its start) in real time on `trail.html`:
```bash
python3 main.py --replay data/logs/walk3-wrist-loop.csv --phone
```
*(Keep the `REPLAY` badge visible on screen and state in narration that it replays a real logged wrist walk.)*

### Backup C — Crisp Simulator / Device UI B-Roll (`-demo` & `-guiding`)
For clean close-up B-roll of the iOS interface in Xcode:
1. Open `ios/Wayback/Wayback.xcodeproj` in Xcode.
2. Go to **Product → Scheme → Edit Scheme… → Run → Arguments**.
3. Check **`-demo`** (and **`-guiding`** for active return guidance) and press **Run (`⌘R`)**.
4. Uncheck both before filming a real walk!

---

## 6. Post-Shoot Assembly Commands (`ffmpeg`)

Once you AirDrop your camera clip (`hallway.mov`) and iPhone screen recording (`screen.mp4`) to your Mac:

### Option 1: Put the iPhone Screen Recording Picture-in-Picture (Bottom-Right) Over Camera Video
```bash
ffmpeg -i hallway.mov -i screen.mp4 \
  -filter_complex "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2[bg]; \
                   [1:v]scale=-1:760[pip]; \
                   [bg][pip]overlay=W-w-48:H-h-48:shortest=1[v]" \
  -map "[v]" -map 0:a -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 192k submission/wayback-live-demo.mp4
```

### Option 2: Combine Commercial Cold-Open (First 15s) + Live Working Demo
```bash
ffmpeg -ss 0 -t 15 -i submission/wayback-trail-commercial.mp4 -i submission/wayback-live-demo.mp4 \
  -filter_complex "[0:v]scale=1920:1080,fps=30[v0];[1:v]scale=1920:1080,fps=30[v1]; \
                   [0:a]aresample=44100[a0];[1:a]aresample=44100[a1]; \
                   [v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" \
  -map "[v]" -map "[a]" -c:v libx264 -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k \
  submission/wayback-final-submission.mp4
```

---

## 7. Final Submission Upload Checklist
- [ ] Video plays cleanly in QuickTime & Chrome (`1920×1080`, H.264 + AAC `.mp4`, audio clearly audible).
- [ ] Shows **live Vexo band interaction**, **voice landmark creation**, **map trail drawing**, **wrong-way → lock-on haptic guidance**, and **arrival**.
- [ ] Includes the safety note in description/end card: *"Wayback is an experimental indoor navigation aid, not a safety-critical wayfinding system."*
- [ ] Repo URL (`https://github.com/anjalist08/vexohacks`) has no `.env` or API keys committed (`git status -s` clean).
