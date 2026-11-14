# Wayback for iPhone

**Two ways to use it:**
- **iPhone only (no laptop):** tap **Use this iPhone only** on the Guide tab. The phone connects to
  Vexo-HACK-80 over Bluetooth and does everything itself:
  - tracking (a Swift port of the team's wrist tracker)
  - places and the route graph
  - guidance, buzzing, and the band's light
  - voice: double-tap → band mic → Deepgram → Gemini 4 → ElevenLabs, or the iPhone's own voice
  Add your keys once in **Band → Keys**. They are kept in the iOS Keychain. Without keys, the
  buttons, typing and keyword commands still work, and the iPhone speaks with its own voice.
- **With the laptop:** paste the `--phone` link (below). The laptop app does the work, and the
  phone shows it and buzzes.

Native iPhone app that turns the laptop app's guidance into **real iPhone haptics** (Core Haptics).
Web pages cannot vibrate on iPhone, so this app does it. The laptop app still runs the band,
tracking, routes and voice; the phone receives buzz cues over Wi-Fi.

## Install on your iPhone (developer mode)
1. On the iPhone: Settings → Privacy & Security → **Developer Mode** → on (it restarts).
2. Connect the iPhone to the Mac with a cable and tap **Trust**.
3. Open `ios/Wayback/Wayback.xcodeproj` in Xcode.
4. Xcode → Settings → Accounts → add your Apple ID (a free Personal Team is enough).
5. Select the **Wayback** target → Signing & Capabilities → **Team**: your Personal Team.
   If Xcode says the bundle ID is taken, change `com.vexohacks.wayback` to something unique.
6. Pick your iPhone at the top of Xcode and press **Run** (⌘R).
7. First time only, on the iPhone: Settings → General → VPN & Device Management → trust your developer profile.

## Use it
1. On the laptop: `python3 main.py --band --phone` and copy the **"Phone (on the same Wi-Fi)"** link.
2. In Wayback: paste the link, tap **Connect**, allow local network access.
3. Keep the app open (screen on): iOS only plays haptics for the app on screen.

Buzz patterns match `store/haptics.py`. Left cues feel softer, right cues crisper.

## Let the iPhone carry the band (no Bluetooth on the laptop)
The app can connect to the band itself (CoreBluetooth) and relay it to the laptop, like the
Chrome bridge. Then the laptop only needs to be on the same Wi-Fi, not near the band.

1. On the laptop: `python3 main.py --bridge --phone` (no band connection on the laptop).
2. Double-tap the band, then open Wayback, paste the phone link and Connect.
3. Allow Bluetooth when asked. The app finds **only Vexo-HACK-80** (exact name or the number
   in its advertising packet), checks the band's own number, and then relays motion, steps,
   taps, battery, temperature and microphone audio. Voice, guidance and buzzing work as before.

The band number is in one place: `BandConfig.number` in `Wayback/BandProtocol.swift`.
The decoder was checked against the worked frame examples in `vexo-open-kit/docs/bluetooth-contract.md`.
