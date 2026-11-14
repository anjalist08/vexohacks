# Wayback haptics (iPhone)

A small iPhone app that buzzes when main.py says something happened: route started, landmark
saved, turn left (2 sharp taps), turn right (3), turn around (buzz + 2), arrived (buzz + 3),
position unsure (2 slow thuds). It only listens to main.py's WebSocket, the same feed the map uses.

## Run it
1. Xcode > Settings > Accounts: add your Apple ID (once).
2. Open `WaybackHaptics.xcodeproj`, select the WaybackHaptics target > Signing & Capabilities >
   Team: your name (Personal Team). If the bundle id is taken, change it to anything unique.
3. Plug in the iPhone, pick it as the run destination, press Run (⌘R).
   First time on the phone: Settings > Privacy & Security > Developer Mode on (restart),
   and Settings > General > VPN & Device Management > trust your developer profile.
4. iPhone: Settings > Personal Hotspot on. Mac: join it (the USB cable works, or Wi-Fi).
5. Mac: `python3 main.py --band --host hotspot --ws-port 8790 --http-port 8091`.
   It prints `iPhone haptics app: connect to 172.20.10.x:8790`.
6. In the app type that address, tap Connect, allow Local Network access. Try the pattern buttons.

Keep the app open (the screen stays on by itself): iOS stops haptics for apps in the background.
Regenerate the project after changing project.yml: `xcodegen generate`.
