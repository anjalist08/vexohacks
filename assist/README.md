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
    # on the band's double-tap, when a prompt is open: helper.confirm()

Tests: `tests/test_assist.py`.
