# Written responses (Devpost)

The text submitted on Devpost for VexoHacks, kept here so the team can see and edit it in one place.

## General info

**Project name:** Wayback Trail

**Elevator pitch:** Imagine a world where every place you've been is one ask away. Wayback Trail remembers where you walked and guides you back by voice, light and buzz, whether you can see, hear or speak.

## Inspiration

*Vexo remembers what you said. We wanted it to remember **where** you said it.*

Most of the places we get lost in have no map: a hospital floor, an office, a parking garage, a friend's house. GPS doesn't work indoors, and nobody has drawn a floor plan for your route. We wanted a wearable that builds that map from the way you walk, so you can say *"this is the entrance"* and later *"take me back to the entrance."*

We also wanted it to work for people who can't rely on one sense. If you can't see, it speaks to you. If you can't hear, it shows light and buzzes. If you can't speak, you can tap and type. Whichever sense you're missing, you can still find your way back.

## What it does

- **Track where you walk.** The Vexo band's steps give distance and its gyro gives direction, so the path builds up as you move. There's no floor plan and no GPS.
- **Save places by voice.** Double-tap the band and say *"this is the kitchen"*. The name is pinned to your current point on the route and mirrored to the band's own storage.
- **Guide you back.** Say *"take me to the kitchen"*. Wayback Trail walks your saved path backwards, leg by leg, warns you before turns, copes with turning a step early, and resets your position when you arrive, which cancels drift.
- **Turn you the right way with buzzes.** The band has no vibration motor, so **every buzz comes from the phone**. Each time you ask for directions, a haptic coach compares where you face with the next leg of the route, 5 times a second:
  - wrong way, turn left: 2 short buzzes, repeating
  - wrong way, turn right: 3 short buzzes, repeating
  - facing the right way: 1 long buzz ("locked on"), then a light tick every few seconds
  - a turn coming up: ticks that speed up
  - arrived: 3 long buzzes
- **Show light on the wrist.** Green means the route started, amber means recording, purple means a place was saved, white means guiding, red means lost.
- **Re-anchor.** Stand at a saved place and say *"I'm at the stairs"* to snap your position back.

## How we built it

**Band → path.** The band streams motion samples at 50 per second and step counts. Heading comes from the gyro projected onto gravity, where gravity $\hat{g}$ is a low-pass filter of the accelerometer:

$$\omega_{\text{yaw}} = \vec{\omega} \cdot \hat{g} - b, \qquad \theta(t) = \int \omega_{\text{yaw}}\, dt$$

Here $b$ is the gyro bias, measured while you stand still. Each step moves you by the step length $L$ in the direction you face:

$$x \mathrel{+}= L \sin\theta, \qquad y \mathrel{+}= L \cos\theta$$

The heading is smoothed with a rolling median and held on a $90^\circ$ grid, which keeps hallways straight.

**Voice.** A double-tap on the band turns its microphone on. Deepgram turns speech into text, **Gemini 4** (`gemini-4-hydrogen`) picks one of the app's tools with native function calling, and **ElevenLabs** answers out loud in the voice "River", with MiniMax as the backup voice. One rule held throughout: **the model never computes a position**. Gemini picks the action and matches place names, and our code computes every coordinate, distance and turn.

**Guidance.** The route is a graph of the path you actually walked. Guidance merges legs that point the same way and turns them into spoken directions like "Walk 39 steps, then turn left."

**iPhone app.** A native SwiftUI app plays the buzz patterns with Core Haptics, because web pages can't vibrate on an iPhone. Left cues feel softer and right cues crisper. It can run **with no laptop**: it connects to the band over Bluetooth and runs a Swift port of our tracker, guidance and voice.

**Web pages.** A trail page shows the live path, a facing cone, the band's connection and battery, and the voice controls. There's also a team map and a phone page that vibrates on Android. No API key ever reaches a page: keys are read only in Python, and only under our own `VEXO_` names.

**Testing.** 119 unit tests. Every real walk is logged to a CSV, and a replay tool runs any log through the tracker, so we tuned the tracker on recorded walks instead of guesses.

## Challenges we ran into

- **The band can't do what a phone does.** It has no compass, no vibration motor, no speaker and no barometer. Heading had to come from the gyro alone, the buzzes moved to the phone, and spoken guidance comes from the laptop or the iPhone.
- **A wrist is not a body.** Arm swing rocked the raw heading by up to about $100^\circ$, so the first turn detector never settled and one walk ended about 22 m off. A rolling-median heading on a $90^\circ$ grid fixed it.
- **Calibration caught a moving hand.** A fixed calibration window measured the gyro bias while the arm moved, leaving it 1.2°/s wrong. Now calibration waits for real stillness and re-estimates the bias whenever you stop.
- **The band's step counter started about 15 s late** and updated once a second, so we also built a footstep detector on the accelerometer.
- **One connection at a time.** Only one program can hold the band over Bluetooth, so we built several ways to connect: the laptop directly, a USB cable, Chrome, or the iPhone relaying over Wi-Fi.
- **The light turns solid blue while the mic is on**, and we can't change it then. So we listen first, switch the mic off, and only then show the answer on the light.
- **A phone moved in the hand looks like a turn.** When we fused the phone's sensors with the band's, the tracker had to tell a body turn from a phone being moved. Heading fusion is off by default until it's more reliable.

## Accomplishments we're proud of

- On our recorded wrist walk (`walk3`), a 59 m loop, the replayed path ends **1.0 m from where it started**.
- It works eyes-free: double-tap, speak, and follow the light and the buzzes.
- The iPhone app reproduces the Python tracker's results on the same logged walks.

## What we learned

- Fix the hardware limits early. Listing what the band lacks (compass, motor, speaker) shaped the whole design, from gyro-only heading to phone haptics.
- Log every real walk. Each tracker fix came from replaying a real log, not from tuning on synthetic data.
- Keep the model and the math apart. Letting Gemini choose *what* to do, while code decides *where*, made the system predictable and testable.
- Accessibility means more than one channel. Voice, light, buzzes and typing each cover a different person.

## What's next

- Calibrate the step length on measured walks. The 0.70 m in `config.py` is still a placeholder, so we don't quote distance accuracy yet.
- Merge the Pipecat voice pipeline (it's on a branch).
- Turn heading fusion on once it's reliable, and test longer routes.

*Wayback Trail is an experimental navigation aid, not a safety-critical wayfinding system. Routes stay on your own device, and "delete all" forgets every route.*

## Built with

python, javascript, swift, swiftui, html5, css3, gemini, api, deepgram, elevenlabs, minimax, vexo, core, haptics, corebluetooth, avfoundation, keychain, web, bluetooth, websockets, vibration, speech, screen, wake, pyserial

## "Try it out" links

- https://github.com/anjalist08/vexohacks
