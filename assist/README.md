# assist/: sound cues in headphones, vibration, notifications, drift correction

The band has no speaker, no vibration motor and no compass. The person already carries a
phone and often wears headphones (AirPods, bone-conduction or any Bluetooth headphones),
so every guidance moment is given through those: **a short sound in the headphones**, a
vibration where the phone allows it, a notification when the screen is locked, and the
spoken line. Nothing here changes `app.py`, `interfaces.py`, `config.py` or `tracker/`:
`attach(app, send)` listens to the app's event stream from the outside.

    python3 -m assist.demo                   # synthetic walk, cues printed (no band, no phone)
    python3 -m assist.demo --sound           # the same, played on this laptop (headphones paired here)
    python3 -m assist.earcons                # hear each cue once, with its name
    python3 -m assist.phone_server --learn   # the phone plays each cue with its name
    python3 -m assist.phone_server --demo    # synthetic walk, played on the phone

Open the printed address on the phone (same Wi-Fi as the laptop), put the headphones on
and tap **Start**.

## The cues

Each cue is defined once in `cues.py`; the phone (Web Audio) and the laptop (`earcons.py`,
WAV) make the same sound from it. Every sound is under a second and quiet, so it never
hides traffic or a screen reader.

| Moment | Sound in the headphones | Vibration (Android) |
| --- | --- | --- |
| Start a route | rising three-note chime | short, long |
| Begin travelling (first steps) | soft double tick | one tick |
| Travelling | a quiet tick every 5 steps: silence means no steps are counted | none |
| A turn 1-3 steps ahead | pings **from the side of the turn**, higher as it nears | short tick |
| Turn left / right | 2 tones in the **left ear** / 3 tones in the **right ear** | 2 / 3 pulses |
| Turn around | two falling tones | one long buzz |
| The last 3 steps to the destination | pings that rise with each step | short tick |
| Arrive | a resolved four-note chord | long, then two short |
| "Are you at the elevator?" | two rising notes, like a question | two medium |
| Not sure where you are | a low rough buzz, twice | four fast |

Ticks and pings are heard but never shown or announced, so they do not flood TalkBack or
VoiceOver; every other cue is also shown in large text that screen readers announce.
Light-only mode sends no cues. On the page the person can switch sounds, ticks and
vibration on or off and set the volume; the choice stays on that phone.

### Headphones and limits

- Left/right works on any stereo headphones. **Bone-conduction headphones** let the person
  feel the cues on the cheekbones while their ears stay open; with AirPods, Transparency
  mode keeps outside sound coming in.
- Bluetooth adds about 0.2 s; the cues are designed for that.
- **The screen must stay on for sounds on a phone**: phones stop a web page's sound when
  the screen locks. The page keeps the screen awake (an option, on by default), which
  costs battery. When the screen is locked anyway, notifications (below) still arrive.
  Headphones paired with the laptop have no such limit: run with `--laptop-sound`.
- iPhone: the page asks to play even with the ring/silent switch on (Safari 17 and newer).
- Headphones connect to one device at a time: choose the phone or the laptop.

## Notifications: iPhone, Apple Watch, locked screens

iPhone web pages cannot vibrate, and the Apple Watch has no browser, but a notification
buzzes both (the Watch taps the wrist when the phone is locked). Only three key moments
are sent, with fixed words: "Are you at a saved place?", "You have arrived.", "Not sure
where you are." Never turns, landmark names, routes or positions.

### Web Push: no app needed

iOS 16.4 and newer let a Home Screen web page send notifications; Android Chrome takes
them without the Home Screen step.

1. Laptop, once: `python3 -m pip install cryptography`.
2. The phone must **trust** the page's certificate (a "Not secure" page cannot ask for
   notifications). With [mkcert](https://github.com/FiloSottile/mkcert) on the laptop:

       mkcert -install
       mkcert -cert-file cert.pem -key-file key.pem <the laptop's Wi-Fi address>

   Send `rootCA.pem` (in the folder `mkcert -CAROOT` prints) to the iPhone, install it in
   Settings, General, VPN & Device Management, then switch it on in Settings, General,
   About, Certificate Trust Settings. Remove it after the event.
3. Run:

       python3 -m assist.phone_server --demo --webpush --cert cert.pem --key key.pem

4. iPhone: open the printed address in Safari, tap Share, **Add to Home Screen**, open it
   from the Home Screen and tap **Start**, then **Allow** notifications. Press Enter on the
   laptop.

The page address and keys stay the same across restarts (in `data/push/`, kept out of
git), so the Home Screen icon keeps working while the laptop's Wi-Fi address stays the
same. The push service (Apple's or Google's) carries each message encrypted and cannot
read it. `--push-contact` sets the contact address the push services see; the default is
a placeholder.

### Or: the ntfy app

Simpler setup (no certificate), but it needs the free **ntfy** app on the phone:

    python3 -m assist.phone_server --demo --ntfy new     # prints a random topic to subscribe to

Messages go through the ntfy server (ntfy.sh, or your own with `--ntfy-server`); anyone
who knows the topic can read it, so keep it private.

Every notification feels the same and can arrive a second or more late, so turns stay
with the sounds and the spoken audio. Custom vibration on iPhone or Apple Watch would need
a native app.

## Drift correction

- **Arrival prompts.** On the way back, near each saved landmark the app asks "Are you at
  the elevator?". A double-tap of the band (`helper.confirm()`) or the big **Yes** button on
  the phone resets the position there, which clears the drift built up so far. Only the
  position is reset: the heading stays the way the user faces now.
- **Phone compass.** The page sends compass readings; `compass.py` uses only the change
  since "start route", so the phone can sit in a pocket as long as it stays put. It
  corrects the heading only when readings are steady, near a 90-degree hallway direction,
  and disagree with the tracker for 3 seconds. Indoors steel and electronics disturb
  compasses, hence the checks. All thresholds are placeholders until a real walk measures
  them: quote no accuracy gain until then. The compass needs an **https** page (step 2
  above, or a self-made certificate the phone warns about once:
  `openssl req -x509 -newkey rsa:2048 -nodes -days 7 -keyout key.pem -out cert.pem -subj "/CN=vexo"`).

## Privacy

The phone server listens on the local network so the phone can reach it. It serves only
this page, its service worker and manifest, and every address needs the random token in
the printed address. Cues on the page contain landmark names, so use it on a network you
trust. Notifications carry only the fixed words above.

## Wiring it into the live app (for the folder owners)

    from assist import attach, fan_out
    from assist.earcons import LaptopSound
    from assist.phone_server import PhoneHub, start
    hub = PhoneHub()
    helper = attach(app, send=fan_out(hub.broadcast, LaptopSound()))   # drop LaptopSound if unused
    hub.on_message = helper.on_phone_message
    server, url = start(hub)                      # port 8766; the map page uses 8765
    # notifications: add assist.webpush.default_sender() or assist.notify.NtfySender(topic) to fan_out
    # on the band's double-tap, when a prompt is open: helper.confirm()

| File | What it does |
| --- | --- |
| `cues.py` | the cue vocabulary: sound, vibration, ear, quiet or announced |
| `__init__.py` | `attach()`: turns the app's events into cues (start, travelling, turns, approach, arrival) |
| `earcons.py` | renders cues as stereo WAV and plays them on the laptop |
| `phone.html`, `phone_server.py` | the phone page and its server: sound, vibration, Yes button, compass, settings |
| `webpush.py`, `notify.py` | notifications without an app (Web Push) or with the ntfy app |
| `arrival.py`, `compass.py` | drift correction |
| `demo.py` | the synthetic-walk demo |

Tests: `tests/test_assist.py`.
