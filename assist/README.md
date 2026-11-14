# assist/: phone vibration, phone compass, arrival prompts

The band has no vibration motor and no compass. The phone the person already carries
has both, so this folder uses it. Nothing here changes `app.py`, `interfaces.py`,
`config.py` or `tracker/`: `attach(app, send)` wraps the app from the outside.

    python3 -m assist.demo                   # synthetic walk, vibrations printed (no band, no phone)
    python3 -m assist.phone_server --learn   # phone plays each pattern with its name
    python3 -m assist.phone_server --demo    # synthetic walk, the phone really vibrates

Open the printed address on the phone (same Wi-Fi as the laptop) and tap **Start**.

## Vibration (haptics)

| Cue | Pattern | When |
| --- | --- | --- |
| straight | one tick | guidance says walk straight |
| turn left | 2 pulses | |
| turn right | 3 pulses | |
| turn around | 1 long buzz | |
| arrived | long, then 2 short | |
| not sure | 4 fast pulses | the LED's red "uncertain" state |
| are you at…? | 2 medium | arrival prompt (below) |

Every cue is also spoken and shown in large text that screen readers (TalkBack, VoiceOver)
announce. Light-only mode sends no vibration.

**Android Chrome only.** iPhone browsers do not let a web page vibrate; there the page
still shows and announces every cue, and the spoken audio carries the guidance.

### iPhone and Apple Watch: notifications, no app needed (Web Push)

iPhone web pages cannot vibrate, but since iOS 16.4 a web page on the Home Screen may
send notifications. A notification buzzes the iPhone and, when the phone is locked,
should tap a paired Apple Watch like other iPhone notifications. Android Chrome takes the
same notifications without the Home Screen step, even with the screen off.

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
read it, and only the generic words below are sent. `--push-contact` sets the contact
address the push services see; the default is a placeholder.

### Or: the ntfy app

Simpler setup (no certificate), but it needs the free **ntfy** app on the iPhone:

    python3 -m assist.phone_server --demo --ntfy new     # prints a random topic to subscribe to

| Sent | Not sent |
| --- | --- |
| "Are you at a saved place?", "You have arrived.", "Not sure where you are." | turns, landmark names, routes, positions, anything the user said |

Every notification feels the same and can arrive a second or more late, so turns stay
with the spoken audio. Messages go through the ntfy server (ntfy.sh by default, or your
own with `--ntfy-server`); anyone who knows the topic can read it, so keep it private.
Custom vibration patterns on iPhone or Apple Watch would need a native app.

## Localization

- **Arrival prompts.** On the way back, near each saved landmark the app asks "Are you at
  the elevator?". A double-tap of the band (`helper.confirm()`) or the big **Yes** button on
  the phone resets the position there, which clears the drift built up so far. Only the
  position is reset: the heading stays the way the user faces now.
- **Phone compass.** The page sends compass readings; `assist/compass.py` uses only the
  change since "start route", so the phone can sit in a pocket as long as it stays put. It
  corrects the heading only when readings are steady, near a 90-degree hallway direction,
  and disagree with the tracker for 3 seconds. Indoors steel and electronics disturb
  compasses, hence the checks. All thresholds are placeholders until a real walk measures
  them: quote no accuracy gain until then.
- The compass needs an **https** page. Make a certificate once, then pass it:

      openssl req -x509 -newkey rsa:2048 -nodes -days 7 -keyout key.pem -out cert.pem -subj "/CN=vexo"
      python3 -m assist.phone_server --demo --cert cert.pem --key key.pem

  The phone warns about the self-made certificate; accept it once. Keep both files out of git.

## Privacy

The server listens on the local network so the phone can reach it. It serves only this
one page, and the page and websocket need the random token in the printed address. Cues
contain landmark names, so use it on a network you trust.

## Wiring it into the live app (for the folder owners)

    from assist import attach
    from assist.phone_server import PhoneHub, start
    hub = PhoneHub()
    helper = attach(app, send=hub.broadcast)
    hub.on_message = helper.on_phone_message
    server, url = start(hub)
    # iPhone / Apple Watch: from assist.notify import NtfySender, fan_out
    #   helper.send = fan_out(hub.broadcast, NtfySender(topic))
    # on the band's double-tap, when a prompt is open: helper.confirm()

Tests: `tests/test_assist.py`.
