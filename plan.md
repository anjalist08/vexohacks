# Wearable Spatial Memory — VexoHacks Project Plan

> **Working concept:** A pocket-first, camera-optional AI that remembers where people have walked, attaches meaning to places, and helps them return—even where indoor GPS and floor plans are unavailable.
>
> **Event:** VexoHacks, Saturday, November 14, 2026 · Y Combinator, San Francisco · **submissions close 6:00 PM Pacific**.
>
> **Status:** Build-day execution plan; the project name, exact stack, and team assignments can change after a quick engineering feasibility check.

## 1. Executive decision

**We are developing the original indoor spatial-memory concept, not pivoting to an unrelated lost-object detector or a conventional note-taking assistant.**

- **Product vision:** A personal spatial memory for the physical world.
- **Primary technical foundation:** Infrastructure-free, camera-optional **pedestrian dead reckoning (PDR)** and a saved *personal route graph*, not a full building floor plan.
- **First user-visible value:** Walk a route, mark places with your voice, then retrieve a landmark and retrace your steps using a map, speech, and (if ready) wearable haptics.
- **Agentic element:** Interpret natural-language place references, retrieve grounded spatial memories, select a destination, request clarification when ambiguous, and invoke deterministic route-planning tools.
- **Primary sensing:** iPhone steps/distance, accelerometer, gyroscope, magnetometer/compass; optional altitude/floor clues from barometer; Apple Watch as a hands-free interaction and haptics device.
- **Not a launch promise:** Accurate location through every pocket orientation, automatic building geometry, continuous background tracking, reliably identifying arbitrary untagged dropped objects, or universal indoor navigation.
- **Stretch extensions:** Location-linked notes and reminders, watch haptics, altitude/floor recognition, gesture/object-interaction sensing, route export, privacy-preserving sharing and collaborative map alignment.

**Success in one sentence:** A judge can watch us walk from an entrance to a landmark, record that landmark by voice, ask to return, and see the product guide us along the *actually recorded* path—without needing a pre-existing indoor map or continuously using the camera.

## 2. The problem and opportunity

Modern mapping apps are strong outdoors but have limited coverage and/or localization indoors, especially in unfamiliar parking garages, campuses, event venues, and multilevel buildings. People regularly forget where they parked, which hallway they took, or where a particular room was. An app requiring a venue-specific mapped floor plan or continuous camera use may not fit casual, hands-free use.

Our hypothesis is that many users would benefit from **remembering their own route**, rather than needing an authoritative map of the entire environment.

### Important product distinctions

| Conventional navigation | Proposed personal spatial memory |
| --- | --- |
| Often starts from a map of the environment | Starts from the user's own movement |
| Gives directions to known destinations | Can return to places the user personally visited |
| Place labels are typically provider-generated | Place labels can be spoken by the user and remembered by an agent |
| Assumes a map/localization infrastructure | Can record a relative trajectory without venue infrastructure |
| Often visually oriented | Prioritizes wearable, voice, and haptic interactions |

**Do not claim** that no indoor navigation solutions exist or that this market has already been validated. Our differentiation is the *combination* of low-friction personal trajectory learning, voice-anchored semantic memory, and hands-free return navigation. Adoption, accuracy and retention are hypotheses to test.

## 3. Elevator pitch and demo narrative

### ~30-second recruiting pitch

> We're building **Google Maps for indoor places that don't have maps**—but personalized to where *you've actually been*. Your phone estimates the path you walk from motion sensors, and you can say, “Remember this is the entrance” or “I parked on B2.” Later you ask, “Take me back,” and the AI retrieves that location and guides you along your recorded route using voice, a simple map, or wearable haptics. We're focusing on a camera-free-first prototype, with object memory and place-linked notes as extensions. We'd love help shipping the mobile and wearable experience.

### One-line version

> **An AI that remembers where you've been, even when the building hasn't been mapped.**

### Judge-facing story (60–90 seconds)

1. **Begin at A:** “This is the entrance.” Tap Record Route and optionally voice-label the starting location.
2. **Walk to B:** Keep the phone in a consistent carrying position. Show the trajectory being generated from live motion measurements (debug map may be visible to judges).
3. **Mark B:** Speak “Remember: the elevator near the blue sign,” or “I parked here on B2.” Save the approximate route coordinate and transcript.
4. **Walk farther:** Ask “Where was that elevator?” or “Get me back to the entrance.”
5. **Retrieve + route:** The agent identifies the correct stored landmark and requests a deterministic route along recorded segments; the interface shows the route and issues a spoken cue. If working, Apple Watch gives a distinctive haptic cue.
6. **Conclude:** “No building floor plan and no continuous camera feed. We use the path we recorded and semantic landmarks you provided.”

**Backup demo:** Keep an actual recorded route dataset and a deterministic playback mode in case live indoor reception, permission, compass or Bluetooth behavior is unreliable. Explicitly label it as replay—not live sensing.

## 4. Scope: build in layers

| Level | Capability | Priority | Exit criterion |
| --- | --- | --- | --- |
| P0-A | iPhone motion + pedometer ingestion and live telemetry | Must | Real sensor values update on a physical iPhone and are logged with timestamps |
| P0-B | Approximate 2D route recording and visualization | Must | Walking and turning yields a saved, visually interpretable breadcrumb trace under a stated carry assumption |
| P0-C | Add named landmark via tap/text; persist it at a route point | Must | Landmark survives app navigation/restart and can be found |
| P0-D | Reverse route to chosen landmark/start | Must | A previously traversed path is presented in reverse order, not merely a straight-line arrow |
| P0-E | Voice landmark entry or query | Must if feasible | One complete spoken action works; text fallback remains available |
| P1-A | Agent-driven place retrieval and tool calling | High | Natural-language query resolves to a stored landmark and grounded route |
| P1-B | Apple Watch input and/or navigation haptics | High | Real paired Watch triggers an input or receives a navigation cue |
| P1-C | **Notes associated with locations** | High / natural extension | Spoken or typed note attaches to a place or route point; query retrieves it by location |
| P1-D | User-declared floor labels; optional relative barometric cues | Medium | “B2” stored reliably; no fabricated floor number inferred solely from pressure |
| P2-A | Export/share a route or personal spatial notebook | Optional | User can export a structured artifact using iOS share sheet |
| P2-B | Landmark-assisted correction of drift | Optional | Returning to a known anchor reduces plotted route error in a controlled test |
| P2-C | Object/place memory (e.g., “left my bag here”) | Optional | Manually registered object linked to a place and retrievable |
| P3 | Automatic pickup/put-down or possible loss event recognition | Research stretch | Separately evaluated classifier with real sensor data; uncertainty and false positives shown |
| Future | Collaborative indoor maps, robust multi-floor relocalization, untagged object tracking | Post-hackathon | Requires infrastructure, additional research, validation and privacy design |

**Freeze rule:** Do not start a P2/P3 feature until P0 demo and submission artifacts are safe. If PDR proves too inaccurate, retain route + landmarks with explicit waypoint confirmation and present localization as experimental.

## 5. Product experience

### Core screens

1. **Home:** Start Route; Resume Route; Saved Routes; quick “Remember this place” action.
2. **Recording:** Live breadcrumb polyline, approximate distance and step count, sensor/heading status, landmark button, voice capture, clear Recording indicator.
3. **Memory:** Saved landmark list with descriptive names, timestamps, optional floor/route label, and attached notes.
4. **Ask/Find:** Voice or text input: “Where did I park?” / “Take me to the entrance” / “What did I note near the elevator?”
5. **Navigate Back:** Route polyline, current estimated point, next recorded waypoint/turn, distance-along-path estimate, reroute/re-anchor button, optional audio and haptics.
6. **Trip Detail:** Review saved trajectory and notes; export structured data if time allows.

### Interaction hierarchy

- **Default ambition:** Hands-free or low-touch; user does not have to stare at the phone.
- **Haptics (Apple Watch):** Consistent symbolic cues, e.g. one pulse at a waypoint, different patterns for turn/arrival. Haptics do **not** physically indicate a cardinal direction; users must learn the pattern vocabulary.
- **Audio (AirPods 2 or phone):** “Turn right at the elevator landmark” and “You have reached your saved location.” AirPods 2 provide mic/speaker, **not developer-accessible continuous head IMU**.
- **Visual:** Debug and review map; not a required always-on user interface.
- **Voice annotations:** “This is the entrance”; “This is my parking spot, B2”; “Remember: printer is outside this classroom”; “Note: ask about the lab tomorrow.”

### Notes as a natural extension

Notes are **semantic annotations on a spatial graph**, not a pivot to an unrelated task-manager product. A note may have text, created_at, route_id, coordinate/nearest node, optional floor/landmark, and optional reminder intent. Examples:

- “Near the library: I should ask about the robotics workshop.”
- “At the entrance: take a photo of this sign next time.”
- “By the elevators: I parked on level B2.”

Allow retrieval like **“What did I note near the entrance?”**. Initially save within the app; exporting via iOS share sheet is a realistic extension. **Do not assume that third-party apps can directly write arbitrary content into Apple Notes through a public API.**

## 6. Hardware and platform strategy

| Device | Role | Decision |
| --- | --- | --- |
| **iPhone 11** | Main location/motion data source, route recording, processing, state/database, UI, voice | **Essential** |
| **Apple Watch Series 11 GPS, watchOS 26.0** | Hands-free recording/marking, Watch motion as optional auxiliary signal, haptic navigation | **Optional after P0 works** |
| **AirPods 2 (A2031)** | Microphone and spoken navigation audio | **Useful; no headphone motion streaming** |
| **Vexo bracelet** | Possible event-supplied wearable voice/memory surface | **Integrate only after testing actual provided SDK/API** |
| Arduino Uno / ESP8266 ESP-12E/F | Possible custom I/O prototypes but no inherent indoor location advantage | **Leave out of core architecture** |
| External Jetson/robotics compute | No requirement for PDR or core MVP | **Not on critical path** |

**Vexo integration constraint:** The published Vexo MCP documentation describes **read-only access to saved Vexo conversation/memory** with user approval; it does *not*, by itself, establish a developer interface to stream bracelet IMU data, control haptics, or send live commands. The event says bracelets are optional. Ask the hardware/SDK mentors what participants can actually read, write and control, and test with a ten-minute spike. The iPhone + Watch system must remain independently demonstrable.

**No new custom electronics today unless they unlock a critical, working feature.** Bluetooth, battery and board integration can easily consume the build window.

## 7. Technical design: camera-free-first pedestrian tracking

### 7.1 Core concept

**Pedestrian dead reckoning (PDR)** produces a *relative, approximate* path from a known start using traveled distance and estimated heading. This can be useful for retracing the same route, but it is **not the same as reconstructing building geometry** and its error accumulates over time.

Inputs:

- `CMPedometer`: live step count and, where available, **estimated cumulative walking distance**; updates may be delayed or batched.
- `CMMotionManager` / `CMDeviceMotion`: acceleration, rotation rate, attitude, gravity-aligned estimates, and potentially magnetic-reference heading.
- `CLLocationManager` heading and location **if authorized / available**: optional magnetic/true heading; GPS is only useful outdoors or near an open entrance and may fail indoors.
- `CMAltimeter`: relative pressure/altitude changes (if available) for approximate vertical movement, with drift and weather/HVAC caution.
- Optional Apple Watch Core Motion: a *separate orientation/gesture stream*, not a trivially interchangeable walking-heading sensor.

### 7.2 Coordinate model and first algorithm

Use a **local east/north frame** anchored at route start (initial point `(0, 0)`), with a consistent angle convention: heading `theta = 0` means north and positive rotates clockwise. For a distance increment `Δs` and current walking-heading estimate `theta`:

```text
x_next = x_prev + Δs * sin(theta)
y_next = y_prev + Δs * cos(theta)
```

1. Begin a route, zero the relative x/y and distance counters, record wall-clock and monotonic timestamps.
2. Establish a heading reference while the user is standing still and **explicitly holding the phone in a known orientation** (or a tested, fixed pocket position).
3. Read cumulative pedometer distance; compute the new delta only when the counter advances. Reject obviously invalid/negative jumps and annotate gaps.
4. Sample device motion at a reasonable rate (e.g., 25–50 Hz for development), calculate stable yaw/turn estimates, and aggregate to the step/distance update time.
5. Convert distance + walking heading into new x/y; append `PoseSample`, and periodically simplify trajectory nodes for display/storage.
6. Add landmark pins at nearest current route point; serialize checkpoints locally.
7. For return, locate the saved landmark node and **reverse the traversed route sequence** toward it; provide progress against the saved polyline.

**Critical warning:** Phone yaw is the **phone's** orientation, not necessarily the person's direction of travel. A person can rotate a handset while still walking straight; wrist yaw is even less coupled to walking direction. No generic accelerometer/gyro/compass fusion automatically fixes that. Therefore:

- State and test **carry-mode assumptions**: fixed forward-facing handheld, or consistently placed pocket mode.
- First demo uses one reliable, repeatable carry mode rather than promising arbitrary pocket orientation.
- Treat user confirmation (“I am at the elevator”) as a map anchor to reset accumulated error.
- Offer heading re-calibration and an explicit **“correct position / continue route”** control.
- Record sensor streams to diagnose differences between measured path and ground truth.

### 7.3 Filtering / sensor fusion progression

- **Baseline:** use already fused device motion from Core Motion plus pedometer cumulative distance; avoid raw double-integration of accelerometer to recover position (drifts badly).
- **Next:** smooth noisy heading using circular angle interpolation / complementary filtering; reject low-accuracy magnetometer readings and annotate confidence.
- **Next:** detect stops/turns, constrain path to repeated corridors/landmark loops, and add user-verified landmark corrections.
- **Research:** EKF / particle filter / learned gait heading estimation, magnetometer fingerprinting or Wi-Fi CSI, only after collecting meaningful test data.

Do not describe an ordinary Core Motion attitude estimate as a proven world-space human heading. **Measure route drift** against a known hallway path.

### 7.4 Multi-floor support

- **P0:** user speaks a label (“B2,” “Floor 3”) and that label is attached to route/landmarks.
- **P1:** read relative altitude changes from barometer, smooth, detect candidate transitions, and request confirmation; store confidence.
- **Do not claim:** known absolute floor from barometer alone, reliable elevator vs stairs classification, or full 3D map.
- Pedometer floors ascended/descended may refer to walking stairs rather than riding an elevator; use relative pressure only as an additional clue.

### 7.5 Why not vision, UWB, Wi-Fi CSI, or ultrasonics in the MVP?

| Technology | Possible value | Why not critical path today |
| --- | --- | --- |
| Camera / ARKit | Relocalization, landmarks, visual-inertial tracking | Violates pocket-first interaction if continuously required; can be a *user-optional calibration tool* later |
| GPS | Outdoor anchoring near entrance | Usually unreliable indoors |
| UWB | Ranging to participating UWB devices/tags | Does not locate arbitrary untagged objects or automatically produce a building map |
| Wi-Fi RSSI | Coarse environmental fingerprint | Unstable and often insufficient for meter-level precision |
| Wi-Fi CSI / Doppler | Device-free motion sensing / radio localization research | Commodity iOS public APIs do not provide a generic raw CSI pipeline; specialized hardware/firmware may be needed |
| Ultrasonic sonar | Hand/finger or nearby-object sensing research | Audio API access, device behavior, calibration and reflections are a major separate experiment |
| Visual SLAM / LiDAR | More geometric environmental maps | Not necessary for a reliable breadcrumb-path proof of concept |

## 8. Spatial memory and agent architecture

### 8.1 Data representations

Keep a structured source of truth separate from the language model. A suggested minimal schema:

```text
Route {
  id, title, started_at, ended_at, coordinate_frame,
  carry_mode, status, floor_label?, notes?, created_with_version
}
PoseSample {
  route_id, timestamp, x_m, y_m, heading_rad?,
  distance_from_start_m, steps?, relative_altitude_m?,
  heading_accuracy?, confidence, source
}
Landmark {
  id, route_id, pose_index, label, category?,
  floor_label?, created_at, transcript?, confirmed_by_user
}
PlaceNote {
  id, route_id, landmark_id?, pose_index?,
  text, created_at, tags?, reminder_intent?, privacy_scope
}
NavigationSession {
  id, route_id, destination_landmark_id,
  start_pose_index, route_waypoint_indices, progress_index,
  status, confidence
}
CandidateObjectEvent {  // Future / experimental
  id, timestamp, pose_index?, candidate_item?, type?,
  imu_score?, audio_score?, confirmed_by_user?, confidence
}
```

Storage: local JSON/SQLite/SwiftData, whichever the team can ship fastest. The raw trajectory is an ordered polyline with landmark references; if route intersections or multiple journeys are supported later, grow it into a graph.

### 8.2 Agent tools

```text
start_route(title)
stop_route()
remember_landmark(label, optional_floor, current_pose)
save_place_note(text, optional_landmark, current_pose)
list_recent_routes()
search_landmarks(query)
search_place_notes(query, optional_location)
get_route(route_id)
get_current_pose_and_confidence()
plan_return_path(route_id, destination_landmark_id)
start_navigation(route_id, landmark_id)
reanchor_to_confirmed_landmark(landmark_id)
announce_instruction(text)
```

**LLM responsibilities:** parse utterances, match ambiguous references, retrieve or summarize memory, select the correct tool and ask clarifying questions. **Deterministic responsibilities:** step-distance integration, map coordinates, landmark storage, path selection, deviation/progress estimates, and confidence thresholds.

Example agent flow:

```text
User: "Take me back to the entrance."
  -> search_landmarks("entrance")
  -> if multiple matches, ask which one
  -> plan_return_path(route_id, landmark_id)
  -> show saved route polyline
  -> provide short voice / optional haptic guidance
  -> if position uncertain, prompt for landmark re-anchor
```

Always distinguish actual sensor readings from inferred content. Never let an LLM invent a landmark coordinate or claim an unobserved room exists.

### 8.3 Notes and context

- Start with lexical search over landmark labels and place-note text; semantic embeddings are optional only if retrieval quality is inadequate.
- Store a user-supplied note verbatim; summarize separately if desired.
- Attach notes to a location only when the user provides context or tracking is confidently active.
- If location is uncertain, mark `unlocalized` rather than guessing.
- Future: “Remind me when I return near this location,” but background location triggering is much harder and shouldn't be core-day scope.

## 9. Suggested software structure

Use the team's fastest proven native iOS stack. A **SwiftUI iPhone app** provides the most direct route to Apple sensor APIs. Don't introduce React Native, a cloud microservice, and a custom watch app simultaneously unless the team already has working templates for them.

```text
project/
  README.md
  plan.md
  ios/
    App/
      AppEntry.swift
      Screens/         # Home, Record, Memories, Navigate, Settings
      ViewModels/
    Sensors/
      MotionProvider.swift
      PedometerProvider.swift
      AltimeterProvider.swift
      HeadingProvider.swift
    Mapping/
      PDRTracker.swift
      RouteRecorder.swift
      RoutePlanner.swift
      CoordinateUtils.swift
      TrackingConfidence.swift
    Memory/
      Models.swift
      MemoryStore.swift
      LandmarkRepository.swift
      NoteRepository.swift
    Agent/
      IntentRouter.swift
      ToolExecutor.swift
      SpeechService.swift
    Integrations/
      WatchBridge.swift
      VexoBridge.swift        # Only if supported/tested
    Tests/
  watch/                    # Add only after iPhone P0 is stable
    WatchApp/
    HapticCues.swift
    WatchConnectivityBridge.swift
  demo/
    example_route.json
    demo_script.md
    validation_results.md
    demo_video.mp4
```

This tree is **proposed organization**, not a requirement to generate every folder before coding. Prefer one working path over excessive scaffolding.

### Implementation notes

- Use `NSMotionUsageDescription` and any required speech, microphone, or location privacy descriptions; request only permissions actually used.
- Test on a **physical iPhone**: laptop simulators cannot provide realistic walking data.
- Check Xcode/device signing and physical-device deployment immediately.
- If speech recognition fails, support manual text entry; if an agent model is slow, support deterministic label lookup.
- Run route tracking and persistence locally by default. An optional cloud LLM receives only minimally necessary content with consent.
- Do not block route recording on slow model inference.
- Keep `WatchConnectivity` optional because reachability and background behavior vary. Background continuous sensor streams need a separately justified lifecycle plan; do not assume ordinary Watch apps can stream unrestricted forever.

## 10. Fast feasibility tests and decision gates

### Gate A — Sensor availability, 20–30 minutes

- iPhone can run the project on-device.
- `CMPedometer` provides changing step count and/or distance after walking.
- `CMMotionManager` produces motion and attitude values.
- Motion and pedometer timestamps align sufficiently to reconstruct a track.
- App can save a route and reopen it.

**If blocked:** Use a manual checkpoint / step-tap route baseline to guarantee a working memory experience while continuing sensor debugging separately.

### Gate B — Path sanity, 30–45 minutes

Walk a measured rectangular or L-shaped hallway route (e.g., two straight segments and one 90° turn). Compare drawn trace to the intended shape. Measure:

- End position drift (meters) and drift as fraction of actual walked distance.
- Total inferred route length vs approximate known distance.
- Heading/turn error; whether the tested carrying mode is stable.
- Sample dropout, battery drain and pedometer update latency.

**If the path is unrecognizable:** Restrict to a fixed orientation, ask users to confirm turns/landmarks, or show route segments as ordered named checkpoints without claiming metric precision.

### Gate C — Whole-user workflow

One person walks from A to B, saves B by voice/text, continues to C, selects B, and gets actual reversed route guidance. This must succeed **before** adding a new sensing modality or additional AI framework.

### Gate D — Optional wearable

If iPhone MVP is running, test sending one simple command or haptic cue to Watch, then integrate. If Vexo APIs are present, verify one actual live input/output first. Skip if not reliably working.

## 11. Build-day schedule (Pacific time)

The organizer's posted schedule says **10:15 AM hacking starts**, **6:00 PM submissions close**, and **6:30 PM judging begins**. Follow on-site rules/announcements if they differ. If starting this plan later than the times below, compress the research/extension phases first—not final submission.

| Target time | Outcome | Owner guidance |
| --- | --- | --- |
| Start / first 15 min | Agree on concept, pitch, team responsibilities, demo route | Everyone |
| By ~11:00 AM | App deployed to physical iPhone; live step/motion updates | iOS/sensing |
| By ~12:00 PM | Saved trajectory + route map + one landmark | iOS + UI |
| By ~1:00 PM | Complete route record → retrieve landmark → reverse navigation flow | Integration |
| By ~2:00 PM | Voice entry or agent place lookup, with text fallback | AI/interaction |
| By ~3:00 PM | Stable field demo; evaluate route drift; fix largest UX failure | Everyone |
| 3:00–4:00 PM | Add **one** extension: Watch haptics **or** location-linked notes **or** floor annotation | Remaining owner |
| 4:00–5:00 PM | Rehearse and record demo; build README and clear architecture explanation | Presentation + integration |
| **By 5:30 PM** | Public repo, demo video, documentation and Devpost submitted; verify all links | Submission owner |
| **6:00 PM** | **Hard submission close** | No speculative features after submission buffer begins |

**Submission checklist:** public GitHub repository; meaningful commits made after the permitted build start; clear README (problem, how it works, setup, limitations, architecture); demo video; Devpost project link and any organizer-required form fields. Assign one person to own submission early. Check actual requirements on the event portal; don't rely only on this plan.

## 12. Team roles and coordination

Up to **three people**. Names are deliberately omitted; assign based on demonstrated skills, not titles.

| Role | Main ownership | Required handoff |
| --- | --- | --- |
| **Sensor/mapping engineering** | iPhone Core Motion and pedometer, PDR, logging, coordinate/trajectory model | `PoseSample[]` interface + route recording API |
| **Mobile/product UI engineering** | SwiftUI screens, map renderer, landmark and navigation flows, visual polish | Usable on-device path from Record to Navigate |
| **AI/interaction + demo integration** | Voice input, memory search, tool-based agent, optional Watch/haptics, testing and video | Working speech/text workflow and clean demonstration |

The physical team may divide these differently. Designate **one integrator** and **one submission owner** by the first checkpoint. Define minimal interfaces before parallel coding. Have AI coding assistants work in separate files/branches; avoid three independent agents rewriting shared project configuration.

**Critical rule:** No owner should spend more than ~30–45 minutes on a nonessential integration without showing the rest of the team an isolated test result.

## 13. Evaluation, evidence, and demo credibility

### User tests

1. Short straight hallway walk; compare estimated distance with a measured or paced estimate.
2. L-shaped route; compare turn angle and route layout with the walked route.
3. Landmark creation at B; retrieve B after moving to C.
4. Return navigation from C to B or A.
5. Repeat with different carrying positions and document when it fails.
6. If Watch is enabled, test haptic cue while not looking at phone.

### Measures to report if obtained

- End-point position error for short route(s), with route length and carrying mode.
- Distance estimation error.
- Landmark retrieval accuracy on a tiny test set.
- Time to create landmark, time to request route back.
- Demo success rate across repeated trials.
- Sensor and connection failure observations.

**Never invent numbers.** If accuracy hasn't been evaluated, say “prototype” and explain limits. A transparent live demo with known failure modes is more compelling than unsupported precision claims.

### Demo fallback levels

- **Gold:** live nonvisual motion map + spoken landmark + agent retrieval + reverse route + Watch cue.
- **Silver:** live phone map + saved landmarks + reverse navigation; text input/audio and no Watch.
- **Bronze:** previously recorded genuine trace replay + real landmark storage/search + route reconstruction. Clearly call this a replay and explain why.

## 14. Risk register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Human travel direction differs from phone orientation | Severe map drift | Fixed carry mode, calibration, explicit route anchors and corrections |
| Compass distortion in metal-heavy building/garage | Wrong headings | Check accuracy, rely on relative gyro over short spans, show uncertainty and accept corrections |
| Pedometer batches/delays distance | Jerky map updates | Buffer timestamps, update map only with new distance, avoid claiming smooth frame-rate position |
| Indoor route crosses floors | Ambiguous trajectory | Manual floor label as core; pressure as stretch; separate per-floor trace layers |
| Voice recognition/API/network fails | Interaction blocked | Manual text labels and deterministic lookup |
| LLM mistakes route facts | Misleading navigation | Agent tool calls against structured memory; code computes routes |
| Watch/Vexo SDK unavailable | Wearable demo failure | iPhone-first architecture; Watch/Vexo isolated optional adapters |
| Continuous background sensing unavailable | Pocket-first promise overstated | Foreground proof of concept, document background limitations; test supported modes later |
| Feature creep (SLAM, dropped-object ML, ultrasonic) | No finished project | Protect P0 gates; maximum one extension after integration |
| Privacy concerns from persistent movement/voice histories | User trust issues | Opt-in recording, local storage, visible recording state, user delete/export control |
| Missed 6 PM submission | Disqualification | Submit first complete version by 5:30 PM; record backup demo early |

### Safety and privacy

- Label it an **experimental navigation aid**, not a safety-critical wayfinding system.
- Do not use unvalidated navigation to guide users through dangerous areas, stairs, traffic, or accessibility-critical routes.
- Keep raw motion streams local by default and avoid uploading audio/video unnecessarily.
- Don't record bystanders' conversations without consent; favor tap-to-talk voice notes.
- Give the user a clear Stop Recording control and deletion affordance.
- Any future shared map requires user consent, location-data controls, and careful handling of sensitive personal locations.

## 15. Future research roadmap (not required for VexoHacks)

### A. Place-linked personal notes and reminders

Every spatial node can hold a reminder, task, observation, or memory, allowing queries like “What did I note outside the classroom?” This is a straightforward product expansion with immediate user value. Context-aware re-encounter reminders become possible when location confidence and app lifecycle constraints are solved.

### B. Object interaction and lost-item events

Wearable IMU and optional acoustic event classifiers could estimate **candidate pickup/put-down/drop interactions**. A user could pre-register an object, and the system could attach possible interaction events to estimated places. Research on wrist vibration/object manipulation is relevant, but do **not** promise universal automatic identification or mass sensing. A Watch accelerometer measures motion, not static carried weight, and one event does not prove an object was left behind.

### C. Multi-modal localization improvements

- PDR error correction using semantic anchors, loops, gait patterns or a learned heading model.
- Barometric floor transitions + spoken floor tags.
- Optional *brief* camera relocalization initiated by the user (not continuous visual dependency).
- Tested, permissioned Bluetooth beacons or UWB tags for known anchors.
- Wi-Fi CSI or ultrasonic sonar only with hardware and signal-access feasibility demonstrated.

### D. Collaborative map creation

Align anonymized or consented personal route graphs through common landmark anchors, floor labels, and overlapping trajectory segments. Do **not** merely overlay relative paths from different users—their local coordinate systems, scale and heading may be inconsistent. Research map matching, graph alignment, privacy controls and quality scoring.

### E. Agentic navigation / VLA / VLN research

Borrow the **separation of sensing, spatial memory, semantic reasoning and route execution** from robotics (including systems such as dimOS and VLN research). A large robot policy is not needed to return a walking human through a recorded breadcrumb graph. Consider richer embodied planning only after localization and memory quality are demonstrated.

## 16. Research and product questions to validate

- Is finding a car or retracing a hallway frequent and frustrating enough to drive repeat usage?
- Is the effort of starting recording acceptable? Can it become ambient without unacceptable privacy/battery costs?
- What route length, building layout, and carry mode produce tolerable error?
- Does a landmark-based route feel safer and more intelligible than a noisy geometric arrow?
- Is the best initial use case a parking garage, hospital/campus, conference, or a general spatial notebook?
- Do voice/haptics genuinely reduce phone interactions?
- Are location-linked notes more compelling than general notes when tied to real-world context?
- Would users consent to sharing route maps to build collaborative indoor coverage?

## 17. Definition of done

The minimum acceptable submission must have:

- [ ] A real iPhone build that records actual walking data (or a transparently identified route-replay fallback).
- [ ] A visible/saved personal trajectory or ordered route representation.
- [ ] At least one named landmark attached to the recorded route.
- [ ] Retrieval of that landmark and a route back using saved *path segments*.
- [ ] One working natural-language or voice interaction, with text fallback.
- [ ] Clear statement of sensor limitations, carry assumptions and drift.
- [ ] A short, reproducible judge demonstration and backup recording.
- [ ] Public repo, README, demo video, and required submission completed **before 6 PM PT**.

**Optional and explicitly not required:** fully functional custom wearable, object-loss classifier, automatic floor detection, shared maps, true architectural floor plan, LiDAR, vision SLAM, AirPods IMU access, or autonomous navigation.

---

## References and implementation sources

- [VexoHacks event, tracks, and posted schedule](https://www.vexoai.com/hackathon)
- [Vexo event listing: bracelets optional](https://luma.com/chgfm6ec)
- [Vexo developer MCP documentation — permissioned read-only conversation memory](https://www.vexoai.com/docs)
- [Apple: CMPedometer](https://developer.apple.com/documentation/coremotion/cmpedometer)
- [Apple: CMMotionManager / fused device motion](https://developer.apple.com/documentation/coremotion/cmmotionmanager)
- [Apple: Watch extended runtime sessions and their restrictions](https://developer.apple.com/documentation/watchkit/using-extended-runtime-sessions)

**Design principle:** **Build a usable memory of the path someone took before attempting to reconstruct the entire world they moved through.**
