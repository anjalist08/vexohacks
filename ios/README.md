# Wayback for iPhone

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
